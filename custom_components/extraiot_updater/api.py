"""Async client for the Extra IOT update gateway."""
from __future__ import annotations

from typing import Any

import aiohttp


class GatewayError(Exception):
    """Raised for transport / HTTP errors talking to the gateway."""


class GatewayAuthError(GatewayError):
    """License missing, inactive, or revoked (401/403)."""


class ExtraIotGatewayClient:
    def __init__(
        self, session: aiohttp.ClientSession, server_url: str, license_key: str
    ) -> None:
        self._session = session
        self._base = server_url.rstrip("/")
        self._license = license_key

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._license}"}

    async def async_get_manifest(self) -> dict[str, Any]:
        url = f"{self._base}/api/v1/manifest"
        try:
            async with self._session.get(
                url, headers=self._headers, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status in (401, 403):
                    raise GatewayAuthError(f"license rejected ({resp.status})")
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as err:
            raise GatewayError(str(err)) from err

    async def async_download(self, url: str, dest: str) -> None:
        """Stream a ZIP to `dest`."""
        try:
            async with self._session.get(
                url, headers=self._headers, timeout=aiohttp.ClientTimeout(total=300)
            ) as resp:
                if resp.status in (401, 403):
                    raise GatewayAuthError(f"license rejected ({resp.status})")
                resp.raise_for_status()
                with open(dest, "wb") as f:
                    async for chunk in resp.content.iter_chunked(1 << 16):
                        f.write(chunk)
        except aiohttp.ClientError as err:
            raise GatewayError(str(err)) from err

    async def async_register(self, payload: dict[str, Any]) -> None:
        url = f"{self._base}/api/v1/register"
        try:
            async with self._session.post(
                url,
                headers=self._headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                resp.raise_for_status()
        except aiohttp.ClientError:
            # Telemetry is best-effort; never surface to the user.
            return
