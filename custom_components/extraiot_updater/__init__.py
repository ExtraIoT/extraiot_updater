"""The Extra IOT Updater integration."""
from __future__ import annotations

from pathlib import Path

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import issue_registry as ir

from .const import (
    CONF_FILE_ALLOWED_IPS,
    CONF_FILE_ENABLED,
    CONF_FILE_KEY,
    CUSTOM_COMPONENTS,
    DOMAIN,
)
from .coordinator import ExtraIotCoordinator
from .file_api import FileConfig, async_register_file_api, parse_allowed_ips
from .installer import uninstall_package

PLATFORMS = [Platform.UPDATE, Platform.BUTTON]

UNINSTALL_SCHEMA = vol.Schema({vol.Required("domain"): str})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = ExtraIotCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Gated file-access API. Registered once; reads config live from options.
    def _file_config() -> FileConfig:
        for cfg_entry in hass.config_entries.async_entries(DOMAIN):
            opts = cfg_entry.options
            return (
                bool(opts.get(CONF_FILE_ENABLED, False)),
                str(opts.get(CONF_FILE_KEY, "") or ""),
                parse_allowed_ips(opts.get(CONF_FILE_ALLOWED_IPS, "")),
            )
        return (False, "", [])

    async_register_file_api(hass, _file_config)

    async def _handle_check_now(call: ServiceCall) -> None:
        for coord in hass.data.get(DOMAIN, {}).values():
            await coord.async_request_refresh()

    async def _handle_uninstall(call: ServiceCall) -> None:
        domain = call.data["domain"]
        managed: set[str] = set()
        for coord in hass.data.get(DOMAIN, {}).values():
            managed |= set(coord.data or {})
        if domain not in managed:
            raise ServiceValidationError(
                f"'{domain}' is not a licensed Extra IOT integration on this system"
            )
        cc = Path(hass.config.path(CUSTOM_COMPONENTS))
        removed = await hass.async_add_executor_job(uninstall_package, cc, domain)
        if removed:
            ir.async_delete_issue(hass, DOMAIN, f"restart_required_{domain}")
            ir.async_create_issue(
                hass,
                DOMAIN,
                f"removed_{domain}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="removed_restart_required",
                translation_placeholders={"name": domain},
            )
        # installed_version is served from coordinator.data, so re-rendering
        # the entities would just replay the pre-uninstall value. Refresh so
        # the coordinator re-reads the disk.
        for coord in hass.data.get(DOMAIN, {}).values():
            await coord.async_request_refresh()

    if not hass.services.has_service(DOMAIN, "check_now"):
        hass.services.async_register(DOMAIN, "check_now", _handle_check_now)
    if not hass.services.has_service(DOMAIN, "uninstall"):
        hass.services.async_register(
            DOMAIN, "uninstall", _handle_uninstall, schema=UNINSTALL_SCHEMA
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, "check_now")
            hass.services.async_remove(DOMAIN, "uninstall")
    # The registered HTTP view stays for the life of the HA process; it returns
    # 404 while disabled, so leaving it registered is harmless.
    return unload_ok
