# TRAPS

Things that cost >15 minutes on this project. Add to this whenever you get burned.

- Macro check tolerance is asymmetric on purpose (see `pipeline/validate.py`):
  computed-over-stated is usually fiber/rounding; computed-under-stated usually
  means alcohol or wrong numbers. Don't loosen it to make failures pass —
  quarantine and record.
- Check what a row is *per* (per slice vs per whole pizza, per component vs per
  serving) before saving. `serving_note` is required thinking, even if optional
  in schema.
- Ordering APIs and nutrition APIs can reuse ids for different things — spot
  check a famous item before trusting a join.
- Chipotle: entree ids (CMG-1 "Chicken Burrito") carry ONLY the 4-oz protein
  filling's macros, not the whole burrito. Meals must be derived as sums of
  components. Its menu/ordering APIs have no macros at all — nutrition lives at
  `menu-metadata/v1/menu-metadata/nutrition` (see scrapers/chipotle.py).
- Empty-looking JS apps are often bot-blocked, not empty: load in real Chrome
  via CDP (see the Playwright capture pattern) and read network responses.
  Client-side API keys ship in the JS bundle and work from curl.
- sweetgreen: `restaurantsByLocation` returns outposts (office drop-off
  shelves) — filter `isOutpost=false` or the map fills with non-restaurants.
- High-fiber, low-cal items (e.g. OLIPOP: 35 kcal, 9 g fiber) legitimately fail
  the macro overshoot check. That's the check working — leave them quarantined.
- Shake Shack: the widely-linked 2023 master nutrition PDF is stale, and
  `shakeshack.com/*` is Cloudflare-403 even in real Chrome. The current PDF is
  served from `prod.shakeshack.com/nutritionandallergeninfo`.
- Panda Express: `pandaexpress.com/nutritioninformation` is DataDome-blocked to
  curl; parse the rendered table in real Chrome via CDP, by labeled cells
  (`title="Protein (g)"`), never by column position. Entree servings aren't
  meals — plates/bowls must be derived (side + 1-2 entree servings).
- The Melt: EveryBite GraphQL has no exposed client key; their published data
  actually lives in a Wix cloud-data collection (`Nutrition-All`) queried with
  an instance token from `/_api/v1/access-tokens`. Wix 429s aggressive UAs.
  Newest items ship with all-empty nutrition columns — quarantine, don't zero.
- fatsecret brand pages 503 under scripted requests; use the Platform REST API
  (OAuth1, creds in env). SEO calorie sites (snapcalorie, macros.menu) are
  generated content, not crowd data — don't treat them as sources.
- Store locators list whole chains: filter on the city field, not zip (a Daly
  City store carries an SF zip). Chain-provided lat/lng beats geocoding.
- Alcohol rows (Mendocino Farms wines/beers) fail the macro undershoot check by
  design (7 kcal/g alcohol isn't in the macros) — correct quarantine.
