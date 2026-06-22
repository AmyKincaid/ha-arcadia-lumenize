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

### Manual installation

1. Copy the `custom_components/arcadia_lumenize` folder into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.
3. Open Home Assistant and go to Settings > Devices & Services > Integrations.
4. Click `Add Integration` and search for `Arcadia Lumenize`.
5. Follow the setup flow to add your BLE LED bar.

### Installation via HACS

1. Ensure HACS is installed in your Home Assistant instance.
2. Add this repository to HACS as a custom repository if it is not already available.
3. Install the `Arcadia Lumenize` integration from HACS under `Integrations`.
4. Restart Home Assistant after installation.
5. Add the integration from Settings > Devices & Services > Integrations.

## Configuration

### Bluetooth Auto-discovery

If Home Assistant discovers your Arcadia / Lumenize BLE LED bar, it can be added directly from the discovery flow.

### Manual setup

If the device is not discovered automatically, enter the Bluetooth MAC address manually during setup.

## Supported Devices

- Arcadia LumenIZE Jungle Dawn LED Bar
- Arcadia LumenIZE Pro T5 LED Bar (untested)

## Notes

- The integration is implemented as a custom component and is not part of the official Home Assistant core.
- The device must be within Bluetooth range and connectable to Home Assistant.

## Development

This repository contains the custom component under `custom_components/arcadia_lumenize`.

- `manifest.json` defines the integration metadata and dependencies
- `config_flow.py` handles setup and manual address entry
- `protocol.py` contains the BLE packet protocol used by the device
- `transport.py` manages the BLE connection workflow, retries, and notifications
- `device.py` contains the Arcadia device model and command semantics
- `light.py` exposes the Home Assistant entity and maps entity commands to the device

## License

Use this repository under the license specified by the project owner.
