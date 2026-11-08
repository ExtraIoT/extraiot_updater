"""Uninstalled licensed integrations must not show up as pending updates."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.extraiot_updater.const import (
    CONF_FILE_ENABLED,
    CONF_FILE_KEY,
    CONF_LICENSE_KEY,
    CONF_SERVER_URL,
    DOMAIN,
)

PKG = "custom_components.extraiot_updater"

MANIFEST = {
    "client": "Test client",
    "integrations": [
        {
            "domain": "extraiot_installed",
            "name": "Installed One",
            "latest": {"version": "1.2.0", "changelog": "new stuff"},
            "download_url": "https://x/installed.zip",
        },
        {
            "domain": "extraiot_missing",
            "name": "Missing One",
            "latest": {"version": "2.0.0", "changelog": "hi"},
            "download_url": "https://x/missing.zip",
        },
        {
            "domain": "extraiot_missing2",
            "name": "Missing Two",
            "latest": {"version": "0.3.0"},
            "download_url": "https://x/missing2.zip",
        },
    ],
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def on_disk():
    """Mutable map of what is 'installed' in custom_components."""
    return {"extraiot_installed": "1.0.0"}


@pytest.fixture
def mocks(on_disk):
    with (
        patch(
            f"{PKG}.api.ExtraIotGatewayClient.async_get_manifest",
            new=AsyncMock(return_value=MANIFEST),
        ),
        patch(
            f"{PKG}.coordinator._read_installed_versions",
            side_effect=lambda cc, domains: {d: on_disk.get(d) for d in domains},
        ),
        patch(f"{PKG}.async_register_file_api"),
    ):
        yield


async def _setup(hass: HomeAssistant, options: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="LIC",
        data={CONF_SERVER_URL: "https://updates.example", CONF_LICENSE_KEY: "LIC"},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


def _update_entities(hass: HomeAssistant) -> dict[str, str]:
    return {s.entity_id: s.state for s in hass.states.async_all("update")}


async def test_only_installed_integrations_get_update_entities(hass, mocks):
    await _setup(hass)
    states = _update_entities(hass)
    # Exactly one update entity: the installed one, with a real update pending.
    assert list(states.values()) == ["on"]
    state = hass.states.get(next(iter(states)))
    assert state.attributes["installed_version"] == "1.0.0"
    assert state.attributes["latest_version"] == "1.2.0"


async def test_up_to_date_install_is_not_pending(hass, mocks, on_disk):
    on_disk["extraiot_installed"] = "1.2.0"
    await _setup(hass)
    assert list(_update_entities(hass).values()) == ["off"]


async def test_stale_registry_entries_from_old_versions_are_removed(hass, mocks):
    pre = MockConfigEntry(
        domain=DOMAIN,
        unique_id="LIC",
        data={CONF_SERVER_URL: "https://updates.example", CONF_LICENSE_KEY: "LIC"},
    )
    pre.add_to_hass(hass)
    registry = er.async_get(hass)
    stale = registry.async_get_or_create(
        "update", DOMAIN, f"{DOMAIN}_extraiot_missing", config_entry=pre
    )
    assert await hass.config_entries.async_setup(pre.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(stale.entity_id) is None
    assert len(_update_entities(hass)) == 1


async def test_entity_appears_after_install_and_disappears_after_uninstall(
    hass, mocks, on_disk
):
    entry = await _setup(hass)
    coordinator = hass.data[DOMAIN][entry.entry_id]

    on_disk["extraiot_missing"] = "2.0.0"
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert sorted(_update_entities(hass).values()) == ["off", "on"]

    del on_disk["extraiot_missing"]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(_update_entities(hass)) == 1


async def test_options_menu_and_install_step(hass, mocks):
    entry = await _setup(hass, options={CONF_FILE_ENABLED: True, CONF_FILE_KEY: "k"})

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["install", "file_access"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "install"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "install"
    selector = result["data_schema"].schema["domains"]
    offered = [o["value"] for o in selector.config["options"]]
    assert offered == ["extraiot_missing", "extraiot_missing2"]  # not the installed one

    with patch(
        f"{PKG}.coordinator.ExtraIotCoordinator.async_install",
        new=AsyncMock(return_value="2.0.0"),
    ) as install:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"domains": ["extraiot_missing"]}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    install.assert_awaited_once_with("extraiot_missing", refresh=False)
    # Installing must not wipe the file-access options.
    assert entry.options == {CONF_FILE_ENABLED: True, CONF_FILE_KEY: "k"}


async def test_install_step_reports_failures(hass, mocks):
    from homeassistant.exceptions import HomeAssistantError

    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "install"}
    )
    with patch(
        f"{PKG}.coordinator.ExtraIotCoordinator.async_install",
        new=AsyncMock(side_effect=HomeAssistantError("Install rejected: checksum")),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"domains": ["extraiot_missing2"]}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "install_failed"}
    assert "checksum" in result["description_placeholders"]["error"]


async def test_install_step_aborts_when_everything_installed(hass, mocks, on_disk):
    on_disk.update({"extraiot_missing": "2.0.0", "extraiot_missing2": "0.3.0"})
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "install"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "nothing_to_install"


async def test_file_access_step_saves_options(hass, mocks):
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "file_access"}
    )
    assert result["step_id"] == "file_access"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_FILE_ENABLED: True, CONF_FILE_KEY: "secret", "file_access_allowed_ips": ""},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_FILE_ENABLED] is True
    assert entry.options[CONF_FILE_KEY] == "secret"


async def test_install_service(hass, mocks):
    await _setup(hass)
    with patch(
        f"{PKG}.coordinator.ExtraIotCoordinator.async_install",
        new=AsyncMock(return_value="2.0.0"),
    ) as install:
        await hass.services.async_call(
            DOMAIN, "install", {"domain": "extraiot_missing"}, blocking=True
        )
    install.assert_awaited_once_with("extraiot_missing")

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "install", {"domain": "not_licensed"}, blocking=True
        )


async def test_update_entity_install_uses_shared_helper(hass, mocks):
    await _setup(hass)
    entity_id = next(iter(_update_entities(hass)))
    with patch(
        f"{PKG}.coordinator.ExtraIotCoordinator.async_install",
        new=AsyncMock(return_value="1.2.0"),
    ) as install:
        await hass.services.async_call(
            "update", "install", {"entity_id": entity_id}, blocking=True
        )
    install.assert_awaited_once_with("extraiot_installed")
