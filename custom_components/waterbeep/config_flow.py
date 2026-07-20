"""Config flow for the Waterbeep integration.

Handles first-time setup and re-authentication. Waterbeep uses risk-based
two-factor auth: a login from an untrusted IP lands on a one-time-code
challenge. When that happens the flow asks Waterbeep to send the code (SMS or
email), then prompts the user to enter it. Completing the code re-trusts the
connection, after which headless polling resumes.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
import voluptuous as vol

from .api import (
    WaterbeepAuthError,
    WaterbeepClient,
    WaterbeepConnectionError,
    WaterbeepError,
    WaterbeepTwoFactorRequired,
)
from .const import CONF_PASSWORD, CONF_USERNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

# Human-readable labels for the parsed 2FA delivery channels, keyed by the
# radio ``id`` on the challenge page.
_CONTACT_LABELS = {"email": "Email", "phone": "SMS"}


def _contact_label(contact: dict[str, str]) -> str:
    """Build a dropdown label for a delivery channel."""
    return _CONTACT_LABELS.get(contact.get("id", ""), contact.get("id") or "Code")


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Waterbeep."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise transient flow state."""
        self._client: WaterbeepClient | None = None
        self._creds: dict[str, str] = {}
        self._contacts: list[dict[str, str]] = []
        self._is_reauth = False
        self._reauth_entry: ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial credential step."""
        self._is_reauth = False
        errors: dict[str, str] = {}

        if user_input is not None:
            self._creds = user_input
            result = await self._attempt_login(errors)
            if result is not None:
                return result

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Start re-authentication (typically after a 2FA challenge).

        The stored password is normally still valid — a reauth here usually
        means Waterbeep is challenging with 2FA, not that the password changed.
        Try the stored credentials first and only ask for the password if the
        login actually rejects them.
        """
        self._is_reauth = True
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        assert self._reauth_entry is not None

        self._creds = {
            CONF_USERNAME: self._reauth_entry.data[CONF_USERNAME],
            CONF_PASSWORD: self._reauth_entry.data[CONF_PASSWORD],
        }
        errors: dict[str, str] = {}
        result = await self._attempt_login(errors)
        if result is not None:
            # Straight to the 2FA steps (or finished, if no challenge).
            return result
        # Stored password rejected or service unreachable - fall back to
        # asking for the password, surfacing what went wrong.
        return await self.async_step_reauth_confirm(errors=errors)

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> FlowResult:
        """Ask for the password (only reached when the stored one failed)."""
        assert self._reauth_entry is not None
        username = self._reauth_entry.data[CONF_USERNAME]
        errors = errors or {}

        if user_input is not None:
            self._creds = {
                CONF_USERNAME: username,
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            result = await self._attempt_login(errors)
            if result is not None:
                return result

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
            description_placeholders={"username": username},
        )

    async def async_step_contact(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let the user pick where the one-time code is sent, then request it."""
        errors: dict[str, str] = {}

        if user_input is not None and self._client is not None:
            try:
                # The challenge captured when this flow was created may have
                # expired while the user picked a channel; re-issue it so the
                # OTP request posts against a live session (else Waterbeep 500s).
                await self._client.async_refresh_challenge()
                await self._client.async_request_otp(user_input["contact"])
            except WaterbeepConnectionError as err:
                _LOGGER.warning(
                    "Waterbeep OTP request could not reach service: %s", err
                )
                errors["base"] = "cannot_connect"
            except WaterbeepError as err:
                _LOGGER.warning("Waterbeep refused to send the OTP: %s", err)
                errors["base"] = "otp_send_failed"
            else:
                return await self.async_step_otp()

        options = {c["value"]: _contact_label(c) for c in self._contacts}
        default = next(iter(options), None)
        return self.async_show_form(
            step_id="contact",
            data_schema=vol.Schema(
                {vol.Required("contact", default=default): vol.In(options)}
            ),
            errors=errors,
        )

    async def async_step_otp(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Collect the one-time code and complete the challenge."""
        errors: dict[str, str] = {}

        if user_input is not None and self._client is not None:
            try:
                await self._client.async_submit_otp(user_input["code"])
            except WaterbeepAuthError:
                errors["base"] = "invalid_otp"
            except WaterbeepError as err:
                _LOGGER.warning(
                    "Waterbeep OTP submission could not reach service: %s", err
                )
                errors["base"] = "cannot_connect"
            else:
                await self._reset_client()
                return await self._finish()

        return self.async_show_form(
            step_id="otp",
            data_schema=vol.Schema({vol.Required("code"): str}),
            errors=errors,
        )

    async def _attempt_login(self, errors: dict[str, str]) -> FlowResult | None:
        """Run a login. Returns a flow result, or ``None`` after setting errors.

        On a 2FA challenge the client is kept open and the flow advances to the
        contact-picker step.
        """
        await self._reset_client()
        self._client = WaterbeepClient(
            user_code=self._creds[CONF_USERNAME],
            password=self._creds[CONF_PASSWORD],
        )
        try:
            await self._client.async_login()
        except WaterbeepTwoFactorRequired as err:
            self._contacts = err.contacts
            return await self.async_step_contact()
        except WaterbeepAuthError:
            errors["base"] = "invalid_auth"
        except WaterbeepConnectionError:
            errors["base"] = "cannot_connect"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception during Waterbeep login")
            errors["base"] = "unknown"
        else:
            # Logged in without a challenge (IP already trusted).
            await self._reset_client()
            return await self._finish()

        await self._reset_client()
        return None

    async def _finish(self) -> FlowResult:
        """Create the entry (initial setup) or update+reload it (reauth)."""
        if self._is_reauth:
            assert self._reauth_entry is not None
            self.hass.config_entries.async_update_entry(
                self._reauth_entry,
                data={**self._reauth_entry.data, **self._creds},
            )
            await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
            return self.async_abort(reason="reauth_successful")

        await self.async_set_unique_id(self._creds[CONF_USERNAME])
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"Waterbeep ({self._creds[CONF_USERNAME]})",
            data=self._creds,
        )

    async def _reset_client(self) -> None:
        """Close and drop any open client session."""
        if self._client is not None:
            await self._client.close()
            self._client = None


class InvalidAuth(HomeAssistantError):
    """Error to indicate invalid credentials."""


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot reach the service."""
