"""The Melt scraper.

Published nutrition:
  - GET https://www.themelt.com/_api/v1/access-tokens
  - POST https://www.themelt.com/_api/cloud-data/v1/wix-data/collections/query
    for the Nutrition-All collection (99 rows)
  - Nutritionix's public The Melt menu was checked as a secondary source for
    the newer blank Wix items; it had no exact full-macro rows for those items,
    so no vendor overrides are used.

Locations use the same Wix query endpoint against Store_Hours-test and the
rendered /locations page. The Wix cloud-data endpoint 429s aggressively, and
short or unusual User-Agents are blocked; use a full desktop Chrome
User-Agent, reuse one token, and pause between page requests. The published
nutrition collection also silently ships rows with every nutrition column
empty for its newest menu items, so a naive scraper could emit zero-calorie
meals. Those rows are intentionally passed to save_restaurant so validation
quarantines them rather than dropping them.
"""

from __future__ import annotations

import datetime
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

SITE = "https://www.themelt.com"
TOKEN_URL = f"{SITE}/_api/v1/access-tokens"
QUERY_URL = f"{SITE}/_api/cloud-data/v1/wix-data/collections/query"
LOCATIONS_URL = f"{SITE}/locations"
APP_ID = "14f25924-5664-31b2-9568-f9c5ed98c9b1"
GRID_APP_ID = "86325f16-e4f2-4f64-9dff-aaa151e910da"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
TODAY = datetime.date.today().isoformat()


def fetch(url, data=None, headers=None):
    request = urllib.request.Request(
        url, data=data, headers={"User-Agent": UA, **(headers or {})}
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code != 429:
            raise
        command = ["curl", "-fsSL", "-A", UA]
        for key, value in (headers or {}).items():
            command.extend(["-H", f"{key}: {value}"])
        if data is not None:
            command.extend(["--data-binary", data])
        command.append(url)
        return subprocess.check_output(command)


def query(token, collection, offset=0):
    body = json.dumps(
        {
            "collectionName": collection,
            "dataQuery": {"paging": {"limit": 50, "offset": offset}},
            "segment": "LIVE",
            "appId": GRID_APP_ID,
        }
    ).encode()
    result = json.loads(
        fetch(
            QUERY_URL,
            body,
            {"Authorization": token, "Content-Type": "application/json"},
        )
    )
    return result


def number(value):
    if value is None or value == "":
        return None
    match = re.match(r"\s*(-?\d+(?:\.\d+)?)", str(value))
    return float(match.group(1)) if match else None


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


CATEGORY_OVERRIDES = {
    "BBQ Bacon Grilled Chicken": "meal",
    "The Kid Chicken Caesar Salad": "meal",
    "Add Make it a Float": "component",
    "Egg Whites": "component",
    "CHEESE": "component",
    "Soft Serve Cup": "side",
    "Side Caesar Salad": "side",
    "Spinach": "component",
    "Pickle Spear": "component",
    "Pickle, sliced": "component",
    "Fresh Tomato ( two slices)": "component",
    "Fresh Jalapeno": "component",
    "Fresh Red Onion": "component",
    "Pickled Onion": "component",
    "Caramelized Onions": "component",
    "Grilled Mushroom": "component",
    "Fontina": "component",
    "Aged Cheddar": "component",
    "Pepper Jack": "component",
    "Muenster": "component",
    "Provolone": "component",
    "Three Cheese Blend": "component",
    "Swiss": "component",
    "Fontina/Provolone Blend": "component",
    "Add Malt": "component",
    "Add Chocolate Crunch": "component",
    "Beef Patty": "component",
    "Grilled Chicken": "component",
    "Chopped Chicken": "component",
    "Smoked Bacon": "component",
    "Fried Egg": "component",
    "Housemade Aioli": "condiment",
    "Melt Sauce": "condiment",
    "Caesar Dressing": "condiment",
    "Spicy Ketchup": "condiment",
    "Avocado": "component",
    "Romaine lettuce": "component",
    "Green leaf lettuce": "component",
}


def category(row):
    name = row["itemName"]
    source = (row.get("category") or "").lower()
    if source in {"", "---desserts", "add-ons", "add ons", "salads and soup"}:
        try:
            return CATEGORY_OVERRIDES[name]
        except KeyError as error:
            raise RuntimeError(
                f"Unmapped blank/junk category row: {name!r} ({row.get('category')!r})"
            ) from error
    if name in {"Housemade Aioli", "Melt Sauce", "Caesar Dressing", "Spicy Ketchup"}:
        return "condiment"
    if "shake" in name.lower() or source == "shakes":
        return "drink"
    if name in {"Caesar Salad", "Chopped Cobb Salad", "Garlic Chicken Bacon Mac", "Steak Fajita Mac"}:
        return "meal"
    if name == "Side Caesar Salad" or name == "Tomato Soup":
        return "side"
    if source == "fries" or "dessert" in source or name in {
        "Soft Serve Cone",
        "Soft Serve Cup",
        "Chocolate Chip Cookie",
        "Fresh Apple",
    }:
        return "side"
    if source == "drinks":
        return "drink"
    if source in {"meltburgers", "melted classics", "grilled chicken", "kids"}:
        return "meal"
    if source in {"add-ons", "add ons"}:
        return CATEGORY_OVERRIDES[name]
    if not source:
        raise RuntimeError(f"Unmapped blank category row: {name!r}")
    return "component"


def serving_note(name, kind):
    if kind == "meal":
        if "salad" in name.lower():
            return "per salad as served"
        if "mac" in name.lower():
            return "per bowl as served"
        if name.startswith("The Kid"):
            return "per kids meal as served"
        return "per sandwich as served"
    if kind == "drink":
        if "shake" in name.lower():
            return "per shake as served"
        return "per beverage as served"
    return {
        "side": "per regular order",
        "condiment": "per add-on portion",
        "component": "per add-on portion",
    }[kind]


def location_slug(address):
    street = address.get("streetAddress") if isinstance(address, dict) else None
    if isinstance(street, dict) and street.get("number") and street.get("name"):
        value = f"{street['number']} {street['name']}"
    else:
        value = address.get("formatted", "").split(",", 1)[0]
    suffixes = {
        "street": "st",
        "avenue": "ave",
        "boulevard": "blvd",
        "road": "rd",
        "drive": "dr",
    }
    value = re.sub(
        r"\b(street|avenue|boulevard|road|drive)\b",
        lambda match: suffixes[match.group(1).lower()],
        value,
        flags=re.I,
    )
    return slug(value)


def locations(token):
    page = fetch(LOCATIONS_URL).decode()
    rendered = set(
        re.findall(r'href="https://www\.themelt\.com/locations/([^"]+)"', page)
    )
    rows = query(token, "Store_Hours-test")["items"]
    result = []
    for row in rows:
        address = row.get("address")
        if row.get("city") != "San Francisco" or not isinstance(address, dict):
            continue
        formatted = address.get("formatted", "")
        route = f"san-francisco/{location_slug(address)}"
        if route not in rendered:
            continue
        point = address.get("location") or {}
        result.append(
            {
                "address": re.sub(r"\s*,\s*USA$", "", formatted).replace("St.,", "St,"),
                "lat": point.get("latitude"),
                "lng": point.get("longitude"),
                "neighborhood": None,
            }
        )
    for row in result:
        if row["lat"] is not None:
            continue
        url = (
            "https://nominatim.openstreetmap.org/search?format=json&limit=1&q="
            + urllib.parse.quote(row["address"])
        )
        found = json.loads(
            fetch(url, headers={"User-Agent": "sf-meal-finder research/1.0"})
        )
        if not found:
            raise RuntimeError(f"Could not geocode {row['address']}")
        row["lat"], row["lng"] = float(found[0]["lat"]), float(found[0]["lon"])
        time.sleep(1.1)
    for row in result:
        row["neighborhood"] = None
    return result


def main():
    token = json.loads(fetch(TOKEN_URL))["apps"][APP_ID]["instance"]
    first = query(token, "Nutrition-All", 0)
    rows = first["items"]
    if first.get("totalCount", len(rows)) > len(rows):
        time.sleep(10)
        rows.extend(query(token, "Nutrition-All", 50)["items"])

    items = []
    seen = set()
    for row in rows:
        name = row.get("itemName")
        if not name or name in seen:
            continue
        seen.add(name)
        kind = category(row)
        items.append(
            {
                "id": slug(name),
                "name": name,
                "description": None,
                "category": kind,
                "calories": number(row.get("caloriesCal")),
                "protein_g": number(row.get("proteinG")),
                "carbs_g": number(row.get("carbohydratesG")),
                "fat_g": number(row.get("totalFatG")),
                "fiber_g": number(row.get("dietaryFiberG")),
                "sodium_mg": number(row.get("sodiumMg")),
                "serving_note": serving_note(name, kind),
                "is_estimate": False,
            }
        )

    save_restaurant(
        {
            "id": "the-melt",
            "name": "The Melt",
            "website": SITE,
            "nutrition_source": {
                "type": "published",
                "url": QUERY_URL,
                "vendor": None,
                "retrieved": TODAY,
            },
            "locations": locations(token),
            "items": items,
        }
    )


if __name__ == "__main__":
    main()
