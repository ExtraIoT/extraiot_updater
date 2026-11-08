# Changelog

## 1.4.0

- **"Update all" no longer installs every Extra IOT integration.** Update entities now exist only for integrations that are actually installed on this Home Assistant, so the updates list (and "Update all") only offers real updates.
- New integrations are installed on purpose instead: **Settings → Devices & Services → Extra IOT Updater → Configure → Install integrations** lists the licensed integrations that aren't installed yet. Select the ones you want; each is verified (signature + checksum) before it is written, then restart Home Assistant.
- New service `extraiot_updater.install` (domain) to install or reinstall a licensed integration — the counterpart of `extraiot_updater.uninstall`.
- After upgrading, the leftover "available update" entities for integrations that were never installed are removed automatically.
- The integration's Configure menu now has two entries: *Install integrations* and *File access API* (same settings as before).
