"""Diagnostic binary sensors for Arcadia / Lumenize BLE."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .device import ArcadiaBleDevice


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    device: ArcadiaBleDevice = hass.data[DOMAIN][entry.entry_id]
    name = entry.data.get("name", entry.data["address"])
    async_add_entities(
        [
            ArcadiaBLEConnectedBinarySensor(device, name),
            ArcadiaBLEAdvertisingBinarySensor(device, name),
        ]
    )


class _ArcadiaDiagnosticBinarySensor(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, device: ArcadiaBleDevice, device_name: str) -> None:
        self._device = device
        self._device_name = device_name

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device.address)},
            connections={(CONNECTION_BLUETOOTH, self._device.address)},
            name=self._device_name,
            manufacturer="Arcadia / Lumenize",
            model="BLE LED Bar",
        )

    async def async_added_to_hass(self) -> None:
        self._device.register_diagnostic_callback(self._device_update)

    async def async_will_remove_from_hass(self) -> None:
        self._device.unregister_diagnostic_callback(self._device_update)

    def _device_update(self) -> None:
        self.async_write_ha_state()


class ArcadiaBLEConnectedBinarySensor(_ArcadiaDiagnosticBinarySensor):
    _attr_translation_key = "ble_connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_icon = "mdi:bluetooth-connect"
    _attr_entity_registry_enabled_default = False

    def __init__(self, device: ArcadiaBleDevice, device_name: str) -> None:
        super().__init__(device, device_name)
        self._attr_unique_id = f"{device.address.replace(':', '_')}_ble_connected"

    @property
    def is_on(self) -> bool:
        return self._device.ble_connected


class ArcadiaBLEAdvertisingBinarySensor(_ArcadiaDiagnosticBinarySensor):
    _attr_translation_key = "ble_advertising"
    _attr_icon = "mdi:bluetooth-audio"
    _attr_entity_registry_enabled_default = False

    def __init__(self, device: ArcadiaBleDevice, device_name: str) -> None:
        super().__init__(device, device_name)
        self._attr_unique_id = f"{device.address.replace(':', '_')}_ble_advertising"

    @property
    def is_on(self) -> bool | None:
        return self._device.advertising
