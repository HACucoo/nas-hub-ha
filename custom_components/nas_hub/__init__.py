"""NAS Hub: what is new, next and running on the media services of a home NAS."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.storage import Store

from .const import (
    CONF_SERVICE,
    CONF_URL,
    DOMAIN,
    FRONTEND_URL_BASE,
    IMAGE_URL_BASE,
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
    if entry.data[CONF_SERVICE] == SERVICE_EBOOKS and not entry.data.get(CONF_URL):
        # Up to 0.3 the e-book list came from a webhook; now it is read from the
        # ebook-sender container, whose address the entry does not know yet
        raise ConfigEntryError(
            "E-Book-Versand läuft jetzt als Container: bitte unter ⋮ → Neu konfigurieren dessen Adresse eintragen"
        )

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
