"""Admin-gated file read/write API for Extra IOT tooling.

Endpoints (served under Home Assistant's own auth + your loadbalancer):

  GET  /api/extraiot_updater/files?path=<rel>          -> read a file (text)
  GET  /api/extraiot_updater/files?path=<rel>&list=1   -> list a directory
  POST /api/extraiot_updater/files                     -> write a file
       JSON body: {"path": "<rel>", "content": "<text>"}

EVERY request must pass ALL of these, or it is refused:
  1. Home Assistant auth (``requires_auth``) — a valid token for THIS instance.
  2. Admin — the token's user must be an admin (else 403).
  3. Shared secret — header ``X-EIOT-File-Key`` must equal the configured key.
  4. Source allowlist — ``request.remote`` must be inside a configured IP/CIDR
     (this check is skipped only when no allowlist is configured).
Access is also disabled entirely unless explicitly enabled in the integration
options, in which case the endpoint returns 404 (as if it did not exist).

Reads/writes are sandboxed to the Home Assistant config directory; ``..``
traversal outside it is rejected. ``secrets.yaml`` is reachable by design (per
deployment choice). Reads/writes are capped at 5 MB. Every call is audit-logged
(user, source IP, path, action).
"""
from __future__ import annotations

import hmac
import ipaddress
import logging
import os
from collections.abc import Callable, Sequence
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import FILE_API_MAX_BYTES, FILE_API_URL

_LOGGER = logging.getLogger(__name__)

# (enabled, shared_key, allowed_networks)
FileConfig = tuple[bool, str, Sequence[Any]]


def parse_allowed_ips(raw: str | None) -> list[Any]:
    """Parse a comma/space separated list of IPs/CIDRs into ip_network objects."""
    nets: list[Any] = []
    for tok in (raw or "").replace(",", " ").split():
        try:
            nets.append(ipaddress.ip_network(tok, strict=False))
        except ValueError:
            _LOGGER.warning(
                "extraiot_updater: ignoring invalid allowed IP/CIDR %r", tok
            )
    return nets


class ExtraIotFilesView(HomeAssistantView):
    """Gated file read/write under the Home Assistant config directory."""

    url = FILE_API_URL
    name = "api:extraiot_updater:files"
    requires_auth = True

    def __init__(
        self, hass: HomeAssistant, get_config: Callable[[], FileConfig]
    ) -> None:
        self._hass = hass
        self._get_config = get_config

    # -- gating ---------------------------------------------------------

    def _audit(self, level: int, action: str, request: web.Request, **kw: Any) -> None:
        user = request.get("hass_user")
        extra = " ".join(f"{k}={v}" for k, v in kw.items())
        _LOGGER.log(
            level,
            "EIOT-FILES %s user=%s remote=%s %s",
            action,
            getattr(user, "name", None),
            request.remote,
            extra,
        )

    def _forbid(
        self, request: web.Request, reason: str, status: int = 403
    ) -> web.Response:
        self._audit(logging.WARNING, f"DENY({reason})", request)
        return web.Response(status=status, text=f"forbidden: {reason}")

    def _gate(self, request: web.Request) -> web.Response | None:
        enabled, key, nets = self._get_config()
        if not enabled:
            # Behave as if the endpoint does not exist when disabled.
            return self._forbid(request, "disabled", status=404)
        user = request.get("hass_user")
        if user is None or not user.is_admin:
            return self._forbid(request, "admin_required")
        supplied = request.headers.get("X-EIOT-File-Key", "")
        if not key or not hmac.compare_digest(supplied, key):
            return self._forbid(request, "bad_key")
        if nets:
            try:
                remote = ipaddress.ip_address(request.remote or "")
            except ValueError:
                return self._forbid(request, "bad_source_ip")
            if not any(remote in net for net in nets):
                return self._forbid(request, "source_not_allowed")
        return None

    def _resolve(self, rel: str) -> str | None:
        """Resolve a relative path safely inside the config dir, or None."""
        base = os.path.realpath(self._hass.config.path())
        target = os.path.realpath(os.path.join(base, rel))
        if target != base and not target.startswith(base + os.sep):
            return None
        return target

    # -- handlers -------------------------------------------------------

    async def get(self, request: web.Request) -> web.Response:
        denied = self._gate(request)
        if denied is not None:
            return denied
        rel = request.query.get("path", "").lstrip("/")
        target = self._resolve(rel)
        if target is None:
            return self._forbid(request, "path_escapes_config")

        if request.query.get("list"):
            def _list() -> list[dict[str, Any]]:
                out: list[dict[str, Any]] = []
                for name in sorted(os.listdir(target)):
                    p = os.path.join(target, name)
                    is_dir = os.path.isdir(p)
                    out.append(
                        {
                            "name": name,
                            "dir": is_dir,
                            "size": None if is_dir else os.path.getsize(p),
                        }
                    )
                return out

            try:
                entries = await self._hass.async_add_executor_job(_list)
            except OSError as err:
                return web.Response(status=404, text=str(err))
            self._audit(logging.INFO, "LIST", request, path=rel or ".")
            return self.json({"path": rel, "entries": entries})

        def _read() -> str:
            size = os.path.getsize(target)
            if size > FILE_API_MAX_BYTES:
                raise ValueError(f"file too large ({size} bytes)")
            with open(target, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read()

        try:
            content = await self._hass.async_add_executor_job(_read)
        except (OSError, ValueError) as err:
            return web.Response(status=404, text=str(err))
        self._audit(logging.WARNING, "READ", request, path=rel)
        return self.json({"path": rel, "content": content})

    async def post(self, request: web.Request) -> web.Response:
        denied = self._gate(request)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except ValueError:
            return web.Response(status=400, text="invalid json body")
        rel = str(body.get("path", "")).lstrip("/")
        content = body.get("content")
        if not rel or not isinstance(content, str):
            return web.Response(status=400, text="path and text 'content' required")
        if len(content.encode("utf-8")) > FILE_API_MAX_BYTES:
            return web.Response(status=413, text="content exceeds size cap")
        target = self._resolve(rel)
        if target is None:
            return self._forbid(request, "path_escapes_config")

        def _write() -> None:
            parent = os.path.dirname(target)
            if parent:
                os.makedirs(parent, exist_ok=True)
            tmp = f"{target}.eiot.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(content)
            os.replace(tmp, target)  # atomic

        try:
            await self._hass.async_add_executor_job(_write)
        except OSError as err:
            return web.Response(status=500, text=str(err))
        self._audit(
            logging.WARNING, "WRITE", request, path=rel,
            bytes=len(content.encode("utf-8")),
        )
        return self.json({"path": rel, "written": True})


def async_register_file_api(
    hass: HomeAssistant, get_config: Callable[[], FileConfig]
) -> None:
    """Register the files view exactly once for this HA instance."""
    from .const import DOMAIN

    flag = f"{DOMAIN}_file_view_registered"
    if hass.data.get(flag):
        return
    hass.http.register_view(ExtraIotFilesView(hass, get_config))
    hass.data[flag] = True
    _LOGGER.info("extraiot_updater: file API registered at %s", FILE_API_URL)
