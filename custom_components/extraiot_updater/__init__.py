"""The Extra IOT Updater integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall

from .const import (
    CONF_FILE_ALLOWED_IPS,
    CONF_FILE_ENABLED,
    CONF_FILE_KEY,
    DOMAIN,
)
from .coordinator import ExtraIotCoordinator
from .file_api import FileConfig, async_register_file_api, parse_allowed_ips

PLATFORMS = [Platform.UPDATE]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = ExtraIotCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Gated file-access API. The view is registered once; it reads its config
    # live from the (single) updater config entry's options, so toggling it in
    # the Options UI takes effect without a restart.
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

    if not hass.services.has_service(DOMAIN, "check_now"):
        hass.services.async_register(DOMAIN, "check_now", _handle_check_now)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, "check_now")
    # Note: the registered HTTP view stays for the life of the HA process; it
    # returns 404 while disabled, so leaving it registered is harmless.
    return unload_ok
