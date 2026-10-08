"""E-books: tell people when a book they waited for has been sent to their reader.

Like the Seerr pushes: only a book that sat on the recipient's Goodreads
shelf for a while (option, default a week) is worth a push — one added
yesterday is expected anyway. Books on no shelf (picked by hand) never push.

Every newly sent book fires nas_hub_ebook_sent; the push goes to the notify
service the options map to the ebook-sender user.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from .const import DEFAULT_MIN_REQUEST_DAYS, EVENT_EBOOK_SENT, OPT_MIN_REQUEST_DAYS, OPT_NOTIFY_MAP

if TYPE_CHECKING:
    from .coordinator import NasHub

_LOGGER = logging.getLogger(__name__)

TEXTS = {
    "de": {
        "title": "📚 {title} ist da",
        "message": "Stand seit {ago} auf deiner Goodreads-Liste – jetzt ist es auf deinem Reader.",
        "message_author": "{author} – stand seit {ago} auf deiner Goodreads-Liste, jetzt ist es auf deinem Reader.",
        "days": "{n} Tagen",
        "weeks": "{n} Wochen",
        "months": "{n} Monaten",
    },
    "en": {
        "title": "📚 {title} has arrived",
        "message": "On your Goodreads shelf for {ago} – now it is on your reader.",
        "message_author": "{author} – on your Goodreads shelf for {ago}, now it is on your reader.",
        "days": "{n} days",
        "weeks": "{n} weeks",
        "months": "{n} months",
    },
}


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class EbookNotifier:
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

    async def async_announce(self, items: list[dict]) -> None:
        """Called with the books that are new in the 'sent' list, oldest first."""
        for item in items:
            try:
                await self._announce(item)
            except Exception:  # noqa: BLE001 — one failed push must not stop the others
                _LOGGER.exception("Announcing e-book %s failed", item.get("title"))

    async def _announce(self, item: dict) -> None:
        hub = self.hub
        hass = hub.hass
        recipients: list[dict] = item.get("recipients") or []
        hass.bus.async_fire(EVENT_EBOOK_SENT, {
            "title": item.get("title"),
            "author": item.get("subtitle"),
            "recipient": item.get("recipient"),
            "recipients": [
                {"user_id": r.get("id"), "user": r.get("name"), "sent_at": r.get("at"), "listed_at": r.get("listed_at")}
                for r in recipients
            ],
        })

        t = self._texts
        min_wait = timedelta(days=int(hub.option(OPT_MIN_REQUEST_DAYS, DEFAULT_MIN_REQUEST_DAYS)))
        notify_map: dict[str, str] = hub.option(OPT_NOTIFY_MAP, {}) or {}
        for recipient in recipients:
            listed, sent = _parse(recipient.get("listed_at")), _parse(recipient.get("at"))
            if listed is None or sent is None or sent - listed < min_wait:
                continue
            service = notify_map.get(str(recipient.get("id"))) or None
            if not service or not hass.services.has_service("notify", service):
                continue
            ago = self._ago(sent - listed)
            author = item.get("subtitle")
            message = t["message_author"].format(author=author, ago=ago) if author else t["message"].format(ago=ago)
            data: dict[str, Any] = {"tag": f"nas_hub_ebook_{item['id']}"}
            if recipient.get("image"):
                # The Goodreads cover is public, so the phone can load it anywhere
                data["image"] = recipient["image"]
                data["attachment"] = {"url": recipient["image"], "content-type": "jpeg"}
            await hass.services.async_call(
                "notify", service,
                {"title": t["title"].format(title=item.get("title")), "message": message, "data": data},
                blocking=False,
            )
