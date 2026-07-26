"""California Pizza Kitchen MyMenu nutrition scraper."""

import datetime
import json
import re
import sys
import urllib.parse
import urllib.request
import ssl
from http.cookiejar import CookieJar
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

VENDOR_URL = "https://cpk.mymenuhd.com/MyMenu/LoadMenu"
LOCATIONS_URL = "https://api.cpk.com/api/v1.0/restaurants/cpk-stores"
TODAY = datetime.date.today().isoformat()


def load_menu():
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.open(
        urllib.request.Request(
            "https://cpk.mymenuhd.com/MyMenu/Index/10?menu=36&sInitialView=false",
            headers={"User-Agent": "Mozilla/5.0"},
        ),
        timeout=60,
    )
    req = urllib.request.Request(
        VENDOR_URL, data=b"{}", method="POST",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    return json.loads(opener.open(req, timeout=60).read())


def iter_items(section):
    for item in section.get("menuItems", []):
        if item.get("publish") and item.get("item_Nutrition"):
            yield section["name"], item
    for child in section.get("sections", []):
        yield from iter_items(child)


def category(section, name):
    s = f"{section} {name}".lower()
    if any(x in s for x in ("beverage", "drink", "cocktail", "wine", "beer", "sangria", "coffee", "tea")):
        return "drink"
    if any(x in s for x in ("sauce", "dressing", "side of ", "add ")):
        return "condiment" if any(x in s for x in ("sauce", "dressing")) else "component"
    if section in {"Starters", "Soups", "Sweet Treats", "CPKids Sweets", "CPKids Chicken  ",
                   "CPKids Salads & Pastas"}:
        return "side"
    if section == "Smart Swaps" and any(
        x in name.lower() for x in ("egg roll", "cauliflower", "buffalo", "guacamole", "tostada")
    ):
        return "side"
    if section in {"Lunch Duos", "Main Plates", "Salads", "Pastas", "Sandwiches",
                   "Lunch Size Pastas", "Lunch Size Pizzas", "Classic Pizzas",
                   "Globally Inspired Pizzas", "Gluten-Free Pizzas", "CPK Original Pizzas",
                   "CPKids Pizzas", "CPKids Gluten-Free"}:
        return "meal"
    if section == "Smart Swaps":
        return "meal"
    return "component"


def get_locations():
    req = urllib.request.Request(LOCATIONS_URL, headers={"User-Agent": "Mozilla/5.0"})
    data = json.load(urllib.request.urlopen(
        req, timeout=60, context=ssl._create_unverified_context()
    ))
    out = []
    for r in data["data"]["restaurants"]:
        if r.get("city") != "San Francisco":
            continue
        out.append({
            "address": f"{r['address']}, {r['city']}, {r['state']} {r['zip']}",
            "lat": float(r["latitude"]), "lng": float(r["longitude"]),
            "neighborhood": None,
        })
    return out


def main():
    menu = load_menu()
    items = []
    seen = set()
    for section in menu["MenuHierarchy"]["sections"]:
        for section_name, row in iter_items(section):
            nutrition = row["item_Nutrition"]
            name = row["name"].strip()
            if not name or name in seen:
                continue
            # Smart Swaps are alternate builds of base dishes. Prefer the
            # ordinary menu row unless no base row exists; named pizza-size
            # variants remain distinct orderable builds.
            if any(x in name.lower() for x in ("protein packed", "lower cal", "plant forward")):
                continue
            seen.add(name)
            def number(key):
                value = nutrition.get(key)
                return round(float(value), 1) if value not in (None, "", "--") else 0
            items.append({
                "id": "vendor-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"),
                "name": name,
                "description": None,
                "category": (
                    "component"
                    if nutrition.get("aum", "").lower() == "slice"
                    else category(section_name, name)
                ),
                "calories": number("calories"),
                "protein_g": number("protein"),
                "carbs_g": number("carbs"),
                "fat_g": number("fat"),
                "fiber_g": number("fiber"),
                "sodium_mg": number("sodium"),
                "serving_note": f"per {nutrition.get('q', '1')} {nutrition.get('aum', 'serving').lower()}",
                "is_estimate": False,
                "source": {"type": "vendor", "url": VENDOR_URL},
            })
    spot = next(
        (x for x in items if x["name"] == "Original BBQ Chicken Pizza"),
        next((x for x in items if "Original BBQ Chicken Pizza" in x["name"]), None),
    )
    if spot:
        print("CPK BBQ Chicken Pizza spot-check:", spot["calories"], "kcal")
    save_restaurant({
        "id": "california-pizza-kitchen",
        "name": "California Pizza Kitchen",
        "website": "https://www.cpk.com",
        "nutrition_source": {
            "type": "vendor", "url": VENDOR_URL, "vendor": "Healthy Dining",
            "retrieved": TODAY,
        },
        "locations": get_locations(),
        "items": items,
    })


if __name__ == "__main__":
    main()
