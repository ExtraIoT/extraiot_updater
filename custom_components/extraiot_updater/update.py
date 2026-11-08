"""One UpdateEntity per licensed private integration that is INSTALLED here.

Integrations that are licensed but not on disk do not get an update entity:
otherwise Home Assistant counts them as pending updates and "Update all"
installs every published integration. New integrations are installed from the
options flow ("Install integrations") or the ``extraiot_updater.install``
service instead.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import INSTALLED_KEY, ExtraIotCoordinator

_LOGGER = logging.getLogger(__name__)

_UNIQUE_PREFIX = f"{DOMAIN}_"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    coordinator: ExtraIotCoordinator = hass.data[DOMAIN][entry.entry_id]
    registry = er.async_get(hass)

    # One-time cleanup: earlier versions created an update entity for every
    # licensed integration, installed or not. Drop the registry entries for
    # the ones that aren't on disk so they don't linger as "unavailable".
    installed_now = coordinator.installed_domains()
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.domain != "update":
            continue
        domain = reg_entry.unique_id.removeprefix(_UNIQUE_PREFIX)
        if domain not in installed_now:
            registry.async_remove(reg_entry.entity_id)

    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        current = coordinator.installed_domains()

        added = []
        for domain in current - known:
            known.add(domain)
            added.append(ExtraIotUpdateEntity(coordinator, domain))
        if added:
            async_add_entities(added)

        # Remove entities whose integration was uninstalled or is no longer
        # licensed. Otherwise they linger as stale "unknown".
        orphaned = known - current
        if orphaned:
            for domain in orphaned:
                known.discard(domain)
                ent_id = registry.async_get_entity_id(
                    "update", DOMAIN, f"{_UNIQUE_PREFIX}{domain}"
                )
                if ent_id:
                    registry.async_remove(ent_id)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class ExtraIotUpdateEntity(CoordinatorEntity[ExtraIotCoordinator], UpdateEntity):
    """Update entity backed by the gateway manifest + on-disk version."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.RELEASE_NOTES
    )

    def __init__(self, coordinator: ExtraIotCoordinator, domain: str) -> None:
        super().__init__(coordinator)
        self._domain = domain
        self._attr_unique_id = f"{_UNIQUE_PREFIX}{domain}"
        self._attr_name = coordinator.data[domain].get("name", domain)

    @property
    def _entry(self) -> dict[str, Any]:
        return self.coordinator.data.get(self._domain, {})

    @property
    def _latest(self) -> dict[str, Any]:
        return self._entry.get("latest", {})

    @property
    def installed_version(self) -> str | None:
        # Served from coordinator.data, which the coordinator populates in an
        # executor. This property is evaluated on the event loop on every state
        # write, so it must not touch the disk. Entities only exist for
        # installed integrations, so this is a real on-disk version.
        return self._entry.get(INSTALLED_KEY)

    @property
    def latest_version(self) -> str | None:
        return self._latest.get("version")

    @property
    def release_summary(self) -> str | None:
        notes = self._latest.get("changelog")
        return notes[:255] if notes else None

    async def async_release_notes(self) -> str | None:
        return self._latest.get("changelog")

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        await self.coordinator.async_install(self._domain)
