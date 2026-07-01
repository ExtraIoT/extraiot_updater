"""One UpdateEntity per entitled private integration."""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from awesomeversion import AwesomeVersion
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CUSTOM_COMPONENTS,
    DOMAIN,
    NOT_INSTALLED_VERSION,
    RELEASE_PUBLIC_KEY_B64,
)
from .coordinator import ExtraIotCoordinator
from .installer import InstallError, install_package, read_installed_version

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    coordinator: ExtraIotCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        current = set(coordinator.data or {})

        added = []
        for domain in current - known:
            known.add(domain)
            added.append(ExtraIotUpdateEntity(coordinator, domain))
        if added:
            async_add_entities(added)

        # Remove entities whose integration is no longer entitled (e.g. the
        # license lost access). Otherwise they linger as stale "unknown".
        orphaned = known - current
        if orphaned:
            registry = er.async_get(hass)
            for domain in orphaned:
                known.discard(domain)
                ent_id = registry.async_get_entity_id(
                    "update", DOMAIN, f"{DOMAIN}_{domain}"
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
        self._attr_unique_id = f"{DOMAIN}_{domain}"
        self._attr_name = coordinator.data[domain].get("name", domain)

    @property
    def _entry(self) -> dict[str, Any]:
        return self.coordinator.data.get(self._domain, {})

    @property
    def _latest(self) -> dict[str, Any]:
        return self._entry.get("latest", {})

    @property
    def installed_version(self) -> str | None:
        # Report a sentinel (0.0.0) when not yet on disk, so Home Assistant shows
        # the integration as an available install rather than "unknown".
        cc = Path(self.hass.config.path(CUSTOM_COMPONENTS))
        return read_installed_version(cc, self._domain) or NOT_INSTALLED_VERSION

    @property
    def latest_version(self) -> str | None:
        return self._latest.get("version")

    @property
    def release_summary(self) -> str | None:
        notes = self._latest.get("changelog")
        return notes[:255] if notes else None

    async def async_release_notes(self) -> str | None:
        return self._latest.get("changelog")

    def _compatible(self) -> bool:
        min_ha = self._latest.get("min_ha_version")
        if not min_ha:
            return True
        try:
            return AwesomeVersion(HA_VERSION) >= AwesomeVersion(min_ha)
        except Exception:  # noqa: BLE001
            return True

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        latest = self._latest
        if not latest:
            raise HomeAssistantError("No release information available")
        if not self._compatible():
            raise HomeAssistantError(
                f"{self._domain} requires Home Assistant "
                f"{latest.get('min_ha_version')} or newer"
            )

        url = self._entry.get("download_url")
        if not url:
            raise HomeAssistantError("No download URL in manifest")

        tmp = Path(tempfile.mkdtemp(prefix="eiot_dl_"))
        zip_path = tmp / latest.get("filename", f"{self._domain}.zip")
        cc = Path(self.hass.config.path(CUSTOM_COMPONENTS))
        try:
            await self.coordinator.client.async_download(url, str(zip_path))
            await self.hass.async_add_executor_job(
                install_package, zip_path, latest, RELEASE_PUBLIC_KEY_B64, cc
            )
        except InstallError as err:
            raise HomeAssistantError(f"Install rejected: {err}") from err
        finally:
            await self.hass.async_add_executor_job(_cleanup, tmp)

        # A prior "removed" notice no longer applies.
        ir.async_delete_issue(self.hass, DOMAIN, f"removed_{self._domain}")
        # New Python code only loads on restart.
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"restart_required_{self._domain}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="restart_required",
            translation_placeholders={
                "name": self._attr_name,
                "version": latest.get("version", ""),
            },
        )
        self.async_write_ha_state()


def _cleanup(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)
