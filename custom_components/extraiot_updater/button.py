"""One-click 'Check for updates' button for the Extra IOT Updater."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ExtraIotCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: ExtraIotCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ExtraIotCheckButton(coordinator, entry)])


class ExtraIotCheckButton(ButtonEntity):
    """Forces an immediate poll of the update gateway (no reload needed)."""

    _attr_has_entity_name = True
    _attr_name = "Check for updates"
    _attr_icon = "mdi:cloud-refresh"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ExtraIotCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_check_now"

    async def async_press(self) -> None:
        await self._coordinator.async_request_refresh()
