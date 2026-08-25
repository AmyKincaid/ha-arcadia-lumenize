import pytest

from tests.helpers import load_package_module


init_module = load_package_module("custom_components.arcadia_lumenize.__init__")
const_module = load_package_module("custom_components.arcadia_lumenize.const")


class FakeDevice:
    def __init__(
        self,
        hass,
        address,
        connection_mode,
        status_polling,
        status_poll_interval,
    ):
        self.hass = hass
        self.address = address
        self.connection_mode = connection_mode
        self.status_polling = status_polling
        self.status_poll_interval = status_poll_interval
        self.started = False
        self.stopped = False

    async def async_start(self):
        self.started = True

    async def async_stop(self):
        self.stopped = True


class FakeConfigEntries:
    def __init__(self):
        self.forwarded = []
        self.unloaded = []
        self.reloaded = []

    async def async_forward_entry_setups(self, entry, platforms):
        self.forwarded.append((entry.entry_id, tuple(platforms)))

    async def async_unload_platforms(self, entry, platforms):
        self.unloaded.append((entry.entry_id, tuple(platforms)))
        return True

    async def async_reload(self, entry_id):
        self.reloaded.append(entry_id)


class FakeHass:
    def __init__(self):
        self.data = {}
        self.config_entries = FakeConfigEntries()


class FakeEntry:
    def __init__(
        self,
        entry_id="entry-1",
        mode=const_module.DEFAULT_CONNECTION_MODE,
    ):
        self.entry_id = entry_id
        self.data = {"address": "AA:BB:CC:11:22:33"}
        self.options = {const_module.CONF_CONNECTION_MODE: mode}
        self.update_listener = None
        self.unload_callbacks = []

    def add_update_listener(self, listener):
        self.update_listener = listener

        def remove_listener():
            return None

        return remove_listener

    def async_on_unload(self, callback):
        self.unload_callbacks.append(callback)


@pytest.mark.asyncio
async def test_setup_registers_options_listener_and_uses_connection_mode(monkeypatch):
    monkeypatch.setattr(init_module, "ArcadiaBleDevice", FakeDevice)

    hass = FakeHass()
    entry = FakeEntry(mode=const_module.CONNECTION_MODE_TEMPORARY)

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True
    assert entry.update_listener is init_module._async_update_listener
    assert len(entry.unload_callbacks) == 1

    device = hass.data[const_module.DOMAIN][entry.entry_id]
    assert isinstance(device, FakeDevice)
    assert device.connection_mode == const_module.CONNECTION_MODE_TEMPORARY
    assert device.status_polling is True
    assert device.status_poll_interval == const_module.DEFAULT_STATUS_POLL_INTERVAL
    assert device.started is True

    assert hass.config_entries.forwarded == [
        (entry.entry_id, tuple(init_module.PLATFORMS))
    ]

    await entry.update_listener(hass, entry)
    assert hass.config_entries.reloaded == [entry.entry_id]


@pytest.mark.asyncio
async def test_unload_stops_device_and_unloads_platforms(monkeypatch):
    monkeypatch.setattr(init_module, "ArcadiaBleDevice", FakeDevice)

    hass = FakeHass()
    entry = FakeEntry()

    await init_module.async_setup_entry(hass, entry)
    device = hass.data[const_module.DOMAIN][entry.entry_id]

    unloaded = await init_module.async_unload_entry(hass, entry)

    assert unloaded is True
    assert device.stopped is True
    assert entry.entry_id not in hass.data[const_module.DOMAIN]
    assert hass.config_entries.unloaded == [
        (entry.entry_id, tuple(init_module.PLATFORMS))
    ]


@pytest.mark.asyncio
async def test_setup_disables_status_polling_when_option_is_false(monkeypatch):
    monkeypatch.setattr(init_module, "ArcadiaBleDevice", FakeDevice)

    hass = FakeHass()
    entry = FakeEntry(mode=const_module.CONNECTION_MODE_TEMPORARY)
    entry.options[const_module.CONF_STATUS_POLLING] = False

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True
    device = hass.data[const_module.DOMAIN][entry.entry_id]
    assert device.status_polling is False
    assert device.status_poll_interval == const_module.DEFAULT_STATUS_POLL_INTERVAL


@pytest.mark.asyncio
async def test_setup_uses_configured_status_poll_interval(monkeypatch):
    monkeypatch.setattr(init_module, "ArcadiaBleDevice", FakeDevice)

    hass = FakeHass()
    entry = FakeEntry(mode=const_module.CONNECTION_MODE_TEMPORARY)
    entry.options[const_module.CONF_STATUS_POLLING] = True
    entry.options[const_module.CONF_STATUS_POLL_INTERVAL] = 45

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True
    device = hass.data[const_module.DOMAIN][entry.entry_id]
    assert device.status_polling is True
    assert device.status_poll_interval == 45


@pytest.mark.asyncio
async def test_setup_uses_float_status_poll_interval(monkeypatch):
    monkeypatch.setattr(init_module, "ArcadiaBleDevice", FakeDevice)

    hass = FakeHass()
    entry = FakeEntry(mode=const_module.CONNECTION_MODE_TEMPORARY)
    entry.options[const_module.CONF_STATUS_POLLING] = True
    entry.options[const_module.CONF_STATUS_POLL_INTERVAL] = 45.0

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True
    device = hass.data[const_module.DOMAIN][entry.entry_id]
    assert device.status_poll_interval == 45


@pytest.mark.asyncio
async def test_setup_clamps_invalid_status_poll_interval(monkeypatch):
    monkeypatch.setattr(init_module, "ArcadiaBleDevice", FakeDevice)

    hass = FakeHass()
    entry = FakeEntry(mode=const_module.CONNECTION_MODE_TEMPORARY)
    entry.options[const_module.CONF_STATUS_POLLING] = True
    entry.options[const_module.CONF_STATUS_POLL_INTERVAL] = "999"

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True
    device = hass.data[const_module.DOMAIN][entry.entry_id]
    assert device.status_poll_interval == const_module.MAX_STATUS_POLL_INTERVAL


@pytest.mark.asyncio
async def test_setup_ignores_polling_options_in_persistent_mode(monkeypatch):
    monkeypatch.setattr(init_module, "ArcadiaBleDevice", FakeDevice)

    hass = FakeHass()
    entry = FakeEntry(mode=const_module.CONNECTION_MODE_PERSISTENT)
    entry.options[const_module.CONF_STATUS_POLLING] = True
    entry.options[const_module.CONF_STATUS_POLL_INTERVAL] = 99

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True
    device = hass.data[const_module.DOMAIN][entry.entry_id]
    assert device.status_polling is False
    assert device.status_poll_interval == const_module.DEFAULT_STATUS_POLL_INTERVAL
