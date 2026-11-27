# Changelog

## 1.5.0

- **Beta channel per integration.** Each installed Extra IOT integration now has a *beta channel* switch (Settings → Devices & Services → Extra IOT Updater → entities). Off by default: the integration only gets stable releases. On: its update also offers beta versions (e.g. `1.3.0-beta.1`) when there is one newer than the latest stable; the release notes start with "BETA".
- Turning the switch off goes back to the latest stable release, even if it is a lower version than the beta that is installed.
- Integrations that only have beta releases so far can be installed from *Configure → Install integrations* (shown as "- beta").
- Needs gateway support for betas; with an older gateway nothing changes (stable only).

## 1.4.0

- **"Update all" no longer installs every Extra IOT integration.** Update entities now exist only for integrations that are actually installed on this Home Assistant, so the updates list (and "Update all") only offers real updates.
- New integrations are installed on purpose instead: **Settings → Devices & Services → Extra IOT Updater → Configure → Install integrations** lists the licensed integrations that aren't installed yet. Select the ones you want; each is verified (signature + checksum) before it is written, then restart Home Assistant.
- New service `extraiot_updater.install` (domain) to install or reinstall a licensed integration — the counterpart of `extraiot_updater.uninstall`.
- After upgrading, the leftover "available update" entities for integrations that were never installed are removed automatically.
- The integration's Configure menu now has two entries: *Install integrations* and *File access API* (same settings as before).
