"""Fixtures for Waterbeep tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.waterbeep.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    DATA_AVAILABLE,
    DATA_CAPITATION_AVG,
    DATA_CONSUMPTION_7D,
    DATA_CONSUMPTION_30D,
    DATA_CONSUMPTION_DAY,
    DATA_DAILY_LABELS,
    DATA_DAILY_SERIES,
    DATA_DAILY_VALUES,
    DATA_MONTH_LABEL,
    DATA_MONTH_LATEST,
)


@pytest.fixture
def mock_coordinator():
    """Mock WaterbeepCoordinator."""
    coordinator = MagicMock()
    coordinator.data = {
        DATA_AVAILABLE: True,
        DATA_CONSUMPTION_DAY: 0.005,
        DATA_CONSUMPTION_7D: 0.86,
        DATA_CONSUMPTION_30D: 0.86,
        DATA_DAILY_LABELS: ["2 Jul 2026", "3 Jul 2026", "4 Jul 2026", "5 Jul 2026"],
        DATA_DAILY_VALUES: [0.231, 0.592, 0.032, 0.005],
        DATA_DAILY_SERIES: [
            {"iso": "2026-07-02", "value": 0.231},
            {"iso": "2026-07-03", "value": 0.592},
            {"iso": "2026-07-04", "value": 0.032},
            {"iso": "2026-07-05", "value": 0.005},
        ],
        DATA_MONTH_LATEST: 21.0,
        DATA_MONTH_LABEL: "Jun 2026",
        DATA_CAPITATION_AVG: 133.0,
    }
    coordinator.meter_id = "12345678"
    coordinator.last_update_success = True
    coordinator.client = MagicMock()
    coordinator.client.close = AsyncMock()
    return coordinator


@pytest.fixture
def mock_config_entry():
    """Mock ConfigEntry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {
        CONF_USERNAME: "12345678",
        CONF_PASSWORD: "secret",
    }
    entry.options = {}
    return entry
