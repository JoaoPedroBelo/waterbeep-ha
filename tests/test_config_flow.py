"""Tests for the Waterbeep config flow."""

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.waterbeep.api import WaterbeepAuthError, WaterbeepConnectionError
from custom_components.waterbeep.config_flow import ConfigFlow
from custom_components.waterbeep.const import CONF_PASSWORD, CONF_USERNAME

USER_INPUT = {CONF_USERNAME: "12345678", CONF_PASSWORD: "secret"}


def _make_flow(hass: HomeAssistant) -> ConfigFlow:
    flow = ConfigFlow()
    flow.hass = hass
    flow.context = {"source": config_entries.SOURCE_USER}
    return flow


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
