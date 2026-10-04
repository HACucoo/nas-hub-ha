"""Refresh button: asks the service right away, even if the NAS is said to sleep."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NasHubConfigEntry
from .coordinator import NasHub
from .sensor import device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NasHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    if hub.client is not None:
        async_add_entities([NasHubRefreshButton(hub)])


class NasHubRefreshButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "refresh"

    def __init__(self, hub: NasHub) -> None:
        self.hub = hub
        self._attr_unique_id = f"{hub.entry.entry_id}_refresh"
        self._attr_device_info = device_info(hub)

    async def async_press(self) -> None:
        await self.hub.async_refresh_all(force=True)
