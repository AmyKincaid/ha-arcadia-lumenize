"""Arcadia / Lumenize BLE LED Bar device management."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from homeassistant.core import HomeAssistant

from .protocol import (
    build_power_packet,
    brightness_packet,
    parse_status_notification,
)
from .transport import ArcadiaBleTransport

_LOGGER = logging.getLogger(__name__)


class ArcadiaBleDevice:
    def __init__(self, hass: HomeAssistant, address: str) -> None:
        self.hass = hass
        self.address = address

        self._callbacks: list[Callable[[], None]] = []
        self._available = False
        self._is_on = False
        self._lamp_brightness = 100

        self._transport = ArcadiaBleTransport(
            hass,
            address,
            self._handle_notification,
            self._handle_disconnect,
            self._handle_connected,
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

    def register_callback(self, callback: Callable[[], None]) -> None:
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def unregister_callback(self, callback: Callable[[], None]) -> None:
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def restore_state(self, is_on: bool, brightness: int | None) -> None:
        self._is_on = is_on
        if brightness is not None:
            self._lamp_brightness = max(1, round(brightness / 255 * 100))

    async def async_start(self) -> None:
        await self._transport.async_start()

    async def async_stop(self) -> None:
        await self._transport.async_stop()

    async def async_turn_on(self, brightness_pct: int) -> bool:
        if self._is_on:
            success = await self._transport.async_write(brightness_packet(brightness_pct))
        else:
            success = await self._transport.async_write(build_power_packet(True))
            if success:
                await asyncio.sleep(0.2)
                success = await self._transport.async_write(brightness_packet(brightness_pct))

        if success:
            self._is_on = True
            self._lamp_brightness = brightness_pct
            self._notify_state_changed()
        else:
            _LOGGER.error("Turn-on command failed for %s", self.address)

        return success

    async def async_turn_off(self) -> bool:
        success = await self._transport.async_write(build_power_packet(False))
        if success:
            self._is_on = False
            self._notify_state_changed()
        else:
            _LOGGER.error("Turn-off command failed for %s", self.address)

        return success

    def _handle_notification(self, data: bytearray) -> None:
        _LOGGER.debug("Notification from %s: %s", self.address, data.hex())

        raw_brightness = parse_status_notification(data)
        if raw_brightness is None:
            _LOGGER.debug("Ignoring unexpected notification from %s: %s", self.address, data.hex())
            return

        self._lamp_brightness = raw_brightness
        self._notify_state_changed()
        _LOGGER.debug(
            "Parsed brightness from notification: brightness=%s%%",
            raw_brightness,
        )

    def _handle_disconnect(self) -> None:
        _LOGGER.debug("Device %s disconnected", self.address)
        self._set_available(False)

    def _handle_connected(self) -> None:
        self._set_available(True)

    def _set_available(self, available: bool) -> None:
        if self._available != available:
            self._available = available
            self._notify_state_changed()

    def _notify_state_changed(self) -> None:
        for callback in self._callbacks:
            try:
                callback()
            except Exception as exc:  # noqa: BLE001
                _LOGGER.debug("Error in update callback: %s", exc)
