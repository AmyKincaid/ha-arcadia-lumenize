"""Arcadia / Lumenize BLE LED Bar device management."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONNECTION_MODE_TEMPORARY,
    DEFAULT_CONNECTION_MODE,
    DEFAULT_STATUS_POLL_INTERVAL,
    normalize_connection_mode,
)
from .protocol import (
    brightness_packet,
    parse_status_notification,
)
from .transport import ArcadiaBleTransport

_LOGGER = logging.getLogger(__name__)
PRESENCE_REFRESH_INTERVAL = 30


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ArcadiaBleDevice:
    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        *,
        connection_mode: str = DEFAULT_CONNECTION_MODE,
        status_polling: bool = True,
        status_poll_interval: int = DEFAULT_STATUS_POLL_INTERVAL,
    ) -> None:
        self.hass = hass
        self.address = address
        self._connection_mode = normalize_connection_mode(connection_mode)
        self._temporary_mode = self._connection_mode == CONNECTION_MODE_TEMPORARY
        self._status_polling = status_polling
        self._status_poll_interval = status_poll_interval

        self._callbacks: list[Callable[[], None]] = []
        self._diagnostic_callbacks: list[Callable[[], None]] = []
        self._status_poll_unsub: Callable[[], None] | None = None
        self._presence_task: asyncio.Task | None = None
        self._stopping = False

        # In temporary mode, availability should not mirror current GATT link state.
        self._available = self._temporary_mode

        self._is_on = False
        self._lamp_brightness = 100

        # Passive Bluetooth-manager diagnostics. The presence worker only reads
        # Home Assistant's existing Bluetooth cache every 30 seconds. It does
        # not trigger scans, GATT connects, status queries, or lamp commands.
        self._advertising: bool | None = None
        self._last_seen_at: datetime | None = None
        self._last_rssi: int | None = None

        self._transport = ArcadiaBleTransport(
            hass,
            address,
            self._handle_notification,
            self._handle_disconnect,
            self._handle_connected,
            self._notify_diagnostics_changed,
            connection_mode=self._connection_mode,
        )

        self._status_poll_coordinator: DataUpdateCoordinator[bool] | None = None
        if self._temporary_mode and self._status_polling:
            self._status_poll_coordinator = DataUpdateCoordinator(
                hass,
                _LOGGER,
                name=f"arcadia_lumenize_status_poll_{address}",
                update_method=self.async_request_status_update,
                update_interval=timedelta(seconds=self._status_poll_interval),
            )

    @property
    def available(self) -> bool:
        return self._available

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def brightness(self) -> int:
        return round(self._lamp_brightness / 100 * 255)

    @property
    def brightness_pct(self) -> int:
        return self._lamp_brightness

    @property
    def ble_connected(self) -> bool:
        return self._transport.connected

    @property
    def ble_status(self) -> str:
        return self._transport.health_state

    @property
    def advertising(self) -> bool | None:
        return self._advertising

    @property
    def last_seen_at(self) -> datetime | None:
        return self._last_seen_at

    @property
    def last_rssi(self) -> int | None:
        return self._last_rssi

    @property
    def last_connected_at(self) -> datetime | None:
        return self._transport.last_connected_at

    @property
    def last_successful_write_at(self) -> datetime | None:
        return self._transport.last_successful_write_at

    @property
    def last_disconnect_at(self) -> datetime | None:
        return self._transport.last_disconnect_at

    @property
    def last_disconnect_reason(self) -> str | None:
        return self._transport.last_disconnect_reason

    @property
    def last_error_code(self) -> str | None:
        return self._transport.last_error_code

    @property
    def last_error_details(self) -> str | None:
        return self._transport.last_error_details

    @property
    def last_error_at(self) -> datetime | None:
        return self._transport.last_error_at

    def register_callback(self, callback_fn: Callable[[], None]) -> None:
        if callback_fn not in self._callbacks:
            self._callbacks.append(callback_fn)

    def unregister_callback(self, callback_fn: Callable[[], None]) -> None:
        if callback_fn in self._callbacks:
            self._callbacks.remove(callback_fn)

    def register_diagnostic_callback(self, callback_fn: Callable[[], None]) -> None:
        if callback_fn not in self._diagnostic_callbacks:
            self._diagnostic_callbacks.append(callback_fn)

    def unregister_diagnostic_callback(self, callback_fn: Callable[[], None]) -> None:
        if callback_fn in self._diagnostic_callbacks:
            self._diagnostic_callbacks.remove(callback_fn)

    def restore_state(self, is_on: bool, brightness: int | None) -> None:
        self._is_on = is_on
        if brightness is not None:
            self._lamp_brightness = max(1, round(brightness / 255 * 100))

    async def async_start(self) -> None:
        self._stopping = False
        _LOGGER.info(
            "[%s] Starting device manager (connection_mode=%s, status_polling=%s, status_poll_interval=%ss)",
            self.address,
            self._connection_mode,
            self._status_polling if self._temporary_mode else False,
            self._status_poll_interval if self._temporary_mode and self._status_polling else 0,
        )
        self._refresh_passive_presence()
        if self._status_poll_coordinator is not None:
            if self._status_poll_unsub is None:
                self._status_poll_unsub = self._status_poll_coordinator.async_add_listener(
                    lambda: None
                )
            await self._status_poll_coordinator.async_refresh()
        if self._presence_task is None or self._presence_task.done():
            self._presence_task = self.hass.async_create_background_task(
                self._presence_worker(),
                name=f"arcadia_lumenize_presence_{self.address}",
            )
        await self._transport.async_start()

    async def async_stop(self) -> None:
        self._stopping = True
        if self._status_poll_unsub is not None:
            self._status_poll_unsub()
            self._status_poll_unsub = None
        if self._status_poll_coordinator is not None:
            await self._status_poll_coordinator.async_shutdown()
        if self._presence_task is not None and not self._presence_task.done():
            self._presence_task.cancel()
            try:
                await self._presence_task
            except asyncio.CancelledError:
                pass
        self._presence_task = None
        await self._transport.async_stop()

    async def async_request_status_update(self) -> bool:
        """Actively query current lamp status via BLE and notify listeners on success."""
        success = await self._transport.async_poll_status()
        if success and not self._available:
            self._available = True
            self._notify_state_changed()
        return success

    async def async_turn_on(self, brightness_pct: int) -> bool:
        success = await self._transport.async_write(
            brightness_packet(brightness_pct)
        )

        if success:
            self._is_on = True
            self._lamp_brightness = brightness_pct
            self._available = True
            self._notify_state_changed()
        else:
            _LOGGER.error("Turn-on command failed for %s", self.address)

        return success

    async def async_turn_off(self) -> bool:
        success = await self._transport.async_write(brightness_packet(0))

        if success:
            self._is_on = False
            self._available = True
            self._notify_state_changed()
        else:
            _LOGGER.error("Turn-off command failed for %s", self.address)

        return success

    async def _presence_worker(self) -> None:
        try:
            while not self._stopping:
                await asyncio.sleep(PRESENCE_REFRESH_INTERVAL)
                self._refresh_passive_presence()
        except asyncio.CancelledError:
            return

    def _refresh_passive_presence(self) -> None:
        """Read presence/RSSI from HA's Bluetooth cache without extra scanning."""
        present = bluetooth.async_address_present(
            self.hass,
            self.address,
            connectable=False,
        )
        service_info = bluetooth.async_last_service_info(
            self.hass,
            self.address,
            connectable=False,
        )

        changed = self._advertising != present
        self._advertising = present

        if present:
            self._last_seen_at = _utcnow()
            if service_info is not None:
                if self._last_rssi != service_info.rssi:
                    changed = True
                self._last_rssi = service_info.rssi

        if changed or present:
            self._notify_diagnostics_changed()

    def _handle_notification(self, data: bytearray) -> None:
        _LOGGER.debug(
            "Notification from %s: %s",
            self.address,
            data.hex(),
        )

        raw_brightness = parse_status_notification(data)
        if raw_brightness is None:
            _LOGGER.debug(
                "Ignoring unexpected notification from %s: %s",
                self.address,
                data.hex(),
            )
            return

        self._lamp_brightness = raw_brightness
        self._available = True
        self._notify_state_changed()

        _LOGGER.debug(
            "Parsed brightness from notification: brightness=%s%%",
            raw_brightness,
        )

    def _handle_disconnect(self) -> None:
        if self._temporary_mode:
            # A closed GATT connection is normal in temporary mode.
            _LOGGER.debug(
                "Device %s BLE connection closed; keeping HA entity available for on-demand reconnect",
                self.address,
            )
        else:
            _LOGGER.debug(
                "Device %s BLE connection closed; marking entity unavailable until reconnect",
                self.address,
            )
            self._available = False

        self._refresh_passive_presence()
        self._notify_state_changed()

    def _handle_connected(self) -> None:
        self._available = True
        self._refresh_passive_presence()
        self._notify_state_changed()

    def _notify_state_changed(self) -> None:
        """Notify control and diagnostic entities about a real state change."""
        self._run_callbacks(self._callbacks)
        self._run_callbacks(self._diagnostic_callbacks)

    def _notify_diagnostics_changed(self) -> None:
        """Notify only diagnostic entities about a change in passive Bluetooth state (advertising, RSSI, etc.)."""
        self._run_callbacks(self._diagnostic_callbacks)

    def _run_callbacks(self, callbacks: list[Callable[[], None]]) -> None:
        for callback_fn in callbacks:
            try:
                callback_fn()
            except Exception as exc:  # noqa: BLE001
                _LOGGER.debug(
                    "Error in update callback: %s",
                    exc,
                )
