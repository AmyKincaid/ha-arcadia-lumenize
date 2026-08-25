import asyncio
import importlib
import sys
import types

import pytest

# Provide lightweight stubs when bleak packages are not installed in test env.
if "bleak" not in sys.modules:
    bleak = types.ModuleType("bleak")

    class BleakClient:
        pass

    class BleakError(Exception):
        pass

    bleak.BleakClient = BleakClient
    bleak.BleakError = BleakError
    sys.modules["bleak"] = bleak

if "bleak_retry_connector" not in sys.modules:
    connector = types.ModuleType("bleak_retry_connector")

    class BleakClientWithServiceCache:
        pass

    async def establish_connection(*args, **kwargs):
        raise RuntimeError("establish_connection should not run in these unit tests")

    connector.BleakClientWithServiceCache = BleakClientWithServiceCache
    connector.establish_connection = establish_connection
    sys.modules["bleak_retry_connector"] = connector


# Ensure the real transport module is imported (not the test helper stub).
sys.modules.pop("custom_components.arcadia_lumenize.transport", None)

const_module = importlib.import_module("custom_components.arcadia_lumenize.const")
transport_module = importlib.import_module("custom_components.arcadia_lumenize.transport")
ArcadiaBleTransport = transport_module.ArcadiaBleTransport


class FakeHass:
    def async_create_background_task(self, coro, name=None):
        raise RuntimeError("background task should be monkeypatched in these unit tests")


class FakeClient:
    def __init__(self):
        self.is_connected = False


class StatusClient:
    def __init__(self, status_event, notify_on_write=None):
        self.status_event = status_event
        self.notify_on_write = notify_on_write
        self.writes = []

    async def write_gatt_char(self, characteristic, packet, response=False):
        self.writes.append((characteristic, packet, response))
        if self.notify_on_write == len(self.writes):
            self.status_event.set()


class IoClient:
    def __init__(self, connected=True, write_errors=None):
        self.is_connected = connected
        self.write_errors = list(write_errors or [])
        self.writes = []
        self.notifications = []
        self.disconnected = False
        self.stopped_notifications = []
        self.cache_cleared = False

    async def write_gatt_char(self, characteristic, packet, response=False):
        self.writes.append((characteristic, packet, response))
        if self.write_errors:
            error = self.write_errors.pop(0)
            if error is not None:
                raise error

    async def start_notify(self, characteristic, callback):
        self.notifications.append((characteristic, callback))

    async def stop_notify(self, characteristic):
        self.stopped_notifications.append(characteristic)

    async def disconnect(self):
        self.disconnected = True
        self.is_connected = False

    async def clear_cache(self):
        self.cache_cleared = True
        return True


@pytest.mark.asyncio
async def test_unexpected_disconnect_persistent_schedules_reconnect(monkeypatch):
    disconnect_called = []
    reconnect_scheduled = []

    transport = ArcadiaBleTransport(
        FakeHass(),
        "AA:BB:CC:11:22:33",
        notification_callback=lambda data: None,
        disconnect_callback=lambda: disconnect_called.append(True),
        connection_mode=const_module.CONNECTION_MODE_PERSISTENT,
    )

    monkeypatch.setattr(
        transport,
        "_schedule_reconnect",
        lambda: reconnect_scheduled.append(True),
    )

    client = FakeClient()
    transport._client = client

    transport._on_disconnect(client)

    assert reconnect_scheduled == [True]
    assert disconnect_called == [True]
    assert transport.health_state == "reconnecting"
    assert transport._client is None
    assert transport.last_disconnect_reason == "unexpected disconnect"


@pytest.mark.asyncio
async def test_unexpected_disconnect_temporary_does_not_schedule_reconnect(monkeypatch):
    disconnect_called = []
    reconnect_scheduled = []

    transport = ArcadiaBleTransport(
        FakeHass(),
        "AA:BB:CC:44:55:66",
        notification_callback=lambda data: None,
        disconnect_callback=lambda: disconnect_called.append(True),
        connection_mode=const_module.CONNECTION_MODE_TEMPORARY,
    )

    monkeypatch.setattr(
        transport,
        "_schedule_reconnect",
        lambda: reconnect_scheduled.append(True),
    )

    client = FakeClient()
    transport._client = client

    transport._on_disconnect(client)

    assert reconnect_scheduled == []
    assert disconnect_called == [True]
    assert transport.health_state == "error"
    assert transport._client is None
    assert transport.last_disconnect_reason == "unexpected disconnect"


@pytest.mark.asyncio
async def test_poll_status_stops_after_notification():
    transport = ArcadiaBleTransport(
        FakeHass(),
        "AA:BB:CC:77:88:99",
        notification_callback=lambda data: None,
        disconnect_callback=lambda: None,
    )
    client = StatusClient(transport._status_event, notify_on_write=2)

    await transport._poll_status(client)

    assert len(client.writes) == 2
    assert all(write[0] == transport_module.CHAR_UUID for write in client.writes)
    assert all(write[1] == transport_module.STATUS_QUERY_PACKET for write in client.writes)
    assert all(write[2] is False for write in client.writes)


@pytest.mark.asyncio
async def test_poll_status_retries_three_times_without_notification(monkeypatch):
    transport = ArcadiaBleTransport(
        FakeHass(),
        "AA:BB:CC:00:11:22",
        notification_callback=lambda data: None,
        disconnect_callback=lambda: None,
    )
    client = StatusClient(transport._status_event)

    async def always_timeout(awaitable, timeout):
        awaitable.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(transport_module.asyncio, "wait_for", always_timeout)

    await transport._poll_status(client)

    assert len(client.writes) == 3


@pytest.mark.asyncio
async def test_async_write_sends_all_packets_and_records_activity():
    health_changed = []
    transport = ArcadiaBleTransport(
        FakeHass(),
        "AA:BB:CC:12:34:56",
        notification_callback=lambda data: None,
        disconnect_callback=lambda: None,
        health_callback=lambda: health_changed.append(True),
    )
    client = IoClient()
    transport._client = client

    result = await transport.async_write(b"first", b"second")

    assert result is True
    assert [write[1] for write in client.writes] == [b"first", b"second"]
    assert all(write[0] == transport_module.CHAR_UUID for write in client.writes)
    assert all(write[2] is False for write in client.writes)
    assert transport.last_successful_write_at is not None
    assert transport._last_command_at is not None
    assert len(health_changed) == 2


@pytest.mark.asyncio
async def test_async_write_skips_command_while_stopping():
    transport = ArcadiaBleTransport(
        FakeHass(),
        "AA:BB:CC:65:43:21",
        notification_callback=lambda data: None,
        disconnect_callback=lambda: None,
    )
    transport._stopping = True

    result = await transport.async_write(b"command")

    assert result is False


@pytest.mark.asyncio
async def test_async_poll_status_does_not_schedule_temporary_idle_disconnect(monkeypatch):
    transport = ArcadiaBleTransport(
        FakeHass(),
        "AA:BB:CC:65:43:22",
        notification_callback=lambda data: None,
        disconnect_callback=lambda: None,
        connection_mode=const_module.CONNECTION_MODE_TEMPORARY,
    )
    transport._client = IoClient()
    idle_disconnect_scheduled = []

    async def fake_poll_status(client):
        return True

    monkeypatch.setattr(transport, "_poll_status", fake_poll_status)
    monkeypatch.setattr(
        transport,
        "_schedule_idle_disconnect",
        lambda: idle_disconnect_scheduled.append(True),
    )

    result = await transport.async_poll_status()

    assert result is True
    assert idle_disconnect_scheduled == []
    assert transport._last_command_at is None


@pytest.mark.asyncio
async def test_async_poll_status_disconnects_new_temporary_connection(monkeypatch):
    transport = ArcadiaBleTransport(
        FakeHass(),
        "AA:BB:CC:65:43:23",
        notification_callback=lambda data: None,
        disconnect_callback=lambda: None,
        connection_mode=const_module.CONNECTION_MODE_TEMPORARY,
    )
    connected_client = IoClient()
    disconnect_reasons = []

    async def fake_ensure_connected():
        transport._client = connected_client

    async def fake_poll_status(client):
        return True

    async def fake_disconnect(reason):
        disconnect_reasons.append(reason)

    monkeypatch.setattr(transport, "_ensure_connected", fake_ensure_connected)
    monkeypatch.setattr(transport, "_poll_status", fake_poll_status)
    monkeypatch.setattr(transport, "_disconnect_intentionally", fake_disconnect)

    result = await transport.async_poll_status()

    assert result is True
    assert disconnect_reasons == ["status poll complete"]


@pytest.mark.asyncio
async def test_write_packet_retries_until_success(monkeypatch):
    transport = ArcadiaBleTransport(
        FakeHass(),
        "AA:BB:CC:10:20:30",
        notification_callback=lambda data: None,
        disconnect_callback=lambda: None,
    )
    client = IoClient(
        write_errors=[transport_module.BleakError("temporary"), None],
    )
    sleep_calls = []

    async def no_wait(delay):
        sleep_calls.append(delay)

    monkeypatch.setattr(transport_module.asyncio, "sleep", no_wait)

    result = await transport._write_packet(client, b"command")

    assert result is True
    assert len(client.writes) == 2
    assert sleep_calls == [0.5]
    assert transport.last_successful_write_at is not None


@pytest.mark.asyncio
async def test_write_packet_fails_when_disconnected_before_write():
    transport = ArcadiaBleTransport(
        FakeHass(),
        "AA:BB:CC:30:20:10",
        notification_callback=lambda data: None,
        disconnect_callback=lambda: None,
    )
    client = IoClient(connected=False)

    result = await transport._write_packet(client, b"command")

    assert result is False
    assert client.writes == []
    assert transport.last_error_code == "disconnected_before_write"


@pytest.mark.asyncio
async def test_write_packet_returns_false_after_all_retries(monkeypatch):
    transport = ArcadiaBleTransport(
        FakeHass(),
        "AA:BB:CC:31:21:11",
        notification_callback=lambda data: None,
        disconnect_callback=lambda: None,
    )
    client = IoClient(
        write_errors=[
            transport_module.BleakError("failure 1"),
            transport_module.BleakError("failure 2"),
            transport_module.BleakError("failure 3"),
        ],
    )

    async def no_wait(delay):
        return None

    monkeypatch.setattr(transport_module.asyncio, "sleep", no_wait)

    result = await transport._write_packet(client, b"command")

    assert result is False
    assert len(client.writes) == transport_module.MAX_WRITE_RETRIES
    assert transport.last_error_code == "write_failed"
    assert transport.last_successful_write_at is None


@pytest.mark.asyncio
async def test_async_write_disconnects_temporary_connection_after_packet_failure(monkeypatch):
    disconnect_called = []
    transport = ArcadiaBleTransport(
        FakeHass(),
        "AA:BB:CC:32:22:12",
        notification_callback=lambda data: None,
        disconnect_callback=lambda: disconnect_called.append(True),
        connection_mode=const_module.CONNECTION_MODE_TEMPORARY,
    )
    transport._client = IoClient()
    written_packets = []

    async def fake_write_packet(client, packet):
        written_packets.append(packet)
        return False

    async def fake_disconnect_after_error():
        disconnect_called.append(True)

    monkeypatch.setattr(transport, "_write_packet", fake_write_packet)
    monkeypatch.setattr(transport, "_disconnect_after_error", fake_disconnect_after_error)

    result = await transport.async_write(b"failed")

    assert result is False
    assert written_packets == [b"failed"]
    assert disconnect_called == [True]


@pytest.mark.asyncio
async def test_async_write_keeps_persistent_connection_after_packet_failure(monkeypatch):
    transport = ArcadiaBleTransport(
        FakeHass(),
        "AA:BB:CC:32:22:13",
        notification_callback=lambda data: None,
        disconnect_callback=lambda: None,
        connection_mode=const_module.CONNECTION_MODE_PERSISTENT,
    )
    client = IoClient()
    transport._client = client
    disconnect_called = []

    async def failed_write_packet(write_client, packet):
        return False

    async def fake_disconnect_after_error():
        disconnect_called.append(True)

    monkeypatch.setattr(transport, "_write_packet", failed_write_packet)
    monkeypatch.setattr(transport, "_disconnect_after_error", fake_disconnect_after_error)

    result = await transport.async_write(b"failed")

    assert result is False
    assert disconnect_called == []
    assert transport._client is client


def test_handle_notification_sets_event_and_forwards_data():
    received_data = []
    transport = ArcadiaBleTransport(
        FakeHass(),
        "AA:BB:CC:33:23:13",
        notification_callback=received_data.append,
        disconnect_callback=lambda: None,
    )
    data = bytearray(b"state")

    transport._handle_notification("sender", data)

    assert transport._status_event.is_set() is True
    assert received_data == [data]


@pytest.mark.asyncio
async def test_initialize_connection_subscribes_initializes_and_notifies(monkeypatch):
    connected_called = []
    transport = ArcadiaBleTransport(
        FakeHass(),
        "AA:BB:CC:40:50:60",
        notification_callback=lambda data: None,
        disconnect_callback=lambda: None,
        connected_callback=lambda: connected_called.append(True),
    )
    client = IoClient()
    polled_clients = []

    async def fake_poll_status(polled_client):
        polled_clients.append(polled_client)

    async def no_wait(delay):
        return None

    monkeypatch.setattr(transport, "_poll_status", fake_poll_status)
    monkeypatch.setattr(transport_module.asyncio, "sleep", no_wait)

    await transport._initialize_connection(client)

    assert client.notifications[0][0] == transport_module.NOTIFY_CHAR_UUID
    assert client.writes == [
        (transport_module.CHAR_UUID, transport_module.build_init_packet(), False),
    ]
    assert polled_clients == [client]
    assert connected_called == [True]


@pytest.mark.asyncio
async def test_establish_connection_reports_device_not_advertising(monkeypatch):
    transport = ArcadiaBleTransport(
        FakeHass(),
        "AA:BB:CC:70:80:90",
        notification_callback=lambda data: None,
        disconnect_callback=lambda: None,
    )
    monkeypatch.setattr(
        transport_module,
        "async_ble_device_from_address",
        lambda hass, address, connectable=True: None,
    )

    with pytest.raises(RuntimeError, match="not currently advertising/in range"):
        await transport._establish_connection(use_services_cache=True)

    assert transport.health_state == "unavailable"
    assert transport.last_error_code == "not_advertising"


@pytest.mark.asyncio
async def test_connect_and_init_recovers_from_missing_cached_characteristic(monkeypatch):
    transport = ArcadiaBleTransport(
        FakeHass(),
        "AA:BB:CC:90:80:70",
        notification_callback=lambda data: None,
        disconnect_callback=lambda: None,
    )
    cached_client = IoClient()
    fresh_client = IoClient()
    clients = [cached_client, fresh_client]
    connection_modes = []
    initialize_calls = []

    async def fake_establish_connection(*, use_services_cache):
        connection_modes.append(use_services_cache)
        return clients.pop(0)

    async def fake_initialize(client):
        initialize_calls.append(client)
        if client is cached_client:
            raise transport_module.BleakError(
                "Characteristic 0000 was not found"
            )

    async def no_wait(delay):
        return None

    monkeypatch.setattr(transport, "_establish_connection", fake_establish_connection)
    monkeypatch.setattr(transport, "_initialize_connection", fake_initialize)
    monkeypatch.setattr(transport_module.asyncio, "sleep", no_wait)

    await transport._connect_and_init()

    assert connection_modes == [True, False]
    assert initialize_calls == [cached_client, fresh_client]
    assert cached_client.cache_cleared is True
    assert cached_client.disconnected is True
    assert transport._client is fresh_client
    assert transport.connected is True
    assert transport.health_state == "connected"


@pytest.mark.asyncio
async def test_reconnect_worker_reports_exhausted_attempts(monkeypatch):
    transport = ArcadiaBleTransport(
        FakeHass(),
        "AA:BB:CC:91:81:71",
        notification_callback=lambda data: None,
        disconnect_callback=lambda: None,
    )
    attempts = []

    async def failed_attempt(attempt, total):
        attempts.append((attempt, total))
        return False

    monkeypatch.setattr(transport_module, "RECONNECT_DELAYS", (0, 0, 0))
    monkeypatch.setattr(transport, "_try_reconnect_attempt", failed_attempt)

    await transport._reconnect_worker()

    assert attempts == [(1, 3), (2, 3), (3, 3)]
    assert transport.health_state == "error"
    assert transport.last_error_code == "reconnect_exhausted"


@pytest.mark.asyncio
async def test_idle_disconnect_disconnects_after_inactivity(monkeypatch):
    transport = ArcadiaBleTransport(
        FakeHass(),
        "AA:BB:CC:92:82:72",
        notification_callback=lambda data: None,
        disconnect_callback=lambda: None,
        connection_mode=const_module.CONNECTION_MODE_TEMPORARY,
    )
    transport._client = IoClient()
    transport._last_command_at = 10
    disconnect_reasons = []

    async def fake_disconnect(reason):
        disconnect_reasons.append(reason)

    async def no_wait(delay):
        return None

    monkeypatch.setattr(transport, "_disconnect_intentionally", fake_disconnect)
    monkeypatch.setattr(transport_module.asyncio, "sleep", no_wait)
    monkeypatch.setattr(transport_module, "monotonic", lambda: 70)

    await transport._idle_disconnect_worker()

    assert disconnect_reasons == ["60-second idle timeout"]


def test_stale_disconnect_callback_is_ignored():
    disconnect_called = []
    transport = ArcadiaBleTransport(
        FakeHass(),
        "AA:BB:CC:01:02:03",
        notification_callback=lambda data: None,
        disconnect_callback=lambda: disconnect_called.append(True),
    )
    current_client = FakeClient()
    stale_client = FakeClient()
    transport._client = current_client

    transport._on_disconnect(stale_client)

    assert disconnect_called == []
    assert transport._client is current_client
    assert transport.last_disconnect_at is None
