"""Proper Food scraper.

Proper Food publishes the current California nutrition/allergen sheet at
NUTRITION_URL. Pages 1-2 contain nutrition; pages 3-4 are allergen tables.
The PDF's columns are positionally ordered as calories, total fat, saturated
fat, cholesterol, dietary fiber, protein, sugars, carbohydrates, and sodium.
The rotated headers are not reliable text, so rows are parsed by x-position.

TRAPS:
  - Protein appears before sugars and carbohydrates in the PDF.
  - Rows beginning with a separate footnote marker (or ending in an attached
    footnote digit) need that marker removed from the item name.
  - Indented rows are optional add-ons and are not included in the parent
    item's nutrition; dressing nutrition covers the entire packet provided.
  - SFO Terminal 1 has a San Francisco postal address but is outside city
    proper and must not be included as an SF restaurant location.
"""

import datetime
import json
import re
import sys
import tempfile
import unicodedata
import urllib.request
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

NUTRITION_URL = (
    "https://properfood.com/wp-content/uploads/2015/05/"
    "Nutrition_Allergen_CA.pdf"
)
LOCATIONS_URL = (
    "https://api.opentender.io/order-api/locations?"
    "revenue_center_type=OLO&service_type=PICKUP&limit=100"
)
TODAY = datetime.date.today().isoformat()
SF_LAT_RANGE = (37.60, 37.86)
SF_LNG_RANGE = (-122.55, -122.33)
COLUMN_CENTERS = [189.3, 205.4, 220.4, 235.4, 250.4, 265.4, 280.4, 295.4, 309.3]
NUMERIC_FIELDS = (
    "calories",
    "fat_g",
    "saturated_fat_g",
    "cholesterol_mg",
    "fiber_g",
    "protein_g",
    "sugars_g",
    "carbs_g",
    "sodium_mg",
)
NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")
TRAILING_FOOTNOTE_RE = re.compile(r"([A-Za-z])([123])$")

SECTIONS = {
    "Breakfast",
    "Salads",
    "Hot Plate",
    "Greens & Grains",
    "Proteins & Sides",
    "Sandwiches & Wraps",
    "Soup",
    "Juice & Drinks",
    "Cookies, Bars & Snacks",
}
BREAKFAST_MEAL_PREFIXES = (
    "Everything Croissant Sandwich",
    "Rustic ",
    "Hearty Breakfast Plate",
    "Egg White & Avocado Plate",
)
BREAKFAST_SIDES = {
    "A Proper Fruit Cup",
    "Proper Yogurt Parfait with Strawberry Compote",
    "Coconut Chia Pudding",
    "Overnight Oats",
    "Matcha Horchata Overnight Oats",
    "Hardboiled Eggs",
    "Farmers Cheese Cup",
}
FOOD_COMPONENTS = {
    "white cheddar",
    "avocado puree",
    "feta cheese",
    "candied walnuts",
    "agave almonds",
    "wontons",
    "labneh",
    "iceberg lettuce",
}
NEIGHBORHOODS = {
    "100 First Street": "SoMa",
    "116 Montgomery St": "Financial District",
    "180 Howard St": "SoMa",
    "2 Embarcadero Center": "Financial District",
    "35 Spear St": "Financial District",
    "45 Fremont St": "Financial District",
    "525 Market St": "Financial District",
    "555 California Street": "Financial District",
    "588 Mission Bay Blvd N": "Mission Bay",
    "655 Montgomery St": "Financial District",
    "Toni Stone Crossing (Mission Rock)": "Mission Bay",
}
CANONICAL_ITEM_FIELDS = {
    "id",
    "name",
    "description",
    "category",
    "calories",
    "protein_g",
    "carbs_g",
    "fat_g",
    "fiber_g",
    "sodium_mg",
    "serving_note",
    "is_estimate",
    "source",
}


def get_json(url):
    req = urllib.request.Request(
        url,
        headers={
            "Origin": "https://order.properfood.com",
            "client-id": "Z57WoEprZf01VeBX7wYcW9VQ1b705UOAKuyqa5BmeCdcjMuK",
            "brand-id": "64",
            "User-Agent": "Mozilla/5.0 Chrome/126",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def download_pdf():
    request = urllib.request.Request(
        NUTRITION_URL, headers={"User-Agent": "Mozilla/5.0 Chrome/126"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    handle.write(data)
    handle.close()
    return Path(handle.name)


def _rows(page):
    words = [
        word
        for word in page.extract_words()
        if word["x0"] < 320
    ]
    rows = []
    for word in sorted(words, key=lambda item: item["top"]):
        row = next(
            (candidate for candidate in rows if abs(candidate[0] - word["top"]) <= 3),
            None,
        )
        if row is None:
            rows.append([word["top"], [word]])
        else:
            row[1].append(word)
    return [sorted(words, key=lambda item: item["x0"]) for _, words in rows]


def _clean_name(words):
    name = " ".join(word["text"] for word in words if word["x1"] < 180).strip()
    name = re.sub(r"\s+2$", "", name)
    parts = name.split()
    if parts:
        parts[-1] = TRAILING_FOOTNOTE_RE.sub(r"\1", parts[-1])
    return " ".join(parts)


def _numeric_values(words):
    values = {}
    for word in words:
        if word["x0"] < 180 or word["x0"] >= 320:
            continue
        if not NUMBER_RE.fullmatch(word["text"]):
            continue
        token_center = (word["x0"] + word["x1"]) / 2
        nearest = min(
            enumerate(COLUMN_CENTERS),
            key=lambda pair: abs(token_center - pair[1]),
        )
        index, center = nearest
        if abs(token_center - center) > 7:
            raise ValueError(
                f"numeric cell {word['text']!r} at x={token_center:.1f} "
                f"does not match a nutrition column"
            )
        if index in values:
            raise ValueError(f"duplicate nutrition column {index} in row {words}")
        values[index] = float(word["text"])
    if len(values) != len(NUMERIC_FIELDS):
        return None
    result = {}
    for index, field in enumerate(NUMERIC_FIELDS):
        value = values[index]
        result[field] = int(value) if value.is_integer() else value
    if (
        result["saturated_fat_g"] > result["fat_g"]
        or result["sugars_g"] > result["carbs_g"]
        or result["fiber_g"] > result["carbs_g"]
    ):
        raise ValueError(f"column sanity check failed for {result}")
    return result


def parse_pdf(pdf_path):
    parsed = []
    current_section = None
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages[:2], start=1):
            for words in _rows(page):
                name = _clean_name(words)
                numbers = _numeric_values(words)
                main = any(word["x0"] < 55 for word in words)
                indent = min((word["x0"] for word in words), default=999)
                if not numbers:
                    if main and name in SECTIONS:
                        current_section = name
                        parsed.append(
                            {
                                "name": name,
                                "numbers": None,
                                "main": True,
                                "page": page_number,
                            }
                        )
                    continue
                if not name:
                    raise ValueError(f"unnamed nutrition row on page {page_number}")
                if current_section is None:
                    raise ValueError(f"nutrition row before section: {name!r}")
                parsed.append(
                    {
                        "name": name,
                        "numbers": numbers,
                        "main": main and indent < 55,
                        "page": page_number,
                    }
                )
    return parsed


def classify_main(name, section):
    if section == "Breakfast":
        if name.startswith(BREAKFAST_MEAL_PREFIXES):
            return "meal"
        if name in BREAKFAST_SIDES:
            return "side"
    elif section in {"Salads", "Hot Plate", "Greens & Grains", "Sandwiches & Wraps"}:
        return "meal"
    elif section == "Proteins & Sides":
        if "(add-on protein)" in name:
            return "component"
        return "side"
    elif section in {"Soup", "Cookies, Bars & Snacks"}:
        return "side"
    elif section == "Juice & Drinks":
        return "drink"
    raise ValueError(f"unclassified main item {name!r} in section {section!r}")


def classify_sub(name):
    lower = name.lower()
    if "(add-on protein)" in lower or lower in FOOD_COMPONENTS:
        return "component"
    if (
        "vinaigrette" in lower
        or "dressing" in lower
        or "sauce" in lower
        or "cream" in lower
        or lower == "crème fraiche"
    ):
        return "condiment"
    raise ValueError(f"unclassified add-on item {name!r}")


def slugify(name):
    ascii_name = (
        unicodedata.normalize("NFKD", name)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    value = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return value


def item_from_row(row, category, source_type="published"):
    numbers = row["numbers"]
    if row["name"] in {
        "Couscous & Spinach Salad with Salmon",
        "Couscous & Spinach Salad with Chicken",
    }:
        serving_note = (
            "per entire item; heartier portion, often enjoyed as multiple "
            "servings, nutrition shown for the entire item; "
            "dressing/add-ons listed separately"
        )
    elif category == "condiment":
        serving_note = "per full dressing packet provided with the salad"
    elif category == "component":
        serving_note = "per add-on portion"
    elif row["name"].endswith(("Iced Tea", "Cold Brew Coffee")):
        serving_note = "per bottle"
    else:
        serving_note = "per item, as packaged; dressing/add-ons listed separately"
    return {
        "id": slugify(row["name"]),
        "name": row["name"],
        "description": None,
        "category": category,
        "calories": numbers["calories"],
        "protein_g": numbers["protein_g"],
        "carbs_g": numbers["carbs_g"],
        "fat_g": numbers["fat_g"],
        "fiber_g": numbers["fiber_g"],
        "sodium_mg": numbers["sodium_mg"],
        "saturated_fat_g": numbers["saturated_fat_g"],
        "cholesterol_mg": numbers["cholesterol_mg"],
        "sugars_g": numbers["sugars_g"],
        "serving_note": serving_note,
        "is_estimate": source_type == "derived",
        "source": {"type": source_type, "url": NUTRITION_URL},
    }


def parse_items(rows):
    items = []
    current_section = None
    current_main = None
    current_subs = []
    seen_macros = set()
    used_ids = set()
    sub_ids = {}

    def finish_main():
        if current_main is None:
            return
        category = classify_main(current_main["name"], current_section)
        item = item_from_row(current_main, category)
        used_ids.add(item["id"])
        items.append(item)
        for sub in current_subs:
            sub_category = classify_sub(sub["name"])
            key = (sub["name"].lower(), tuple(sub["numbers"].values()))
            if key not in seen_macros:
                seen_macros.add(key)
                sub_item = item_from_row(sub, sub_category)
                base_id = sub_item["id"]
                if base_id in used_ids:
                    suffix = sub_ids.get(base_id, 1) + 1
                    sub_ids[base_id] = suffix
                    sub_item["id"] = f"{base_id}-{suffix}"
                else:
                    sub_ids.setdefault(base_id, 1)
                used_ids.add(sub_item["id"])
                items.append(sub_item)
            if category == "meal" and sub_category == "condiment":
                combined = {
                    key: current_main["numbers"][key] + sub["numbers"][key]
                    for key in NUMERIC_FIELDS
                }
                derived = dict(current_main, numbers=combined)
                derived["name"] = f"{current_main['name']} (with {sub['name']})"
                derived_item = item_from_row(derived, "meal", "derived")
                derived_item["description"] = (
                    f"Recipe sum of the published {current_main['name']} row "
                    f"and the full {sub['name']} packet."
                )
                derived_item["serving_note"] = (
                    "salad/plate plus the full dressing packet as provided"
                )
                if derived_item["id"] in used_ids:
                    raise AssertionError(f"duplicate derived item id {derived_item['id']}")
                used_ids.add(derived_item["id"])
                items.append(derived_item)

    for row in rows:
        if row["main"]:
            if row["name"] in SECTIONS:
                finish_main()
                current_main = None
                current_subs = []
                current_section = row["name"]
                continue
            finish_main()
            current_main = row
            current_subs = []
        else:
            if current_main is None:
                raise ValueError(f"add-on row without a parent: {row['name']!r}")
            current_subs.append(row)
    finish_main()
    return items


def locations():
    data = get_json(LOCATIONS_URL)["data"]
    selected = [
        row
        for row in data
        if row.get("address", {}).get("city") == "San Francisco"
        and row.get("address", {}).get("state") == "CA"
        and row.get("address", {}).get("street") != "SFO Airport"
        # The API labels 700 Gateway Blvd. South as city San Francisco even
        # though its 94080 postal address is in South San Francisco.
        and row.get("address", {}).get("postal_code") != "94080"
    ]
    if len(selected) != 11:
        raise AssertionError(f"expected 11 SF stores, got {len(selected)}")
    result = []
    for row in selected:
        address = row["address"]
        street = address["street"].strip()
        neighborhood = NEIGHBORHOODS.get(street)
        if neighborhood is None:
            raise AssertionError(f"missing neighborhood for {street!r}")
        lat, lng = address["lat"], address["lng"]
        if not (
            SF_LAT_RANGE[0] <= lat <= SF_LAT_RANGE[1]
            and SF_LNG_RANGE[0] <= lng <= SF_LNG_RANGE[1]
        ):
            raise AssertionError(f"location outside SF bounds: {street} {lat},{lng}")
        result.append(
            {
                "address": f"{street}, San Francisco, CA {address['postal_code']}",
                "lat": lat,
                "lng": lng,
                "neighborhood": neighborhood,
            }
        )
    return result


def main():
    pdf_path = download_pdf()
    try:
        rows = parse_pdf(pdf_path)
    finally:
        pdf_path.unlink(missing_ok=True)
    items = parse_items(rows)
    store_locations = locations()

    spot_checks = {item["name"]: item for item in items}
    fruit = spot_checks["A Proper Fruit Cup"]
    assert (
        fruit["calories"],
        fruit["fat_g"],
        fruit["saturated_fat_g"],
        fruit["cholesterol_mg"],
        fruit["fiber_g"],
        fruit["protein_g"],
        fruit["sugars_g"],
        fruit["carbs_g"],
        fruit["sodium_mg"],
    ) == (90, 0, 0, 0, 2, 1, 19, 23, 15)
    chinese = spot_checks["Chinese Chicken Salad"]
    assert (
        chinese["calories"],
        chinese["fat_g"],
        chinese["saturated_fat_g"],
        chinese["cholesterol_mg"],
        chinese["fiber_g"],
        chinese["protein_g"],
        chinese["sugars_g"],
        chinese["carbs_g"],
        chinese["sodium_mg"],
    ) == (291, 6, 1, 80, 4, 37, 13, 22, 440)
    assert len({item["id"] for item in items}) == len(items), "duplicate item ids"
    saved_items = [
        {key: value for key, value in item.items() if key in CANONICAL_ITEM_FIELDS}
        for item in items
    ]

    save_restaurant(
        {
            "id": "proper-food",
            "name": "Proper Food",
            "website": "https://properfood.com",
            "nutrition_source": {
                "type": "published",
                "url": NUTRITION_URL,
                "vendor": None,
                "retrieved": TODAY,
            },
            "locations": store_locations,
            "items": saved_items,
        }
    )
    counts = {}
    for item in items:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    print("category counts:", json.dumps(counts, sort_keys=True))
    print("location count:", len(store_locations))


if __name__ == "__main__":
    main()
