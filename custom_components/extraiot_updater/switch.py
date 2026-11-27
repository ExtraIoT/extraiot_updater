"""One "beta channel" switch per installed Extra IOT integration.

Off (default): the integration's update entity follows stable releases.
On: it also offers betas (versions tagged like v1.3.0-beta.1) when a beta
newer than the newest stable exists. Turning it off offers the newest stable
again, even if that is a lower version than the beta that is installed.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ExtraIotCoordinator

_UNIQUE_PREFIX = f"{DOMAIN}_beta_"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    coordinator: ExtraIotCoordinator = hass.data[DOMAIN][entry.entry_id]
    registry = er.async_get(hass)
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        current = coordinator.installed_domains()
        added = []
        for domain in current - known:
            known.add(domain)
            added.append(ExtraIotBetaSwitch(coordinator, domain))
        if added:
            async_add_entities(added)
        for domain in known - current:
            known.discard(domain)
            ent_id = registry.async_get_entity_id(
                "switch", DOMAIN, f"{_UNIQUE_PREFIX}{domain}"
            )
            if ent_id:
                registry.async_remove(ent_id)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class ExtraIotBetaSwitch(CoordinatorEntity[ExtraIotCoordinator], SwitchEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "beta"
    _attr_icon = "mdi:flask-outline"

    def __init__(self, coordinator: ExtraIotCoordinator, domain: str) -> None:
        super().__init__(coordinator)
        self._domain = domain
        self._attr_unique_id = f"{_UNIQUE_PREFIX}{domain}"
        self._attr_translation_placeholders = {
            "name": coordinator.data[domain].get("name", domain)
        }

    @property
    def is_on(self) -> bool:
        return self.coordinator.is_beta(self._domain)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        beta = (self.coordinator.data or {}).get(self._domain, {}).get("latest_beta")
        return {"latest_beta": beta.get("version") if beta else None}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_beta(self._domain, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_beta(self._domain, False)
