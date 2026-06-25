"""Arcadia / Lumenize BLE transport management."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from bleak import BleakClient, BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.components.bluetooth import async_scanner_count
from homeassistant.core import HomeAssistant

from .protocol import (
    CHAR_UUID,
    NOTIFY_CHAR_UUID,
    STATUS_QUERY_PACKET,
    build_init_packet,
)

_LOGGER = logging.getLogger(__name__)

WRITE_TIMEOUT = 10
MAX_WRITE_RETRIES = 3
RECONNECT_DELAY = 20
NO_SLOT_DELAY = 45
SLOT_RELEASE_DELAY = 8
NOT_FOUND_BACKOFF = [15, 30, 60]


class ArcadiaBleTransport:
    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        notification_callback: Callable[[bytearray], None],
        disconnect_callback: Callable[[], None],
        connected_callback: Callable[[], None] | None = None,
    ) -> None:
        self.hass = hass
        self.address = address
        self._notification_callback = notification_callback
        self._disconnect_callback = disconnect_callback
        self._connected_callback = connected_callback

        self._client: BleakClient | None = None
        self._lock = asyncio.Lock()
        self._disconnect_event = asyncio.Event()
        self._reconnect_task: asyncio.Task | None = None
        self._status_event = asyncio.Event()

    async def async_start(self) -> None:
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = self.hass.async_create_background_task(
                self._connection_loop(),
                name=f"arcadia_lumenize_transport_{self.address}",
            )

    async def async_stop(self) -> None:
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        await self._force_disconnect()

    async def async_write(self, *packets: bytes) -> bool:
        async with self._lock:
            for pkt in packets:
                for attempt in range(MAX_WRITE_RETRIES):
                    if self._client is None or not self._client.is_connected:
                        _LOGGER.warning("Not connected to %s – skipping write", self.address)
                        return False
                    try:
                        await asyncio.wait_for(
                            self._client.write_gatt_char(CHAR_UUID, pkt, response=False),
                            timeout=WRITE_TIMEOUT,
                        )
                        break
                    except (BleakError, asyncio.TimeoutError) as exc:
                        _LOGGER.debug("Write attempt %d failed: %s", attempt + 1, exc)
                        if attempt < MAX_WRITE_RETRIES - 1:
                            await asyncio.sleep(0.5)
                        else:
                            _LOGGER.error("All write attempts to %s failed", self.address)
                            return False
            return True

    async def _connection_loop(self) -> None:
        for _ in range(30):  # max. 60 Sekunden
            if async_scanner_count(self.hass, connectable=True) > 0:
                break
            _LOGGER.debug("Warte auf BLE-Scanner...")
            await asyncio.sleep(2)

        not_found_attempts = 0
        while True:
            try:
                await self._connect_and_init()
                not_found_attempts = 0
                self._disconnect_event.clear()
                await self._disconnect_event.wait()
                delay = RECONNECT_DELAY
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001
                err = str(exc)
                if "connection slot" in err:
                    _LOGGER.debug("Proxy slot busy – waiting %ss", NO_SLOT_DELAY)
                    delay = NO_SLOT_DELAY
                elif "not found in BLE scanner" in err:
                    wait = NOT_FOUND_BACKOFF[min(not_found_attempts, len(NOT_FOUND_BACKOFF) - 1)]
                    not_found_attempts += 1
                    _LOGGER.debug(
                        "Device not visible (attempt %d) – waiting %ss",
                        not_found_attempts,
                        wait,
                    )
                    delay = wait
                else:
                    _LOGGER.debug("BLE error for %s: %s", self.address, err)
                    delay = RECONNECT_DELAY
            finally:
                await self._force_disconnect()
            _LOGGER.debug("Reconnecting in %ss", delay)
            await asyncio.sleep(delay)

    async def _connect_and_init(self) -> None:
        _LOGGER.debug("Connecting to %s", self.address)
        client = await self._establish_connection()
        self._client = client
        await self._initialize_connection(client)

    async def _establish_connection(self) -> BleakClient:
        ble_device = async_ble_device_from_address(self.hass, self.address, connectable=True)
        if ble_device is None:
            raise RuntimeError(
                f"Device {self.address} not found in BLE scanner – is the proxy running and in range?"
            )

        return await establish_connection(
            client_class=BleakClientWithServiceCache,
            device=ble_device,
            name=self.address,
            disconnected_callback=self._on_disconnect,
            max_attempts=3,
        )

    async def _initialize_connection(self, client: BleakClient) -> None:
        try:
            await client.start_notify(NOTIFY_CHAR_UUID, self._handle_notification)
            _LOGGER.debug("Subscribed to notifications on %s", NOTIFY_CHAR_UUID)
        except BleakError as exc:
            _LOGGER.debug("Could not subscribe to notifications: %s", exc)
            raise

        await client.write_gatt_char(CHAR_UUID, build_init_packet(), response=False)
        await asyncio.sleep(0.2)

        await self._poll_status(client)

        if self._connected_callback is not None:
            self._connected_callback()

    async def _poll_status(self, client: BleakClient) -> None:
        self._status_event.clear()
        for attempt in range(3):
            await client.write_gatt_char(CHAR_UUID, STATUS_QUERY_PACKET, response=False)
            _LOGGER.debug("Sent status query attempt %d", attempt + 1)
            try:
                await asyncio.wait_for(self._status_event.wait(), timeout=1.0)
                break
            except asyncio.TimeoutError:
                continue

        if not self._status_event.is_set():
            _LOGGER.debug(
                "No state notification received after status query attempts; preserving current on/off state"
            )

    def _handle_notification(self, sender: Any, data: bytearray) -> None:
        self._status_event.set()
        self._notification_callback(data)

    def _on_disconnect(self, client: BleakClient) -> None:
        _LOGGER.debug("Disconnected from %s", self.address)
        self._disconnect_event.set()
        self._disconnect_callback()

    async def _force_disconnect(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            try:
                if client.is_connected:
                    await client.disconnect()
                    await asyncio.sleep(SLOT_RELEASE_DELAY)
            except BleakError as exc:
                _LOGGER.debug("Error during force-disconnect: %s", exc)
