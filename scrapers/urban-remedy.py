"""Urban Remedy crowd-nutrition scraper.

The official locator is GET https://urbanremedy.com/locations/ and its
runtime HTML marks the San Francisco region with data-city="san francisco".
The addresses are parsed at runtime; Nominatim-derived coordinates use the
address-keyed lookup in _geo.py with a live fallback. Nutrition comes from
exact-brand FatSecret foods.search and food.get.v2 rows, all crowd/estimated
because Urban Remedy publishes no complete nutrition source.

TRAPS hit: filter the locator's city field rather than ZIP codes, and never
default an unknown nutrition row to meal. Ordered rules classify salads,
bowls, and wraps as meals; juices and shakes as drinks; desserts and bars as
sides; dressings as condiments; otherwise components.

Spot check: The Vegan Caesar parses as 520 kcal, 39 g fat, 31 g carbs, and
18 g protein.
"""

import datetime
import html
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fatsecret import fatsecret  # noqa: E402
from _geo import geocode  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

LOCATOR_URL = "https://urbanremedy.com/locations/"
API_URL = "https://platform.fatsecret.com/rest/server.api"
SEARCH_URL = f"{API_URL}?method=foods.search&search_expression=Urban+Remedy&max_results=50&page_number=0"
TODAY = datetime.date.today().isoformat()
BRAND = "urban remedy"
SEARCHES = ("Urban Remedy", "UrbanRemedy", "Urban Remedy Salad")
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"

CATEGORY_RULES = (
    ("drink", (
        "juice", "smoothie", "shake", "cleanse", "tea", "coffee", "lemonade",
        "milk", "tonic", "greens", "time machine",
    )),
    ("meal", (
        "salad", "bowl", "wrap", "sandwich", "entree", "entrée", "summer rolls",
        "soba noodles", "caesar",
    )),
    ("side", (
        "cookie", "cake", "muffin", "pastry", "chips", "bar", "dessert",
        "parfait", "pudding",
    )),
    ("condiment", ("dressing", "sauce", "spread")),
)


def _fetch():
    request = urllib.request.Request(LOCATOR_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def sf_locations():
    source = _fetch()
    addresses = []
    for match in re.finditer(
        r'<p\s+itemprop=["\']address["\'][^>]*>(.*?)</p>',
        source,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        text = html.unescape(re.sub(r"<[^>]+>", "\n", match.group(1)))
        lines = [
            re.sub(r"\s+", " ", line).strip(" ,")
            for line in text.splitlines()
            if re.sub(r"\s+", " ", line).strip(" ,")
        ]
        city_index = next(
            (
                index for index, line in enumerate(lines)
                if re.search(r"San\s+Francisco,\s*CA\s+\d{5}", line, re.IGNORECASE)
            ),
            None,
        )
        if city_index is None or city_index == 0:
            continue
        street = lines[city_index - 1].rstrip(".")
        city = re.sub(r"San\s+Frans?isco", "San Francisco", lines[city_index], flags=re.IGNORECASE)
        addresses.append(f"{street}, {city}")
    locations = []
    for address in dict.fromkeys(addresses):
        lat, lng = geocode(address)
        locations.append({
            "address": address,
            "lat": lat,
            "lng": lng,
            "neighborhood": None,
        })
    if not locations:
        raise RuntimeError("Urban Remedy locator returned no SF addresses")
    return locations


def category(name):
    lowered = name.casefold()
    for value, keywords in CATEGORY_RULES:
        if any(keyword in lowered for keyword in keywords):
            return value
    return "component"


def number(value):
    return None if value in (None, "") else float(value)


def _serving(servings):
    if isinstance(servings, dict):
        servings = [servings]
    return next(
        (serving for serving in servings if "100g" not in serving.get("serving_description", "").lower()),
        servings[0],
    )


def brand_foods():
    found = {}
    for expression in SEARCHES:
        for page in range(100):
            result = fatsecret({
                "method": "foods.search",
                "search_expression": expression,
                "max_results": 50,
                "page_number": page,
            })
            block = result.get("foods", {})
            rows = block.get("food", [])
            if isinstance(rows, dict):
                rows = [rows]
            for row in rows:
                if (row.get("brand_name") or "").strip().casefold() == BRAND:
                    found[row["food_id"]] = row
            if not rows or (page + 1) * 50 >= int(block.get("total_results", 0)):
                break
    return found


def items():
    found = brand_foods()
    print(f"classifying {len(found)} FatSecret Urban Remedy rows")
    output = []
    for food_id, row in sorted(found.items(), key=lambda item: item[1].get("food_name", "")):
        food = fatsecret({"method": "food.get.v2", "food_id": food_id}).get("food")
        if not food:
            continue
        serving = _serving(food["servings"]["serving"])
        name = row["food_name"].strip()
        value = category(name)
        print(f"  [{value}] {name}")
        output.append({
            "id": re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") + f"-{food_id}",
            "name": name,
            "description": None,
            "category": value,
            "calories": number(serving.get("calories")),
            "protein_g": number(serving.get("protein")),
            "carbs_g": number(serving.get("carbohydrate")),
            "fat_g": number(serving.get("fat")),
            "fiber_g": number(serving.get("fiber")),
            "sodium_mg": number(serving.get("sodium")),
            "serving_note": (
                f"per {serving['serving_description'].strip()} "
                "(crowd-submitted; Urban Remedy publishes no nutrition)"
            ),
            "is_estimate": True,
            "source": {"type": "crowd", "url": food["food_url"]},
        })
    return output


def main():
    save_restaurant({
        "id": "urban-remedy",
        "name": "Urban Remedy",
        "website": "https://urbanremedy.com",
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
