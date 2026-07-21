"""Async client for the Extra IOT update gateway."""
from __future__ import annotations

import asyncio
from functools import partial
from typing import Any

import aiohttp

# A signed integration package is a few tens of KB. Cap downloads well above
# that but far below "fills the disk", so a malformed or hostile manifest
# cannot exhaust storage on a client's Home Assistant box.
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024

# Chunks are accumulated to roughly this size before being handed to the
# executor, so a download costs a handful of thread hops rather than one per
# 64 KiB chunk.
_WRITE_BUFFER_BYTES = 1 << 20


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
        """Stream a ZIP to `dest`.

        Called from the event loop, so the file I/O runs in the executor:
        both ``open()`` and ``write()`` block. The transfer is capped at
        ``MAX_DOWNLOAD_BYTES``, checked against Content-Length up front and
        against the running total as chunks arrive, because a truthful
        Content-Length cannot be assumed.
        """
        loop = asyncio.get_running_loop()
        try:
            async with self._session.get(
                url, headers=self._headers, timeout=aiohttp.ClientTimeout(total=300)
            ) as resp:
                if resp.status in (401, 403):
                    raise GatewayAuthError(f"license rejected ({resp.status})")
                resp.raise_for_status()
                declared = resp.content_length
                if declared is not None and declared > MAX_DOWNLOAD_BYTES:
                    raise GatewayError(
                        f"refusing {declared} byte download "
                        f"(limit {MAX_DOWNLOAD_BYTES})"
                    )

                handle = await loop.run_in_executor(None, partial(open, dest, "wb"))
                try:
                    total = 0
                    buf = bytearray()
                    async for chunk in resp.content.iter_chunked(1 << 16):
                        total += len(chunk)
                        if total > MAX_DOWNLOAD_BYTES:
                            raise GatewayError(
                                f"download exceeded {MAX_DOWNLOAD_BYTES} bytes"
                            )
                        buf += chunk
                        if len(buf) >= _WRITE_BUFFER_BYTES:
                            await loop.run_in_executor(None, handle.write, bytes(buf))
                            buf.clear()
                    if buf:
                        await loop.run_in_executor(None, handle.write, bytes(buf))
                finally:
                    await loop.run_in_executor(None, handle.close)
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
