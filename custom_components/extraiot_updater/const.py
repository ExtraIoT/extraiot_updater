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
# PRODUCTION key. The matching private key lives ONLY on the self-hosted runner.
# Rotating it means re-signing existing releases and shipping an updater update.
RELEASE_PUBLIC_KEY_B64 = "csoZRvS+caIRtuBHKxjBSlMpZyXn8VDnGPXAytsfyoE="

# Where client integrations are installed.
CUSTOM_COMPONENTS = "custom_components"

# Reported as installed_version when a licensed integration is not yet on disk,
# so Home Assistant offers it as an install (0.0.0 < any real version).
NOT_INSTALLED_VERSION = "0.0.0"

# --- Gated file-access API (see file_api.py) -------------------------------
# All optional; configured via the integration's Options flow. The endpoint is
# OFF unless CONF_FILE_ENABLED is true, and always requires the shared key +
# admin token (+ source allowlist if set).
CONF_FILE_ENABLED = "file_access_enabled"
CONF_FILE_KEY = "file_access_key"
CONF_FILE_ALLOWED_IPS = "file_access_allowed_ips"

FILE_API_URL = "/api/extraiot_updater/files"
FILE_API_MAX_BYTES = 5 * 1024 * 1024  # 5 MB cap on read + write
