"""Tests for the Waterbeep coordinator normalisation + accumulator logic.

Payloads mirror the real responses captured live from the waterbeep tenant.
"""

from custom_components.waterbeep.const import (
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
