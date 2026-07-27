# Devin Eats

Find meals in San Francisco by calorie range and protein minimum, with a map of
every place that serves them. The point is trustworthy numbers and real local
coverage: every row is validated, every number's provenance is tracked, and
every restaurant carries all of its SF locations with lat/lng.

## Data

76 restaurants, 4,100+ meals (plus sides/drinks/condiments/components kept as
non-surfaced modifiers) — national chains and SF locals alike. Current counts
come from `app/public/data/restaurants.json` and `meals.json`.

Guarantees, enforced in `pipeline/` (see `pipeline/README.md`):

- **Only meals surface.** Every row is tagged `meal | side | drink | condiment | component`.
- **Every number is validated**: `9·fat + 4·carbs + 4·protein` must land near
  stated calories (asymmetric tolerance; see `pipeline/validate.py`). Failures
  are quarantined in `data/rejected/`, never silently dropped, never published.
- **Provenance per number**: `published | vendor | crowd | derived`, with the
  exact endpoint/file URL and retrieval date. Crowd/derived rows render as
  estimates (`~` prefix + amber badge) and are excluded unless the user opts in.
- **Locations are data**: all SF locations per restaurant with lat/lng,
  bounds-checked against the city.

Scrapers live in `scrapers/` — one per restaurant, each importing the shared
`save_restaurant()`. Re-run any of them to refresh, then `python3
pipeline/build_dist.py` to regenerate the app's data files. `TRAPS.md` records
everything that burned us.

## App

`app/` — Vite + React + TypeScript, Leaflet/OpenStreetMap (no API key).

```bash
cd app && npm install && npm run dev
```

Dense tool UI: filter bar (calorie range, protein min, search, estimate opt-in),
results table sorted by protein, map with per-location dots.
Security posture: all scraped text is sanitized on ingest and rendered as React
text (never HTML); the app is fully static with no server or secrets; scraper
credentials stay in environment variables.
