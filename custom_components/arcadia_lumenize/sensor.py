"""Diagnostic sensors for Arcadia / Lumenize BLE."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, SIGNAL_STRENGTH_DECIBELS_MILLIWATT
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
            ArcadiaBLEStatusSensor(device, name),
            ArcadiaBLELastSeenSensor(device, name),
            ArcadiaBLELastConnectedSensor(device, name),
            ArcadiaBLELastWriteSensor(device, name),
            ArcadiaBLELastDisconnectSensor(device, name),
            ArcadiaBLELastErrorSensor(device, name),
            ArcadiaBLERssiSensor(device, name),
        ]
    )


class _ArcadiaDiagnosticSensor(SensorEntity):
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


class ArcadiaBLEStatusSensor(_ArcadiaDiagnosticSensor):
    _attr_translation_key = "ble_status"
    _attr_icon = "mdi:bluetooth-settings"

    def __init__(self, device: ArcadiaBleDevice, device_name: str) -> None:
        super().__init__(device, device_name)
        self._attr_unique_id = f"{device.address.replace(':', '_')}_ble_status"
        self._last_snapshot: tuple[Any, ...] | None = None

    @property
    def native_value(self) -> str:
        return self._device.ble_status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "connected": self._device.ble_connected,
            "advertising": self._device.advertising,
            "last_rssi_at_last_status_change": self._device.last_rssi,
            "last_disconnect_reason": self._device.last_disconnect_reason,
            "last_error_code": self._device.last_error_code,
        }

    def _device_update(self) -> None:
        # last_rssi is exposed as an attribute but must not trigger a write on
        # its own; only write when something other than the RSSI changed.
        snapshot = (
            self._device.ble_status,
            self._device.ble_connected,
            self._device.advertising,
            self._device.last_disconnect_reason,
            self._device.last_error_code,
        )
        if snapshot == self._last_snapshot:
            return
        self._last_snapshot = snapshot
        self.async_write_ha_state()


class _TimestampSensor(_ArcadiaDiagnosticSensor):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _value_getter: Callable[[ArcadiaBleDevice], datetime | None]

    @property
    def native_value(self) -> datetime | None:
        return self._value_getter(self._device)


class ArcadiaBLELastSeenSensor(_TimestampSensor):
    _attr_translation_key = "ble_last_seen"
    _attr_icon = "mdi:radar"
    # Changes on every presence refresh; disabled by default to avoid recorder churn.
    _attr_entity_registry_enabled_default = False
    _value_getter = staticmethod(lambda device: device.last_seen_at)

    def __init__(self, device: ArcadiaBleDevice, device_name: str) -> None:
        super().__init__(device, device_name)
        self._attr_unique_id = f"{device.address.replace(':', '_')}_ble_last_seen"


class ArcadiaBLELastConnectedSensor(_TimestampSensor):
    _attr_translation_key = "ble_last_connected"
    _attr_icon = "mdi:link-variant"
    _attr_entity_registry_enabled_default = False
    _value_getter = staticmethod(lambda device: device.last_connected_at)

    def __init__(self, device: ArcadiaBleDevice, device_name: str) -> None:
        super().__init__(device, device_name)
        self._attr_unique_id = f"{device.address.replace(':', '_')}_ble_last_connected"


class ArcadiaBLELastWriteSensor(_TimestampSensor):
    _attr_translation_key = "ble_last_write"
    _attr_icon = "mdi:send-check"
    _value_getter = staticmethod(lambda device: device.last_successful_write_at)

    def __init__(self, device: ArcadiaBleDevice, device_name: str) -> None:
        super().__init__(device, device_name)
        self._attr_unique_id = f"{device.address.replace(':', '_')}_ble_last_write"


class ArcadiaBLELastDisconnectSensor(_TimestampSensor):
    _attr_translation_key = "ble_last_disconnect"
    _attr_icon = "mdi:link-variant-off"
    _attr_entity_registry_enabled_default = False
    _value_getter = staticmethod(lambda device: device.last_disconnect_at)

    def __init__(self, device: ArcadiaBleDevice, device_name: str) -> None:
        super().__init__(device, device_name)
        self._attr_unique_id = f"{device.address.replace(':', '_')}_ble_last_disconnect"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"reason": self._device.last_disconnect_reason}


class ArcadiaBLELastErrorSensor(_ArcadiaDiagnosticSensor):
    _attr_translation_key = "ble_last_error"
    _attr_icon = "mdi:alert-circle-outline"
    _attr_entity_registry_enabled_default = False

    def __init__(self, device: ArcadiaBleDevice, device_name: str) -> None:
        super().__init__(device, device_name)
        self._attr_unique_id = f"{device.address.replace(':', '_')}_ble_last_error"

    @property
    def native_value(self) -> str | None:
        return self._device.last_error_code

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "details": self._device.last_error_details,
            "timestamp": self._device.last_error_at,
        }


class ArcadiaBLERssiSensor(_ArcadiaDiagnosticSensor):
    _attr_translation_key = "ble_rssi"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_icon = "mdi:signal"
    # Fluctuates on every presence refresh; disabled by default to avoid recorder churn.
    _attr_entity_registry_enabled_default = False

    def __init__(self, device: ArcadiaBleDevice, device_name: str) -> None:
        super().__init__(device, device_name)
        self._attr_unique_id = f"{device.address.replace(':', '_')}_ble_rssi"

    @property
    def native_value(self) -> int | None:
        return self._device.last_rssi
