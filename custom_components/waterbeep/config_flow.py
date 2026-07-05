"""Config flow for the Waterbeep integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
import voluptuous as vol

from .api import WaterbeepAuthError, WaterbeepClient, WaterbeepConnectionError
from .const import CONF_PASSWORD, CONF_USERNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the credentials by performing a login."""
    client = WaterbeepClient(
        user_code=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
    )
    try:
        await client.async_login()
    finally:
        await client.close()

    return {
        "title": f"Waterbeep ({data[CONF_USERNAME]})",
        "unique_id": data[CONF_USERNAME],
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Waterbeep."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except WaterbeepAuthError:
                errors["base"] = "invalid_auth"
            except WaterbeepConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception during Waterbeep login")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["unique_id"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class InvalidAuth(HomeAssistantError):
    """Error to indicate invalid credentials."""


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot reach the service."""
