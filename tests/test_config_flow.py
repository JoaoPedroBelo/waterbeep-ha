"""Tests for the Waterbeep config flow."""

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.waterbeep.api import (
    WaterbeepAuthError,
    WaterbeepConnectionError,
    WaterbeepTwoFactorRequired,
)
from custom_components.waterbeep.config_flow import ConfigFlow
from custom_components.waterbeep.const import CONF_PASSWORD, CONF_USERNAME, DOMAIN

USER_INPUT = {CONF_USERNAME: "12345678", CONF_PASSWORD: "secret"}
CONTACTS = [{"id": "phone", "value": "PhoneVal"}, {"id": "email", "value": "EmailVal"}]


def _make_flow(hass: HomeAssistant) -> ConfigFlow:
    flow = ConfigFlow()
    flow.hass = hass
    flow.context = {"source": config_entries.SOURCE_USER}
    return flow


def _mock_2fa_client():
    """A patched WaterbeepClient whose login triggers a 2FA challenge."""
    instance = AsyncMock()
    instance.async_login = AsyncMock(side_effect=WaterbeepTwoFactorRequired(CONTACTS))
    instance.async_request_otp = AsyncMock()
    instance.async_submit_otp = AsyncMock()
    instance.close = AsyncMock()
    return instance


async def test_form_shown(hass: HomeAssistant) -> None:
    """The initial step shows the form with no errors."""
    flow = _make_flow(hass)
    result = await flow.async_step_user()
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {}


async def test_form_success(hass: HomeAssistant) -> None:
    """A valid login creates the entry."""
    flow = _make_flow(hass)

    with patch(
        "custom_components.waterbeep.config_flow.WaterbeepClient",
    ) as mock_client:
        instance = mock_client.return_value
        instance.async_login = AsyncMock()
        instance.close = AsyncMock()

        result = await flow.async_step_user(USER_INPUT)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Waterbeep (12345678)"
    assert result["data"] == USER_INPUT


async def test_form_invalid_auth(hass: HomeAssistant) -> None:
    """Bad credentials surface an invalid_auth error."""
    flow = _make_flow(hass)

    with patch(
        "custom_components.waterbeep.config_flow.WaterbeepClient",
    ) as mock_client:
        instance = mock_client.return_value
        instance.async_login = AsyncMock(side_effect=WaterbeepAuthError("bad"))
        instance.close = AsyncMock()

        result = await flow.async_step_user(USER_INPUT)

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_form_cannot_connect(hass: HomeAssistant) -> None:
    """A connection error surfaces cannot_connect."""
    flow = _make_flow(hass)

    with patch(
        "custom_components.waterbeep.config_flow.WaterbeepClient",
    ) as mock_client:
        instance = mock_client.return_value
        instance.async_login = AsyncMock(side_effect=WaterbeepConnectionError("down"))
        instance.close = AsyncMock()

        result = await flow.async_step_user(USER_INPUT)

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_two_factor_full_flow(hass: HomeAssistant) -> None:
    """A 2FA challenge routes through contact + code steps to a created entry."""
    flow = _make_flow(hass)
    instance = _mock_2fa_client()

    with patch(
        "custom_components.waterbeep.config_flow.WaterbeepClient",
        return_value=instance,
    ):
        # Login is challenged -> contact picker shown.
        result = await flow.async_step_user(USER_INPUT)
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "contact"

        # Pick SMS -> code entry shown, and Waterbeep was asked to send it.
        result = await flow.async_step_contact({"contact": "PhoneVal"})
        instance.async_request_otp.assert_awaited_once_with("PhoneVal")
        assert result["step_id"] == "otp"

        # Enter the code -> entry created.
        result = await flow.async_step_otp({"code": "123456"})

    instance.async_submit_otp.assert_awaited_once_with("123456")
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == USER_INPUT


async def test_otp_invalid_code_shows_error(hass: HomeAssistant) -> None:
    """A rejected code re-shows the OTP form with an error."""
    flow = _make_flow(hass)
    instance = _mock_2fa_client()
    instance.async_submit_otp = AsyncMock(side_effect=WaterbeepAuthError("bad"))

    with patch(
        "custom_components.waterbeep.config_flow.WaterbeepClient",
        return_value=instance,
    ):
        await flow.async_step_user(USER_INPUT)
        await flow.async_step_contact({"contact": "PhoneVal"})
        result = await flow.async_step_otp({"code": "000000"})

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "otp"
    assert result["errors"] == {"base": "invalid_otp"}


async def test_reauth_two_factor_flow(hass: HomeAssistant) -> None:
    """Reauth reuses the stored password and goes straight to the 2FA steps."""
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT, unique_id="12345678")
    entry.add_to_hass(hass)

    flow = ConfigFlow()
    flow.hass = hass
    flow.context = {"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id}

    instance = _mock_2fa_client()

    with (
        patch(
            "custom_components.waterbeep.config_flow.WaterbeepClient",
            return_value=instance,
        ) as mock_client,
        patch.object(
            hass.config_entries, "async_reload", AsyncMock(return_value=True)
        ) as mock_reload,
    ):
        # No password prompt: the stored password is tried automatically and
        # the 2FA challenge routes straight to the contact picker.
        result = await flow.async_step_reauth(dict(entry.data))
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "contact"
        assert mock_client.call_args.kwargs["password"] == "secret"

        result = await flow.async_step_contact({"contact": "PhoneVal"})
        assert result["step_id"] == "otp"

        result = await flow.async_step_otp({"code": "123456"})

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    mock_reload.assert_awaited_once_with(entry.entry_id)
    assert entry.data[CONF_PASSWORD] == "secret"


async def test_reauth_asks_password_only_when_rejected(hass: HomeAssistant) -> None:
    """The password form only appears when the stored password fails."""
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT, unique_id="12345678")
    entry.add_to_hass(hass)

    flow = ConfigFlow()
    flow.hass = hass
    flow.context = {"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id}

    rejected = AsyncMock()
    rejected.async_login = AsyncMock(side_effect=WaterbeepAuthError("bad"))
    rejected.close = AsyncMock()

    with (
        patch(
            "custom_components.waterbeep.config_flow.WaterbeepClient",
            return_value=rejected,
        ),
        patch.object(
            hass.config_entries, "async_reload", AsyncMock(return_value=True)
        ) as mock_reload,
    ):
        # Stored password rejected -> password form with the error shown.
        result = await flow.async_step_reauth(dict(entry.data))
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"
        assert result["errors"] == {"base": "invalid_auth"}

        # A working password then completes the reauth (no 2FA challenge).
        rejected.async_login = AsyncMock()
        result = await flow.async_step_reauth_confirm({CONF_PASSWORD: "newpass"})

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    mock_reload.assert_awaited_once_with(entry.entry_id)
    assert entry.data[CONF_PASSWORD] == "newpass"
