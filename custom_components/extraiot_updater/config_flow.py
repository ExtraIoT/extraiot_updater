"""Config flow: collect server URL + license key.

Options flow (menu):
- Install integrations: pick licensed integrations that aren't installed yet.
- File access: enable + configure the gated file-access API.
"""
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
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

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

CONF_INSTALL_DOMAINS = "domains"


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
    """Install new integrations, or configure the gated file-access API."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init", menu_options=["install", "file_access"]
        )

    # ------------------------------------------------------------------ #
    # Install integrations
    # ------------------------------------------------------------------ #
    async def async_step_install(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        coordinator = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        if coordinator is None:
            return self.async_abort(reason="not_loaded")

        # Make sure the catalog and the on-disk state are current.
        await coordinator.async_refresh()
        available = sorted(coordinator.available_domains())
        if not available:
            return self.async_abort(reason="nothing_to_install")

        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {"error": ""}

        if user_input is not None:
            chosen = [d for d in user_input.get(CONF_INSTALL_DOMAINS, []) if d in available]
            if not chosen:
                errors["base"] = "none_selected"
            else:
                installed: list[str] = []
                failed: list[str] = []
                for domain in chosen:
                    try:
                        await coordinator.async_install(domain, refresh=False)
                        installed.append(domain)
                    except HomeAssistantError as err:
                        failed.append(f"{domain}: {err}")
                await coordinator.async_refresh()
                if failed:
                    errors["base"] = "install_failed"
                    placeholders["error"] = "; ".join(failed)
                    # Anything that did install is no longer offered.
                    available = sorted(coordinator.available_domains())
                    if not available:
                        return self.async_abort(
                            reason="install_failed_abort",
                            description_placeholders=placeholders,
                        )
                else:
                    # Options are unchanged; this step only performs installs.
                    return self.async_create_entry(
                        title="", data=dict(self.config_entry.options)
                    )

        options: list[SelectOptionDict] = []
        for domain in available:
            entry = coordinator.data[domain]
            latest = entry.get("latest") or {}
            label = f"{entry.get('name', domain)} ({latest.get('version', '?')})"
            options.append(SelectOptionDict(value=domain, label=label))

        schema = vol.Schema(
            {
                vol.Required(CONF_INSTALL_DOMAINS, default=[]): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="install",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )

    # ------------------------------------------------------------------ #
    # File access
    # ------------------------------------------------------------------ #
    async def async_step_file_access(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="", data={**self.config_entry.options, **user_input}
            )

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
        return self.async_show_form(step_id="file_access", data_schema=schema)
