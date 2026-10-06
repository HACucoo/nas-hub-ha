"""Polling, caching and the NAS's sleep for one NAS Hub entry.

Each entry has two coordinators:

* lists — slow (default hourly): newly added, upcoming, continue listening.
  The last good answer is stored in .storage and survives both a sleeping NAS
  and a Home Assistant restart.
* live  — fast (default every minute): what is playing, what is downloading.
  Stale live data would be wrong, so it is simply empty while the NAS sleeps.

While the availability entity says the NAS is asleep nothing is requested at
all; when it wakes up both are refreshed after a short delay.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import CLIENTS, AuthError, BaseClient, SeerrClient, ServiceError
from .const import (
    ASLEEP_STATES,
    CONF_API_KEY,
    CONF_PUBLIC_URL,
    CONF_SERVICE,
    CONF_URL,
    DEFAULT_DAYS_AHEAD,
    DEFAULT_ITEM_COUNT,
    DEFAULT_LIST_MINUTES,
    DEFAULT_LIVE_SECONDS,
    DOMAIN,
    EBOOK_HISTORY,
    OPT_AVAILABILITY_ENTITY,
    OPT_DAYS_AHEAD,
    OPT_ITEM_COUNT,
    OPT_LIST_MINUTES,
    OPT_LIVE_SECONDS,
    OPT_SHOW_CINEMA,
    SERVICE_EBOOKS,
    SERVICE_RADARR,
    SERVICE_SEERR,
    STORAGE_KEY,
    STORAGE_VERSION,
    WAKE_REFRESH_DELAY,
)
from .images import ImageCache
from .seerr_notify import RequestNotifier

_LOGGER = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class NasHub:
    """Everything one config entry needs at runtime."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.service: str = entry.data[CONF_SERVICE]
        self.store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY.format(entry_id=entry.entry_id))
        self.images = ImageCache(hass, entry.entry_id)
        self.session = async_get_clientsession(hass)
        self.client: BaseClient | None = None
        if self.service in CLIENTS:
            self.client = CLIENTS[self.service](
                self.session,
                entry.data[CONF_URL],
                entry.data[CONF_API_KEY],
                entry.data.get(CONF_PUBLIC_URL) or None,
            )
            if self.service == SERVICE_RADARR:
                self.client.show_cinema = bool(entry.options.get(OPT_SHOW_CINEMA, False))
            if isinstance(self.client, SeerrClient):
                self.client.language = (hass.config.language or "en").split("-")[0]
        self.notifier: RequestNotifier | None = RequestNotifier(self) if self.service == SERVICE_SEERR else None
        self.stored: dict[str, Any] = {}
        self.lists = ListCoordinator(hass, entry, self)
        self.live: LiveCoordinator | None = (
            LiveCoordinator(hass, entry, self) if self.client and self.client.live_keys else None
        )
        self._unsub_wake: CALLBACK_TYPE | None = None

    # ── options ──

    def option(self, key: str, default: Any) -> Any:
        return self.entry.options.get(key, default)

    @property
    def item_count(self) -> int:
        return int(self.option(OPT_ITEM_COUNT, DEFAULT_ITEM_COUNT))

    @property
    def days_ahead(self) -> int:
        return int(self.option(OPT_DAYS_AHEAD, DEFAULT_DAYS_AHEAD.get(self.service, 14)))

    @property
    def availability_entity(self) -> str | None:
        return self.option(OPT_AVAILABILITY_ENTITY, None) or None

    def nas_awake(self) -> bool:
        entity_id = self.availability_entity
        if not entity_id:
            return True
        state = self.hass.states.get(entity_id)
        return state is not None and state.state.lower() not in ASLEEP_STATES

    # ── lifecycle ──

    async def async_setup(self) -> None:
        self.stored = await self.store.async_load() or {}
        await self.lists.async_config_entry_first_refresh()
        if self.live:
            await self.live.async_config_entry_first_refresh()
        if self.availability_entity:
            self.entry.async_on_unload(
                async_track_state_change_event(self.hass, [self.availability_entity], self._availability_changed)
            )
        self.entry.async_on_unload(self._cancel_wake)

    @callback
    def _availability_changed(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        was_awake = old is not None and old.state.lower() not in ASLEEP_STATES
        if was_awake or not self.nas_awake():
            if not self.nas_awake() and self.live:
                # Asleep now: nothing is playing or downloading any more
                self.hass.async_create_task(self.live.async_refresh())
            return
        self._cancel_wake()
        self._unsub_wake = async_call_later(self.hass, WAKE_REFRESH_DELAY, self._woke_up)

    async def _woke_up(self, _now: datetime) -> None:
        self._unsub_wake = None
        await self.async_refresh_all()

    @callback
    def _cancel_wake(self) -> None:
        if self._unsub_wake:
            self._unsub_wake()
            self._unsub_wake = None

    async def async_refresh_all(self, force: bool = False) -> None:
        self.lists.force_next = force
        await self.lists.async_refresh()
        if self.live:
            self.live.force_next = force
            await self.live.async_refresh()

    async def async_prune_images(self) -> None:
        keep: set[str] = set()
        for data in (self.lists.data, self.live.data if self.live else None):
            for entries in (data or {}).values():
                keep.update(item["image"] for item in entries if item.get("image"))
        await self.images.prune(keep)

    async def async_save(self, lists: dict[str, list] | None = None) -> None:
        """Write the cache; other keys in it (Seerr's bookkeeping) are kept."""
        if lists is not None:
            self.stored["lists"] = lists
            self.stored["updated"] = self.lists.updated
        await self.store.async_save(self.stored)

    # ── e-books arrive by webhook ──

    async def async_add_ebook(self, item: dict) -> None:
        sent = [item] + [i for i in (self.lists.data or {}).get("sent", []) if i["id"] != item["id"]]
        lists = {"sent": sent[:EBOOK_HISTORY]}
        await self.images.resolve(self.session, {}, lists)
        self.lists.mark_success()
        await self.async_save(lists)
        self.lists.async_set_updated_data(lists)
        await self.async_prune_images()


class _HubCoordinator(DataUpdateCoordinator[dict[str, list]]):
    """Common state: when the data was last fetched and whether it is stale."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, hub: NasHub, name: str, interval: timedelta | None) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title} {name}",
            update_interval=interval,
        )
        self.hub = hub
        self.updated: str | None = None
        # True while the shown data is not the service's current answer
        self.stale = False
        self.asleep = False
        self.force_next = False

    def mark_success(self) -> None:
        self.updated = _now_iso()
        self.stale = False
        self.asleep = False

    def _skip(self) -> bool:
        force, self.force_next = self.force_next, False
        self.asleep = not self.hub.nas_awake()
        return self.asleep and not force


class ListCoordinator(_HubCoordinator):
    """Slow lists, cached in .storage."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, hub: NasHub) -> None:
        interval = None
        if hub.client:
            interval = timedelta(minutes=int(entry.options.get(OPT_LIST_MINUTES, DEFAULT_LIST_MINUTES)))
        super().__init__(hass, entry, hub, "lists", interval)

    def _cached(self) -> dict[str, list]:
        if self.data is not None:
            return self.data
        stored = self.hub.stored
        self.updated = stored.get("updated")
        return stored.get("lists") or {}

    async def _async_update_data(self) -> dict[str, list]:
        hub = self.hub
        if hub.service == SERVICE_EBOOKS or hub.client is None:
            return self._cached()
        if self._skip():
            self.stale = True
            return self._cached()
        try:
            lists = await hub.client.fetch_lists(hub.item_count, hub.days_ahead)
        except AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ServiceError as err:
            # Unreachable is normal for a NAS that sleeps — keep the last answer
            _LOGGER.debug("%s not reachable, keeping the cached lists: %s", self.config_entry.title, err)
            self.stale = True
            return self._cached()
        await hub.images.resolve(hub.session, hub.client.auth_headers, lists)
        self.mark_success()
        await hub.async_save(lists)
        self.data = lists  # so the pruning below sees the new lists
        await hub.async_prune_images()
        if hub.notifier and isinstance(hub.client, SeerrClient):
            try:
                await hub.notifier.async_check(hub.client)
            except ServiceError as err:
                _LOGGER.debug("Seerr check postponed: %s", err)
        return lists


class LiveCoordinator(_HubCoordinator):
    """Fast, uncached: playing and downloading."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, hub: NasHub) -> None:
        seconds = int(entry.options.get(OPT_LIVE_SECONDS, DEFAULT_LIVE_SECONDS))
        super().__init__(hass, entry, hub, "live", timedelta(seconds=seconds))

    def _empty(self) -> dict[str, list]:
        return {key: [] for key in self.hub.client.live_keys}

    async def _async_update_data(self) -> dict[str, list]:
        hub = self.hub
        if self._skip():
            self.stale = True
            return self._empty()
        try:
            live = await hub.client.fetch_live()
        except AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ServiceError as err:
            _LOGGER.debug("%s not reachable: %s", self.config_entry.title, err)
            self.stale = True
            return self._empty()
        await hub.images.resolve(hub.session, hub.client.auth_headers, live)
        self.mark_success()
        return live
