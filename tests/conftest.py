import sys
import types


def _make_module(name):
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m


# Minimal stub of the homeassistant package used by the integration to allow tests
ha = _make_module("homeassistant")

# submodules
config_entries = _make_module("homeassistant.config_entries")
core = _make_module("homeassistant.core")
components = _make_module("homeassistant.components")
components_bluetooth = _make_module("homeassistant.components.bluetooth")
components_light = _make_module("homeassistant.components.light")
data_entry_flow = _make_module("homeassistant.data_entry_flow")
const = _make_module("homeassistant.const")
exceptions = _make_module("homeassistant.exceptions")
helpers = _make_module("homeassistant.helpers")
helpers_restore = _make_module("homeassistant.helpers.restore_state")
helpers_device = _make_module("homeassistant.helpers.device_registry")
helpers_entity = _make_module("homeassistant.helpers.entity")
helpers_platform = _make_module("homeassistant.helpers.entity_platform")
helpers_update_coordinator = _make_module("homeassistant.helpers.update_coordinator")


# lightweight class placeholders
class ConfigEntry:
    pass


class HomeAssistant:
    pass


class ConfigEntryNotReady(Exception):
    pass


class RestoreEntity:
    pass


class DeviceInfo:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class LightEntity:
    pass


class DataUpdateCoordinator:
    def __init__(self, hass, logger, name=None, update_method=None, update_interval=None):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_method = update_method
        self.update_interval = update_interval
        self._listeners = []

    def async_add_listener(self, listener):
        self._listeners.append(listener)

        def _unsub():
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _unsub

    async def async_refresh(self):
        if self.update_method is not None:
            await self.update_method()

    async def async_shutdown(self):
        self._listeners.clear()


class BluetoothServiceInfoBleak:
    pass


def async_ble_device_from_address(hass, address, connectable=True):
    return None


def async_scanner_count(hass, connectable=True):
    return 0


def async_address_present(hass, address, connectable=False):
    return False


def async_last_service_info(hass, address, connectable=False):
    return None


# enums / constants
ATTR_BRIGHTNESS = "brightness"


class ColorMode:
    BRIGHTNESS = "brightness"


# expose in modules
config_entries.ConfigEntry = ConfigEntry
core.HomeAssistant = HomeAssistant
exceptions.ConfigEntryNotReady = ConfigEntryNotReady
helpers_restore.RestoreEntity = RestoreEntity
helpers_device.CONNECTION_BLUETOOTH = ("bluetooth",)
helpers_entity.DeviceInfo = DeviceInfo
components_bluetooth.BluetoothServiceInfoBleak = BluetoothServiceInfoBleak
components_bluetooth.async_ble_device_from_address = async_ble_device_from_address
components_bluetooth.async_scanner_count = async_scanner_count
components_bluetooth.async_address_present = async_address_present
components_bluetooth.async_last_service_info = async_last_service_info
components_light.ATTR_BRIGHTNESS = ATTR_BRIGHTNESS
components_light.ColorMode = ColorMode
components_light.LightEntity = LightEntity
helpers_platform.AddEntitiesCallback = object
helpers_update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
data_entry_flow.FlowResult = object
const.STATE_ON = "on"
