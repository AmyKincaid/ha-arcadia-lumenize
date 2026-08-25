"""Constants for the Arcadia Lumenize integration."""
from typing import Any

DOMAIN = "arcadia_lumenize"

CONF_CONNECTION_MODE = "connection_mode"
CONF_STATUS_POLLING = "status_polling"
CONF_STATUS_POLL_INTERVAL = "status_poll_interval"
CONNECTION_MODE_PERSISTENT = "persistent"
CONNECTION_MODE_TEMPORARY = "temporary"
DEFAULT_CONNECTION_MODE = CONNECTION_MODE_PERSISTENT
DEFAULT_STATUS_POLLING_TEMPORARY = True
DEFAULT_STATUS_POLLING_PERSISTENT = False
DEFAULT_STATUS_POLL_INTERVAL = 30
MIN_STATUS_POLL_INTERVAL = 10
MAX_STATUS_POLL_INTERVAL = 300


def normalize_connection_mode(value: Any) -> str:
    """Normalize configured connection mode to canonical internal values."""
    if value == CONNECTION_MODE_TEMPORARY:
        return CONNECTION_MODE_TEMPORARY
    if value == CONNECTION_MODE_PERSISTENT:
        return CONNECTION_MODE_PERSISTENT
    return DEFAULT_CONNECTION_MODE


def normalize_status_polling(value: Any, connection_mode: str) -> bool:
    """Normalize status polling option with mode-specific defaults."""
    if isinstance(value, bool):
        return value
    if connection_mode == CONNECTION_MODE_TEMPORARY:
        return DEFAULT_STATUS_POLLING_TEMPORARY
    return DEFAULT_STATUS_POLLING_PERSISTENT


def normalize_status_poll_interval(
    value: Any,
    connection_mode: str,
    status_polling: bool,
) -> int:
    """Normalize status polling interval and clamp to safe limits."""
    if connection_mode != CONNECTION_MODE_TEMPORARY or not status_polling:
        return DEFAULT_STATUS_POLL_INTERVAL

    try:
        raw_interval = int(float(value))
    except (TypeError, ValueError):
        raw_interval = DEFAULT_STATUS_POLL_INTERVAL

    return max(MIN_STATUS_POLL_INTERVAL, min(MAX_STATUS_POLL_INTERVAL, raw_interval))
