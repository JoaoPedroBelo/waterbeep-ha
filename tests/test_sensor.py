"""Tests for the Waterbeep sensor entities."""

from custom_components.waterbeep.const import (
    DATA_CONSUMPTION_7D,
    DATA_CONSUMPTION_30D,
    DATA_CONSUMPTION_DAY,
    DATA_MONTH_LATEST,
    SENSOR_CONSUMPTION_7D,
    SENSOR_CONSUMPTION_30D,
    SENSOR_CONSUMPTION_DAY,
    SENSOR_MONTH,
)
from custom_components.waterbeep.sensor import (
    WaterbeepCapitationSensor,
    WaterbeepTotalConsumptionSensor,
    WaterbeepValueSensor,
)


def test_daily_sensor(mock_coordinator, mock_config_entry):
    s = WaterbeepValueSensor(
        mock_coordinator,
        mock_config_entry,
        SENSOR_CONSUMPTION_DAY,
        "Daily Consumption",
        DATA_CONSUMPTION_DAY,
        "mdi:water",
        with_series=True,
    )
    assert s.native_value == 0.005
    assert s.unique_id == "test_entry_id_consumption_day"
    assert s.extra_state_attributes["meter_id"] == "12345678"
    assert s.extra_state_attributes["values"] == [0.231, 0.592, 0.032, 0.005]


def test_seven_and_thirty_day_sensors(mock_coordinator, mock_config_entry):
    s7 = WaterbeepValueSensor(
        mock_coordinator,
        mock_config_entry,
        SENSOR_CONSUMPTION_7D,
        "7-Day Consumption",
        DATA_CONSUMPTION_7D,
        "mdi:water-outline",
    )
    s30 = WaterbeepValueSensor(
        mock_coordinator,
        mock_config_entry,
        SENSOR_CONSUMPTION_30D,
        "30-Day Consumption",
        DATA_CONSUMPTION_30D,
        "mdi:water-outline",
    )
    assert s7.native_value == 0.86
    assert s30.native_value == 0.86


def test_month_sensor_has_label(mock_coordinator, mock_config_entry):
    s = WaterbeepValueSensor(
        mock_coordinator,
        mock_config_entry,
        SENSOR_MONTH,
        "Last Month Consumption",
        DATA_MONTH_LATEST,
        "mdi:calendar-month",
        with_month_label=True,
    )
    assert s.native_value == 21.0
    assert s.extra_state_attributes["month"] == "Jun 2026"


def test_capitation_sensor(mock_coordinator, mock_config_entry):
    s = WaterbeepCapitationSensor(mock_coordinator, mock_config_entry)
    assert s.native_value == 133.0
    assert s.native_unit_of_measurement == "L"


def test_total_sensor_reports_and_persists_cursor(mock_coordinator, mock_config_entry):
    s = WaterbeepTotalConsumptionSensor(mock_coordinator, mock_config_entry)
    # Simulate a restored running total + cursor.
    s._total = 12.5
    s._last_iso = "2026-07-04"
    assert s.native_value == 12.5
    assert s.state_class is not None
    assert s.extra_state_attributes["last_counted_date"] == "2026-07-04"


def test_missing_data_returns_none(mock_coordinator, mock_config_entry):
    mock_coordinator.data = {}
    s = WaterbeepValueSensor(
        mock_coordinator,
        mock_config_entry,
        SENSOR_CONSUMPTION_DAY,
        "Daily Consumption",
        DATA_CONSUMPTION_DAY,
        "mdi:water",
    )
    assert s.native_value is None
