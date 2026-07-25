"""Mendocino Farms scraper.

The restaurant publishes a single nutrition/allergen PDF.  The PDF is
columnar, but pdfplumber's text extraction preserves each nutrition row in
the order name, serving, and nutrition values.
"""

import datetime
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402


PDF_URL = "https://contact.mendocinofarms.com/wp-content/uploads/2026/02/Feb2026_NutritionalAllergen.pdf"
TODAY = datetime.date.today().isoformat()
LOCATION_URLS = [
    "https://www.mendocinofarms.com/location-directory/norcal/465-california-st-san-francisco-ca-94104",
    "https://www.mendocinofarms.com/location-directory/norcal/303-2nd-street-san-francisco-ca-94107",
]
LOCATION_ADDRESSES = [
    ("465 California St, San Francisco, CA 94104", "Financial District"),
    ("303 2nd Street, San Francisco, CA 94107", "SoMa"),
]

SECTION_CATEGORIES = {
    "seasonal": "meal",
    "sandwiches": "meal",
    "½ sandwich combos": "meal",
    "salads": "meal",
    "wraps": "meal",
    "kids meals": "meal",
    "dressings & sauces": "condiment",
    "sauces & dressings": "condiment",
    "breads": "side",
    "deli sides": "side",
    "gourmet deli sides": "side",
    "soups": "side",
    "desserts": "side",
    "beverages": "drink",
    "housemade beverages": "drink",
    "wines": "drink",
    "beers": "drink",
    "cheffy cocktail sandwiches": "meal",
    "specialty leafy salads": "meal",
    "boxed salads": "meal",
    "boxed sandwiches": "meal",
    "crafted for kids": "meal",
    "grazing trays": "side",
}

NAME_FIXES = {
    "ProsciuBo": "Prosciutto",
    "ProsciuAo": "Prosciutto",
    "VinaigreBe": "Vinaigrette",
    "VinaigreAe": "Vinaigrette",
    "BuBer": "Butter",
    "CiabaBa": "Ciabatta",
    "TorWlla": "Tortilla",
    "TorZlla": "Tortilla",
    "LiBle": "Little",
    "PorQons": "Portions",
    "PorWon": "Portion",
    "porWon": "portion",
    "nutriQon": "nutrition",
    "Cheffy": "Cheffy",
}
SPOT_CHECK_EXTERNAL_URL = (
    "https://foods.fatsecret.com/calories-nutrition/mendocino-farms/"
    "%E2%80%9Cnot-so-fried%E2%80%9D-chicken-sandwich"
)
SPOT_CHECK_PDF_VALUES = {
    "calories": 900,
    "protein_g": 35,
    "carbs_g": 79,
    "fat_g": 48,
}

UNIT_TOKENS = {"oz", "piece", "sandwich", "roll", "wrap"}
SERVING_PREFIXES = {"cup", "bowl", "low", "high", "1/2"}
NUMBER_RE = re.compile(r"^(?:\d+(?:\.\d+)?|\d+/\d+)$")
VALUE_RE = re.compile(r"^(?:\d+(?:\.\d+)?|<\d+(?:\.\d+)?(?:g|mg)?)$")


def clean_name(value):
    for old, new in NAME_FIXES.items():
        value = value.replace(old, new)
    return re.sub(r"\s+", " ", value).strip()


def normalize_tokens(line):
    line = line.replace("< 1g", "<1g").replace("< 5mg", "<5mg").replace("<1 g", "<1g")
    return line.split()


def parse_value(token):
    if token.startswith("<"):
        return 0.5
    return float(token) if "." in token else int(token)


def parse_row(line):
    tokens = normalize_tokens(line)
    if len(tokens) < 14:
        return None

    stats_start = None
    for i in range(len(tokens) - 11, 0, -1):
        if all(VALUE_RE.match(t) for t in tokens[i:]) and len(tokens[i:]) == 11:
            stats_start = i
            break
    if stats_start is None:
        return None

    unit_index = None
    for i in range(stats_start - 1, -1, -1):
        if tokens[i].lower() in UNIT_TOKENS:
            unit_index = i
            break
    if unit_index is None:
        return None

    serving_start = unit_index - 1
    if serving_start > 0 and (
        tokens[serving_start - 1].lower() in SERVING_PREFIXES
        or tokens[serving_start].lower() == "sandwich"
        and tokens[serving_start - 1] == "1/2"
    ):
        serving_start -= 1
    name = clean_name(" ".join(tokens[:serving_start]))
    serving = " ".join(tokens[serving_start:stats_start])
    values = [parse_value(t) for t in tokens[stats_start:]]
    if not name or not serving:
        return None
    return name, serving, values


def category_for(section, name):
    lowered = name.lower()
    if lowered.startswith("add "):
        return "component"
    if lowered == "apples":
        return "side"
    section_category = SECTION_CATEGORIES.get(section)
    has_condiment_keyword = any(
        word in lowered for word in ("dressing", "vinaigrette", "sauce", "mustard", "ketchup", "ranch")
    )
    has_meal_word = any(word in lowered for word in ("salad", "sandwich", "wrap", "combo", "bowl"))
    if has_condiment_keyword and not has_meal_word:
        return "condiment"
    return SECTION_CATEGORIES.get(section, "side")


def item_from_row(row, section, previous_name):
    original_name, serving, values = row
    clarified = original_name.lower() in {"without dressing", "low portion", "high portion"}
    add_on = original_name.lower().startswith("add ")
    name, serving, values = row
    if clarified:
        name = f"{previous_name} ({name.lower()})"
    elif add_on:
        name = f"{name} to {previous_name}"
    category = category_for(section, name)
    calories, _calories_from_fat, fat, _sat_fat, _trans_fat, cholesterol, sodium, carbs, fiber, _sugar, protein = values
    return {
        "id": re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"),
        "name": name,
        "description": None,
        "category": category,
        "calories": calories,
        "protein_g": protein,
        "carbs_g": carbs,
        "fat_g": fat,
        "fiber_g": fiber,
        "sodium_mg": sodium,
        "serving_note": serving_note(section, name, serving, clarified, add_on),
        "is_estimate": False,
        "source": {"type": "published", "url": PDF_URL},
    }


def serving_note(section, name, serving, clarified, add_on):
    if add_on:
        return f"per protein add-on ({serving})"
    if section == "½ sandwich combos":
        label = "½ sandwich combo"
    elif section in {"salads", "specialty leafy salads", "boxed salads"}:
        label = "salad"
    elif section in {"sandwiches", "cheffy cocktail sandwiches", "boxed sandwiches"}:
        label = "sandwich"
    elif section == "wraps":
        label = "wrap"
    elif clarified and "portion" in name.lower():
        label = "recommended portion"
    else:
        label = name.lower()
    if clarified:
        label += " without dressing" if "without dressing" in name.lower() else ""
    return f"per {label} ({serving})"


def parse_pdf(path):
    items = []
    seen = set()
    section = None
    previous_name = "item"
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages[:5]:
            for raw_line in (page.extract_text() or "").splitlines():
                line = raw_line.strip()
                lowered = line.lower()
                if lowered in SECTION_CATEGORIES:
                    section = lowered
                    continue
                row = parse_row(line)
                if row is None:
                    continue
                item = item_from_row(row, section, previous_name)
                if not (
                    row[0].lower().startswith("add ")
                    or row[0].lower() in {"without dressing", "low portion", "high portion"}
                ):
                    previous_name = item["name"]
                base_id = item["id"]
                suffix = 2
                while item["id"] in seen:
                    item["id"] = f"{base_id}-{suffix}"
                    suffix += 1
                seen.add(item["id"])
                items.append(item)
    return items


def geocode(address):
    query = urllib.parse.quote(address)
    url = f"https://nominatim.openstreetmap.org/search?format=json&limit=1&q={query}"
    req = urllib.request.Request(
        url, headers={"User-Agent": "sf-meal-finder/1.0 (nutrition data scraper)"}
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        results = json.load(response)
    if not results:
        raise RuntimeError(f"Could not geocode {address}")
    return float(results[0]["lat"]), float(results[0]["lon"])


def get_locations():
    locations = []
    for index, (address, neighborhood) in enumerate(LOCATION_ADDRESSES):
        lat, lng = geocode(address)
        locations.append(
            {"address": address, "lat": lat, "lng": lng, "neighborhood": neighborhood}
        )
        if index + 1 < len(LOCATION_ADDRESSES):
            time.sleep(1.1)
    return locations


def main():
    pdf_path = Path("/tmp/mendocino-farms-nutrition.pdf")
    request = urllib.request.Request(PDF_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        pdf_path.write_bytes(response.read())

    items = parse_pdf(pdf_path)
    spot_check = next(i for i in items if i["name"] == '"Not So Fried" Chicken')
    assert {
        key: spot_check[key] for key in SPOT_CHECK_PDF_VALUES
    } == SPOT_CHECK_PDF_VALUES, SPOT_CHECK_EXTERNAL_URL
    locations = get_locations()
    doc = {
        "id": "mendocino-farms",
        "name": "Mendocino Farms",
        "website": "https://www.mendocinofarms.com",
        "nutrition_source": {
            "type": "published",
            "url": PDF_URL,
            "vendor": None,
            "retrieved": TODAY,
        },
        "locations": locations,
        "items": items,
    }
    print(f"Parsed {len(items)} rows; categories: {dict(Counter(i['category'] for i in items))}")
    print("Spot check: \"Not So Fried\" Chicken = 900 kcal, 35g protein, 79g carbs, 48g fat")
    save_restaurant(doc)


if __name__ == "__main__":
    main()
