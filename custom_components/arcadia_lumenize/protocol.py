"""Arcadia / Lumenize BLE LED Bar – BLE protocol."""
from __future__ import annotations

import re

SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"

MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}$")

# Sent once after connecting – also acts as the password packet (default "1234" → bytes 3-6 = 1,2,3,4)
INIT_PACKET = bytes([
    0x05, 0xF0, 0x00, 0x01, 0x02, 0x03, 0x04,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x50,
])

POWER_ON_PACKET = bytes([
    0x04, 0x0F, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x40,
])

POWER_OFF_PACKET = bytes([
    0x04, 0xF0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x40,
])

STATUS_QUERY_PACKET = bytes([
    0x02, 0x0F, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x20,
])


def normalize_mac(address: str) -> str:
    """Normalise a MAC address to colon-separated uppercase form."""
    normalized = address.strip().upper().replace("-", ":")
    if not MAC_RE.match(normalized):
        raise ValueError("Invalid MAC address")
    return normalized


def build_init_packet() -> bytes:
    """Return the 16-byte init/auth packet."""
    return INIT_PACKET


def build_power_packet(on: bool) -> bytes:
    """Return the 16-byte packet for power on/off."""
    return POWER_ON_PACKET if on else POWER_OFF_PACKET


def brightness_packet(brightness_pct: int) -> bytes:
    """Return the 16-byte packet that sets brightness (0-100)."""
    b = max(0, min(100, brightness_pct))
    return bytes([
        0x02, 0xF1, 0x00, b,
        0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x20,
    ])


def parse_status_notification(data: bytearray) -> int | None:
    """Parse a lamp status notification and return brightness percent."""
    if len(data) != 16 or data[0] != 0x02 or data[1] != 0xF0:
        return None
    raw_brightness = data[3]
    return raw_brightness if raw_brightness <= 100 else None
