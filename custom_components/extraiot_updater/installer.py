"""Install logic for private integrations. Deliberately free of Home Assistant
imports so it can be unit-tested standalone and run inside an executor thread.

Safety order: verify signature -> verify checksum -> validate ZIP shape ->
backup current -> extract to temp -> atomic swap. Any failure rolls back.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from .eiot_crypto import verify_payload, verify_zip


class InstallError(Exception):
    """Any failure that must abort an install (verification or filesystem)."""


def read_installed_version(custom_components: Path, domain: str) -> str | None:
    manifest = custom_components / domain / "manifest.json"
    if not manifest.is_file():
        return None
    try:
        return json.loads(manifest.read_text(encoding="utf-8")).get("version")
    except (json.JSONDecodeError, OSError):
        return None


def verify_package(release: dict, zip_path: Path, public_key_b64: str) -> None:
    if not verify_payload(public_key_b64, release):
        raise InstallError("signature verification failed")
    if not verify_zip(release, zip_path):
        raise InstallError("checksum mismatch")


def _validate_zip_shape(zip_path: Path, domain: str) -> None:
    """Every entry must live under the single top-level <domain>/ folder and
    must not escape it (zip-slip protection)."""
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if not names:
            raise InstallError("empty ZIP")
        for name in names:
            norm = os.path.normpath(name)
            if norm.startswith("..") or os.path.isabs(norm):
                raise InstallError(f"unsafe path in ZIP: {name}")
            top = norm.split(os.sep, 1)[0]
            if top != domain:
                raise InstallError(
                    f"ZIP top-level '{top}' does not match domain '{domain}'"
                )


def install_package(
    zip_path: Path, release: dict, public_key_b64: str, custom_components: Path
) -> None:
    """Verify and install. Raises InstallError on any problem (with rollback)."""
    domain = release["domain"]
    verify_package(release, zip_path, public_key_b64)
    _validate_zip_shape(zip_path, domain)

    custom_components.mkdir(parents=True, exist_ok=True)
    target = custom_components / domain
    backup = custom_components / f".{domain}.backup"
    staging = Path(tempfile.mkdtemp(prefix="eiot_", dir=custom_components))

    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(staging)
        new_dir = staging / domain
        if not (new_dir / "manifest.json").is_file():
            raise InstallError("extracted package missing manifest.json")
        if backup.exists():
            shutil.rmtree(backup)
        if target.exists():
            os.replace(target, backup)
        try:
            os.replace(new_dir, target)
        except OSError as err:
            if backup.exists():
                os.replace(backup, target)
            raise InstallError(f"swap failed: {err}") from err
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def uninstall_package(custom_components: Path, domain: str) -> bool:
    """Remove an installed integration, keeping a one-slot backup.

    Returns True if something was removed, False if it wasn't installed.
    """
    target = custom_components / domain
    if not target.exists():
        return False
    backup = custom_components / f".{domain}.removed"
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    os.replace(target, backup)  # atomic move aside (acts as backup)
    return True
