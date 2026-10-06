"""Seerr: tell people when what they wished for has arrived.

Rules:

* A movie counts once, when Seerr reports it available.
* A series counts once per season, when its first episodes are there —
  not again for every further episode.
* Only wishes at least a week old (option) are worth a push; whoever asked
  yesterday is still waiting for it anyway.
* Media seen for the first time is only remembered, never announced: on the
  first run, after a failed lookup or for a season that was already there
  when someone asked, nothing new has happened.

Every announcement fires an event; the push goes to the notify service the
options map to the requester's Seerr user.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import TYPE_CHECKING, Any

from .api import MEDIA_AVAILABLE, MEDIA_PARTIAL, REQUEST_DECLINED, SeerrClient
from .const import DEFAULT_MIN_REQUEST_DAYS, EVENT_REQUEST_AVAILABLE, OPT_MIN_REQUEST_DAYS, OPT_NOTIFY_MAP

if TYPE_CHECKING:
    from .coordinator import NasHub

_LOGGER = logging.getLogger(__name__)

ARRIVED = (MEDIA_PARTIAL, MEDIA_AVAILABLE)

TEXTS = {
    "de": {
        "movie_title": "🎬 {title} ist da",
        "movie_message": "Dein Wunsch von {ago} ist jetzt auf Jellyfin.",
        "season_title": "📺 {title}: {seasons}",
        "season_one": "Staffel {n}",
        "season_many": "Staffeln {list}",
        "season_partial": "Die neue Staffel hat angefangen – die ersten Folgen sind auf Jellyfin.",
        "season_complete": "Ist jetzt komplett auf Jellyfin.",
        "days": "vor {n} Tagen",
        "weeks": "vor {n} Wochen",
        "months": "vor {n} Monaten",
    },
    "en": {
        "movie_title": "🎬 {title} is here",
        "movie_message": "Your wish from {ago} is now on Jellyfin.",
        "season_title": "📺 {title}: {seasons}",
        "season_one": "season {n}",
        "season_many": "seasons {list}",
        "season_partial": "The new season has started – the first episodes are on Jellyfin.",
        "season_complete": "Now complete on Jellyfin.",
        "days": "{n} days ago",
        "weeks": "{n} weeks ago",
        "months": "{n} months ago",
    },
}


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class RequestNotifier:
    """Compares Seerr's state with what was already announced."""

    def __init__(self, hub: NasHub) -> None:
        self.hub = hub

    @property
    def _texts(self) -> dict[str, str]:
        lang = (self.hub.hass.config.language or "en").split("-")[0]
        return TEXTS.get(lang, TEXTS["en"])

    def _ago(self, delta: timedelta) -> str:
        t = self._texts
        days = max(1, delta.days)
        if days >= 60:
            return t["months"].format(n=round(days / 30))
        if days >= 14:
            return t["weeks"].format(n=days // 7)
        return t["days"].format(n=days)

    async def async_check(self, client: SeerrClient) -> None:
        hub = self.hub
        state: dict[str, Any] = hub.stored.setdefault("seerr", {})
        seen: set[str] = set(state.get("seen", []))
        done: set[str] = set(state.get("done", []))
        before = (len(seen), len(done))

        # Who asked for what, and since when (earliest wish per person)
        wishes: dict[tuple[str, int], dict[Any, dict]] = {}
        movie_status: dict[int, Any] = {}
        for req in client.requests:
            if req["status"] == REQUEST_DECLINED or req["user_id"] is None:
                continue
            people = wishes.setdefault((req["type"], req["tmdb"]), {})
            created = _parse(req["created"])
            known = people.get(req["user_id"])
            if known is None or (created and known["created"] and created < known["created"]):
                people[req["user_id"]] = {"name": req["user_name"], "created": created}
            if req["type"] == "movie":
                movie_status[req["tmdb"]] = req["media_status"]

        announcements = []
        for (kind, tmdb), people in wishes.items():
            media_key = f"{kind[0]}{tmdb}"
            if kind == "movie":
                arrived = {None: movie_status.get(tmdb)} if movie_status.get(tmdb) == MEDIA_AVAILABLE else {}
            else:
                page = client.series.get(tmdb)
                if page is None:
                    continue  # lookup failed — decide next time, not now
                arrived = {n: s for n, s in page["seasons"].items() if s in ARRIVED}
            keys = {n: f"{media_key}s{n}" if n is not None else media_key for n in arrived}
            new = {n: s for n, s in arrived.items() if keys[n] not in done}
            done.update(keys.values())
            first_sight = media_key not in seen
            seen.add(media_key)
            if new and not first_sight:
                announcements.append((kind, tmdb, people, new))

        for kind, tmdb, people, new in announcements:
            try:
                await self._announce(client, kind, tmdb, people, new)
            except Exception:  # noqa: BLE001 — a failed push must not lose the bookkeeping
                _LOGGER.exception("Announcing Seerr media %s %s failed", kind, tmdb)

        if (len(seen), len(done)) != before:
            state["seen"] = sorted(seen)
            state["done"] = sorted(done)
            await hub.async_save()

    async def _announce(self, client: SeerrClient, kind: str, tmdb: int, people: dict, new: dict) -> None:
        hub = self.hub
        t = self._texts
        if kind == "movie":
            page = await client.movie(tmdb)
            link = next((r["media_url"] for r in client.requests if r["tmdb"] == tmdb and r["media_url"]), None)
            title = t["movie_title"].format(title=page["title"])
            seasons: list[int] = []
        else:
            page = client.series[tmdb]
            link = page.get("media_url")
            seasons = sorted(new)
            label = (
                t["season_one"].format(n=seasons[0])
                if len(seasons) == 1
                else t["season_many"].format(list=", ".join(str(n) for n in seasons))
            )
            title = t["season_title"].format(title=page["title"], seasons=label)
            complete = all(new[n] == MEDIA_AVAILABLE for n in seasons)
            body = t["season_complete"] if complete else t["season_partial"]
        link = link or f"{client.public_url}/{kind}/{tmdb}"

        now = datetime.now(timezone.utc)
        min_age = timedelta(days=int(hub.option(OPT_MIN_REQUEST_DAYS, DEFAULT_MIN_REQUEST_DAYS)))
        notify_map: dict[str, str] = hub.option(OPT_NOTIFY_MAP, {}) or {}
        for user_id, person in people.items():
            created = person["created"]
            age = now - created if created else None
            if age is None or age < min_age:
                continue
            message = t["movie_message"].format(ago=self._ago(age)) if kind == "movie" else body
            service = notify_map.get(str(user_id)) or None
            hub.hass.bus.async_fire(EVENT_REQUEST_AVAILABLE, {
                "media_type": kind,
                "title": page["title"],
                "seasons": seasons,
                "seerr_user_id": user_id,
                "seerr_user": person["name"],
                "notify_service": service,
                "requested_at": created.isoformat(),
                "link": link,
                "image": page.get("poster"),
                "message_title": title,
                "message": message,
            })
            if not service or not hub.hass.services.has_service("notify", service):
                continue
            data: dict[str, Any] = {"tag": f"nas_hub_{kind}_{tmdb}", "url": link, "clickAction": link}
            if page.get("poster"):
                data["image"] = page["poster"]
                data["attachment"] = {"url": page["poster"], "content-type": "jpeg"}
            await hub.hass.services.async_call(
                "notify", service, {"title": title, "message": message, "data": data}, blocking=False
            )
