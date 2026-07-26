"""Jamba crowd-nutrition scraper.

Jamba publishes no complete machine-readable nutrition source in the locator
flow, so this dataset uses FatSecret's user-submitted brand rows as crowd data.
Every item is source_type "crowd" with is_estimate=True.

  nutrition: GET https://platform.fatsecret.com/rest/server.api
             ?method=foods.search&search_expression=Jamba&max_results=50
             &page_number=<page>, then method=food.get.v2&food_id=<id>
  locations: https://locations.jamba.com/ca/san-francisco — the Yext HTML
             city page links four SF pages; their schema meta tags carry coords.

TRAPS hit here:
  - foods.search must be paged across multiple spellings; a single page misses
    most of the Jamba Juice brand rows.
  - FatSecret has both whole-item and per-100g/per-oz servings. The scraper
    prefers a whole-item serving and records the selected serving description.
  - Classification is intentionally explicit: smoothies and juices are drinks,
    bowls/wraps/sandwiches are meals, desserts/pastries are sides, and boosts,
    toppings, and packaged components are components.

Spot check: Razzmatazz Smoothie, medium (16 fl oz), was checked against the
FatSecret page/API parse before saving; the selected serving is 360 kcal.
"""

import base64
import datetime
import json
import re
import sys
import urllib.request
from urllib.parse import urljoin
import html
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fatsecret import fatsecret as cached_fatsecret  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

API_URL = "https://platform.fatsecret.com/rest/server.api"
SEARCH_URL = f"{API_URL}?method=foods.search&search_expression=Jamba&max_results=50&page_number=0"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
TODAY = datetime.date.today().isoformat()
BRAND = "jamba juice"
SEARCHES = ("Jamba", "Jamba Juice", "Jamba Juice Smoothie", "Jamba Smoothies")

LOCATOR_URL = "https://locations.jamba.com/ca/san-francisco"

# First match wins. Keep the table explicit so the full classified list can be
# reviewed from the run log before data is accepted.
CATEGORY_RULES = (
    ("drink", ("smoothie", "juice", "shake", "refresher", "lemonade", "coffee", "tea",
               "espresso", "latte", "cocoa", "beverage", "milk, 8 fl oz", "coconutmilk",
               "watermelon breeze", "blue lava", "peachberry blast", "strawberry lemon twist",
               "vanilla blue sky", "cold brew", "over ice", "electric ice",
               "dragon fruit delight", "matcha over ice")),
    ("meal", ("bowl", "wrap", "sandwich", "toast", "breakfast", "flatbread", "acai ",
              "peanut butter banana", "strawberry blueberry", "handwich")),
    ("side", ("parfait", "pretzel", "oatmeal", "muffin", "cookie", "cake", "pastry",
              "scone", "chips", "granola", "popcorn", "waffle", "sherbet", "fruit cup",
              "empanada", "bites", "frozen yogurt", "frozen dessert")),
    ("condiment", ("syrup", "sauce", "dressing", "spread", "dip cup")),
    ("component", ("boost", "topping", "protein", "whey", "soy", "spinach", "tijin",
                   "tajin", "fresh fruit", "strawberr", "banana", "blueberr", "mango",
                   "apple", "peanut butter", "coconutmilk", "milk, 8 fl oz", "add-in",
                   "shot", "powder", "vitamin", "2% milk", "soymilk")),
)


def fatsecret(params):
    return cached_fatsecret(params)


def sf_locations():
    request = urllib.request.Request(
        LOCATOR_URL,
        headers={"User-Agent": UA},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        source = response.read().decode("utf-8", "replace")
    links = {
        urljoin(LOCATOR_URL, html.unescape(match))
        for match in re.findall(
            r'href=["\']([^"\']*(?:locations\.jamba\.com/ca/san-francisco/|\.\./ca/san-francisco/)[^"\']+)["\']',
            source,
        )
    }
    locations = []
    for link in sorted(links):
        request = urllib.request.Request(link, headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=30) as response:
            page = response.read().decode("utf-8", "replace")
        locality = re.search(
            r'itemprop=["\']addressLocality["\'][^>]*content=["\']([^"\']+)',
            page,
            re.IGNORECASE,
        )
        if not locality or "san francisco" not in html.unescape(locality.group(1)).casefold():
            continue
        street = re.search(
            r'itemprop=["\']streetAddress["\'][^>]*(?:content=["\']([^"\']+)|>([^<]+))',
            page,
            re.IGNORECASE,
        )
        region = re.search(
            r'itemprop=["\']addressRegion["\'][^>]*(?:content=["\']([^"\']+)|>([^<]+))',
            page,
            re.IGNORECASE,
        )
        postal = re.search(
            r'itemprop=["\']postalCode["\'][^>]*(?:content=["\']([^"\']+)|>([^<]+))',
            page,
            re.IGNORECASE,
        )
        latitude = re.search(r'latitude["\']?\s*content=["\']([^"\']+)', page, re.IGNORECASE)
        longitude = re.search(r'longitude["\']?\s*content=["\']([^"\']+)', page, re.IGNORECASE)
        if not (street and region and postal and latitude and longitude):
            continue
        values = []
        for part in (street, locality, region, postal):
            value = part.group(1)
            if not value and part.lastindex and part.lastindex > 1:
                value = part.group(2)
            values.append(html.unescape(value).strip())
        address = " ".join(values)
        locations.append({
            "address": address,
            "lat": float(latitude.group(1)),
            "lng": float(longitude.group(1)),
            "neighborhood": None,
        })
    if not locations:
        raise RuntimeError("Jamba locator returned no SF locations")
    return locations


def search(expression, page):
    params = {
        "method": "foods.search",
        "search_expression": expression,
        "max_results": 50,
        "page_number": page,
    }
    result = {}
    for attempt in range(3):
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
        if any(keyword in lowered for keyword in keywords):
            return value
    return "component"


def number(value):
    return None if value in (None, "") else float(value)


def serving_for(servings, name):
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
    print(f"classifying {len(found)} FatSecret Jamba Juice rows")
    out = []
    for food_id, row in sorted(found.items(), key=lambda pair: pair[1].get("food_name", "")):
        result = {}
        for attempt in range(3):
            result = fatsecret({"method": "food.get.v2", "food_id": food_id})
            if "food" in result:
                break
            time.sleep(1)
        if "food" not in result:
            print(f"  skipping {food_id} {row.get('food_name')}: {result}", file=sys.stderr)
            continue
        food = result["food"]
        serving = serving_for(food["servings"]["serving"], row.get("food_name", ""))
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
            "serving_note": f"per {serving['serving_description'].strip()} (crowd-submitted; Jamba publishes no nutrition)",
            "is_estimate": True,
            "source": {"type": "crowd", "url": food["food_url"]},
        })
    return out


def main():
    save_restaurant({
        "id": "jamba",
        "name": "Jamba",
        "website": "https://www.jamba.com",
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
