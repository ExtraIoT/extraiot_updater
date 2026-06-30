"""Polls the gateway and exposes the per-integration latest-version map."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ExtraIotGatewayClient, GatewayAuthError, GatewayError
from .const import (
    CONF_LICENSE_KEY,
    CONF_SERVER_URL,
    DOMAIN,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


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
        return {i["domain"]: i for i in manifest.get("integrations", [])}
