"""Vendored from extraiot_updater_phase1/scripts/eiot_crypto.py.

VERIFY-ONLY use on the client. Must stay byte-identical to the signer's copy
so canonicalization always matches. `cryptography` ships with Home Assistant.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

SIGNATURE_FIELD = "signature"


def canonical_bytes(payload: dict) -> bytes:
    body = {k: v for k, v in payload.items() if k != SIGNATURE_FIELD}
    return json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_public_key_b64(b64: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(b64))


def verify_payload(public_key_b64: str, payload: dict) -> bool:
    sig_b64 = payload.get(SIGNATURE_FIELD)
    if not sig_b64:
        return False
    try:
        load_public_key_b64(public_key_b64).verify(
            base64.b64decode(sig_b64), canonical_bytes(payload)
        )
        return True
    except (InvalidSignature, ValueError):
        return False


def verify_zip(release: dict, zip_path: str | Path) -> bool:
    expected = release.get("sha256")
    return bool(expected) and sha256_file(zip_path) == expected
