"""Config flow for Arcadia / Lumenize BLE LED Bar."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN
from .protocol import normalize_mac


class ArcadiaBLEConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Arcadia BLE."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None

    # ------------------------------------------------------------------
    # Bluetooth auto-discovery (optional – works if HA sees the device)
    # ------------------------------------------------------------------
    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle a discovered BLE device."""
        if not discovery_info.connectable:
            return self.async_abort(reason="not_connectable")

        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict | None = None
    ) -> FlowResult:
        assert self._discovery_info is not None
        if user_input is not None:
            name = user_input.get("name") or self._discovery_info.name or self._discovery_info.address
            return self.async_create_entry(
                title=name,
                data={
                    "address": self._discovery_info.address,
                    "name": name,
                },
            )
        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema(
                {vol.Optional("name", default=self._discovery_info.name or ""): str}
            ),
            description_placeholders={"address": self._discovery_info.address},
        )

    # ------------------------------------------------------------------
    # Manual entry
    # ------------------------------------------------------------------
    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                address = normalize_mac(user_input["address"])
            except ValueError:
                errors["address"] = "invalid_address"
            else:
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()

                name = user_input.get("name") or address
                return self.async_create_entry(
                    title=name,
                    data={"address": address, "name": name},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("address"): str,
                    vol.Optional("name", default="Lumenize Pro LED Bar"): str,
                }
            ),
            errors=errors,
        )
