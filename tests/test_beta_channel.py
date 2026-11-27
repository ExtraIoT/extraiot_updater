"""Per-integration beta channel."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.extraiot_updater.const import (
    CONF_BETA_DOMAINS,
    CONF_LICENSE_KEY,
    CONF_SERVER_URL,
    DOMAIN,
)

PKG = "custom_components.extraiot_updater"

MANIFEST = {
    "client": "Test client",
    "integrations": [
        {
            "domain": "extraiot_a",
            "name": "Alpha",
            "latest": {"version": "1.2.0", "changelog": "stable notes"},
            "download_url": "https://x/a/1.2.0",
            "latest_beta": {"version": "1.3.0-beta.2", "changelog": "beta notes"},
            "beta_download_url": "https://x/a/1.3.0-beta.2",
        },
        {
            "domain": "extraiot_new",
            "name": "Brand New",
            "latest_beta": {"version": "0.1.0-beta.1"},
            "beta_download_url": "https://x/new/0.1.0-beta.1",
        },
    ],
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def on_disk():
    return {"extraiot_a": "1.2.0"}


@pytest.fixture
def manifest_mock():
    return AsyncMock(return_value=MANIFEST)


@pytest.fixture
def mocks(on_disk, manifest_mock):
    with (
        patch(f"{PKG}.api.ExtraIotGatewayClient.async_get_manifest", new=manifest_mock),
        patch(
            f"{PKG}.coordinator._read_installed_versions",
            side_effect=lambda cc, domains: {d: on_disk.get(d) for d in domains},
        ),
        patch(f"{PKG}.async_register_file_api"),
    ):
        yield


async def _setup(hass: HomeAssistant, options: dict | None = None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="LIC",
        data={CONF_SERVER_URL: "https://updates.example", CONF_LICENSE_KEY: "LIC"},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _one(hass, platform):
    states = hass.states.async_all(platform)
    assert len(states) == 1, [s.entity_id for s in states]
    return states[0]


async def test_manifest_requested_with_betas(hass, mocks, manifest_mock):
    await _setup(hass)
    manifest_mock.assert_awaited_with(include_beta=True)


async def test_switch_off_by_default_tracks_stable(hass, mocks):
    await _setup(hass)
    sw = _one(hass, "switch")
    assert sw.state == "off"
    assert sw.attributes["latest_beta"] == "1.3.0-beta.2"
    up = _one(hass, "update")
    assert up.state == "off"
    assert up.attributes["latest_version"] == "1.2.0"


async def test_turning_beta_on_offers_beta(hass, mocks):
    entry = await _setup(hass)
    sw = _one(hass, "switch")
    await hass.services.async_call("switch", "turn_on", {"entity_id": sw.entity_id}, blocking=True)
    await hass.async_block_till_done()
    assert entry.options[CONF_BETA_DOMAINS] == ["extraiot_a"]
    assert hass.states.get(sw.entity_id).state == "on"
    up = _one(hass, "update")
    assert up.state == "on"
    assert up.attributes["latest_version"] == "1.3.0-beta.2"
    assert up.attributes["release_summary"].startswith("BETA.")


async def test_beta_choice_survives_reload(hass, mocks):
    entry = await _setup(hass, {CONF_BETA_DOMAINS: ["extraiot_a"]})
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _one(hass, "switch").state == "on"
    assert _one(hass, "update").attributes["latest_version"] == "1.3.0-beta.2"


async def test_turning_beta_off_offers_lower_stable(hass, mocks, on_disk):
    on_disk["extraiot_a"] = "1.3.0-beta.2"
    await _setup(hass, {CONF_BETA_DOMAINS: ["extraiot_a"]})
    up = _one(hass, "update")
    assert up.state == "off"  # running the newest beta
    sw = _one(hass, "switch")
    await hass.services.async_call("switch", "turn_off", {"entity_id": sw.entity_id}, blocking=True)
    await hass.async_block_till_done()
    up = _one(hass, "update")
    assert up.attributes["latest_version"] == "1.2.0"
    assert up.state == "on"  # going back to stable is offered


async def test_stable_release_supersedes_installed_beta(hass, mocks, on_disk, manifest_mock):
    on_disk["extraiot_a"] = "1.3.0-beta.2"
    manifest_mock.return_value = {
        "integrations": [
            {
                "domain": "extraiot_a",
                "name": "Alpha",
                "latest": {"version": "1.3.0"},
                "download_url": "https://x/a/1.3.0",
            }
        ]
    }
    await _setup(hass, {CONF_BETA_DOMAINS: ["extraiot_a"]})
    up = _one(hass, "update")
    assert up.attributes["latest_version"] == "1.3.0"
    assert up.state == "on"


async def test_install_uses_beta_url_when_on(hass, mocks):
    entry = await _setup(hass, {CONF_BETA_DOMAINS: ["extraiot_a"]})
    coordinator = hass.data[DOMAIN][entry.entry_id]
    with (
        patch(f"{PKG}.api.ExtraIotGatewayClient.async_download", new=AsyncMock()) as dl,
        patch(f"{PKG}.coordinator.install_package") as inst,
    ):
        assert await coordinator.async_install("extraiot_a") == "1.3.0-beta.2"
    assert dl.await_args.args[0] == "https://x/a/1.3.0-beta.2"
    assert inst.call_args.args[1]["version"] == "1.3.0-beta.2"


async def test_beta_only_integration_is_installable(hass, mocks):
    entry = await _setup(hass)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert "extraiot_new" in coordinator.available_domains()
    release, url = coordinator.target("extraiot_new")
    assert release["version"] == "0.1.0-beta.1" and url.endswith("0.1.0-beta.1")
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "install"}
    )
    labels = [o["label"] for o in result["data_schema"].schema["domains"].config["options"]]
    assert "Brand New (0.1.0-beta.1 - beta)" in labels
