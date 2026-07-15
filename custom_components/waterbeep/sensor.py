"""Sensor platform for the Waterbeep integration.

Daily/monthly consumption values are in cubic metres (m³); capitation is in
litres per person per day. All verified live.

The Energy/Water dashboard is fed by the ``waterbeep:consumption`` long-term
statistic imported by the coordinator (see ``statistics.py``), not by a live
sensor: Waterbeep data is backdated, so a live ``total_increasing`` sensor would
misattribute each day's usage to the poll hour.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_LABELS,
    ATTR_METER_ID,
    ATTR_VALUES,
    DATA_CAPITATION_AVG,
    DATA_CONSUMPTION_7D,
    DATA_CONSUMPTION_30D,
    DATA_CONSUMPTION_DAY,
    DATA_DAILY_LABELS,
    DATA_DAILY_VALUES,
    DATA_MONTH_LABEL,
    DATA_MONTH_LATEST,
    DOMAIN,
    SENSOR_CAPITATION,
    SENSOR_CONSUMPTION_7D,
    SENSOR_CONSUMPTION_30D,
    SENSOR_CONSUMPTION_DAY,
    SENSOR_MONTH,
)
from .coordinator import WaterbeepCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Waterbeep sensors."""
    coordinator: WaterbeepCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            # Informative period sensors (m³). The Energy/Water dashboard is fed
            # by the imported ``waterbeep:consumption`` statistic, not a sensor.
            WaterbeepValueSensor(
                coordinator,
                entry,
                SENSOR_CONSUMPTION_DAY,
                "Daily Consumption",
                DATA_CONSUMPTION_DAY,
                "mdi:water",
                with_series=True,
            ),
            WaterbeepValueSensor(
                coordinator,
                entry,
                SENSOR_CONSUMPTION_7D,
                "7-Day Consumption",
                DATA_CONSUMPTION_7D,
                "mdi:water-outline",
            ),
            WaterbeepValueSensor(
                coordinator,
                entry,
                SENSOR_CONSUMPTION_30D,
                "30-Day Consumption",
                DATA_CONSUMPTION_30D,
                "mdi:water-outline",
            ),
            WaterbeepValueSensor(
                coordinator,
                entry,
                SENSOR_MONTH,
                "Last Month Consumption",
                DATA_MONTH_LATEST,
                "mdi:calendar-month",
                with_month_label=True,
            ),
            # Per-capita average (litres per person per day).
            WaterbeepCapitationSensor(coordinator, entry),
        ]
    )


class _WaterbeepBase(CoordinatorEntity[WaterbeepCoordinator], SensorEntity):
    """Shared device info / identity for Waterbeep sensors."""

    def __init__(
        self,
        coordinator: WaterbeepCoordinator,
        entry: ConfigEntry,
        sensor_type: str,
        name: str,
    ) -> None:
        """Initialise identity and device info."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{sensor_type}"
        self._attr_name = name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Waterbeep",
            "manufacturer": "Aquamatrix",
            "model": "Waterbeep (EPAL)",
        }


class WaterbeepValueSensor(_WaterbeepBase):
    """A water-consumption sensor backed by a single coordinator.data key (m³)."""

    def __init__(
        self,
        coordinator: WaterbeepCoordinator,
        entry: ConfigEntry,
        sensor_type: str,
        name: str,
        data_key: str,
        icon: str,
        *,
        with_series: bool = False,
        with_month_label: bool = False,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, entry, sensor_type, name)
        self._data_key = data_key
        self._with_series = with_series
        self._with_month_label = with_month_label
        self._attr_icon = icon
        self._attr_device_class = SensorDeviceClass.WATER
        self._attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = 3

    @property
    def native_value(self) -> float | None:
        """Return the consumption value in m³."""
        return self.coordinator.data.get(self._data_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the daily series or the month label where relevant."""
        if self._with_series:
            return {
                ATTR_METER_ID: self.coordinator.meter_id,
                ATTR_LABELS: self.coordinator.data.get(DATA_DAILY_LABELS),
                ATTR_VALUES: self.coordinator.data.get(DATA_DAILY_VALUES),
            }
        if self._with_month_label:
            return {"month": self.coordinator.data.get(DATA_MONTH_LABEL)}
        return None


class WaterbeepCapitationSensor(_WaterbeepBase):
    """Per-capita average consumption (litres per person per day)."""

    def __init__(self, coordinator: WaterbeepCoordinator, entry: ConfigEntry) -> None:
        """Initialise the sensor."""
        super().__init__(
            coordinator, entry, SENSOR_CAPITATION, "Average Per-Capita Consumption"
        )
        self._attr_icon = "mdi:account-multiple"
        self._attr_native_unit_of_measurement = "L"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = 0

    @property
    def native_value(self) -> float | None:
        """Return litres per person per day."""
        return self.coordinator.data.get(DATA_CAPITATION_AVG)
