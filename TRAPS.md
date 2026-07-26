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
- Crowd nutrition pages can expose calories without macros (MyNetDiary); skip
  those rows rather than filling missing values with zeroes. FatSecret brand
  names may prefix the product ("& The Juice Tunacado"), so strip the brand
  before category matching, and expect the Platform API to rate-limit quickly.
- Image-backed nutrition needs independent OCR agreement; never choose between
  OCR candidates because one satisfies the macro check. Verify tables against
  the source image, since wrong sodium or serving sizes can still pass validation.
- A nutrition PDF may contain only image panels, and tiny embedded rasters can
  defeat Tesseract; extract the native image and use a higher-quality OCR engine.
  Never publish OCR rows whose product name is unrecoverable.
- Square Online location pages may expose a placeholder address; prefer the
  chain's store-location API. Likewise, "locations" pages can list SEO,
  coming-soon, or stale markets—confirm city-proper stores with the official
  locator.
- Vendor calculators require structural checks: blank cells are not zero,
  normalize malformed decimals explicitly, count parsed cells against headers,
  and reject builds that depend on blank component rows.
- Check size-series monotonicity in bowl and pizza tables, and categorize
  smoothie/juice sections by their source section rather than row shape.
- Nutrition locators and nutrition guides drift independently: verify current
  locations from the chain locator, and verify the exact product variant and
  serving unit before comparing a famous item.
- Rotated PDF headers still provide usable x-position anchors; assert their
  left-to-right order instead of trusting extracted header text or fixed column
  indexes.
- Per-serving party packs can legitimately exceed the sodium plausibility cap;
  quarantine them rather than weakening the bound.
