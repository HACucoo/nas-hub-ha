"""Small API clients for the media services NAS Hub reads.

Every client turns its service's answers into the same flat item dicts, so
the sensors and the card never need to know where an item came from:

    id        stable id, unique across services ("jf-…", "sonarr-…")
    kind      movie | series | episode | audiobook | ebook | download | session
    title     main line
    subtitle  second line (tagline, episode title, author) or None
    episode   "S02E05", "S02E01–E08" or None
    date      ISO date or datetime the list is sorted by
    date_type added | air | digital | physical | cinema | progress | sent
    meta      studio, network, narrator, user · device …
    rating    0–10 or None
    genres    up to four strings
    progress  0–1 for downloads, playback and listening progress, else None
    link      page in the service's web UI or None
    image_src artwork candidates, resolved into "image" by the image cache
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

import aiohttp

from .const import REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)


class ServiceError(Exception):
    """The service could not be reached or answered with an error."""


class AuthError(ServiceError):
    """The service rejected the API key."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _ms_to_iso(ms: Any) -> str | None:
    try:
        return _iso(datetime.fromtimestamp(int(ms) / 1000, timezone.utc))
    except (TypeError, ValueError, OverflowError):
        return None


def _parse_iso(value: Any) -> datetime | None:
    """Jellyfin writes seven fractional digits; Python takes six."""
    if not value or not isinstance(value, str):
        return None
    text = value.replace("Z", "+00:00")
    if "." in text:
        head, _, tail = text.partition(".")
        digits = "".join(ch for ch in tail if ch.isdigit())
        zone = tail[len(digits):]
        text = f"{head}.{digits[:6]}{zone}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# A series added within this span of its newest episode came in as a whole
NEW_SERIES_WINDOW = timedelta(days=1)
# Episodes that aired this recently are new even if a re-scan touched the rest
RECENT_AIRING = timedelta(days=60)


def _rating(value: Any) -> float | None:
    try:
        rating = round(float(value), 1)
    except (TypeError, ValueError):
        return None
    return rating if rating > 0 else None


def _episode_label(pairs: list[tuple[int | None, int | None]]) -> str | None:
    """S02E05, S02E01–E08 for a run in one season, else None (the count says it)."""
    pairs = [(s, e) for s, e in pairs if s is not None and e is not None]
    if not pairs:
        return None
    pairs.sort()
    if len(pairs) == 1:
        season, episode = pairs[0]
        return f"S{season:02d}E{episode:02d}"
    seasons = {s for s, _ in pairs}
    numbers = [e for _, e in pairs]
    if len(seasons) == 1 and numbers == list(range(numbers[0], numbers[0] + len(numbers))):
        season = pairs[0][0]
        return f"S{season:02d}E{numbers[0]:02d}–E{numbers[-1]:02d}"
    return None


class BaseClient:
    """Shared HTTP handling."""

    list_keys: tuple[str, ...] = ()
    live_keys: tuple[str, ...] = ()

    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        api_key: str,
        public_url: str | None = None,
    ) -> None:
        self._session = session
        self.url = url.rstrip("/")
        self._api_key = api_key
        self.public_url = (public_url or url).rstrip("/")

    @property
    def auth_headers(self) -> dict[str, str]:
        raise NotImplementedError

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                resp = await self._session.get(
                    f"{self.url}{path}", params=params, headers=self.auth_headers
                )
                if resp.status in (401, 403):
                    raise AuthError(f"{path}: HTTP {resp.status}")
                if resp.status >= 400:
                    raise ServiceError(f"{path}: HTTP {resp.status}")
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise ServiceError(f"{path}: {err!r}") from err

    async def validate(self) -> None:
        raise NotImplementedError

    async def fetch_lists(self, count: int, days_ahead: int) -> dict[str, list]:
        return {}

    async def fetch_live(self) -> dict[str, list]:
        return {}


# ── Jellyfin ─────────────────────────────────────────────────────────────────


class JellyfinClient(BaseClient):
    """Jellyfin: newly added movies and series, what is playing right now."""

    list_keys = ("latest",)
    live_keys = ("now_playing",)

    @property
    def auth_headers(self) -> dict[str, str]:
        # Newer servers only accept the key in this header, not as ?api_key=
        return {"Authorization": f'MediaBrowser Token="{self._api_key}"'}

    async def validate(self) -> None:
        await self._get("/System/Info")

    def _image(self, item_id: str, item: dict) -> list[dict]:
        sources = []
        if item.get("BackdropImageTags"):
            sources.append(f"/Items/{item_id}/Images/Backdrop?maxWidth=720&quality=75")
        if item.get("ParentBackdropItemId") and item.get("ParentBackdropImageTags"):
            parent = item["ParentBackdropItemId"]
            sources.append(f"/Items/{parent}/Images/Backdrop?maxWidth=720&quality=75")
        if (item.get("ImageTags") or {}).get("Primary"):
            sources.append(f"/Items/{item_id}/Images/Primary?maxWidth=480&quality=75")
        return [{"url": f"{self.url}{path}", "auth": True} for path in sources]

    def _link(self, item_id: str) -> str:
        return f"{self.public_url}/web/#/details?id={item_id}"

    async def fetch_lists(self, count: int, days_ahead: int) -> dict[str, list]:
        fields = "Genres,Studios,Taglines,PremiereDate,DateCreated,CommunityRating"
        movies, episodes = await asyncio.gather(
            self._get("/Items", {
                "Recursive": "true",
                "IncludeItemTypes": "Movie",
                "SortBy": "DateCreated",
                "SortOrder": "Descending",
                "Limit": count,
                "Fields": fields,
            }),
            # Generous: a whole series (or a re-scanned one) easily brings
            # dozens of episodes and must not push every other series out
            self._get("/Items", {
                "Recursive": "true",
                "IncludeItemTypes": "Episode",
                "SortBy": "DateCreated",
                "SortOrder": "Descending",
                "Limit": count * 25,
                "Fields": "DateCreated,PremiereDate",
                "EnableImages": "false",
            }),
        )

        items = [self._movie(m) for m in movies.get("Items", [])]

        # Newly added episodes are shown per series: "Futurama, S14E08 new"
        series: dict[str, dict] = {}
        for ep in episodes.get("Items", []):
            sid = ep.get("SeriesId")
            if not sid:
                continue
            entry = series.setdefault(sid, {"date": ep.get("DateCreated"), "eps": []})
            entry["eps"].append((ep.get("ParentIndexNumber"), ep.get("IndexNumber"), ep.get("PremiereDate")))
        series_ids = list(series)[:count]
        if series_ids:
            details = await self._get("/Items", {"Ids": ",".join(series_ids), "Fields": fields + ",ChildCount"})
            for show in details.get("Items", []):
                entry = series.get(show.get("Id"))
                if entry:
                    items.append(self._series(show, entry))

        items.sort(key=lambda i: i.get("date") or "", reverse=True)
        return {"latest": items[:count]}

    def _base(self, item: dict) -> dict:
        studios = item.get("Studios") or []
        return {
            "rating": _rating(item.get("CommunityRating")),
            "genres": (item.get("Genres") or [])[:4],
            "meta": studios[0].get("Name") if studios else None,
            "released": (item.get("PremiereDate") or "")[:10] or None,
            "link": self._link(item["Id"]),
            "image_src": self._image(item["Id"], item),
        }

    def _movie(self, item: dict) -> dict:
        taglines = item.get("Taglines") or []
        return {
            "id": f"jf-{item['Id']}",
            "kind": "movie",
            "title": item.get("Name"),
            "subtitle": taglines[0] if taglines else None,
            "episode": None,
            "date": item.get("DateCreated"),
            "date_type": "added",
            "progress": None,
            **self._base(item),
        }

    def _series(self, item: dict, entry: dict) -> dict:
        """One row per series; tells a new series, new episodes and a re-scan apart.

        * Many episodes at once, a few of them aired recently → a re-scan (files
          renamed or moved): only the recently aired ones are new. A whole
          running series downloaded fresh looks the same and then shows its
          latest episode — the lesser evil.
        * Otherwise, the series itself was added together with its episodes →
          "new series" with the number of seasons, not a (capped) episode count.
        * Otherwise all of them count (e.g. an old season added later).
        """
        eps = entry["eps"]
        added = _parse_iso(entry["date"])
        series_added = _parse_iso(item.get("DateCreated"))
        row = {
            "id": f"jf-{item['Id']}",
            "kind": "series",
            "title": item.get("Name"),
            "subtitle": None,
            "date": entry["date"],
            "date_type": "added",
            "progress": None,
            **self._base(item),
        }
        # Recently aired episodes among many old ones: a re-scan (Jellyfin may
        # even re-create the series item when its folder moves), so only the
        # recent ones are news. Checked first for exactly that reason.
        if len(eps) > 1:
            cutoff = _utc_now() - RECENT_AIRING
            recent = [e for e in eps if (_parse_iso(e[2]) or cutoff) > cutoff]
            if recent and len(recent) < len(eps):
                pairs = [(s, e) for s, e, _ in recent]
                return {**row, "episode": _episode_label(pairs), "new_count": len(pairs)}

        if len(eps) > 1 and added and series_added and abs(added - series_added) <= NEW_SERIES_WINDOW:
            return {**row, "episode": None, "new_count": None, "new_series": True, "season_count": item.get("ChildCount")}

        pairs = [(s, e) for s, e, _ in eps]
        return {**row, "episode": _episode_label(pairs), "new_count": len(pairs)}

    async def fetch_live(self) -> dict[str, list]:
        sessions = await self._get("/Sessions", {"activeWithinSeconds": 960})
        items = []
        for sess in sessions or []:
            item = sess.get("NowPlayingItem")
            if not item:
                continue
            state = sess.get("PlayState") or {}
            runtime = item.get("RunTimeTicks") or 0
            position = state.get("PositionTicks") or 0
            is_episode = item.get("Type") == "Episode"
            transcoding = sess.get("TranscodingInfo") or {}
            if not transcoding:
                method = "direct"
            elif transcoding.get("IsVideoDirect", False):
                method = "audio"  # only the sound is converted, the picture passes through
            else:
                method = "transcode"
            items.append({
                "id": f"jf-session-{sess.get('Id')}",
                "kind": "session",
                "media": "episode" if is_episode else "movie",
                "title": item.get("SeriesName") if is_episode else item.get("Name"),
                "subtitle": item.get("Name") if is_episode else None,
                "episode": _episode_label([(item.get("ParentIndexNumber"), item.get("IndexNumber"))])
                if is_episode else None,
                "date": None,
                "date_type": None,
                "meta": " · ".join(x for x in (sess.get("UserName"), sess.get("DeviceName")) if x),
                "user": sess.get("UserName"),
                "client": sess.get("Client"),
                "paused": bool(state.get("IsPaused")),
                "play_method": method,
                "progress": round(position / runtime, 3) if runtime else None,
                "rating": None,
                "genres": [],
                "link": self._link(item["Id"]),
                "image_src": self._image(item["Id"], item),
            })
        return {"now_playing": items}


# ── Sonarr / Radarr ──────────────────────────────────────────────────────────


class ArrClient(BaseClient):
    """Common bits of the *arr v3 API."""

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"X-Api-Key": self._api_key}

    async def validate(self) -> None:
        await self._get("/api/v3/system/status")

    def _cover(self, own_id: Any, images: list[dict] | None) -> list[dict]:
        """Prefer the small fanart the service keeps itself, then the online copy."""
        sources = []
        if own_id is not None:
            sources.append({"url": f"{self.url}/api/v3/mediacover/{own_id}/fanart-360.jpg", "auth": True})
        for cover_type in ("fanart", "poster"):
            for img in images or []:
                if img.get("coverType") == cover_type and img.get("remoteUrl"):
                    # TMDB serves sizes by path; the original is several MB
                    url = img["remoteUrl"].replace("/t/p/original/", "/t/p/w780/")
                    sources.append({"url": url, "auth": False})
        return sources

    @staticmethod
    def _download(record: dict) -> tuple[float | None, str]:
        size = record.get("size") or 0
        left = record.get("sizeleft") or 0
        progress = round(1 - left / size, 3) if size else None
        status = (record.get("trackedDownloadState") or record.get("status") or "").lower()
        return progress, status


class SonarrClient(ArrClient):
    """Sonarr: upcoming episodes and the download queue."""

    list_keys = ("upcoming",)
    live_keys = ("queue",)

    async def fetch_lists(self, count: int, days_ahead: int) -> dict[str, list]:
        now = _utc_now()
        episodes = await self._get("/api/v3/calendar", {
            "start": _iso(now - timedelta(hours=6)),
            "end": _iso(now + timedelta(days=days_ahead)),
            "includeSeries": "true",
            "unmonitored": "false",
        })
        # A season dropped at once becomes one row: "S02E01–E08"
        groups: dict[tuple, dict] = {}
        for ep in episodes or []:
            air = ep.get("airDateUtc")
            if not air:
                continue
            key = (ep.get("seriesId"), air[:10])
            group = groups.setdefault(key, {"first": ep, "eps": [], "titles": []})
            group["eps"].append((ep.get("seasonNumber"), ep.get("episodeNumber")))
            # Not yet named episodes are called "TBA" — no subtitle is better
            title = ep.get("title")
            group["titles"].append(None if (title or "").strip().upper() in ("TBA", "TBD") else title)

        items = []
        for (series_id, _day), group in groups.items():
            ep = group["first"]
            series = ep.get("series") or {}
            ratings = series.get("ratings") or {}
            items.append({
                "id": f"sonarr-{series_id}-{ep.get('airDateUtc', '')[:10]}",
                "kind": "episode",
                "title": series.get("title"),
                "subtitle": group["titles"][0] if len(group["titles"]) == 1 else None,
                "episode": _episode_label(group["eps"]),
                "new_count": len(group["eps"]),
                "date": ep.get("airDateUtc"),
                "date_type": "air",
                "meta": series.get("network"),
                "rating": _rating(ratings.get("value")),
                "genres": (series.get("genres") or [])[:4],
                "progress": None,
                "has_file": bool(ep.get("hasFile")),
                "link": f"{self.public_url}/series/{series['titleSlug']}" if series.get("titleSlug") else None,
                "image_src": self._cover(series_id, series.get("images")),
            })
        items.sort(key=lambda i: i["date"])
        return {"upcoming": items[:count]}

    async def fetch_live(self) -> dict[str, list]:
        queue = await self._get("/api/v3/queue", {
            "pageSize": 50,
            "includeSeries": "true",
            "includeEpisode": "true",
        })
        # A season pack is one download but one queue record per episode
        downloads: dict[str, dict] = {}
        for rec in (queue or {}).get("records", []):
            key = rec.get("downloadId") or str(rec.get("id"))
            entry = downloads.setdefault(key, {"rec": rec, "eps": []})
            episode = rec.get("episode") or {}
            entry["eps"].append((episode.get("seasonNumber"), episode.get("episodeNumber")))

        items = []
        for key, entry in downloads.items():
            rec = entry["rec"]
            series = rec.get("series") or {}
            progress, status = self._download(rec)
            items.append({
                "id": f"sonarr-dl-{key}",
                "kind": "download",
                "media": "episode",
                "title": series.get("title") or rec.get("title"),
                "subtitle": (rec.get("episode") or {}).get("title") if len(entry["eps"]) == 1 else None,
                "episode": _episode_label(entry["eps"]),
                "date": rec.get("estimatedCompletionTime"),
                "date_type": "eta",
                "meta": None,
                "status": status,
                "timeleft": rec.get("timeleft"),
                "size": rec.get("size"),
                "progress": progress,
                "rating": None,
                "genres": [],
                "link": f"{self.public_url}/activity/queue",
                "image_src": self._cover(rec.get("seriesId"), series.get("images")),
            })
        return {"queue": items}


class RadarrClient(ArrClient):
    """Radarr: upcoming releases and the download queue."""

    list_keys = ("upcoming",)
    live_keys = ("queue",)
    # A cinema start is nothing to watch at home yet; off unless the options say so
    show_cinema = False

    async def fetch_lists(self, count: int, days_ahead: int) -> dict[str, list]:
        now = _utc_now()
        start, end = now - timedelta(hours=6), now + timedelta(days=days_ahead)
        kinds = (("digitalRelease", "digital"), ("physicalRelease", "physical"))
        if self.show_cinema:
            kinds += (("inCinemas", "cinema"),)
        movies = await self._get("/api/v3/calendar", {
            "start": _iso(start),
            "end": _iso(end),
            "unmonitored": "false",
        })
        items = []
        for movie in movies or []:
            # The calendar lists a movie for any of its dates; show the next one
            dates = []
            for field, kind in kinds:
                value = movie.get(field)
                if not value:
                    continue
                try:
                    when = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if start <= when <= end:
                    dates.append((when, kind, value))
            if not dates:
                continue
            _when, date_type, value = min(dates)
            ratings = movie.get("ratings") or {}
            rating = (ratings.get("tmdb") or {}).get("value") or (ratings.get("imdb") or {}).get("value")
            slug = movie.get("titleSlug") or movie.get("tmdbId")
            items.append({
                "id": f"radarr-{movie.get('id')}",
                "kind": "movie",
                "title": movie.get("title"),
                "subtitle": None,
                "episode": None,
                "date": value,
                "date_type": date_type,
                "meta": movie.get("studio"),
                "rating": _rating(rating),
                "genres": (movie.get("genres") or [])[:4],
                "progress": None,
                "has_file": bool(movie.get("hasFile")),
                "link": f"{self.public_url}/movie/{slug}" if slug else None,
                "image_src": self._cover(movie.get("id"), movie.get("images")),
            })
        items.sort(key=lambda i: i["date"])
        return {"upcoming": items[:count]}

    async def fetch_live(self) -> dict[str, list]:
        queue = await self._get("/api/v3/queue", {"pageSize": 50, "includeMovie": "true"})
        items = []
        for rec in (queue or {}).get("records", []):
            movie = rec.get("movie") or {}
            progress, status = self._download(rec)
            items.append({
                "id": f"radarr-dl-{rec.get('downloadId') or rec.get('id')}",
                "kind": "download",
                "media": "movie",
                "title": movie.get("title") or rec.get("title"),
                "subtitle": None,
                "episode": None,
                "date": rec.get("estimatedCompletionTime"),
                "date_type": "eta",
                "meta": None,
                "status": status,
                "timeleft": rec.get("timeleft"),
                "size": rec.get("size"),
                "progress": progress,
                "rating": None,
                "genres": [],
                "link": f"{self.public_url}/activity/queue",
                "image_src": self._cover(rec.get("movieId"), movie.get("images")),
            })
        return {"queue": items}


# ── Audiobookshelf ───────────────────────────────────────────────────────────


class AudiobookshelfClient(BaseClient):
    """Audiobookshelf: new audiobooks, continue listening, open sessions."""

    list_keys = ("new", "in_progress")
    live_keys = ("now_playing",)

    @property
    def auth_headers(self) -> dict[str, str]:
        key = self._api_key
        return {"Authorization": key if key.lower().startswith("bearer ") else f"Bearer {key}"}

    async def validate(self) -> None:
        await self._get("/api/me")

    def _cover(self, item_id: str) -> list[dict]:
        return [{"url": f"{self.url}/api/items/{item_id}/cover?width=480&format=jpeg", "auth": True}]

    def _book(self, item: dict, kind: str = "audiobook") -> dict:
        media = item.get("media") or {}
        meta = media.get("metadata") or {}
        series = meta.get("seriesName") or None
        return {
            "id": f"abs-{item.get('id')}",
            "kind": kind,
            "title": meta.get("title"),
            "subtitle": meta.get("authorName") or None,
            "episode": None,
            "date": _ms_to_iso(item.get("addedAt")),
            "date_type": "added",
            "meta": series,
            "series": series,
            "narrator": meta.get("narratorName") or None,
            "duration": media.get("duration"),
            "rating": None,
            "genres": (meta.get("genres") or [])[:4],
            "progress": None,
            "link": f"{self.public_url}/item/{item.get('id')}",
            "image_src": self._cover(item.get("id")),
        }

    async def fetch_lists(self, count: int, days_ahead: int) -> dict[str, list]:
        libraries = (await self._get("/api/libraries")).get("libraries", [])
        book_libs = [lib["id"] for lib in libraries if lib.get("mediaType") == "book"]
        pages, me, in_progress = await asyncio.gather(
            asyncio.gather(*(
                self._get(f"/api/libraries/{lib_id}/items", {
                    "sort": "addedAt", "desc": 1, "limit": count * 2, "minified": 1,
                })
                for lib_id in book_libs
            )),
            self._get("/api/me"),
            self._get("/api/me/items-in-progress", {"limit": count}),
        )

        new = []
        for page in pages:
            for item in page.get("results", []):
                # Book libraries may hold plain e-books too; only what can be listened to
                if (item.get("media") or {}).get("duration"):
                    new.append(self._book(item))
        new.sort(key=lambda i: i.get("date") or "", reverse=True)

        progress = {
            p.get("libraryItemId"): p
            for p in (me or {}).get("mediaProgress", [])
            if not p.get("episodeId")
        }
        listening = []
        for item in (in_progress or {}).get("libraryItems", []):
            if item.get("mediaType", "book") != "book":
                continue
            prog = progress.get(item.get("id")) or {}
            if prog.get("isFinished") or prog.get("hideFromContinueListening"):
                continue
            book = self._book(item)
            book["id"] = f"abs-progress-{item.get('id')}"
            book["progress"] = round(prog.get("progress") or 0, 3)
            book["date"] = _ms_to_iso(prog.get("lastUpdate") or item.get("progressLastUpdate"))
            book["date_type"] = "progress"
            listening.append(book)
        listening.sort(key=lambda i: i.get("date") or "", reverse=True)

        return {"new": new[:count], "in_progress": listening[:count]}

    async def fetch_live(self) -> dict[str, list]:
        data = await self._get("/api/sessions/open")
        # The app syncs about every 15 s while playing; a session not touched
        # for five minutes is paused or the app is gone
        cutoff = (_utc_now().timestamp() - 300) * 1000
        items = []
        for sess in (data or {}).get("sessions", []):
            if (sess.get("updatedAt") or 0) < cutoff:
                continue
            duration = sess.get("duration") or 0
            user = (sess.get("user") or {}).get("username")
            device = (sess.get("deviceInfo") or {})
            device_name = device.get("deviceName") or device.get("clientName")
            items.append({
                "id": f"abs-session-{sess.get('id')}",
                "kind": "session",
                "media": "audiobook",
                "title": sess.get("displayTitle"),
                "subtitle": sess.get("displayAuthor"),
                "episode": None,
                "date": None,
                "date_type": None,
                "meta": " · ".join(x for x in (user, device_name) if x),
                "user": user,
                "paused": False,
                "play_method": None,
                "progress": round((sess.get("currentTime") or 0) / duration, 3) if duration else None,
                "rating": None,
                "genres": [],
                "link": f"{self.public_url}/item/{sess.get('libraryItemId')}",
                "image_src": self._cover(sess.get("libraryItemId")),
            })
        return {"now_playing": items}


# ── Seerr ────────────────────────────────────────────────────────────────────

# Seerr's media states (Overseerr/Jellyseerr share them)
MEDIA_PENDING = 2
MEDIA_PROCESSING = 3
MEDIA_PARTIAL = 4
MEDIA_AVAILABLE = 5
REQUEST_PENDING = 1
REQUEST_DECLINED = 3

TMDB_IMAGE = "https://image.tmdb.org/t/p"


class SeerrClient(BaseClient):
    """Seerr: the wishes and which of them have arrived.

    The request list only carries ids and states; titles, artwork and the
    state of every season come from the movie/tv pages. Movie titles never
    change and are kept; series are asked again each time, because new
    seasons are exactly what the notifications are about.
    """

    list_keys = ("requests",)
    language = "en"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.movies: dict[int, dict] = {}
        # Filled by fetch_lists for the notifier: normalised requests and series pages
        self.requests: list[dict] = []
        self.series: dict[int, dict] = {}

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"X-Api-Key": self._api_key}

    async def validate(self) -> None:
        await self._get("/api/v1/auth/me")

    async def fetch_users(self) -> list[dict]:
        data = await self._get("/api/v1/user", {"take": 100, "skip": 0})
        return [
            {"id": u.get("id"), "name": u.get("displayName") or u.get("jellyfinUsername") or u.get("username") or u.get("email")}
            for u in (data or {}).get("results", [])
            if u.get("id") is not None
        ]

    async def _fetch_requests(self) -> list[dict]:
        requests: list[dict] = []
        skip, take = 0, 100
        while True:
            data = await self._get("/api/v1/request", {"take": take, "skip": skip, "filter": "all", "sort": "added"})
            page = (data or {}).get("results", [])
            for req in page:
                media = req.get("media") or {}
                user = req.get("requestedBy") or {}
                if not media.get("tmdbId"):
                    continue
                requests.append({
                    "id": req.get("id"),
                    "type": "tv" if (req.get("type") or media.get("mediaType")) == "tv" else "movie",
                    "status": req.get("status"),
                    "created": req.get("createdAt"),
                    "tmdb": media["tmdbId"],
                    "media_id": media.get("id"),
                    "media_status": media.get("status"),
                    "media_url": media.get("mediaUrl"),
                    "seasons": [s.get("seasonNumber") for s in req.get("seasons") or []],
                    "user_id": user.get("id"),
                    "user_name": user.get("displayName") or user.get("jellyfinUsername") or user.get("username"),
                })
            info = (data or {}).get("pageInfo") or {}
            skip += take
            if not page or skip >= (info.get("results") or 0) or skip >= 1000:
                return requests

    @staticmethod
    def _art(page: dict) -> list[dict]:
        sources = []
        if page.get("backdropPath"):
            sources.append({"url": f"{TMDB_IMAGE}/w780{page['backdropPath']}", "auth": False})
        if page.get("posterPath"):
            sources.append({"url": f"{TMDB_IMAGE}/w500{page['posterPath']}", "auth": False})
        return sources

    async def movie(self, tmdb: int) -> dict:
        if tmdb not in self.movies:
            page = await self._get(f"/api/v1/movie/{tmdb}", {"language": self.language})
            self.movies[tmdb] = {
                "title": page.get("title") or page.get("originalTitle"),
                "poster": f"{TMDB_IMAGE}/w500{page['posterPath']}" if page.get("posterPath") else None,
                "art": self._art(page),
                "genres": [g.get("name") for g in page.get("genres") or [] if g.get("name")][:4],
                "rating": _rating(page.get("voteAverage")),
            }
        return self.movies[tmdb]

    async def tv(self, tmdb: int) -> dict:
        page = await self._get(f"/api/v1/tv/{tmdb}", {"language": self.language})
        info = page.get("mediaInfo") or {}
        return {
            "title": page.get("name") or page.get("originalName"),
            "poster": f"{TMDB_IMAGE}/w500{page['posterPath']}" if page.get("posterPath") else None,
            "art": self._art(page),
            "genres": [g.get("name") for g in page.get("genres") or [] if g.get("name")][:4],
            "rating": _rating(page.get("voteAverage")),
            "media_url": info.get("mediaUrl"),
            # Season 0 are the specials — no "new season" to announce
            "seasons": {
                int(s["seasonNumber"]): s.get("status")
                for s in info.get("seasons") or []
                if s.get("seasonNumber")
            },
        }

    async def fetch_lists(self, count: int, days_ahead: int) -> dict[str, list]:
        requests = await self._fetch_requests()
        wanted = [r for r in requests if r["status"] != REQUEST_DECLINED]
        series_ids = list(dict.fromkeys(r["tmdb"] for r in wanted if r["type"] == "tv"))
        limit = asyncio.Semaphore(4)

        async def _tv(tmdb: int) -> tuple[int, dict | None]:
            async with limit:
                try:
                    return tmdb, await self.tv(tmdb)
                except AuthError:
                    raise
                except ServiceError as err:
                    _LOGGER.debug("Seerr series %s: %s", tmdb, err)
                    return tmdb, None

        series = {tmdb: page for tmdb, page in await asyncio.gather(*(_tv(t) for t in series_ids)) if page}

        newest = sorted(requests, key=lambda r: r["created"] or "", reverse=True)[:count]
        items = []
        for req in newest:
            if req["type"] == "tv":
                page = series.get(req["tmdb"]) or {}
            else:
                try:
                    page = await self.movie(req["tmdb"])
                except AuthError:
                    raise
                except ServiceError:
                    page = {}
            items.append({
                "id": f"seerr-{req['id']}",
                "kind": "series" if req["type"] == "tv" else "movie",
                "title": page.get("title") or f"TMDB {req['tmdb']}",
                "subtitle": None,
                "episode": None,
                "date": req["created"],
                "date_type": "requested",
                "meta": req["user_name"],
                "request_status": self.request_state(req),
                "rating": page.get("rating"),
                "genres": page.get("genres") or [],
                "progress": None,
                "link": f"{self.public_url}/{req['type']}/{req['tmdb']}",
                "image_src": page.get("art") or [],
            })

        self.requests = requests
        self.series = series
        return {"requests": items}

    @staticmethod
    def request_state(req: dict) -> str:
        if req["status"] == REQUEST_DECLINED:
            return "declined"
        if req["media_status"] == MEDIA_AVAILABLE:
            return "available"
        if req["media_status"] == MEDIA_PARTIAL:
            return "partial"
        if req["status"] == REQUEST_PENDING:
            return "pending"
        return "processing"


CLIENTS: dict[str, type[BaseClient]] = {
    "jellyfin": JellyfinClient,
    "audiobookshelf": AudiobookshelfClient,
    "sonarr": SonarrClient,
    "radarr": RadarrClient,
    "seerr": SeerrClient,
}
