"""Local copies of artwork, so the cards keep their pictures while the NAS sleeps."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
import shutil

import aiohttp

from homeassistant.core import HomeAssistant

from .const import IMAGE_DIR_NAME, IMAGE_URL_BASE, MAX_IMAGE_BYTES, REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)

PARALLEL_DOWNLOADS = 4


def image_root(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(IMAGE_DIR_NAME))


class ImageCache:
    """One folder per config entry; a file is named after the hash of its source."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._dir = image_root(hass) / entry_id
        # Pruning must not delete what a running update has just fetched
        self._lock = asyncio.Lock()

    def _url(self, name: str) -> str:
        return f"{IMAGE_URL_BASE}/{self._entry_id}/{name}"

    async def resolve(
        self,
        session: aiohttp.ClientSession,
        auth_headers: dict[str, str],
        lists: dict[str, list],
    ) -> None:
        """Replace every item's image_src with the URL of a local copy (or None)."""
        async with self._lock:
            await self._resolve(session, auth_headers, lists)

    async def _resolve(
        self,
        session: aiohttp.ClientSession,
        auth_headers: dict[str, str],
        lists: dict[str, list],
    ) -> None:
        await self._hass.async_add_executor_job(self._dir.mkdir, 0o755, True, True)
        existing = set(await self._hass.async_add_executor_job(self._list))
        sem = asyncio.Semaphore(PARALLEL_DOWNLOADS)
        # The same artwork is often wanted by several items (one series, two lists)
        pending: dict[str, asyncio.Task] = {}

        async def fetch(sources: list[dict]) -> str | None:
            for src in sources:
                name = hashlib.sha1(src["url"].encode()).hexdigest()[:20] + ".jpg"
                if name in existing:
                    return name
                if name not in pending:
                    pending[name] = asyncio.ensure_future(self._download(session, sem, src, auth_headers, name))
                if await pending[name]:
                    existing.add(name)
                    return name
            return None

        # Items that already carry a local image (cached lists, e-book covers) stay as they are
        items = [item for entries in lists.values() for item in entries if "image_src" in item]
        names = await asyncio.gather(*(fetch(item.get("image_src") or []) for item in items))
        for item, name in zip(items, names):
            item.pop("image_src", None)
            item["image"] = self._url(name) if name else None

    async def _download(
        self,
        session: aiohttp.ClientSession,
        sem: asyncio.Semaphore,
        src: dict,
        auth_headers: dict[str, str],
        name: str,
    ) -> bool:
        async with sem:
            try:
                async with asyncio.timeout(REQUEST_TIMEOUT):
                    resp = await session.get(src["url"], headers=auth_headers if src.get("auth") else None)
                    if resp.status != 200 or not resp.content_type.startswith("image/"):
                        return False
                    body = await resp.content.read(MAX_IMAGE_BYTES + 1)
            except (aiohttp.ClientError, TimeoutError) as err:
                _LOGGER.debug("Artwork %s not loaded: %r", src["url"], err)
                return False
        if not body or len(body) > MAX_IMAGE_BYTES:
            return False
        await self._hass.async_add_executor_job((self._dir / name).write_bytes, body)
        return True

    def _list(self) -> list[str]:
        return [p.name for p in self._dir.iterdir() if p.is_file()]

    async def prune(self, keep: set[str]) -> None:
        """Delete files no list refers to any more."""
        def _prune() -> None:
            if not self._dir.is_dir():
                return
            for path in self._dir.iterdir():
                if path.is_file() and self._url(path.name) not in keep:
                    path.unlink(missing_ok=True)

        async with self._lock:
            await self._hass.async_add_executor_job(_prune)

    async def remove_all(self) -> None:
        await self._hass.async_add_executor_job(shutil.rmtree, self._dir, True)
