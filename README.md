# Extra IOT Updater (Home Assistant integration)

Installs and updates your licensed Extra IOT private integrations directly from
Home Assistant — a clean "Update available → Install" experience, with no access
to private GitHub repos.

## Install (client)
1. In HACS, add this repository as a **custom repository** (category: Integration), or copy `custom_components/extraiot_updater/` into your HA `config/custom_components/`.
2. Restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → Extra IOT Updater**.
4. Enter the server URL (default `https://updates.extraiot.com.mx`) and your **license key**.

To install an integration: **Extra IOT Updater → Configure → Install integrations**,
select the ones you want, then restart Home Assistant when prompted (or call the
`extraiot_updater.install` service with the integration's domain).

Once installed, each integration appears as an **Update** entity, so new versions
show up in Home Assistant's normal updates list. Licensed integrations that are
not installed never appear there, so "Update all" only updates what you run.

## How it works
The integration polls the Extra IOT gateway every 6 hours (or via the
`extraiot_updater.check_now` service), shows one update entity per **installed**
licensed integration, and on install **verifies an Ed25519 signature and SHA-256 checksum**
before replacing files. Tampered or unsigned packages are refused.

## Security
- The embedded **public** key in `const.py` only verifies; it cannot sign.
- Replace `RELEASE_PUBLIC_KEY_B64` with your production key before publishing.
- New Python code loads only after a restart (raised as a repair issue).
