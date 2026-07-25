"""Super Duper Burgers scraper.

Super Duper publishes NO nutrition information anywhere (no menu PDF, no
nutrition page, no vendor widget in the Toast ordering flow), so this dataset is
deliberately CROWD data: fatsecret's user-submitted brand entries, pulled from
the fatsecret Platform REST API (OAuth 1.0a, HMAC-SHA1) — every item is
source_type "crowd" with is_estimate=True.

  nutrition: GET https://platform.fatsecret.com/rest/server.api
             ?method=foods.search&search_expression=Super+Duper
             then method=food.get.v2&food_id=<id> for full macros
  locations: https://www.superduperburgers.com/store-locator/ — the BentoBox
             storeLocatorConfig() payload embedded in the page carries the
             chain's own lat/lng per store, so no geocoding is needed.

TRAPS hit here:
  - fatsecret only carries 4 Super Duper rows. There is no Veggie Burger entry;
    the SEO pages that "have" one (snapcalorie / nutritionfactshub / macros.menu)
    are generated content, not crowd submissions, so it is skipped rather than
    invented.
  - The store locator lists the whole chain (Bay Area + Sacramento + Napa) and
    one suburban store carries an SF zip (Serramonte, "Daly City, CA 94105").
    Filter on the city field, never on the zip.
  - fatsecret's brand pages 503 under scripted requests; the REST API is the
    reliable path (spot check was done in real Chrome, see below).

Spot check: Super Burger, fatsecret web page rendered in real Chrome
(https://www.fatsecret.com/calories-nutrition/super-duper/super-burger) shows
670 cal / 41 g fat / 39 g carbs / 37 g protein — identical to the API parse.
"""

import base64
import datetime
import hashlib
import hmac
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

API_URL = "https://platform.fatsecret.com/rest/server.api"
SEARCH_URL = f"{API_URL}?method=foods.search&search_expression=Super+Duper"
LOCATOR_URL = "https://www.superduperburgers.com/store-locator/"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
TODAY = datetime.date.today().isoformat()

# fatsecret food_id -> (item slug, display name, category, description)
# Only rows whose brand_name is exactly "Super Duper" and that exist on the
# real Super Duper Burgers menu.
WANTED = {
    "2531611": ("super-burger", "Super Burger", "meal",
                "Quarter-pound burger with cheese, Super Sauce, lettuce, tomato, onion, pickle."),
    "50513027": ("mini-burger", "Mini Burger", "meal",
                 "Single mini patty burger with cheese, Super Sauce and fixings."),
    "16977722": ("chicken-sandwich", "Chicken Sandwich", "meal",
                 "Fried chicken sandwich."),
    "24470684": ("french-fries", "French Fries", "side", None),
}


def fatsecret(params):
    key = os.environ["FATSECRET_CONSUMER_KEY"]
    secret = os.environ["FATSECRET_CONSUMER_SECRET"]
    p = {
        "oauth_consumer_key": key,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_nonce": str(random.getrandbits(64)),
        "oauth_version": "1.0",
        "format": "json",
    }
    p.update(params)
    normalized = "&".join(f"{k}={urllib.parse.quote(str(p[k]), '')}" for k in sorted(p))
    base = "&".join(["GET", urllib.parse.quote(API_URL, ""), urllib.parse.quote(normalized, "")])
    p["oauth_signature"] = base64.b64encode(
        hmac.new((secret + "&").encode(), base.encode(), hashlib.sha1).digest()
    ).decode()
    req = urllib.request.Request(f"{API_URL}?{urllib.parse.urlencode(p)}", headers={"User-Agent": UA})
    return json.load(urllib.request.urlopen(req, timeout=30))


def _num(value):
    return None if value in (None, "") else float(value)


def brand_foods():
    """food_id -> search hit, for brand_name == 'Super Duper' only."""
    hits = {}
    for expr in ("Super Duper", "Super Duper Burgers", "Super Duper Chicken Sandwich",
                 "Super Duper Veggie Burger", "Super Duper Fries"):
        foods = fatsecret({"method": "foods.search", "search_expression": expr, "max_results": 50})
        foods = foods.get("foods", {}).get("food", [])
        if isinstance(foods, dict):
            foods = [foods]
        for f in foods:
            if (f.get("brand_name") or "").strip().lower() == "super duper":
                hits[f["food_id"]] = f
    return hits


def items():
    found = brand_foods()
    missing = sorted(set(WANTED) - set(found))
    if missing:
        print(f"note: no fatsecret entry for food_id(s) {missing}", file=sys.stderr)
    out = []
    for food_id, (slug, name, category, desc) in WANTED.items():
        if food_id not in found:
            continue
        food = fatsecret({"method": "food.get.v2", "food_id": food_id})["food"]
        servings = food["servings"]["serving"]
        if isinstance(servings, dict):
            servings = [servings]
        # prefer the whole-item serving ("1 burger"/"1 sandwich") over per-100g
        serving = servings[0]
        for s in servings:
            if re.match(r"^1 (burger|sandwich|serving)", s.get("serving_description", "")):
                serving = s
                break
        out.append({
            "id": slug,
            "name": name,
            "description": desc,
            "category": category,
            "calories": _num(serving["calories"]),
            "protein_g": _num(serving["protein"]),
            "carbs_g": _num(serving["carbohydrate"]),
            "fat_g": _num(serving["fat"]),
            "fiber_g": _num(serving.get("fiber")),
            "sodium_mg": _num(serving.get("sodium")),
            "serving_note": f"per {serving['serving_description'].strip()} "
                            f"(crowd-submitted; Super Duper publishes no nutrition)",
            "is_estimate": True,
            "source": {"type": "crowd", "url": food["food_url"]},
        })
    return out


def sf_locations():
    req = urllib.request.Request(LOCATOR_URL, headers={"User-Agent": UA})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    # BentoBox embeds each store as JSON inside storeLocatorConfig(...);
    # lat/lng precede the address block in the same object.
    pattern = re.compile(
        r'"lat":\s*"([-0-9.]+)",\s*"lng":\s*"([-0-9.]+)".{0,4000}?'
        r'"address":\s*"([^"]*)",\s*"street":\s*"([^"]*)",\s*"city":\s*"([^"]*)"',
        re.S,
    )
    locs, seen = [], set()
    for lat, lng, address, _street, city in (m.groups() for m in pattern.finditer(html)):
        if city.strip().rstrip(",").lower() != "san francisco":
            continue  # chain-wide locator; zip codes are unreliable, city is not
        address = address.strip()
        if address in seen:
            continue
        seen.add(address)
        locs.append({"address": address, "lat": float(lat), "lng": float(lng), "neighborhood": None})
    if not locs:
        raise SystemExit("no SF locations parsed — store locator payload shape changed")
    return locs


def main():
    save_restaurant({
        "id": "super-duper-burgers",
        "name": "Super Duper Burgers",
        "website": "https://www.superduperburgers.com",
        "nutrition_source": {
            "type": "crowd",
            "url": SEARCH_URL,
            "vendor": "fatsecret",
            "retrieved": TODAY,
        },
        "locations": sf_locations(),
        "items": items(),
    })


if __name__ == "__main__":
    main()
