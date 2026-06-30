"""Constants for the Extra IOT Updater integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "extraiot_updater"

CONF_SERVER_URL = "server_url"
CONF_LICENSE_KEY = "license_key"

DEFAULT_SERVER_URL = "https://updates.extraiot.com.mx"

# How often to poll the gateway for new versions.
UPDATE_INTERVAL = timedelta(hours=6)

# Embedded Ed25519 PUBLIC key (base64 of the raw 32 bytes). Verification only.
# !!! REPLACE with your production public key from genkeys.py before release.
# This value matches the Phase 1 test keypair so the bundled example works.
RELEASE_PUBLIC_KEY_B64 = "m1XwDpPQHJqIqxVoSBjCM8zFpjqohLzoiFWtbyqBpW0="

# Where client integrations are installed.
CUSTOM_COMPONENTS = "custom_components"
