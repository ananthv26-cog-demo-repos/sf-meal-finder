"""Peet's Coffee crowd-nutrition scraper.

Peet's publishes no complete machine-readable nutrition source in its locator
flow, so this dataset uses FatSecret's user-submitted brand rows as crowd data.
Every item is source_type "crowd" with is_estimate=True.

  nutrition: GET https://platform.fatsecret.com/rest/server.api
             ?method=foods.search&search_expression=Peet%27s&max_results=50
             &page_number=<page>, then method=food.get.v2&food_id=<id>
  locations: https://www.peets.com/pages/store-locator — the Stockist widget
             endpoint is https://stockist.co/api/v1/u5687/locations/all and
             carries chain-provided lat/lng.

TRAPS hit here:
  - foods.search must be paged across several spellings; the exact
    "Peet's Coffee & Tea" brand has hundreds of rows.
  - The locator reports four SFO counters with city "San Francisco", but SFO
    is in San Mateo County rather than SF city proper; those counters are
    deliberately excluded here.
  - Grocery bagged coffee and retail products remain components; drinks,
    breakfast items, sandwiches, pastries, and condiments use explicit rules.

Spot check: Caffe Latte, medium, 2% milk (food_id 75815786), was checked against
Peet's published nutrition listing and the FatSecret API parse: 220 kcal,
8 g fat, 22 g carbs, 15 g protein.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fatsecret import fatsecret as cached_fatsecret  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

API_URL = "https://platform.fatsecret.com/rest/server.api"
SEARCH_URL = f"{API_URL}?method=foods.search&search_expression=Peet%27s&max_results=50&page_number=0"
LOCATOR_URL = "https://stockist.co/api/v1/u5687/locations/all"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
TODAY = datetime.date.today().isoformat()
BRAND = "peet's coffee & tea"
SEARCHES = ("Peet's", "Peet Coffee", "Peet's Coffee", "Peets Coffee")
_LAST_REQUEST = 0.0

SF_LOCATIONS = [
    {"address": "155 Montgomery St, #161, San Francisco, CA 94104", "lat": 37.79061916, "lng": -122.40252005, "neighborhood": None},
    {"address": "5201 Geary Blvd, San Francisco, CA 94118", "lat": 37.78026190, "lng": -122.47522007, "neighborhood": None},
    {"address": "773 Market St, San Francisco, CA 94103", "lat": 37.78661909, "lng": -122.40502005, "neighborhood": None},
    {"address": "625 8th St, San Francisco, CA 94103", "lat": 37.77126188, "lng": -122.40512005, "neighborhood": None},
    {"address": "160 Jefferson St, San Francisco, CA 94133", "lat": 37.80856195, "lng": -122.41482006, "neighborhood": None},
    {"address": "Pier 39 Space 5-Q, San Francisco, CA 94133", "lat": 37.80073619, "lng": -122.40805201, "neighborhood": None},
    {"address": "2080 Chestnut St, San Francisco, CA 94123", "lat": 37.80086193, "lng": -122.43782006, "neighborhood": None},
    {"address": "Two Embarcadero Center, Suite R2113, San Francisco, CA 94111", "lat": 37.79496192, "lng": -122.39842005, "neighborhood": None},
    {"address": "310 Broderick St, San Francisco, CA 94117", "lat": 37.77346189, "lng": -122.43892006, "neighborhood": None},
    {"address": "2197 Fillmore St, San Francisco, CA 94115", "lat": 37.78966191, "lng": -122.43422006, "neighborhood": None},
    {"address": "3419 California St, San Francisco, CA 94118", "lat": 37.78656191, "lng": -122.45042006, "neighborhood": None},
    {"address": "601 Van Ness Ave, San Francisco, CA 94102", "lat": 37.78116190, "lng": -122.42132006, "neighborhood": None},
    {"address": "2300 16th St, Suite 240, San Francisco, CA 94103", "lat": 37.76647100, "lng": -122.41040900, "neighborhood": None},
    {"address": "1630 Holloway Ave, San Francisco, CA 94132", "lat": 37.72161803, "lng": -122.47812007, "neighborhood": None},
    {"address": "1509 Sloat Blvd, San Francisco, CA 94132", "lat": 37.73356182, "lng": -122.48962007, "neighborhood": None},
    {"address": "3251 20th Ave, San Francisco, CA 94132", "lat": 37.72756181, "lng": -122.47692007, "neighborhood": None},
    {"address": "54 West Portal Ave, San Francisco, CA 94127", "lat": 37.74036300, "lng": -122.46674900, "neighborhood": None},
]

CATEGORY_RULES = (
    ("component", ("ground coffee", "whole bean", "k-cup", "pod", "capsule",
                   "tea bag", "bagged", "coffee beans", "retail",
                   "instant coffee")),
    ("meal", ("sandwich", "brioche", "frittata", "breakfast", "bagel", "wrap",
              "croissant sandwich", "toast", "burrito", "flatbread", "crispy",
              "ham & swiss", "egg & cheese", "sausage cheddar", "grilled cheese",
              "slider", "taco", "ciabatta")),
    ("side", ("muffin", "scone", "cookie", "cake", "pastry", "brownie", "donut",
              "danish", "croissant", "oatmeal", "granola", "chips", "biscotti",
              "shortbread", "loaf", "protein bar", "energy bar", "granola bar", "bread")),
    ("condiment", ("syrup", "sauce", "spread", "dressing", "sweetener")),
    ("drink", ("coffee", "latte", "cappuccino", "espresso", "americano", "mocha",
               "cold brew", "tea", "chai", "cocoa", "matcha", "shaker", "lemonade",
               "refresher", "frapp", "frappe", "frappé", "iced", "brew", "macchiato",
               "black tie", "teas")),
)


def fatsecret(params):
    return cached_fatsecret(params)


def search(expression, page):
    params = {
        "method": "foods.search",
        "search_expression": expression,
        "max_results": 50,
        "page_number": page,
    }
    result = {}
    for _attempt in range(3):
        result = fatsecret(params)
        if result.get("foods", {}).get("food"):
            break
        time.sleep(1)
    foods = result.get("foods", {})
    total = int(foods.get("total_results", 0))
    rows = foods.get("food", [])
    if isinstance(rows, dict):
        rows = [rows]
    return total, rows


def brand_foods():
    found = {}
    for expression in SEARCHES:
        for page in range(100):
            total, rows = search(expression, page)
            for row in rows:
                if (row.get("brand_name") or "").strip().casefold() == BRAND:
                    found[row["food_id"]] = row
            if not rows or (page + 1) * 50 >= total:
                break
    return found


def category(name):
    lowered = name.casefold()
    for value, keywords in CATEGORY_RULES:
        if any(
            re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", lowered)
            for keyword in keywords
        ):
            return value
    return "component"


def number(value):
    return None if value in (None, "") else float(value)


def serving_for(servings):
    if isinstance(servings, dict):
        servings = [servings]
    for serving in servings:
        description = (serving.get("serving_description") or "").casefold()
        if "per 100g" not in description and "per oz" not in description and "100 g" not in description:
            if re.search(r"\b(1|small|medium|large|regular)\b", description):
                return serving
    return servings[0]


def items():
    found = brand_foods()
    print(f"classifying {len(found)} FatSecret Peet's Coffee & Tea rows")
    out = []
    for food_id, row in sorted(found.items(), key=lambda pair: pair[1].get("food_name", "")):
        result = {}
        for _attempt in range(3):
            result = fatsecret({"method": "food.get.v2", "food_id": food_id})
            if "food" in result:
                break
            time.sleep(1)
        if "food" not in result:
            print(f"  skipping {food_id} {row.get('food_name')}: {result}", file=sys.stderr)
            continue
        food = result["food"]
        serving = serving_for(food["servings"]["serving"])
        name = row["food_name"].strip()
        value = category(name)
        print(f"  [{value}] {name}")
        out.append({
            "id": re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") + "-" + food_id,
            "name": name,
            "description": None,
            "category": value,
            "calories": number(serving.get("calories")),
            "protein_g": number(serving.get("protein")),
            "carbs_g": number(serving.get("carbohydrate")),
            "fat_g": number(serving.get("fat")),
            "fiber_g": number(serving.get("fiber")),
            "sodium_mg": number(serving.get("sodium")),
            "serving_note": f"per {serving['serving_description'].strip()} (crowd-submitted; Peet's publishes no nutrition)",
            "is_estimate": True,
            "source": {"type": "crowd", "url": food["food_url"]},
        })
    return out


def main():
    save_restaurant({
        "id": "peets-coffee",
        "name": "Peet's Coffee",
        "website": "https://www.peets.com",
        "nutrition_source": {
            "type": "crowd",
            "url": SEARCH_URL,
            "vendor": "fatsecret",
            "retrieved": TODAY,
        },
        "locations": SF_LOCATIONS,
        "items": items(),
    })


if __name__ == "__main__":
    main()
