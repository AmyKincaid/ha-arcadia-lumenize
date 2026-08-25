"""Arcadia / Lumenize BLE LED Bar integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONNECTION_MODE_TEMPORARY,
    CONF_CONNECTION_MODE,
    CONF_STATUS_POLL_INTERVAL,
    CONF_STATUS_POLLING,
    DEFAULT_CONNECTION_MODE,
    DOMAIN,
    normalize_connection_mode,
    normalize_status_poll_interval,
    normalize_status_polling,
)
from .device import ArcadiaBleDevice

PLATFORMS = ["light", "sensor", "binary_sensor"]


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options change so connection mode is reapplied."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Arcadia BLE from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    raw_connection_mode = entry.options.get(
        CONF_CONNECTION_MODE,
        DEFAULT_CONNECTION_MODE,
    )
    connection_mode = normalize_connection_mode(raw_connection_mode)
    status_polling = normalize_status_polling(
        entry.options.get(CONF_STATUS_POLLING),
        connection_mode,
    )
    if connection_mode != CONNECTION_MODE_TEMPORARY:
        status_polling = False
    status_poll_interval = normalize_status_poll_interval(
        entry.options.get(CONF_STATUS_POLL_INTERVAL),
        connection_mode,
        status_polling,
    )

    device = ArcadiaBleDevice(
        hass,
        entry.data["address"],
        connection_mode=connection_mode,
        status_polling=status_polling,
        status_poll_interval=status_poll_interval,
    )
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
