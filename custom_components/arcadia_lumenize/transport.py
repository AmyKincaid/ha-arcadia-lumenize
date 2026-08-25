"""Arcadia / Lumenize BLE transport management.

Connection strategy can be selected per config entry:
- persistent: keep a long-lived BLE connection once initialized.
- temporary: reconnect on demand and disconnect after 60 seconds idle.

Diagnostics are passive: health state is updated from connection/write events only.
No extra BLE health-check connections are created.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from time import monotonic
from typing import Any, Callable

from bleak import BleakClient, BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components.bluetooth import (
    async_ble_device_from_address,
    async_scanner_count,
)
from homeassistant.core import HomeAssistant

from .const import (
    CONNECTION_MODE_TEMPORARY,
    DEFAULT_CONNECTION_MODE,
    normalize_connection_mode,
)
from .protocol import (
    CHAR_UUID,
    NOTIFY_CHAR_UUID,
    STATUS_QUERY_PACKET,
    build_init_packet,
)

_LOGGER = logging.getLogger(__name__)

WRITE_TIMEOUT = 10
MAX_WRITE_RETRIES = 3
IDLE_DISCONNECT_DELAY = 60
SLOT_RELEASE_DELAY = 3
GATT_RECOVERY_DELAY = 2
SCANNER_WAIT_ATTEMPTS = 30
SCANNER_WAIT_DELAY = 2
RECONNECT_DELAYS = (0, 15, 30, 60)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ArcadiaBleTransport:
    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        notification_callback: Callable[[bytearray], None],
        disconnect_callback: Callable[[], None],
        connected_callback: Callable[[], None] | None = None,
        health_callback: Callable[[], None] | None = None,
        connection_mode: str = DEFAULT_CONNECTION_MODE,
    ) -> None:
        self.hass = hass
        self.address = address
        self._notification_callback = notification_callback
        self._disconnect_callback = disconnect_callback
        self._connected_callback = connected_callback
        self._health_callback = health_callback
        self._connection_mode = normalize_connection_mode(connection_mode)
        self._temporary_mode = self._connection_mode == CONNECTION_MODE_TEMPORARY

        self._client: BleakClientWithServiceCache | None = None
        self._lock = asyncio.Lock()
        self._status_event = asyncio.Event()
        self._startup_task: asyncio.Task | None = None
        self._idle_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._last_command_at: float | None = None
        self._intentional_disconnect_client_ids: set[int] = set()
        self._stopping = False

        # Passive diagnostics. These values never trigger extra BLE I/O.
        self._health_state = "idle"
        self._last_connected_at: datetime | None = None
        self._last_successful_write_at: datetime | None = None
        self._last_disconnect_at: datetime | None = None
        self._last_disconnect_reason: str | None = None
        self._last_error_code: str | None = None
        self._last_error_details: str | None = None
        self._last_error_at: datetime | None = None

    @property
    def connected(self) -> bool:
        client = self._client
        return bool(client is not None and client.is_connected)

    @property
    def health_state(self) -> str:
        return self._health_state

    @property
    def last_connected_at(self) -> datetime | None:
        return self._last_connected_at

    @property
    def last_successful_write_at(self) -> datetime | None:
        return self._last_successful_write_at

    @property
    def last_disconnect_at(self) -> datetime | None:
        return self._last_disconnect_at

    @property
    def last_disconnect_reason(self) -> str | None:
        return self._last_disconnect_reason

    @property
    def last_error_code(self) -> str | None:
        return self._last_error_code

    @property
    def last_error_details(self) -> str | None:
        return self._last_error_details

    @property
    def last_error_at(self) -> datetime | None:
        return self._last_error_at

    async def async_start(self) -> None:
        self._stopping = False
        if self._startup_task is None or self._startup_task.done():
            self._startup_task = self.hass.async_create_background_task(
                self._initial_connect(),
                name=f"arcadia_lumenize_initial_connect_{self.address}",
            )

    async def async_stop(self) -> None:
        self._stopping = True
        if self._startup_task and not self._startup_task.done():
            self._startup_task.cancel()
            try:
                await self._startup_task
            except asyncio.CancelledError:
                pass

        self._cancel_idle_task()
        self._cancel_reconnect_task()
        async with self._lock:
            await self._disconnect_intentionally("integration stop")

    async def async_write(self, *packets: bytes) -> bool:
        async with self._lock:
            if self._stopping:
                _LOGGER.warning("[%s] Transport is stopping – skipping write", self.address)
                return False

            try:
                await self._ensure_connected()
            except Exception as exc:  # noqa: BLE001
                if self._health_state not in ("unavailable", "error"):
                    self._set_error("connection_failed", str(exc), "error")
                _LOGGER.warning(
                    "[%s] Could not establish BLE connection for command: %s",
                    self.address,
                    exc,
                )
                return False

            client = self._client
            if client is None or not client.is_connected:
                self._set_error(
                    "connection_lost",
                    "BLE client not connected after preparation",
                    "error",
                )
                _LOGGER.warning("[%s] BLE client not connected after preparation", self.address)
                return False

            for pkt in packets:
                success = await self._write_packet(client, pkt)
                if not success:
                    if self._temporary_mode:
                        await self._disconnect_after_error()
                    return False

            self._mark_activity()
            return True

    async def async_poll_status(self) -> bool:
        """Actively query the lamp status and wait for a response notification."""
        async with self._lock:
            if self._stopping:
                _LOGGER.warning("[%s] Transport is stopping – skipping status poll", self.address)
                return False

            was_connected = self.connected
            try:
                await self._ensure_connected()
            except Exception as exc:  # noqa: BLE001
                if self._health_state not in ("unavailable", "error"):
                    self._set_error("connection_failed", str(exc), "error")
                _LOGGER.warning(
                    "[%s] Could not establish BLE connection for status poll: %s",
                    self.address,
                    exc,
                )
                return False

            client = self._client
            if client is None or not client.is_connected:
                self._set_error(
                    "connection_lost",
                    "BLE client not connected before status poll",
                    "error",
                )
                _LOGGER.warning("[%s] BLE client not connected before status poll", self.address)
                return False

            try:
                return await self._poll_status(client)
            finally:
                if self._temporary_mode and not was_connected:
                    await self._disconnect_intentionally("status poll complete")

    async def _initial_connect(self) -> None:
        try:
            await self._wait_for_ble_scanner()

            async with self._lock:
                if self._stopping:
                    return
                await self._run_initial_state_sync()

        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if self._health_state not in ("unavailable", "error"):
                self._set_error("initial_sync_failed", str(exc), "error")
            _LOGGER.warning(
                "[%s] Initial BLE state synchronization failed: %s. "
                "Will retry automatically on the next command.",
                self.address,
                exc,
            )
            async with self._lock:
                await self._disconnect_after_error(preserve_health_state=True)

    async def _wait_for_ble_scanner(self) -> None:
        for _ in range(SCANNER_WAIT_ATTEMPTS):
            if async_scanner_count(self.hass, connectable=True) > 0:
                break
            _LOGGER.debug("[%s] Waiting for BLE scanner...", self.address)
            await asyncio.sleep(SCANNER_WAIT_DELAY)

    async def _run_initial_state_sync(self) -> None:
        _LOGGER.info("[%s] Initial BLE state synchronization", self.address)
        await self._connect_and_init()
        self._mark_activity()

    async def _ensure_connected(self) -> None:
        client = self._client
        if client is not None and client.is_connected:
            return
        await self._connect_and_init()

    async def _connect_and_init(self) -> None:
        if self._client is not None and self._client.is_connected:
            return

        self._set_health_state("connecting")
        _LOGGER.info("[%s] Connecting on demand", self.address)
        client = await self._establish_connection(use_services_cache=True)
        self._client = client

        try:
            await self._initialize_connection(client)
        except BleakError as exc:
            if not self._looks_like_missing_characteristic(exc):
                self._set_error("initialization_failed", str(exc), "error")
                await self._disconnect_after_error(preserve_health_state=True)
                raise

            _LOGGER.warning(
                "[%s] Required GATT characteristic missing after cached connect; "
                "clearing cache and retrying uncached: %s",
                self.address,
                exc,
            )
            await self._clear_cache_and_disconnect(client)
            await asyncio.sleep(GATT_RECOVERY_DELAY)

            _LOGGER.info("[%s] Reconnecting with fresh GATT service discovery", self.address)
            client = await self._establish_connection(use_services_cache=False)
            self._client = client
            await self._initialize_connection(client)
            _LOGGER.info("[%s] Fresh GATT service discovery succeeded", self.address)

        self._last_connected_at = _utcnow()
        self._clear_error()
        self._set_health_state("connected", force_notify=True)
        _LOGGER.info(
            "[%s] BLE connection initialized and ready (%s mode)",
            self.address,
            self._connection_mode,
        )

    async def _establish_connection(
        self,
        *,
        use_services_cache: bool,
    ) -> BleakClientWithServiceCache:
        ble_device = async_ble_device_from_address(
            self.hass,
            self.address,
            connectable=True,
        )

        if ble_device is None:
            message = (
                f"Device {self.address} not found in BLE scanner – "
                "device is not currently advertising/in range"
            )
            self._set_error("not_advertising", message, "unavailable")
            raise RuntimeError(message)

        try:
            return await establish_connection(
                client_class=BleakClientWithServiceCache,
                device=ble_device,
                name=self.address,
                disconnected_callback=self._on_disconnect,
                max_attempts=3,
                use_services_cache=use_services_cache,
            )
        except Exception as exc:  # noqa: BLE001
            self._set_error("connection_failed", str(exc), "error")
            raise

    async def _initialize_connection(
        self,
        client: BleakClientWithServiceCache,
    ) -> None:
        try:
            await client.start_notify(
                NOTIFY_CHAR_UUID,
                self._handle_notification,
            )
            _LOGGER.debug(
                "[%s] Subscribed to notifications on %s",
                self.address,
                NOTIFY_CHAR_UUID,
            )
        except BleakError as exc:
            _LOGGER.debug(
                "[%s] Could not subscribe to notifications: %s",
                self.address,
                exc,
            )
            raise

        await client.write_gatt_char(
            CHAR_UUID,
            build_init_packet(),
            response=False,
        )
        await asyncio.sleep(0.2)
        await self._poll_status(client)

        if self._connected_callback is not None:
            self._connected_callback()

    async def _poll_status(
        self,
        client: BleakClientWithServiceCache,
    ) -> bool:
        self._status_event.clear()

        for attempt in range(3):
            await client.write_gatt_char(
                CHAR_UUID,
                STATUS_QUERY_PACKET,
                response=False,
            )
            _LOGGER.debug(
                "[%s] Sent status query attempt %d",
                self.address,
                attempt + 1,
            )

            try:
                await asyncio.wait_for(
                    self._status_event.wait(),
                    timeout=1.0,
                )
                return True
            except asyncio.TimeoutError:
                continue

        _LOGGER.debug(
            "[%s] No state notification after status query attempts; "
            "preserving current state",
            self.address,
        )
        return False

    async def _write_packet(
        self,
        client: BleakClientWithServiceCache,
        pkt: bytes,
    ) -> bool:
        for attempt in range(MAX_WRITE_RETRIES):
            if not client.is_connected:
                self._set_error(
                    "disconnected_before_write",
                    f"Disconnected before BLE write attempt {attempt + 1}",
                    "error",
                )
                _LOGGER.warning(
                    "[%s] Disconnected before BLE write attempt %d",
                    self.address,
                    attempt + 1,
                )
                return False

            try:
                _LOGGER.debug(
                    "[%s] BLE WRITE attempt=%d packet=%s",
                    self.address,
                    attempt + 1,
                    pkt.hex(),
                )
                await asyncio.wait_for(
                    client.write_gatt_char(
                        CHAR_UUID,
                        pkt,
                        response=False,
                    ),
                    timeout=WRITE_TIMEOUT,
                )
                self._last_successful_write_at = _utcnow()
                self._clear_error()
                self._notify_health_changed()
                return True

            except (BleakError, asyncio.TimeoutError) as exc:
                self._set_error("write_failed", str(exc), "error")
                _LOGGER.warning(
                    "[%s] BLE write attempt %d failed: %s",
                    self.address,
                    attempt + 1,
                    exc,
                )
                if attempt < MAX_WRITE_RETRIES - 1:
                    await asyncio.sleep(0.5)

        _LOGGER.error("[%s] All BLE write attempts failed", self.address)
        return False

    def _schedule_idle_disconnect(self) -> None:
        if not self._temporary_mode:
            return
        self._cancel_idle_task()
        self._idle_task = self.hass.async_create_background_task(
            self._idle_disconnect_worker(),
            name=f"arcadia_lumenize_idle_disconnect_{self.address}",
        )

    def _cancel_idle_task(self) -> None:
        task = self._idle_task
        self._idle_task = None
        if task is not None and not task.done():
            task.cancel()

    def _schedule_reconnect(self) -> None:
        if self._temporary_mode or self._stopping:
            return
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return
        self._reconnect_task = self.hass.async_create_background_task(
            self._reconnect_worker(),
            name=f"arcadia_lumenize_reconnect_{self.address}",
        )

    def _cancel_reconnect_task(self) -> None:
        task = self._reconnect_task
        self._reconnect_task = None
        if task is not None and not task.done():
            task.cancel()

    async def _reconnect_worker(self) -> None:
        try:
            attempt_count = len(RECONNECT_DELAYS)
            for attempt, delay in enumerate(RECONNECT_DELAYS, start=1):
                if self._stopping:
                    return

                if delay > 0:
                    await asyncio.sleep(delay)

                if self._stopping:
                    return

                reconnect_successful = await self._try_reconnect_attempt(
                    attempt,
                    attempt_count,
                )
                if reconnect_successful:
                    return

            self._set_error(
                "reconnect_exhausted",
                "Exceeded reconnect attempts after unexpected disconnect",
                "error",
            )
            _LOGGER.error("[%s] Reconnect attempts exhausted", self.address)

        except asyncio.CancelledError:
            return
        finally:
            if self._reconnect_task is asyncio.current_task():
                self._reconnect_task = None

    async def _try_reconnect_attempt(self, attempt: int, total: int) -> bool:
        async with self._lock:
            if self._stopping:
                return True

            client = self._client
            if client is not None and client.is_connected:
                return True

            _LOGGER.info(
                "[%s] Reconnect attempt %d/%d",
                self.address,
                attempt,
                total,
            )
            try:
                await self._connect_and_init()
                _LOGGER.info("[%s] Reconnect successful", self.address)
                return True
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._set_error_details("reconnect_attempt_failed", str(exc))
                self._set_health_state("reconnecting", force_notify=True)
                _LOGGER.warning(
                    "[%s] Reconnect attempt %d/%d failed: %s",
                    self.address,
                    attempt,
                    total,
                    exc,
                )
                return False

    async def _idle_disconnect_worker(self) -> None:
        try:
            await asyncio.sleep(IDLE_DISCONNECT_DELAY)

            async with self._lock:
                if self._stopping:
                    return

                client = self._client
                if client is None or not client.is_connected:
                    return

                if self._last_command_at is None:
                    return

                idle_for = monotonic() - self._last_command_at
                if idle_for < IDLE_DISCONNECT_DELAY:
                    self._schedule_idle_disconnect()
                    return

                _LOGGER.info(
                    "[%s] No command for %.0fs – disconnecting BLE cleanly",
                    self.address,
                    idle_for,
                )
                await self._disconnect_intentionally(
                    f"{IDLE_DISCONNECT_DELAY}-second idle timeout"
                )

        except asyncio.CancelledError:
            return
        finally:
            if self._idle_task is asyncio.current_task():
                self._idle_task = None

    async def _disconnect_intentionally(self, reason: str) -> None:
        client = self._client
        self._client = None

        if client is None:
            if not self._stopping:
                self._set_health_state("idle")
            return

        _LOGGER.info(
            "[%s] Intentional BLE disconnect: %s",
            self.address,
            reason,
        )
        disconnect_error = await self._disconnect_client(client, stop_notify=True)
        if disconnect_error is not None:
            self._set_error("disconnect_failed", disconnect_error, "error")
            _LOGGER.debug(
                "[%s] Error during intentional disconnect: %s",
                self.address,
                disconnect_error,
            )

        self._last_disconnect_at = _utcnow()
        self._last_disconnect_reason = reason
        if self._health_state != "error":
            self._set_health_state("idle", force_notify=True)
        else:
            self._notify_health_changed()

    async def _disconnect_after_error(self, preserve_health_state: bool = False) -> None:
        client = self._client
        self._client = None
        self._cancel_idle_task()

        await self._disconnect_client(client)

        self._last_disconnect_at = _utcnow()
        self._last_disconnect_reason = "error cleanup"
        if not preserve_health_state and self._health_state not in ("unavailable", "error"):
            self._set_health_state("error", force_notify=True)
        else:
            self._notify_health_changed()

        if self._disconnect_callback is not None:
            self._disconnect_callback()

    async def _clear_cache_and_disconnect(
        self,
        client: BleakClientWithServiceCache,
    ) -> None:
        try:
            cleared = await client.clear_cache()
            _LOGGER.info(
                "[%s] BLE GATT service cache clear result: %s",
                self.address,
                cleared,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "[%s] Could not clear BLE GATT service cache: %s",
                self.address,
                exc,
            )

        self._client = None
        await self._disconnect_client(client)

    def _handle_notification(
        self,
        sender: Any,
        data: bytearray,
    ) -> None:
        self._status_event.set()
        self._notification_callback(data)

    def _on_disconnect(
        self,
        client: BleakClient,
    ) -> None:
        client_id = id(client)

        if self._is_intentional_disconnect_callback(client_id):
            _LOGGER.info(
                "[%s] BLE disconnect callback after intentional disconnect",
                self.address,
            )
            return

        if self._is_stale_disconnect_callback(client):
            _LOGGER.debug(
                "[%s] Ignoring disconnect callback from stale BLE client",
                self.address,
            )
            return

        _LOGGER.warning(
            "[%s] Unexpected BLE disconnect callback fired",
            self.address,
        )

        self._record_unexpected_disconnect()

        if self._temporary_mode:
            self._handle_unexpected_disconnect_temporary()
        else:
            self._handle_unexpected_disconnect_persistent()

        if self._disconnect_callback is not None:
            self._disconnect_callback()

    def _is_intentional_disconnect_callback(self, client_id: int) -> bool:
        return client_id in self._intentional_disconnect_client_ids

    def _is_stale_disconnect_callback(self, client: BleakClient) -> bool:
        return self._client is not None and client is not self._client

    def _record_unexpected_disconnect(self) -> None:
        self._client = None
        self._cancel_idle_task()
        self._last_disconnect_at = _utcnow()
        self._last_disconnect_reason = "unexpected disconnect"
        self._set_error_details(
            "unexpected_disconnect",
            "Unexpected BLE disconnect callback fired",
        )

    def _mark_activity(self) -> None:
        self._last_command_at = monotonic()
        if self._temporary_mode:
            self._schedule_idle_disconnect()

    def _handle_unexpected_disconnect_temporary(self) -> None:
        self._set_health_state("error", force_notify=True)

    def _handle_unexpected_disconnect_persistent(self) -> None:
        self._set_health_state("reconnecting", force_notify=True)
        self._schedule_reconnect()

    async def _disconnect_client(
        self,
        client: BleakClientWithServiceCache | None,
        *,
        stop_notify: bool = False,
    ) -> str | None:
        if client is None:
            return None

        client_id = id(client)
        self._intentional_disconnect_client_ids.add(client_id)
        try:
            if client.is_connected:
                if stop_notify:
                    try:
                        await client.stop_notify(NOTIFY_CHAR_UUID)
                    except (BleakError, asyncio.TimeoutError) as exc:
                        _LOGGER.debug(
                            "[%s] stop_notify before disconnect failed: %s",
                            self.address,
                            exc,
                        )
                await client.disconnect()
                await asyncio.sleep(SLOT_RELEASE_DELAY)
            return None
        except (BleakError, asyncio.TimeoutError) as exc:
            return str(exc)
        finally:
            asyncio.get_running_loop().call_later(
                SLOT_RELEASE_DELAY,
                self._intentional_disconnect_client_ids.discard,
                client_id,
            )

    def _clear_error(self) -> None:
        self._last_error_code = None
        self._last_error_details = None
        self._last_error_at = None

    def _set_error_details(self, code: str, details: str) -> None:
        self._last_error_code = code
        self._last_error_details = details
        self._last_error_at = _utcnow()

    def _set_health_state(self, state: str, force_notify: bool = False) -> None:
        changed = self._health_state != state
        self._health_state = state
        if changed or force_notify:
            self._notify_health_changed()

    def _set_error(self, code: str, details: str, state: str) -> None:
        self._set_error_details(code, details)
        self._health_state = state
        self._notify_health_changed()

    def _notify_health_changed(self) -> None:
        if self._health_callback is None:
            return
        try:
            self._health_callback()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("[%s] Error in health callback: %s", self.address, exc)

    @staticmethod
    def _looks_like_missing_characteristic(exc: BleakError) -> bool:
        message = str(exc).lower()
        return "characteristic" in message and "was not found" in message
