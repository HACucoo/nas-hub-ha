# Changelog

## 0.8.0 — 2026-10-23

- Tdarr: switch "Paused" — on pauses all Tdarr nodes like "Pause all" in Tdarr (running jobs finish, no new ones start), off resumes them. For automations, e.g. pause Tdarr while SABnzbd downloads and unpacks.

## 0.7.1 — 2026-10-23

- Tdarr: an episode in a series folder without season folders is named by the series, not by the library folder.

## 0.7.0 — 2026-10-23

- New service **Tdarr**: sensors "Processing" (what the transcode workers are on, with progress, time left and fps) and "Queue" (files waiting, plus done/failed and health-check counts as attributes). The card shows Tdarr jobs like downloads.

## 0.6.0 — 2026-10-14

- Seerr: a push "Season 3 complete" when the last episode of a requested season is in Jellyfin (Seerr reports the season available), to everyone who asked — without the minimum request age. A season that arrives complete at once gets only this push instead of two.
- `nas_hub_request_available` carries `event`: `arrived` or `season_complete`.
- The first check after the update only learns which seasons are complete already; nothing old is announced.

## 0.5.0 — 2026-10-08

- E-book sending: a push like Seerr's when a book that sat on the recipient's Goodreads shelf for at least a week (option) has been sent to their reader. Each ebook-sender user is mapped to a notify service in the options; books picked by hand (on no shelf) never push. `nas_hub_ebook_sent` now also lists the recipients with `sent_at` and `listed_at`.
- Needs ebook-sender 1.2.0 or later (it reports since when a book was on the shelf).

## 0.4.0 — 2026-10-07

- E-book sending reads the new ebook-sender container instead of receiving a webhook: the entry takes the container's address (no key). Sensors "Sent" and, new, "Waiting for a recipient" (a count). `nas_hub_ebook_sent` still fires for every newly sent book.
- Breaking: an e-book entry set up with the webhook stops with a setup error until it is reconfigured with the container's address.
- Card: e-books waiting for a recipient, failed or too large carry a status chip.

## 0.3.2 — 2026-10-06

- Jellyfin "new": the re-scan check comes before the new-series check — Jellyfin re-creates the series item when its folder moves, which made a re-scanned series look brand new.

## 0.3.1 — 2026-10-06

- Jellyfin "new": a series added as a whole shows "New series · 16 seasons" instead of a capped episode count.
- A re-scan (files renamed or moved, every episode with a fresh "added" date) no longer reads as dozens of new episodes: for an existing series only recently aired episodes count; an old season added later still counts in full.
- More episodes are fetched (25 per list entry) so one big import cannot push the other series out of the list.

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
