"""Chipotle scraper.

Chipotle publishes per-COMPONENT nutrition (each ingredient portion), not
per-meal totals — its site shows only calorie ranges per entree. So:
  - components are saved as category "component" with source "published"
  - canonical meals (standard builds) are DERIVED as sums of published
    components: source "derived", is_estimate=True, recipe in description.

APIs (client-side key ships in https://orderweb-cdn.chipotle.com/js/app.js,
works from curl with header Ocp-Apim-Subscription-Key):
  - nutrition per item: GET https://services.chipotle.com/menu-metadata/v1/menu-metadata/nutrition?channel=web&region=US
    -> items[<itemId>].nutrition {tcal, prot, carb, tfat, fibe, sodi}
  - item names: GET https://services.chipotle.com/menuinnovation/v1/universalmenus/menurules?country=US
  - SF locations: POST https://services.chipotle.com/restaurant/v3/restaurant
TRAP: entree ids like CMG-1 "Chicken Burrito" carry ONLY the protein
filling's macros (4 oz chicken = 180 cal), not the whole burrito.
"""

import datetime
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

KEY = "b4d9f36380184a3788857063bce25d6a"
BASE = "https://services.chipotle.com"
NUTRITION_URL = f"{BASE}/menu-metadata/v1/menu-metadata/nutrition?channel=web&region=US"
RULES_URL = f"{BASE}/menuinnovation/v1/universalmenus/menurules?country=US"
RESTAURANT_URL = f"{BASE}/restaurant/v3/restaurant"
HEADERS = {"Ocp-Apim-Subscription-Key": KEY, "User-Agent": "Mozilla/5.0 Chrome/126"}
TODAY = datetime.date.today().isoformat()


def get(url, data=None):
    req = urllib.request.Request(url, headers=dict(HEADERS), data=data)
    if data:
        req.add_header("Content-Type", "application/json")
    return json.load(urllib.request.urlopen(req, timeout=30))


# component itemId -> short label; standard-portion items only
COMPONENTS = {
    "CMG-1": "Chicken (4 oz)",
    "CMG-2": "Steak (4 oz)",
    "CMG-3": "Carnitas (4 oz)",
    "CMG-4": "Barbacoa (4 oz)",
    "CMG-5": "Sofritas (4 oz)",
    "CMG-16": "Chicken Tinga (4 oz)",
    "CMG-17": "Crispy Chicken (4 oz)",
    "CMG-11": "Pollo Asado (4 oz)",
    "CMG-5001": "White Rice (4 oz)",
    "CMG-5002": "Brown Rice (4 oz)",
    "CMG-5051": "Black Beans (4 oz)",
    "CMG-5052": "Pinto Beans (4 oz)",
    "CMG-5101": "Fajita Veggies",
    "CMG-5201": "Fresh Tomato Salsa",
    "CMG-5204": "Tomatillo-Red Chili Salsa",
    "CMG-5251": "Sour Cream",
    "CMG-5252": "Cheese",
    "CMG-5301": "Guacamole (4 oz)",
    "CMG-5351": "Romaine Lettuce",
    "CMG-5501": "Burrito Flour Tortilla",
    "CMG-5403": "2 Crispy Corn Tortillas",
    "CMG-5404": "2 Soft Flour Tortillas",
    "CMG-5353": "Chipotle-Honey Vinaigrette",
}

FILLINGS = {
    "chicken": ("CMG-1", "Chicken"),
    "steak": ("CMG-2", "Steak"),
    "carnitas": ("CMG-3", "Carnitas"),
    "barbacoa": ("CMG-4", "Barbacoa"),
    "sofritas": ("CMG-5", "Sofritas"),
    "pollo-asado": ("CMG-11", "Pollo Asado"),
}

# format -> (label, extra component ids beyond filling)
BOWL = ["CMG-5001", "CMG-5051", "CMG-5201", "CMG-5252", "CMG-5351"]
FORMATS = {
    "bowl": ("Burrito Bowl", BOWL, "with white rice, black beans, fresh tomato salsa, cheese and lettuce"),
    "burrito": ("Burrito", ["CMG-5501"] + BOWL, "with white rice, black beans, fresh tomato salsa, cheese and lettuce"),
    "salad": ("Salad", ["CMG-5351", "CMG-5051", "CMG-5201", "CMG-5252", "CMG-5353"], "with black beans, fresh tomato salsa, cheese and honey vinaigrette"),
}


def main():
    nut = get(NUTRITION_URL)["items"]
    rules = get(RULES_URL)
    names = {}

    def walk(o):
        if isinstance(o, dict):
            if "itemId" in o and "itemName" in o:
                names[o["itemId"]] = o["itemName"]
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(rules)

    def macros(cid):
        n = nut[cid]["nutrition"]
        return {
            "calories": n["tcal"], "protein_g": n["prot"], "carbs_g": n["carb"],
            "fat_g": n["tfat"], "fiber_g": n.get("fibe"), "sodium_mg": n.get("sodi"),
        }

    items = []
    for cid, label in COMPONENTS.items():
        m = macros(cid)
        p = nut[cid].get("portion") or {}
        items.append({
            "id": f"component-{cid.lower()}", "name": label, "description": None,
            "category": "component", "is_estimate": False,
            "serving_note": f"per {p.get('value')} {p.get('unit')}" if p else None,
            "source": {"type": "published", "url": NUTRITION_URL}, **m,
        })

    for fkey, (fid, fname) in FILLINGS.items():
        for fmt, (flabel, extras, desc) in FORMATS.items():
            total = {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": 0, "sodium_mg": 0}
            for cid in [fid] + extras:
                m = macros(cid)
                for k in total:
                    total[k] += m[k] or 0
            items.append({
                "id": f"{fkey}-{fmt}",
                "name": f"{fname} {flabel}",
                "description": f"Standard build {desc}. Sum of Chipotle's published per-ingredient nutrition.",
                "category": "meal", "is_estimate": True,
                "serving_note": "per standard entree build",
                "source": {"type": "derived", "url": NUTRITION_URL}, **total,
            })

    body = json.dumps({
        "latitude": 37.7749, "longitude": -122.4194, "radius": 8000,
        "restaurantStatuses": ["OPEN"], "conceptIds": ["CMG"],
        "orderBy": "distance", "orderByDescending": False,
        "pageSize": 50, "pageIndex": 0,
        "embeds": {"addressTypes": ["MAIN"], "realHours": False, "directions": False,
                   "catering": False, "onlineOrdering": False, "timezone": False,
                   "marketing": False, "chipotlane": False, "sustainability": False,
                   "experience": False},
    }).encode()
    locs = []
    for r in get(RESTAURANT_URL, body)["data"]:
        a = r["addresses"][0]
        if a.get("locality") != "San Francisco":
            continue
        locs.append({
            "address": f"{a['addressLine1'].strip()}, San Francisco, CA {a.get('postalCode', '')}".strip(),
            "lat": a["latitude"], "lng": a["longitude"], "neighborhood": None,
        })

    save_restaurant({
        "id": "chipotle", "name": "Chipotle Mexican Grill",
        "website": "https://www.chipotle.com",
        "nutrition_source": {"type": "published", "url": NUTRITION_URL, "vendor": None, "retrieved": TODAY},
        "locations": locs, "items": items,
    })


if __name__ == "__main__":
    main()
