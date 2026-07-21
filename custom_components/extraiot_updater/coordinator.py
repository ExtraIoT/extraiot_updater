"""Polls the gateway and exposes the per-integration latest-version map."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ExtraIotGatewayClient, GatewayAuthError, GatewayError
from .const import (
    CONF_LICENSE_KEY,
    CONF_SERVER_URL,
    CUSTOM_COMPONENTS,
    DOMAIN,
    UPDATE_INTERVAL,
)
from .installer import read_installed_version

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


# Key under which the on-disk version is merged into each manifest entry.
INSTALLED_KEY = "installed"


class ExtraIotCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Keeps the manifest fresh. data = {domain: integration_entry}."""

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
