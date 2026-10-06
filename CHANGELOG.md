# Changelog

## 0.3.0 — 2026-10-06

- New service **Seerr**: sensor with the latest requests and their state (card chip: available, partly here, processing, awaiting approval, declined).
- Notifies the requester when a wish has arrived — movies once, series once per new season, only requests at least 7 days old (option). Seerr users are mapped to notify services in the options; every announcement fires `nas_hub_request_available`.
- The cache file now keeps additional keys next to the lists (Seerr's bookkeeping).

## 0.2.1 — 2026-10-04

- Card: paused playback is no longer dimmed — the "Paused" chip says it, the row stays readable.

## 0.2.0 — 2026-10-04

- Radarr: cinema releases are hidden unless the new option "Show cinema releases" is on.
- Card: upcoming lists get muted artwork (`image_style: auto`), the others full artwork on the right edge like the Meal Planner card; `bright`/`muted` force a style.

## 0.1.0 — 2026-10-04

- First version: Jellyfin, Sonarr, Radarr, Audiobookshelf and an e-book webhook as cached list sensors, live playing/downloads, local artwork copies, availability entity for a sleeping NAS, `nas-hub-card` with tiles and rows layout and a visual editor.
