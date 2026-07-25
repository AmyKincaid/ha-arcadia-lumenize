import asyncio
import pytest
from tests.helpers import load_package_module


device_module = load_package_module("custom_components.arcadia_lumenize.device")


class FakeTransport:
    def __init__(self, hass, address, notification_cb, disconnect_cb, connected_cb):
        self.hass = hass
        self.address = address
        self._notification_cb = notification_cb
        self._disconnect_cb = disconnect_cb
        self._connected_cb = connected_cb
        self.writes = []
        self.next_write_result = True

    async def async_start(self):
        # simulate connection established
        if self._connected_cb:
            self._connected_cb()

    async def async_stop(self):
        # simulate disconnect
        self._disconnect_cb()

    async def async_write(self, pkt: bytes) -> bool:
        self.writes.append(bytes(pkt))
        return self.next_write_result

    # helper to simulate incoming notification
    def simulate_notification(self, data: bytearray):
        self._notification_cb(data)


@pytest.mark.asyncio
async def test_turn_on_off_and_notifications(monkeypatch):
    # Patch transport creation to use our fake transport
    monkeypatch.setattr(device_module, "ArcadiaBleTransport", FakeTransport)

    hass = object()  # we don't need a full hass for these unit tests
    addr = "AA:BB:CC:11:22:33"
    dev = device_module.ArcadiaBleDevice(hass, addr)

    # No callbacks registered yet
    assert dev.available is False

    called = []

    def cb():
        called.append(True)

    dev.register_callback(cb)

    # start transport (calls connected callback)
    await dev.async_start()
    assert dev.available is True
    assert called

    # async_turn_on should write packet and update state when transport returns True
    fake_tr = dev._transport
    fake_tr.next_write_result = True
    ok = await dev.async_turn_on(42)
    assert ok is True
    assert dev.is_on is True
    assert dev.brightness_pct == 42
    assert len(fake_tr.writes) >= 1

    # simulate notification: brightness 80
    fake_tr.simulate_notification(bytearray([0x02, 0xF0, 0x00, 80] + [0x00] * 12))
    assert dev.brightness_pct == 80

    # turn off
    fake_tr.next_write_result = True
    ok = await dev.async_turn_off()
    assert ok is True
    assert dev.is_on is False

    # when write fails, state shouldn't change and returns False
    fake_tr.next_write_result = False
    prev_brightness = dev.brightness_pct
    ok = await dev.async_turn_on(10)
    assert ok is False
    assert dev.brightness_pct == prev_brightness

    # test disconnect handling
    dev._handle_disconnect()
    assert dev.available is False

    dev.unregister_callback(cb)
