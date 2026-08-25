# Arcadia Lumenize

Home Assistant custom component for Arcadia / Lumenize BLE LED bars.

This integration adds local Bluetooth support for Arcadia / Lumenize LED bar devices as a Home Assistant `light` entity.

## Features

- Connects to Arcadia / Lumenize BLE LED bars using Home Assistant Bluetooth
- Adds the device as a `light` entity
- Supports brightness control
- Auto-discovery via Bluetooth when the device is connectable
- Manual setup using the device Bluetooth MAC address

## Requirements

- Home Assistant 2023.10.0 or later
- Bluetooth support enabled
- The `bluetooth` integration installed and running

## Installation

### Installation via HACS

1. Ensure HACS is installed in your Home Assistant instance.
2. Add this repository to HACS as a custom repository if it is not already available.
3. Install the `Arcadia Lumenize` integration from HACS under `Integrations`.
4. Restart Home Assistant after installation.
5. Add the integration from Settings > Devices & Services > Integrations.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=amykincaid&repository=ha-arcadia-lumenize&category=integration)

### Manual installation

1. Copy the `custom_components/arcadia_lumenize` folder into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.
3. Open Home Assistant and go to Settings > Devices & Services > Integrations.
4. Click `Add Integration` and search for `Arcadia Lumenize`.
5. Follow the setup flow to add your BLE LED bar.

## Configuration

### Bluetooth Auto-discovery

If Home Assistant discovers your Arcadia / Lumenize BLE LED bar, it can be added directly from the discovery flow.

### Manual setup

If the device is not discovered automatically, enter the Bluetooth MAC address manually during setup.

### Connection mode option

During setup, and later in the integration options, choose the BLE connection strategy per device. You can also configure status polling and its interval there. Status polling is useful when the lamp can be changed by another controller or by the official app.

#### Persistent connection

`Persistent (always connected)` keeps a long-lived BLE connection and reconnects automatically if needed.

Advantages:

- Commands can be sent without waiting for a new BLE connection.
- The integration can maintain a continuously available connection and monitor the device more directly.

Disadvantages:

- The connection remains active and can use more Bluetooth resources.
- A weak or unstable Bluetooth link can cause repeated disconnects and reconnect attempts.
- If the lamp's Bluetooth controller gets stuck, the lamp may stop being discoverable over Bluetooth until it is reset.

#### Temporary connection

`Temporary (connect on command)` connects when a command is sent and disconnects again after a short idle period.

Advantages:

- Bluetooth is occupied only while the lamp is being controlled.
- It avoids keeping a potentially unstable long-lived connection open.
- It can be a useful fallback when persistent mode repeatedly loses the connection.

Disadvantages:

- Commands can take slightly longer because a connection must be established first.
- The lamp is not continuously connected, so state updates depend on status polling and the configured polling interval.

### Bluetooth connection stability and recovery

The lamp's Bluetooth controller appears to require a very good and stable Bluetooth connection. With insufficient signal quality or interference, the connection can drop and the lamp may no longer be discoverable over Bluetooth. In that situation, briefly disconnect the lamp from power and reconnect it to reset the Bluetooth controller.

If this happens repeatedly while using `Persistent (always connected)`, switch the device to `Temporary (connect on command)` in the integration options. Also check the Bluetooth adapter's placement, range, and possible sources of interference.

## Supported Devices

- Arcadia LumenIZE Jungle Dawn LED Bar
- Arcadia LumenIZE Pro T5 LED Bar (untested)

## Notes

- The integration is implemented as a custom component and is not part of the official Home Assistant core.
- The device must be within Bluetooth range and connectable to Home Assistant.

## Development

The integration is implemented as a Home Assistant custom component in `custom_components/arcadia_lumenize`.

### Component structure

- `manifest.json` defines the integration metadata, Bluetooth discovery matchers, dependency, and version.
- `__init__.py` creates and unloads config entries, applies connection and polling options, and forwards setup to the platforms.
- `config_flow.py` implements Bluetooth discovery, manual setup, and the integration options flow.
- `const.py` contains shared constants and normalization for connection and status-polling options.
- `protocol.py` encodes commands and parses the BLE status packets used by the device.
- `transport.py` manages BLE connections, notifications, retries, reconnects, temporary idle disconnects, and transport health.
- `device.py` contains the device model, command semantics, state, diagnostics, and status polling.
- `light.py` exposes the controllable Home Assistant `light` entity.
- `sensor.py` exposes diagnostic sensors such as status, timestamps, RSSI, and the last error.
- `binary_sensor.py` exposes diagnostic connection and advertising state.
- `strings.json` and `translations/` contain the config-flow and entity translations.
- `brand/` contains the integration branding assets.

### Tests

The `tests/` directory contains focused tests for setup and unloading, device behavior, the BLE protocol and transport, the light platform, and translations. Run the complete test suite from the repository root with:

```text
python -m pytest -q
```

When changing a specific area, run its test module first, for example:

```text
python -m pytest tests/test_transport.py -q
```

The tests provide lightweight Home Assistant and Bluetooth test doubles, so a full Home Assistant installation is not required for the unit-test suite.

## License

Use this repository under the license specified by the project owner.
