"""Arcadia / Lumenize BLE LED Bar integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .device import ArcadiaBleDevice

PLATFORMS = ["light"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Arcadia BLE from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    device = ArcadiaBleDevice(hass, entry.data["address"])
    hass.data[DOMAIN][entry.entry_id] = device
    await device.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    device = hass.data[DOMAIN].pop(entry.entry_id, None)
    if device is not None:
        await device.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
