"""Tdarr: pause and resume all of its nodes (e.g. while downloads unpack on the same disks)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NasHubConfigEntry
from .api import TdarrClient
from .coordinator import NasHub, _HubCoordinator
from .sensor import device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NasHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    if isinstance(hub.client, TdarrClient) and hub.live:
        async_add_entities([TdarrPauseSwitch(hub)])


class TdarrPauseSwitch(CoordinatorEntity[_HubCoordinator], SwitchEntity):
    """On = Tdarr's nodes are paused: running jobs finish, no new ones start."""

    _attr_has_entity_name = True
    _attr_translation_key = "tdarr_paused"

    def __init__(self, hub: NasHub) -> None:
        super().__init__(hub.live)
        self.hub = hub
        self._attr_unique_id = f"{hub.entry.entry_id}_paused"
        self._attr_device_info = device_info(hub)

    @property
    def _stats(self) -> dict:
        items = (self.coordinator.data or {}).get("stats") or []
        return items[0] if items else {}

    @property
    def available(self) -> bool:
        # Unknown while the NAS sleeps
        return "paused" in self._stats

    @property
    def is_on(self) -> bool | None:
        return self._stats.get("paused")

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, paused: bool) -> None:
        await self.hub.client.set_paused(paused)
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
