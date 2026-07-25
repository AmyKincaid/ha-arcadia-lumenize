import asyncio
import pytest
from tests.helpers import load_package_module


mod_light = load_package_module("custom_components.arcadia_lumenize.light")
ArcadiaBLELight = mod_light.ArcadiaBLELight


class FakeDevice:
    def __init__(self):
        self.address = "AA:BB:CC:11:22:33"
        self.is_on = False
        self.brightness = 255
        self.brightness_pct = 100
        self.available = True
        self._callbacks = []

    def register_callback(self, cb):
        self._callbacks.append(cb)

    def unregister_callback(self, cb):
        if cb in self._callbacks:
            self._callbacks.remove(cb)

    def restore_state(self, is_on, brightness):
        self.is_on = is_on
        if brightness is not None:
            self.brightness = brightness
            self.brightness_pct = max(1, round(brightness / 255 * 100))

    async def async_turn_on(self, pct):
        # simulate success and update internal brightness
        self.is_on = True
        self.brightness_pct = pct
        self.brightness = round(pct / 100 * 255)
        # notify callbacks
        for cb in list(self._callbacks):
            cb()
        return True

    async def async_turn_off(self):
        self.is_on = False
        for cb in list(self._callbacks):
            cb()
        return True


@pytest.mark.asyncio
async def test_light_updates_and_commands(monkeypatch):
    fake = FakeDevice()
    light = ArcadiaBLELight(fake, "Test Light")

    # avoid calls to hass by monkeypatching state write
    monkeypatch.setattr(light, "async_write_ha_state", lambda: None, raising=False)

    # initial values copied from device
    assert light._attr_is_on is False
    assert light._attr_brightness == fake.brightness

    # simulate device update
    fake.is_on = True
    fake.brightness = 128
    fake.brightness_pct = 50
    light._device_update()
    assert light._attr_is_on is True
    assert light._attr_brightness == 128

    # test async_turn_on with explicit HA brightness (0-255)
    # 50% of 255 ≈ 128 -> rounded to 50% for device
    await light.async_turn_on(brightness=128)
    assert light._attr_is_on is True
    assert 0 <= light._attr_brightness <= 255

    # test async_turn_off
    await light.async_turn_off()
    assert light._attr_is_on is False
