"""Polls the gateway and exposes the per-integration latest-version map."""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from awesomeversion import AwesomeVersion
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ExtraIotGatewayClient, GatewayAuthError, GatewayError
from .const import (
    CONF_LICENSE_KEY,
    CONF_SERVER_URL,
    CUSTOM_COMPONENTS,
    DOMAIN,
    RELEASE_PUBLIC_KEY_B64,
    UPDATE_INTERVAL,
)
from .installer import InstallError, install_package, read_installed_version

_LOGGER = logging.getLogger(__name__)


def _read_installed_versions(
    custom_components: Path, domains: tuple[str, ...]
) -> dict[str, str | None]:
    """Read every on-disk manifest in a single executor job.

    Entities cannot do this themselves: ``UpdateEntity.installed_version`` is
    a synchronous property that Home Assistant evaluates on the event loop,
    and reading the manifest is blocking I/O. Batching the reads here costs
    one executor hop per poll instead of one per entity per state write.
    """
    return {d: read_installed_version(custom_components, d) for d in domains}


def _make_download_dir() -> str:
    return tempfile.mkdtemp(prefix="eiot_dl_")


def _cleanup(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


# Key under which the on-disk version is merged into each manifest entry.
INSTALLED_KEY = "installed"


class ExtraIotCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Keeps the manifest fresh. data = {domain: integration_entry}.

    ``data`` is the full licensed catalog. Whether an integration is actually
    on this system is ``entry[INSTALLED_KEY]`` (None when not on disk).
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.entry = entry
        self.client = ExtraIotGatewayClient(
            async_get_clientsession(hass),
            entry.data[CONF_SERVER_URL],
            entry.data[CONF_LICENSE_KEY],
        )

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            manifest = await self.client.async_get_manifest()
        except GatewayAuthError as err:
            # Surface as a clear, non-retrying auth problem.
            raise UpdateFailed(f"License rejected: {err}") from err
        except GatewayError as err:
            raise UpdateFailed(f"Gateway unreachable: {err}") from err
        integrations = {i["domain"]: dict(i) for i in manifest.get("integrations", [])}
        installed = await self.hass.async_add_executor_job(
            _read_installed_versions,
            Path(self.hass.config.path(CUSTOM_COMPONENTS)),
            tuple(integrations),
        )
        for domain, entry in integrations.items():
            entry[INSTALLED_KEY] = installed.get(domain)
        return integrations

    # ------------------------------------------------------------------ #
    # Catalog views
    # ------------------------------------------------------------------ #
    def installed_domains(self) -> set[str]:
        """Licensed integrations that are on disk on this system."""
        return {d for d, e in (self.data or {}).items() if e.get(INSTALLED_KEY)}

    def available_domains(self) -> set[str]:
        """Licensed integrations that are NOT installed on this system."""
        return set(self.data or {}) - self.installed_domains()

    @staticmethod
    def is_compatible(latest: dict[str, Any]) -> bool:
        min_ha = latest.get("min_ha_version")
        if not min_ha:
            return True
        try:
            return AwesomeVersion(HA_VERSION) >= AwesomeVersion(min_ha)
        except Exception:  # noqa: BLE001
            return True

    # ------------------------------------------------------------------ #
    # Install (shared by the update entity, the install service and the
    # options-flow "Install integrations" step)
    # ------------------------------------------------------------------ #
    async def async_install(self, domain: str, *, refresh: bool = True) -> str:
        """Download, verify and install the latest release of ``domain``.

        Returns the installed version. Raises HomeAssistantError on failure.
        """
        entry = (self.data or {}).get(domain)
        if entry is None:
            raise HomeAssistantError(
                f"'{domain}' is not a licensed Extra IOT integration"
            )
        latest = entry.get("latest") or {}
        if not latest:
            raise HomeAssistantError("No release information available")
        if not self.is_compatible(latest):
            raise HomeAssistantError(
                f"{domain} requires Home Assistant "
                f"{latest.get('min_ha_version')} or newer"
            )
        url = entry.get("download_url")
        if not url:
            raise HomeAssistantError("No download URL in manifest")

        tmp = Path(await self.hass.async_add_executor_job(_make_download_dir))
        zip_path = tmp / latest.get("filename", f"{domain}.zip")
        cc = Path(self.hass.config.path(CUSTOM_COMPONENTS))
        try:
            await self.client.async_download(url, str(zip_path))
            await self.hass.async_add_executor_job(
                install_package, zip_path, latest, RELEASE_PUBLIC_KEY_B64, cc
            )
        except InstallError as err:
            raise HomeAssistantError(f"Install rejected: {err}") from err
        except GatewayError as err:
            raise HomeAssistantError(f"Download failed: {err}") from err
        finally:
            await self.hass.async_add_executor_job(_cleanup, tmp)

        version = latest.get("version", "")
        # A prior "removed" notice no longer applies.
        ir.async_delete_issue(self.hass, DOMAIN, f"removed_{domain}")
        # New Python code only loads on restart.
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"restart_required_{domain}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="restart_required",
            translation_placeholders={
                "name": entry.get("name", domain),
                "version": version,
            },
        )
        # installed_version lives in coordinator.data, so the coordinator has
        # to re-read the disk. A fresh install also makes its update entity
        # appear (update.py only creates entities for installed integrations).
        if refresh:
            await self.async_request_refresh()
        return version
