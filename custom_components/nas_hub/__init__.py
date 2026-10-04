"""NAS Hub: what is new, next and running on the media services of a home NAS."""
from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import hashlib
import logging
from pathlib import Path
from typing import Any

from aiohttp import web

from homeassistant.components import webhook
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    CONF_SERVICE,
    CONF_WEBHOOK_ID,
    DOMAIN,
    EVENT_EBOOK_SENT,
    FRONTEND_URL_BASE,
    IMAGE_URL_BASE,
    MAX_IMAGE_BYTES,
    SERVICE_EBOOKS,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .coordinator import NasHub
from .images import ImageCache, image_root

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BUTTON]
FRONTEND_DIR = Path(__file__).parent / "frontend"

# Static paths can only be registered once per HA run — survives entry reloads
DATA_HTTP_REGISTERED = f"{DOMAIN}_http_registered"

NasHubConfigEntry = ConfigEntry[NasHub]


async def async_setup_entry(hass: HomeAssistant, entry: NasHubConfigEntry) -> bool:
    """Set up one service."""
    if not hass.data.get(DATA_HTTP_REGISTERED):
        root = image_root(hass)
        await hass.async_add_executor_job(root.mkdir, 0o755, True, True)
        await hass.http.async_register_static_paths([
            StaticPathConfig(FRONTEND_URL_BASE, str(FRONTEND_DIR), cache_headers=False),
            StaticPathConfig(IMAGE_URL_BASE, str(root), cache_headers=True),
        ])
        hass.data[DATA_HTTP_REGISTERED] = True

    hub = NasHub(hass, entry)
    await hub.async_setup()
    entry.runtime_data = hub

    if entry.data[CONF_SERVICE] == SERVICE_EBOOKS:
        webhook.async_register(
            hass,
            DOMAIN,
            entry.title,
            entry.data[CONF_WEBHOOK_ID],
            _handle_ebook_webhook,
            local_only=True,
            allowed_methods=["POST"],
        )
        entry.async_on_unload(lambda: webhook.async_unregister(hass, entry.data[CONF_WEBHOOK_ID]))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NasHubConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: NasHubConfigEntry) -> None:
    """Forget cache and artwork of a removed service."""
    await Store(hass, STORAGE_VERSION, STORAGE_KEY.format(entry_id=entry.entry_id)).async_remove()
    await ImageCache(hass, entry.entry_id).remove_all()


async def _async_options_updated(hass: HomeAssistant, entry: NasHubConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _find_ebook_entry(hass: HomeAssistant, webhook_id: str) -> NasHubConfigEntry | None:
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        if entry.data.get(CONF_WEBHOOK_ID) == webhook_id:
            return entry
    return None


async def _handle_ebook_webhook(hass: HomeAssistant, webhook_id: str, request: web.Request) -> web.Response:
    """A sent e-book: {"title", "author", "recipient", "sent_at", "cover_url" | "cover_base64"}."""
    entry = _find_ebook_entry(hass, webhook_id)
    if entry is None:
        return web.Response(status=503)
    try:
        payload: dict[str, Any] = await request.json()
    except ValueError:
        return web.Response(status=400, text="JSON expected")
    title = str(payload.get("title") or "").strip()
    if not title:
        return web.Response(status=400, text="title is required")

    hub: NasHub = entry.runtime_data
    sent_at = payload.get("sent_at") or datetime.now(timezone.utc).isoformat()
    author = str(payload.get("author") or "").strip() or None
    recipient = str(payload.get("recipient") or "").strip() or None
    item_id = "ebook-" + hashlib.sha1(f"{title}|{author}|{recipient}|{sent_at}".encode()).hexdigest()[:12]

    item: dict[str, Any] = {
        "id": item_id,
        "kind": "ebook",
        "title": title,
        "subtitle": author,
        "episode": None,
        "date": sent_at,
        "date_type": "sent",
        "meta": recipient,
        "recipient": recipient,
        "rating": None,
        "genres": [],
        "progress": None,
        "link": None,
        "image": None,
    }
    # The cover either comes along (the script has it from the EPUB) or by URL
    if payload.get("cover_base64"):
        try:
            data = base64.b64decode(payload["cover_base64"], validate=True)
        except (binascii.Error, ValueError):
            data = b""
        if 0 < len(data) <= MAX_IMAGE_BYTES:
            name = await _store_cover(hass, entry.entry_id, data)
            item["image"] = f"{IMAGE_URL_BASE}/{entry.entry_id}/{name}"
    elif payload.get("cover_url"):
        item["image_src"] = [{"url": str(payload["cover_url"]), "auth": False}]
    await hub.async_add_ebook(item)
    hass.bus.async_fire(EVENT_EBOOK_SENT, {"title": title, "author": author, "recipient": recipient})
    return web.Response(status=200, text="ok")


async def _store_cover(hass: HomeAssistant, entry_id: str, data: bytes) -> str:
    folder = image_root(hass) / entry_id
    name = hashlib.sha1(data).hexdigest()[:20] + ".jpg"

    def _write() -> None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)

    await hass.async_add_executor_job(_write)
    return name
