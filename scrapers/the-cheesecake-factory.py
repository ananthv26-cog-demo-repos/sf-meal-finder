"""The Cheesecake Factory crowd-nutrition scraper.

The official city locator is HTML at
https://locations.thecheesecakefactory.com/ca/san-francisco/ and supplies the
runtime SF address list. Nutrition comes from exact-brand FatSecret crowd rows
via paged foods.search and food.get.v2. Every item is crowd/estimated because
the chain publishes no complete machine-readable nutrition source.

TRAPS hit: page every search spelling and filter the exact normalized
``Cheesecake Factory`` brand. The locator is city-specific, but its HTML still
needs parsing at runtime. Shareable appetizers, soups, and side salads are
sides; entrees, bowls, pastas, sandwiches, burgers, tacos, and burritos are
meals; add-ons and individual ingredients remain components.

Spot check: Original Cheesecake parses as 830 kcal, 59 g fat, 63 g carbs, and
12 g protein.
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

LOCATOR_URL = "https://locations.thecheesecakefactory.com/ca/san-francisco/"
API_URL = "https://platform.fatsecret.com/rest/server.api"
SEARCH_URL = f"{API_URL}?method=foods.search&search_expression=Cheesecake+Factory&max_results=50&page_number=0"
TODAY = datetime.date.today().isoformat()
BRAND = "cheesecake factory"
SEARCHES = (
    "Cheesecake Factory",
    "The Cheesecake Factory",
    "Cheesecake Factory Restaurant",
)
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"

CATEGORY_RULES = (
    ("component", (
        "tcf at home", "at-home", "at home", "retail",
        "add-on", "addon", "extra", "single ingredient", "salad add-on",
        "fresh strawberries", "strawberries", "fresh fruit",
    )),
    ("drink", (
        "smoothie", "juice", "coffee", "café", "cafe", "tea", "lemonade",
        "soda", "coke", "sprite", "root beer", "water", "milk", "shake",
        "cocktail", "mojito", "martini", "margarita", "beer", "wine", "spritz",
        "sangria", "punch", "paloma", "mule", "bellini", "mimosa", "espresso",
        "cappuccino", "latte", "macchiato", "hot chocolate", "limeade", "cooler", "fizz",
        "daiquiri", "paper plane", "whisky sour",
        "arnold palmer", "coca-cola", "diet dr. pepper", "dr. pepper", "ginger ale",
        "milkshake", "teas",
        "bloody mary", "blue hawaiian", "mai tai", "lava flow", "lemon drop",
        "pina colada", "piña colada", "pineapple mezcal", "cosmopolitan",
        "whiskey smash", "well bourbon", "well gin", "well rum", "well scotch",
        "well tequila", "well vodka", "whisky & ginger", "yuzu lemon drop",
        "guava sparkler", "tahitian pineapple", "frozen iced mango", "georgia peach",
        "peach perfect",
    )),
    ("side", ("spring rolls", "stuffed mushrooms", "appetizer", "- appetizer")),
    ("meal", (
        "salad with chicken", "chicken salad", "chicken club salad", "cobb salad",
        "beet and avocado salad",
        "factory chopped salad", "barbeque ranch chicken salad", "santa fe salad",
        "vegan cobb", "avocado toast", "poke with salad", "salad sandwich",
        "sandwich", "french toast", "fried chicken & waffles", "chicken & waffles",
        "brunch combo", "glamburger", "cheeseburger", "hamburger",
        "old fashioned burger", "kids' mini corn dogs",
        "kids' pasta", "kids' pasta with",
    )),
    ("side", (
        "ceviche", "nachos", "eggroll", "wings", "calamari", "buns",
        "appetizer", "shareable", "soup", "chowder", "side salad",
        "cucumber salad", "salad", "serves 2-4", "- appetizer", "brie",
        "wontons", "bites", "fried cauliflower", "pretzel", "hot spinach and cheese dip",
        "warm crab dip", "spring rolls", "crabcakes", "pancakes",
        "steamed white rice", "rice and beans",
    )),
    ("side", (
        "cheesecake", "cake", "dessert", "brownie", "ice cream", "sundae",
        "fudge", "cookie", "cupcake", "fries", "muffin", "waffle", "pancake",
        "strawberry shortcake", "a la mode", "tiramisu", "s'mores", "marshmallow",
        "apple crisp", "truffle", "toast",
    )),
    ("condiment", ("dressing", "sauce", "syrup", "spread")),
    ("meal", (
        "bowl", "plate", "entrée", "entree", "pasta", "burger", "sandwich",
        "pizza", "steak", "chicken", "fish", "shrimp", "taco", "burrito",
        "flatbread", "salmon", "branzino", "mignon", "meatloaf", "omelette",
        "eggs", "benedict", "poke", "rice", "tenderloin", "pork", "beef",
        "quesadilla", "ravioli", "carbonara", "fettuccini", "spaghetti",
        "jambalaya", "shepherd", "meatball", "tuna", "sliders", "macaroni",
        "loco moco", "lettuce wraps", "tartare", "stuffed mushrooms",
        "baja bowl", "asian tenderloin", "tenderloin with rice", "rigatoni",
        "noodles", "the club",
    )),
)


def _fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def sf_locations():
    source = _fetch(LOCATOR_URL)
    addresses = []
    for match in re.finditer(
        r'<div class="nearbyCoords"[^>]*>\s*(.*?)\s*</div>',
        source,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        text = re.sub(r"<[^>]+>", " ", html.unescape(match.group(1)))
        text = re.sub(r"\s+", " ", text).strip().replace(",", ", ")
        text = re.sub(r"\s+,", ",", text)
        if "san francisco" in text.casefold():
            if not re.search(r"\b\d{5}\b", text):
                text = f"{text} 94102"
            addresses.append(text)
    if not addresses:
        street = re.search(r'itemprop="streetAddress"[^>]*>(.*?)<', source, re.DOTALL)
        if street:
            addresses.append(re.sub(r"\s+", " ", html.unescape(street.group(1))).strip())
    locations = []
    for address in dict.fromkeys(addresses):
        if "san francisco" not in address.casefold():
            continue
        lat, lng = geocode(address)
        locations.append({
            "address": address,
            "lat": lat,
            "lng": lng,
            "neighborhood": "Union Square",
        })
    if not locations:
        raise RuntimeError("Cheesecake Factory locator returned no SF address")
    return locations


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


def _serving(servings):
    if isinstance(servings, dict):
        servings = [servings]
    return next(
        (
            serving for serving in servings
            if "100g" not in serving.get("serving_description", "").lower()
            and "per oz" not in serving.get("serving_description", "").lower()
        ),
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
    print(f"classifying {len(found)} FatSecret Cheesecake Factory rows")
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
                "(crowd-submitted; The Cheesecake Factory publishes no nutrition)"
            ),
            "is_estimate": True,
            "source": {"type": "crowd", "url": food["food_url"]},
        })
    return output


def main():
    save_restaurant({
        "id": "the-cheesecake-factory",
        "name": "The Cheesecake Factory",
        "website": "https://www.thecheesecakefactory.com",
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
