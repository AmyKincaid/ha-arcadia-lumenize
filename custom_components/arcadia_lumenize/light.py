"""Arcadia / Lumenize BLE LED Bar – light platform."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import bluetooth as bluetooth_component
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .device import ArcadiaBleDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if bluetooth_component.async_scanner_count(hass, connectable=True) == 0:
        _LOGGER.debug(
            "No connectable Bluetooth scanners available during startup for %s; the entity will be added as unavailable until Bluetooth is ready",
            entry.entry_id,
        )

    device = hass.data[DOMAIN].get(entry.entry_id)
    if device is None:
        raise ConfigEntryNotReady("Device manager missing for config entry")

    async_add_entities(
        [ArcadiaBLELight(device, entry.data.get("name", entry.data["address"]))],
        update_before_add=False,
    )


class ArcadiaBLELight(RestoreEntity, LightEntity):
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device: ArcadiaBleDevice, name: str) -> None:
        self._device = device
        self._attr_name = name
        self._attr_unique_id = f"arcadia_lumenize_{device.address.replace(':', '_')}"
        self._attr_is_on = device.is_on
        self._attr_brightness = device.brightness
        self._attr_available = device.available

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device.address)},
            connections={(CONNECTION_BLUETOOTH, self._device.address)},
            name=self._attr_name,
            manufacturer="Arcadia / Lumenize",
            model="BLE LED Bar",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == STATE_ON
            if last_state.attributes.get(ATTR_BRIGHTNESS) is not None:
                self._attr_brightness = int(last_state.attributes[ATTR_BRIGHTNESS])
                self._device.restore_state(self._attr_is_on, self._attr_brightness)
            self.async_write_ha_state()

        self._device.register_callback(self._device_update)

    async def async_will_remove_from_hass(self) -> None:
        self._device.unregister_callback(self._device_update)

    def _device_update(self) -> None:
        self._attr_is_on = self._device.is_on
        self._attr_brightness = self._device.brightness
        self._attr_available = self._device.available
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        ha_brightness = kwargs.get(ATTR_BRIGHTNESS)
        if ha_brightness is not None:
            brightness_pct = max(1, round(ha_brightness / 255 * 100))
        else:
            brightness_pct = self._device.brightness_pct or 100

        if await self._device.async_turn_on(brightness_pct):
            self._attr_is_on = True
            self._attr_brightness = self._device.brightness
            self.async_write_ha_state()
        else:
            _LOGGER.error("Turn-on command failed for %s", self._device.address)

    async def async_turn_off(self, **kwargs: Any) -> None:
        if await self._device.async_turn_off():
            self._attr_is_on = False
            self.async_write_ha_state()
        else:
            _LOGGER.error("Turn-off command failed for %s", self._device.address)
