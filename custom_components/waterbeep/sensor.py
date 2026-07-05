"""Sensor platform for the Waterbeep integration.

Daily/monthly consumption values are in cubic metres (m³); capitation is in
litres per person per day. All verified live.
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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_LABELS,
    ATTR_LAST_COUNTED,
    ATTR_METER_ID,
    ATTR_VALUES,
    DATA_CAPITATION_AVG,
    DATA_CONSUMPTION_7D,
    DATA_CONSUMPTION_30D,
    DATA_CONSUMPTION_DAY,
    DATA_DAILY_LABELS,
    DATA_DAILY_SERIES,
    DATA_DAILY_VALUES,
    DATA_MONTH_LABEL,
    DATA_MONTH_LATEST,
    DOMAIN,
    SENSOR_CAPITATION,
    SENSOR_CONSUMPTION_7D,
    SENSOR_CONSUMPTION_30D,
    SENSOR_CONSUMPTION_DAY,
    SENSOR_MONTH,
    SENSOR_TOTAL,
)
from .coordinator import WaterbeepCoordinator, accumulate_total


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Waterbeep sensors."""
    coordinator: WaterbeepCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            # Cumulative accumulator - the Energy/Water dashboard entity.
            WaterbeepTotalConsumptionSensor(coordinator, entry),
            # Informative period sensors (m³).
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


class WaterbeepTotalConsumptionSensor(_WaterbeepBase, RestoreEntity):
    """Cumulative water consumption (m³) for the Energy/Water dashboard.

    The Waterbeep API exposes only per-period consumption, so there is no
    lifetime meter index. This sensor keeps a monotonic running total by adding
    each newly completed day exactly once (``accumulate_total``) and persisting
    the total plus a cursor across restarts. On a fresh install it seeds the
    cursor to the newest complete day so historical days are not imported as a
    one-off spike.
    """

    def __init__(self, coordinator: WaterbeepCoordinator, entry: ConfigEntry) -> None:
        """Initialise the accumulator."""
        super().__init__(coordinator, entry, SENSOR_TOTAL, "Total Consumption")
        self._attr_icon = "mdi:water-pump"
        self._attr_device_class = SensorDeviceClass.WATER
        self._attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_suggested_display_precision = 3
        self._total: float | None = None
        self._last_iso: str | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the running total, or seed a fresh baseline."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        restored = False
        if last is not None and last.state not in (None, "unknown", "unavailable"):
            try:
                self._total = float(last.state)
                self._last_iso = last.attributes.get(ATTR_LAST_COUNTED)
                restored = True
            except (ValueError, TypeError):
                restored = False
        if not restored:
            # Fresh install: don't import history as a spike; only count days
            # completed from now on.
            self._total = 0.0
            self._last_iso = self._newest_complete_iso()
        self._recompute()

    def _newest_complete_iso(self) -> str | None:
        today_iso = dt_util.now().date().isoformat()
        series = self.coordinator.data.get(DATA_DAILY_SERIES) or []
        past = [e["iso"] for e in series if e["iso"] < today_iso]
        return max(past) if past else None

    def _recompute(self) -> None:
        series = self.coordinator.data.get(DATA_DAILY_SERIES) or []
        today_iso = dt_util.now().date().isoformat()
        base = self._total if self._total is not None else 0.0
        self._total, self._last_iso = accumulate_total(
            base, self._last_iso, series, today_iso
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self._recompute()
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> float | None:
        """Return the cumulative total in m³."""
        return self._total

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Persist the accumulation cursor across restarts."""
        return {ATTR_LAST_COUNTED: self._last_iso}
