"""sweetgreen scraper.

Unauthenticated GraphQL at https://order.sweetgreen.com/graphql provides full
per-item macros (proteinG, totalCarbsG, totalFatG, dietaryFiberG, calories) on
each menu product's baseProduct. Locations via restaurantsByLocation — filter
isOutpost=false (outposts are office drop-off shelves, not restaurants).
"""

import datetime
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

URL = "https://order.sweetgreen.com/graphql"
TODAY = datetime.date.today().isoformat()

LOCATIONS_QUERY = """query L($latitude: Float!, $longitude: Float!, $radius: Float!){
  restaurantsByLocation(latitude:$latitude, longitude:$longitude, radius:$radius){
    id name latitude longitude slug address city state zipCode isOutpost}}"""

MENU_QUERY = """query M($id: ID!){ restaurant(id:$id){ id name menu { categories {
  name products { id name description calories baseProduct {
    slug proteinG totalCarbsG totalFatG dietaryFiberG calories }}}}}}"""


def gql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "Content-Type": "application/json", "User-Agent": "Mozilla/5.0 Chrome/126"})
    out = json.load(urllib.request.urlopen(req, timeout=30))
    if out.get("errors"):
        raise RuntimeError(out["errors"])
    return out["data"]


CATEGORY_MAP = {
    "beverages": "drink", "drinks": "drink", "sides": "side", "dressings": "condiment",
    "dessert": "side", "featured": "side", "kids drinks": "drink",
    "kids meals": "meal", "summer menu": "meal", "wraps": "meal",
    "the function health menu": "meal", "bowls": "meal", "salads": "meal",
    "protein plates": "meal", "new": "meal", "ripple fries": "side", "custom": "component",
}


def main():
    locs_raw = gql(LOCATIONS_QUERY, {"latitude": 37.7749, "longitude": -122.4194, "radius": 8.0})
    stores = [r for r in locs_raw["restaurantsByLocation"]
              if r["city"] == "San Francisco" and not r["isOutpost"]]
    locations = [{
        "address": f"{r['address']}, San Francisco, CA {r['zipCode']}",
        "lat": r["latitude"], "lng": r["longitude"], "neighborhood": r["name"],
    } for r in stores]

    menu = gql(MENU_QUERY, {"id": stores[0]["id"]})["restaurant"]["menu"]
    items, seen = [], set()
    for cat in menu["categories"]:
        section = cat["name"].strip().lower()
        cat_kind = CATEGORY_MAP.get(section)
        if cat_kind is None:
            print(f"Warning: unmapped sweetgreen menu section {cat['name']!r}; defaulting to component", file=sys.stderr)
            cat_kind = "component"
        for p in cat["products"]:
            item_category = "drink" if "juice" in p["name"].lower() else cat_kind
            bp = p.get("baseProduct") or {}
            if bp.get("calories") in (None, 0) and not p.get("calories"):
                continue
            slug = bp.get("slug") or re.sub(r"[^a-z0-9]+", "-", p["name"].lower()).strip("-")
            if slug in seen:
                continue
            seen.add(slug)
            if bp.get("proteinG") is None:
                continue
            items.append({
                "id": slug, "name": p["name"], "description": p.get("description"),
                "category": item_category,
                "calories": bp["calories"], "protein_g": bp["proteinG"],
                "carbs_g": bp["totalCarbsG"], "fat_g": bp["totalFatG"],
                "fiber_g": bp.get("dietaryFiberG"), "sodium_mg": None,
                "serving_note": "per menu item as served",
                "is_estimate": False,
                "source": {"type": "published", "url": URL},
            })

    save_restaurant({
        "id": "sweetgreen", "name": "sweetgreen",
        "website": "https://www.sweetgreen.com",
        "nutrition_source": {"type": "published", "url": URL, "vendor": None, "retrieved": TODAY},
        "locations": locations, "items": items,
    })


if __name__ == "__main__":
    main()
