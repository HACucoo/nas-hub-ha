"""List sensors: the items live in the "items" attribute, read by the NAS Hub card."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NasHubConfigEntry
from .const import (
    CONF_PUBLIC_URL,
    CONF_URL,
    DOMAIN,
    SERVICE_AUDIOBOOKSHELF,
    SERVICE_EBOOKS,
    SERVICE_JELLYFIN,
    SERVICE_NAMES,
    SERVICE_RADARR,
    SERVICE_SEERR,
    SERVICE_SONARR,
)
from .coordinator import NasHub, _HubCoordinator


@dataclass(frozen=True, kw_only=True)
class NasHubSensorDescription(SensorEntityDescription):
    list_key: str
    live: bool = False
    # How the card sorts several lists merged into one: asc = soonest first
    order: str = "desc"
    # State is the number of items (like the live lists) instead of the first title
    count_state: bool = False


SENSORS: dict[str, tuple[NasHubSensorDescription, ...]] = {
    SERVICE_JELLYFIN: (
        NasHubSensorDescription(key="latest", translation_key="jellyfin_latest", list_key="latest"),
        NasHubSensorDescription(key="now_playing", translation_key="jellyfin_now_playing", list_key="now_playing", live=True, order="none"),
    ),
    SERVICE_SONARR: (
        NasHubSensorDescription(key="upcoming", translation_key="sonarr_upcoming", list_key="upcoming", order="asc"),
        NasHubSensorDescription(key="queue", translation_key="sonarr_queue", list_key="queue", live=True, order="none"),
    ),
    SERVICE_RADARR: (
        NasHubSensorDescription(key="upcoming", translation_key="radarr_upcoming", list_key="upcoming", order="asc"),
        NasHubSensorDescription(key="queue", translation_key="radarr_queue", list_key="queue", live=True, order="none"),
    ),
    SERVICE_AUDIOBOOKSHELF: (
        NasHubSensorDescription(key="new", translation_key="abs_new", list_key="new"),
        NasHubSensorDescription(key="in_progress", translation_key="abs_in_progress", list_key="in_progress"),
        NasHubSensorDescription(key="now_playing", translation_key="abs_now_playing", list_key="now_playing", live=True, order="none"),
    ),
    SERVICE_SEERR: (
        NasHubSensorDescription(key="requests", translation_key="seerr_requests", list_key="requests"),
    ),
    SERVICE_EBOOKS: (
        NasHubSensorDescription(key="sent", translation_key="ebooks_sent", list_key="sent"),
        # Counted, not named: "2 books wait for someone to pick a reader"
        NasHubSensorDescription(key="waiting", translation_key="ebooks_waiting", list_key="waiting", count_state=True),
    ),
}


def device_info(hub: NasHub) -> DeviceInfo:
    entry = hub.entry
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="NAS Hub",
        model=SERVICE_NAMES.get(hub.service),
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=entry.data.get(CONF_PUBLIC_URL) or entry.data.get(CONF_URL),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NasHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    async_add_entities(
        NasHubListSensor(hub, description)
        for description in SENSORS.get(hub.service, ())
    )


class NasHubListSensor(CoordinatorEntity[_HubCoordinator], SensorEntity):
    """State: live lists count their items, the other lists name their first one."""

    entity_description: NasHubSensorDescription
    _attr_has_entity_name = True
    # The item list changes with every update and would bloat the recorder
    _unrecorded_attributes = frozenset({"items"})

    def __init__(self, hub: NasHub, description: NasHubSensorDescription) -> None:
        coordinator = hub.live if description.live else hub.lists
        super().__init__(coordinator)
        self.hub = hub
        self.entity_description = description
        self._attr_unique_id = f"{hub.entry.entry_id}_{description.key}"
        self._attr_device_info = device_info(hub)

    @property
    def available(self) -> bool:
        # Cached lists stay usable while the service is unreachable
        return True

    @property
    def _items(self) -> list[dict]:
        return (self.coordinator.data or {}).get(self.entity_description.list_key, [])

    @property
    def native_value(self) -> str | int | None:
        items = self._items
        if self.entity_description.live or self.entity_description.count_state:
            return len(items)
        if not items:
            return None
        return (items[0].get("title") or "")[:255] or None

    @property
    def extra_state_attributes(self) -> dict:
        coordinator = self.coordinator
        return {
            "service": self.hub.service,
            "list": self.entity_description.list_key,
            "order": self.entity_description.order,
            "count": len(self._items),
            "updated": coordinator.updated,
            "stale": coordinator.stale,
            "asleep": coordinator.asleep,
            "items": self._items,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
