import importlib
import importlib.util
import os
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def preload_protocol():
    """Load protocol module into package namespace so relative imports work."""
    proto_name = "custom_components.arcadia_lumenize.protocol"
    if proto_name in sys.modules:
        return sys.modules[proto_name]
    proto_path = os.path.join(ROOT, "custom_components", "arcadia_lumenize", "protocol.py")
    spec = importlib.util.spec_from_file_location(proto_name, proto_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules[proto_name] = mod
    return mod


def preload_transport_stub():
    """Create a lightweight transport stub module in sys.modules.

    Tests can monkeypatch the `ArcadiaBleTransport` attribute on modules
    loaded from the package.
    """
    name = "custom_components.arcadia_lumenize.transport"
    if name in sys.modules:
        return sys.modules[name]
    m = types.ModuleType(name)
    # minimal class placeholder
    class ArcadiaBleTransport:  # noqa: N801 - test helper
        pass

    m.ArcadiaBleTransport = ArcadiaBleTransport
    sys.modules[name] = m
    return m


def load_package_module(module_name: str):
    """Load a module from the integration package safely for tests.

    Ensures `protocol` is preloaded and a transport stub exists so that
    importing package modules does not execute side-effectful package
    `__init__` code that requires BLE or Home Assistant runtime.
    """
    preload_protocol()
    preload_transport_stub()
    return importlib.import_module(module_name)
