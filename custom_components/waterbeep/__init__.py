"""The Waterbeep (EPAL) integration.

Author: João Belo
Independent open-source integration for the Aquamatrix Waterbeep water
telemetry service. Not affiliated with Aquamatrix or EPAL.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import WaterbeepCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Waterbeep from a config entry."""
    _LOGGER.debug("Setting up Waterbeep integration")

    # Options override data for configurable fields.
    config = {**entry.data, **entry.options}

    coordinator = WaterbeepCoordinator(hass, config)

    # Fail fast (ConfigEntryNotReady triggers HA retry) if the first poll fails.
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Poll twice a day (01:00 / 13:00) instead of a periodic interval.
    coordinator.async_setup_schedule()
    entry.async_on_unload(coordinator.async_teardown_schedule)

    _LOGGER.info("Waterbeep integration setup complete")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Waterbeep integration")

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: WaterbeepCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.client.close()

    return unload_ok
