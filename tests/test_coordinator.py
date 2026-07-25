"""Tests for the Waterbeep coordinator normalisation + accumulator logic.

Payloads mirror the real responses captured live from the waterbeep tenant.
"""

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
import pytest

from custom_components.waterbeep.api import WaterbeepTwoFactorRequired
from custom_components.waterbeep.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    DATA_AVAILABLE,
    DATA_CAPITATION_AVG,
    DATA_CONSUMPTION_7D,
    DATA_CONSUMPTION_30D,
    DATA_CONSUMPTION_DAY,
    DATA_DAILY_SERIES,
    DATA_MONTH_LABEL,
    DATA_MONTH_LATEST,
)
from custom_components.waterbeep.coordinator import WaterbeepCoordinator

# Trimmed real responses.
SEVEN = {
    "succeed": True,
    "data": {
        "labels": ["2 Jul 2026", "3 Jul 2026", "4 Jul 2026"],
        "years": [2026, 2026, 2026],
        "months": [7, 7, 7],
        "days": [2, 3, 4],
        "values": [0.231, 0.592, 0.032],
        "averageDailyConsumption": 0.285,
    },
}
THIRTY = {
    "succeed": True,
    "data": {
        "labels": ["2 Jul 2026", "3 Jul 2026", "4 Jul 2026", "5 Jul 2026"],
        "years": [2026, 2026, 2026, 2026],
        "months": [7, 7, 7, 7],
        "days": [2, 3, 4, 5],
        "values": [0.231, 0.592, 0.032, 0.005],
        "averageDailyConsumption": 0.215,
    },
}
MONTHLY = {
    "succeed": True,
    "data": {
        "labels": ["Mai 2026", "Jun 2026"],
        "years": [2026, 2026],
        "months": [5, 6],
        "values": [14, 21],
        "averageDailyConsumption": 0,
    },
}
CAPITATION = {
    "succeed": True,
    "data": {
        "labels": ["Mai 2026", "Jun 2026"],
        "values": [224, 342],
        "averageDailyConsumption": 133,
    },
}
RAW = {
    "thirty_days": THIRTY,
    "seven_days": SEVEN,
    "monthly": MONTHLY,
    "capitation": CAPITATION,
}


class TestNormalise:
    """`_normalise` maps the four live payloads into flat sensor data."""

    def test_full_payload(self):
        data = WaterbeepCoordinator._normalise(RAW, today_iso="2026-07-06")
        assert data[DATA_AVAILABLE] is True
        assert data[DATA_CONSUMPTION_30D] == 0.86
        assert data[DATA_CONSUMPTION_7D] == 0.855
        # latest complete day (< today) is 5 Jul = 0.005
        assert data[DATA_CONSUMPTION_DAY] == 0.005
        assert data[DATA_MONTH_LATEST] == 21.0
        assert data[DATA_MONTH_LABEL] == "Jun 2026"
        assert data[DATA_CAPITATION_AVG] == 133.0
        assert len(data[DATA_DAILY_SERIES]) == 4
        assert data[DATA_DAILY_SERIES][0] == {"iso": "2026-07-02", "value": 0.231}

    def test_daily_ignores_today(self):
        # today = 5 Jul -> latest complete day is 4 Jul = 0.032
        data = WaterbeepCoordinator._normalise(RAW, today_iso="2026-07-05")
        assert data[DATA_CONSUMPTION_DAY] == 0.032

    def test_failed_payload_still_available(self):
        data = WaterbeepCoordinator._normalise(
            {"thirty_days": {"succeed": False, "data": None}}, today_iso="2026-07-06"
        )
        assert data[DATA_AVAILABLE] is True
        assert DATA_CONSUMPTION_30D not in data


CONFIG = {CONF_USERNAME: "12345678", CONF_PASSWORD: "secret"}
CONTACTS = [{"id": "phone", "value": "PhoneVal"}, {"id": "email", "value": "EmailVal"}]


def _build_coordinator(hass: HomeAssistant, client, mailbox):
    """Build a coordinator with the network client and Resend inbox mocked out."""
    with (
        patch(
            "custom_components.waterbeep.coordinator.WaterbeepClient",
            return_value=client,
        ),
        patch(
            "custom_components.waterbeep.coordinator.async_create_mailbox",
            return_value=mailbox,
        ),
    ):
        return WaterbeepCoordinator(hass, CONFIG)


def _challenged_client():
    """A client whose first fetch is challenged by 2FA and then succeeds."""
    client = AsyncMock()
    client.async_get_data = AsyncMock(
        side_effect=[WaterbeepTwoFactorRequired(CONTACTS), RAW]
    )
    return client


class TestUnattendedTwoFactor:
    """A 2FA challenge is cleared from the forwarded email when configured."""

    async def test_code_from_the_inbox_clears_the_challenge(
        self, hass: HomeAssistant
    ) -> None:
        """The poll asks for the code by email, reads it, and returns real data."""
        client = _challenged_client()
        mailbox = AsyncMock()
        mailbox.async_wait_for_code = AsyncMock(return_value="123456")
        coordinator = _build_coordinator(hass, client, mailbox)

        with patch.object(coordinator, "_async_import_statistics", AsyncMock()):
            data = await coordinator._async_update_data()

        # The email channel is picked, never SMS.
        client.async_request_otp.assert_awaited_once_with("EmailVal")
        client.async_submit_otp.assert_awaited_once_with("123456")
        assert data[DATA_CONSUMPTION_DAY] == 0.005

    async def test_without_a_mailbox_it_still_asks_the_user(
        self, hass: HomeAssistant
    ) -> None:
        """With the feature off, the pre-existing reauth prompt is untouched."""
        client = _challenged_client()
        coordinator = _build_coordinator(hass, client, None)

        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()

        client.async_request_otp.assert_not_awaited()

    async def test_a_code_that_never_arrives_falls_back_to_reauth(
        self, hass: HomeAssistant
    ) -> None:
        """A silent inbox degrades to the manual prompt, not to a broken entry."""
        client = _challenged_client()
        mailbox = AsyncMock()
        mailbox.async_wait_for_code = AsyncMock(return_value=None)
        coordinator = _build_coordinator(hass, client, mailbox)

        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()

        client.async_request_otp.assert_awaited_once_with("EmailVal")
        client.async_submit_otp.assert_not_awaited()

    async def test_no_email_channel_falls_back_to_reauth(
        self, hass: HomeAssistant
    ) -> None:
        """If Waterbeep only offers SMS there is nothing to read from a mailbox."""
        client = AsyncMock()
        client.async_get_data = AsyncMock(
            side_effect=WaterbeepTwoFactorRequired([{"id": "phone", "value": "P"}])
        )
        mailbox = AsyncMock()
        coordinator = _build_coordinator(hass, client, mailbox)

        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()

        client.async_request_otp.assert_not_awaited()
        mailbox.async_wait_for_code.assert_not_awaited()
