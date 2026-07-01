"""Config flow: collect server URL + license key; options for file access."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ExtraIotGatewayClient, GatewayAuthError, GatewayError
from .const import (
    CONF_FILE_ALLOWED_IPS,
    CONF_FILE_ENABLED,
    CONF_FILE_KEY,
    CONF_LICENSE_KEY,
    CONF_SERVER_URL,
    DEFAULT_SERVER_URL,
    DOMAIN,
)


class ExtraIotConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            server = user_input[CONF_SERVER_URL].rstrip("/")
            license_key = user_input[CONF_LICENSE_KEY].strip()
            await self.async_set_unique_id(license_key)
            self._abort_if_unique_id_configured()

            client = ExtraIotGatewayClient(
                async_get_clientsession(self.hass), server, license_key
            )
            try:
                manifest = await client.async_get_manifest()
            except GatewayAuthError:
                errors["base"] = "invalid_license"
            except GatewayError:
                errors["base"] = "cannot_connect"
            else:
                count = len(manifest.get("integrations", []))
                return self.async_create_entry(
                    title=manifest.get("client") or "Extra IOT Updater",
                    data={CONF_SERVER_URL: server, CONF_LICENSE_KEY: license_key},
                    description_placeholders={"count": str(count)},
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_SERVER_URL, default=DEFAULT_SERVER_URL): str,
                vol.Required(CONF_LICENSE_KEY): str,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "ExtraIotOptionsFlow":
        return ExtraIotOptionsFlow()


class ExtraIotOptionsFlow(OptionsFlow):
    """Enable + configure the gated file-access API."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_FILE_ENABLED,
                    default=opts.get(CONF_FILE_ENABLED, False),
                ): bool,
                vol.Optional(
                    CONF_FILE_KEY, default=opts.get(CONF_FILE_KEY, "")
                ): str,
                vol.Optional(
                    CONF_FILE_ALLOWED_IPS,
                    default=opts.get(CONF_FILE_ALLOWED_IPS, ""),
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
