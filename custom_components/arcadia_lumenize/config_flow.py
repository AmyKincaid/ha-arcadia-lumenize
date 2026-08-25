"""Config flow for Arcadia / Lumenize BLE LED Bar."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_CONNECTION_MODE,
    CONF_STATUS_POLL_INTERVAL,
    CONF_STATUS_POLLING,
    CONNECTION_MODE_PERSISTENT,
    CONNECTION_MODE_TEMPORARY,
    DEFAULT_CONNECTION_MODE,
    MAX_STATUS_POLL_INTERVAL,
    MIN_STATUS_POLL_INTERVAL,
    DOMAIN,
    normalize_connection_mode,
    normalize_status_poll_interval,
    normalize_status_polling,
)
from .protocol import normalize_mac


class ArcadiaBLEConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Arcadia BLE."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return ArcadiaBLEOptionsFlow(config_entry)

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None

    @staticmethod
    def _build_initial_options_schema(
        *,
        current_mode: str = DEFAULT_CONNECTION_MODE,
        current_status_polling: bool | None = None,
        current_status_poll_interval: int | None = None,
    ) -> vol.Schema:
        """Build schema for initial connection and polling options."""
        normalized_mode = normalize_connection_mode(current_mode)
        normalized_status_polling = normalize_status_polling(
            current_status_polling,
            normalized_mode,
        )
        normalized_status_poll_interval = normalize_status_poll_interval(
            current_status_poll_interval,
            CONNECTION_MODE_TEMPORARY,
            True,
        )

        return vol.Schema(
            {
                vol.Required(
                    CONF_CONNECTION_MODE,
                    default=normalized_mode,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            CONNECTION_MODE_PERSISTENT,
                            CONNECTION_MODE_TEMPORARY,
                        ],
                        translation_key=CONF_CONNECTION_MODE,
                    )
                ),
                vol.Required(
                    CONF_STATUS_POLLING,
                    default=normalized_status_polling,
                ): bool,
                vol.Required(
                    CONF_STATUS_POLL_INTERVAL,
                    default=normalized_status_poll_interval,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_STATUS_POLL_INTERVAL,
                        max=MAX_STATUS_POLL_INTERVAL,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )

    @staticmethod
    def _normalize_initial_options(user_input: dict) -> dict:
        """Normalize and validate initial options entered by the user."""
        normalized_mode = normalize_connection_mode(
            user_input.get(CONF_CONNECTION_MODE)
        )
        status_polling = normalize_status_polling(
            user_input.get(CONF_STATUS_POLLING),
            normalized_mode,
        )
        status_poll_interval = normalize_status_poll_interval(
            user_input.get(CONF_STATUS_POLL_INTERVAL),
            CONNECTION_MODE_TEMPORARY,
            True,
        )

        return {
            CONF_CONNECTION_MODE: normalized_mode,
            CONF_STATUS_POLLING: status_polling,
            CONF_STATUS_POLL_INTERVAL: status_poll_interval,
        }

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle a discovered BLE device."""
        if not discovery_info.connectable:
            return self.async_abort(reason="not_connectable")

        # The official Arcadia LumenIZE Android app only accepts scanned
        # devices whose BLE name contains "Arcadia".
        #
        # Keep this check in addition to the manifest matcher so unrelated
        # devices advertising generic FFF0/manufacturer data cannot create
        # false Arcadia discovery flows.
        device_name = discovery_info.name or ""
        if "arcadia" not in device_name.lower():
            return self.async_abort(reason="not_arcadia_device")

        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Confirm a discovered Arcadia device."""
        assert self._discovery_info is not None

        if user_input is not None:
            name = (
                user_input.get("name")
                or self._discovery_info.name
                or self._discovery_info.address
            )
            options = self._normalize_initial_options(user_input)
            return self.async_create_entry(
                title=name,
                data={
                    "address": self._discovery_info.address,
                    "name": name,
                },
                options=options,
            )

        options_schema = self._build_initial_options_schema()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=options_schema.extend(
                {
                    vol.Optional(
                        "name",
                        default=self._discovery_info.name or "",
                    ): str
                }
            ),
            description_placeholders={
                "address": self._discovery_info.address,
                "min_interval": str(MIN_STATUS_POLL_INTERVAL),
                "max_interval": str(MAX_STATUS_POLL_INTERVAL),
            },
        )

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Handle manual setup."""
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
                options = self._normalize_initial_options(user_input)
                return self.async_create_entry(
                    title=name,
                    data={
                        "address": address,
                        "name": name,
                    },
                    options=options,
                )

        options_schema = self._build_initial_options_schema(
            current_mode=(user_input or {}).get(
                CONF_CONNECTION_MODE,
                DEFAULT_CONNECTION_MODE,
            ),
            current_status_polling=(user_input or {}).get(CONF_STATUS_POLLING),
            current_status_poll_interval=(user_input or {}).get(
                CONF_STATUS_POLL_INTERVAL
            ),
        )
        return self.async_show_form(
            step_id="user",
            data_schema=options_schema.extend(
                {
                    vol.Required(
                        "address",
                        default=(user_input or {}).get("address", ""),
                    ): str,
                    vol.Optional(
                        "name",
                        default=(user_input or {}).get(
                            "name",
                            "Lumenize Pro LED Bar",
                        ),
                    ): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "min_interval": str(MIN_STATUS_POLL_INTERVAL),
                "max_interval": str(MAX_STATUS_POLL_INTERVAL),
            },
        )


class ArcadiaBLEOptionsFlow(config_entries.OptionsFlow):
    """Handle Arcadia integration options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict | None = None,
    ) -> FlowResult:
        current_mode = normalize_connection_mode(
            self._config_entry.options.get(
                CONF_CONNECTION_MODE,
                DEFAULT_CONNECTION_MODE,
            )
        )

        if user_input is not None:
            normalized_mode = normalize_connection_mode(
                user_input.get(CONF_CONNECTION_MODE)
            )

            if CONF_STATUS_POLLING in user_input:
                status_polling_input = user_input.get(CONF_STATUS_POLLING)
            else:
                status_polling_input = self._config_entry.options.get(
                    CONF_STATUS_POLLING
                )

            status_polling = normalize_status_polling(
                status_polling_input,
                normalized_mode,
            )

            if CONF_STATUS_POLL_INTERVAL in user_input:
                interval_input = user_input.get(CONF_STATUS_POLL_INTERVAL)
            else:
                interval_input = self._config_entry.options.get(
                    CONF_STATUS_POLL_INTERVAL
                )

            status_poll_interval = normalize_status_poll_interval(
                interval_input,
                CONNECTION_MODE_TEMPORARY,
                True,
            )

            return self.async_create_entry(
                title="",
                data={
                    CONF_CONNECTION_MODE: normalized_mode,
                    CONF_STATUS_POLLING: status_polling,
                    CONF_STATUS_POLL_INTERVAL: status_poll_interval,
                },
            )

        current_status_polling = normalize_status_polling(
            self._config_entry.options.get(CONF_STATUS_POLLING),
            current_mode,
        )
        current_status_poll_interval = normalize_status_poll_interval(
            self._config_entry.options.get(CONF_STATUS_POLL_INTERVAL),
            CONNECTION_MODE_TEMPORARY,
            True,
        )

        schema_fields: dict = {
            vol.Required(
                CONF_CONNECTION_MODE,
                default=current_mode,
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        CONNECTION_MODE_PERSISTENT,
                        CONNECTION_MODE_TEMPORARY,
                    ],
                    translation_key=CONF_CONNECTION_MODE,
                )
            ),
            vol.Required(
                CONF_STATUS_POLLING,
                default=current_status_polling,
            ): bool,
            vol.Required(
                CONF_STATUS_POLL_INTERVAL,
                default=current_status_poll_interval,
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_STATUS_POLL_INTERVAL,
                    max=MAX_STATUS_POLL_INTERVAL,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        }

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_fields),
            description_placeholders={
                "min_interval": str(MIN_STATUS_POLL_INTERVAL),
                "max_interval": str(MAX_STATUS_POLL_INTERVAL),
            },
        )
