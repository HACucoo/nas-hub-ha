# NAS Hub for Home Assistant

What is new, next and running on the media services of a home NAS — as sensors and as a dashboard card that keeps working while the NAS sleeps.

| Service | Lists (cached) | Live (only while the NAS is awake) |
|---|---|---|
| Jellyfin | newly added movies and series (series grouped: "S14E08", "3 new episodes") | now playing, with direct play / transcoding |
| Sonarr | upcoming episodes (a season dropped at once is one row) | download queue |
| Radarr | upcoming releases (digital, disc, cinema) | download queue |
| Audiobookshelf | new audiobooks, continue listening | open listening sessions |
| E-book sending | books your own script sent, reported by webhook | — |

## How it behaves while the NAS sleeps

- Lists are fetched hourly by default. The last good answer is stored in `.storage` and survives a sleeping NAS and a Home Assistant restart. Artwork is copied locally (`/config/nas_hub_images`, served at `/nas_hub_images/…`), so the cards keep their pictures.
- Live lists (playing, downloading) are empty while the service is unreachable — stale "now playing" would be wrong.
- Optional **availability entity** per service: while it is off/unavailable nothing is requested at all; when it turns on, everything is refreshed after 90 seconds.
- The card shows "as of …, NAS asleep" under lists that are not current.

## Setup

1. Install via HACS (custom repository `https://github.com/HACucoo/nas-hub-ha`, category Integration) or copy `custom_components/nas_hub` into your config. Restart.
2. **Settings → Devices & services → Add integration → NAS Hub**, pick a service, enter its local address and API key. Repeat for each service.
3. A new key later? **⋮ → Reconfigure** on the entry. Intervals, list length, look-ahead and the availability entity are in **Configure**.

Each service becomes a device with its sensors and a **Refresh** button (asks right away, even if the NAS is said to sleep).

### Sensors

The items are in the `items` attribute (not written to the recorder). The state is the number of items for live lists and the title of the first item for the others, so an automation can react to "something new arrived". Further attributes: `updated`, `stale`, `asleep`, `count`, `list`, `order`.

### E-book webhook

Adding "E-book sending" shows a webhook path. Your script POSTs JSON to `http://<home-assistant>:8123/api/webhook/<id>` after each sent book — accepted from the local network only:

```json
{"title": "Project Hail Mary", "author": "Andy Weir", "recipient": "me@kindle.com",
 "sent_at": "2026-10-04T18:00:00+02:00", "cover_base64": "…"}
```

Only `title` is required; `cover_url` works instead of `cover_base64`. Each report also fires the event `nas_hub_ebook_sent`.

## Card

Register the resource once (dashboard → ⋮ → Edit → Manage resources):

| URL | `/nas_hub_frontend/nas-hub-card.js` |
|---|---|
| Resource type | JavaScript module |

```yaml
type: custom:nas-hub-card
entities:                 # one or more NAS Hub sensors, merged into one list
  - sensor.sonarr_nachste_folgen
  - sensor.radarr_nachste_filme
title: Next up
layout: tiles             # tiles (large) or rows (slim, fits a swipe card)
max_items: 8
image_style: auto         # auto (upcoming muted), bright or muted
show_genres: true
relative: true            # Today / Tomorrow / 2 days ago
open_links: false         # tap opens the item in Jellyfin, Sonarr, …
```

Everything can be set in the visual card editor. After an update, add a version to the resource URL (`…/nas-hub-card.js?v=0.2.1`) so tablets load the new file.
