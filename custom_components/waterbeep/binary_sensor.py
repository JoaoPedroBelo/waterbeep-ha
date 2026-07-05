"""Binary sensor platform for the Waterbeep integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BINARY_SENSOR_AVAILABLE, DATA_AVAILABLE, DOMAIN
from .coordinator import WaterbeepCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Waterbeep binary sensors."""
    coordinator: WaterbeepCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            WaterbeepAvailableBinarySensor(coordinator, entry),
        ]
    )


class WaterbeepBinarySensorBase(
    CoordinatorEntity[WaterbeepCoordinator], BinarySensorEntity
):
    """Base class for Waterbeep binary sensors."""

    def __init__(
        self,
        coordinator: WaterbeepCoordinator,
        entry: ConfigEntry,
        sensor_type: str,
        name: str,
    ) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{sensor_type}"
        self._attr_name = name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Waterbeep",
            "manufacturer": "Aquamatrix",
            "model": "Waterbeep (EPAL)",
        }


class WaterbeepAvailableBinarySensor(WaterbeepBinarySensorBase):
    """ON when the Waterbeep service was reachable on the last poll."""

    def __init__(self, coordinator: WaterbeepCoordinator, entry: ConfigEntry) -> None:
        """Initialise the binary sensor."""
        super().__init__(
            coordinator, entry, BINARY_SENSOR_AVAILABLE, "Service Available"
        )
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_entity_registry_enabled_default = False

    @property
    def is_on(self) -> bool:
        """Return True when the last update succeeded."""
        return bool(
            self.coordinator.last_update_success
            and self.coordinator.data.get(DATA_AVAILABLE)
        )
