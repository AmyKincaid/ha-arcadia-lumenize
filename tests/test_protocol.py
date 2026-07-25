import importlib.util
import os
import sys
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

spec = importlib.util.spec_from_file_location(
    "arcadia_protocol",
    os.path.join(ROOT, "custom_components", "arcadia_lumenize", "protocol.py"),
)
protocol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(protocol)


def test_normalize_mac_valid():
    assert protocol.normalize_mac("aa:bb:cc:11:22:33") == "AA:BB:CC:11:22:33"
    assert protocol.normalize_mac("aa-bb-cc-11-22-33") == "AA:BB:CC:11:22:33"


def test_normalize_mac_invalid():
    with pytest.raises(ValueError):
        protocol.normalize_mac("invalid-mac")


def test_build_init_packet():
    pkt = protocol.build_init_packet()
    assert isinstance(pkt, (bytes, bytearray))
    assert len(pkt) == 16


@pytest.mark.parametrize("pct,idx", [(0, 3), (50, 3), (100, 3), (-10, 3), (200, 3)])
def test_brightness_packet_bounds(pct, idx):
    pkt = protocol.brightness_packet(pct)
    assert isinstance(pkt, (bytes, bytearray))
    assert len(pkt) == 16
    # brightness lives at index 3 and is clamped 0-100
    assert 0 <= pkt[idx] <= 100


def test_parse_status_notification_valid():
    data = bytearray([0x02, 0xF0, 0x00, 75] + [0x00] * 12)
    assert protocol.parse_status_notification(data) == 75


def test_parse_status_notification_invalid():
    # wrong length
    assert protocol.parse_status_notification(bytearray(b"short")) is None
    # wrong header
    data = bytearray([0x01, 0x00] + [0x00] * 14)
    assert protocol.parse_status_notification(data) is None
    # brightness out of range
    data = bytearray([0x02, 0xF0, 0x00, 255] + [0x00] * 12)
    assert protocol.parse_status_notification(data) is None
