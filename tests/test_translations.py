import json
from pathlib import Path


def test_entity_translations_exist() -> None:
    strings_path = Path(__file__).resolve().parents[1] / "custom_components" / "arcadia_lumenize" / "strings.json"
    data = json.loads(strings_path.read_text(encoding="utf-8"))

    sensor_names = {
        "ble_status",
        "ble_last_seen",
        "ble_last_connected",
        "ble_last_write",
        "ble_last_disconnect",
        "ble_last_error",
        "ble_rssi",
    }
    binary_sensor_names = {"ble_connected", "ble_advertising"}

    assert sensor_names.issubset(data["entity"]["sensor"].keys())
    assert binary_sensor_names.issubset(data["entity"]["binary_sensor"].keys())
