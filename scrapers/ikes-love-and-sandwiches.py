"""Ike's Love & Sandwiches scraper.

Nutrition: ikessandwich.com/nutritional/ links to Ike's contracted Nutritionix
portal; the full grid is https://www.nutritionix.com/ikes-love-sandwiches/menu/premium
(source "vendor", vendor "nutritionix"). TRAP: the brand slug is
"ikes-love-sandwiches" (no "and"), so guessing the slug from the trade name
404s.

TRAP: sandwich rows are ALREADY complete builds — the section header says the
numbers are "for Meat Sandwiches made on Dutch Crunch Bread, and include the
default cheese and regular Dirty Sauce". The Bread / Cheese / Dirty Sauce
sections below are swap-out references (cheese is per 1 oz), NOT additions, so
nothing is derived here and those rows stay components/condiments. Adding a
bread row to a sandwich row would double-count the bread.

Locations: official SOCi locator locations.ikessandwich.com. Its
/rest/locatorsearch JSON endpoint 302s to the homepage unless it is called from
the page itself, and it geolocates off the caller's IP (from this VM it returned
Reno/Boardman stores), so the store list is taken from the locator's own
sitemap.xml and each store page's schema.org LocalBusiness block, which carries
the official lat/lng — no geocoding needed.
"""

from __future__ import annotations

import datetime
import json
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE))

import _nutritionix as nx  # noqa: E402
from save import save_restaurant  # noqa: E402

BRAND = "ikes-love-sandwiches"
MENU_URL = nx.menu_url(BRAND)
SITEMAP_URL = "https://locations.ikessandwich.com/sitemap.xml"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36"}

_SAUCE_RE = re.compile(r"sauce|dressing|mustard", re.I)


def categorize(section: str, name: str) -> str:
    """Sandwiches are complete builds; everything else is a swap-out reference."""
    if section.startswith(("Meat Sandwiches", "Veggie Sandwiches", "Kids Menu")):
        return "meal"
    if section.startswith("Dirty Sauce") or section.endswith("Side of Sauce"):
        return "condiment"
    if section.startswith("Kids Additional Options"):
        return "condiment" if _SAUCE_RE.search(name) else "component"
    if section.startswith("Catering Salads"):
        return "component"      # party bowls, 2000+ kcal each
    # Bread / Cheese reference sections.
    return "component"


def serving_note(section: str, name: str) -> str:
    if section.startswith(("Meat Sandwiches", "Veggie Sandwiches")):
        return "per whole sandwich on Dutch Crunch bread, with default cheese and regular Dirty Sauce"
    if section.startswith("Kids Menu"):
        return "per kids-menu order"
    if "Cheese" in section:
        return "per 1 oz portion of cheese (swap-out reference, already included in sandwich rows)"
    if "Bread" in section:
        return "per sandwich roll (swap-out reference, already included in sandwich rows)"
    if section.startswith("Dirty Sauce"):
        return "per sandwich portion of sauce (already included in sandwich rows)"
    if section.startswith("Catering Salads"):
        return "per catering salad bowl (multiple servings)"
    return "per item as served"


def sf_locations():
    sitemap = urllib.request.urlopen(
        urllib.request.Request(SITEMAP_URL, headers=UA), timeout=60
    ).read().decode("utf-8", "replace")
    urls = sorted(set(re.findall(
        r"https://locations\.ikessandwich\.com/ca/san-francisco/\d+/", sitemap
    )))

    locations = []
    for url in urls:
        page = urllib.request.urlopen(
            urllib.request.Request(url, headers=UA), timeout=60
        ).read().decode("utf-8", "replace")
        store = None
        for blob in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
            try:
                data = json.loads(blob)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("@type") == "LocalBusiness":
                store = data
                break
        if store is None:
            raise SystemExit(f"ikes: no LocalBusiness block on {url}")
        addr, geo = store["address"], store["geo"]
        if addr["addressLocality"].strip() != "San Francisco" or addr["addressRegion"] != "CA":
            continue
        locations.append({
            "address": f"{addr['streetAddress']}, San Francisco, CA {addr['postalCode']}",
            "lat": float(geo["latitude"]),
            "lng": float(geo["longitude"]),
            "neighborhood": None,
        })
    if not locations:
        raise SystemExit("ikes: no SF locations found — locator layout probably changed")
    return locations


def main() -> None:
    html = nx.fetch(BRAND)
    retrieved = nx.last_updated(html) or datetime.date.today().isoformat()

    items, seen = [], set()
    for row in nx.parse_rows(html):
        if row.get("calories") is None:
            continue
        name, section = row["name"], row["section"] or ""
        items.append({
            "id": nx.dedupe_id(nx.slug(name), seen),
            "name": name,
            "description": f"Ike's menu section: {section.split(' Nutrition information')[0]}." if section else None,
            "category": categorize(section, name),
            "serving_note": serving_note(section, name),
            "is_estimate": False,
            "source": {"type": "vendor", "url": MENU_URL},
            "calories": row["calories"],
            "protein_g": row.get("protein_g") or 0,
            "carbs_g": row.get("carbs_g") or 0,
            "fat_g": row.get("fat_g") or 0,
            "fiber_g": row.get("fiber_g"),
            "sodium_mg": row.get("sodium_mg"),
        })

    spot_check(items)

    save_restaurant({
        "id": "ikes-love-and-sandwiches",
        "name": "Ike's Love & Sandwiches",
        "website": "https://www.ikessandwich.com",
        "nutrition_source": {
            "type": "vendor",
            "url": MENU_URL,
            "vendor": "nutritionix",
            "retrieved": retrieved,
        },
        "locations": sf_locations(),
        "items": items,
    })


# Famous item: the Menage A Trois (#111). FatSecret has no Ike's brand data, so
# the independent number comes from Ike's own ordering platform, which posts
# California menu calories in the item description — "111. MENAGE A TROIS ...
# [1610 cal]" (oxb.pxsweb.com menu tier behind
# ikesloveandsandwiches.orderexperience.net) vs 1600 kcal in the vendor grid.
def spot_check(items) -> None:
    hit = next((i for i in items if i["name"].startswith("111. Menage A Trois")), None)
    if hit is None:
        raise SystemExit("ikes: spot-check item 'Menage A Trois' missing")
    if not 1300 <= hit["calories"] <= 1900:
        raise SystemExit(f"ikes: spot check failed — Menage A Trois {hit['calories']} kcal")
    print(
        f"spot check: {hit['name']} {hit['calories']} kcal / {hit['protein_g']}g protein / "
        f"{hit['carbs_g']}g carbs / {hit['fat_g']}g fat"
    )


if __name__ == "__main__":
    main()
