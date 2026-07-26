"""Blaze Pizza nutrition and San Francisco location scraper.

Blaze does not publish nutrition on ``blazepizza.com``; its contracted vendor
page is the Nutritionix interactive nutrition menu, which is server-rendered
HTML and readable without a browser.  Every numeric cell carries a labeled
``title`` attribute ("390mg Sodium"), so columns are resolved by label rather
than by position.

What the rows are PER matters here: the two pizza sections publish a SLICE
(1 of 6 for 11-inch, 1 of 8 for large), which is not an orderable item, so
those rows are kept as components and whole pizzas are derived as slice sums
(source "derived", is_estimate=True).  The "Take Two" section publishes half
pizzas, which Blaze does sell, so those are meals with a half-pizza serving
note.  Build-your-own dough/sauce/cheese/topping sections are components.

Locations come from Blaze's official Yext-backed store directory at
``locations.blazepizza.com``, which embeds schema.org coordinates.
"""

from __future__ import annotations

import datetime
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

NUTRITION_URL = "https://www.nutritionix.com/blaze-pizza/menu/premium"
DIRECTORY_URL = "https://locations.blazepizza.com/us/ca"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/133 Safari/537.36"}
TODAY = datetime.date.today().isoformat()

# Nutritionix cell labels -> our field names.
FIELD_LABELS = {
    "Calories": "calories",
    "Total Fat": "fat_g",
    "Total Carbohydrates": "carbs_g",
    "Dietary Fiber": "fiber_g",
    "Sodium": "sodium_mg",
    "Protein": "protein_g",
}
MACROS = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sodium_mg")

SLICE_SECTIONS = {"Pizza - 11 Inch": (6, "11-inch"), "Pizza - Large": (8, "large")}
DRINK_SECTIONS = {"Drinks - 16 oz", "Drinks - 24 oz", "Other Drinks", "Beer & Wine"}
COMPONENT_SECTIONS = {
    "Dough 11 Inch Pizzas",
    "Dough Large Pizzas",
    "Sauce 11 Inch Pizzas",
    "Sauce Large Pizzas",
    "Cheese 11 Inch Pizzas",
    "Cheese Large Pizzas",
    "Meats and Veggies 11 Inch Pizzas",
    "Meats and Veggies Large Pizzas",
    "Finishes 11 Inch Pizzas",
    "Finishes Large Pizzas",
}
SIDE_SECTIONS = {"Sides", "Dessert"}
CONDIMENT_WORDS = ("sauce", "drizzle", "glaze", "oil", "vinaigrette", "dressing", "ranch")

ROW_RE = re.compile(r'<tr class="(?:odd|even)">(.*?)</tr>', re.S)
NAME_RE = re.compile(r'class="nmItem"[^>]*>(.*?)</a>', re.S)
CELL_RE = re.compile(r'<td class="col" title="([^"]*)"')
VALUE_RE = re.compile(r"^<?\s*([\d.]+)\s*(?:g|mg)?\s+(.*)$")
SLICE_RE = re.compile(r"\((?:1 of (\d+) slices?)\)", re.I)


def fetch(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", "replace")


def slug(text):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def clean(text):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text))).strip()


def parse_cells(row_html):
    """Return {field: number} decoded from the labeled title attributes."""
    values = {}
    for title in CELL_RE.findall(row_html):
        match = VALUE_RE.match(html.unescape(title).strip())
        if not match:
            continue
        number, label = match.groups()
        label = label.strip()
        if label in FIELD_LABELS:
            values[FIELD_LABELS[label]] = float(number)
    return values


def category_for(section, name):
    if section in SLICE_SECTIONS:
        return "component"
    if section == "Take Two (Half Pizza)":
        return "meal"
    if section == "Simple Salads":
        return "meal" if "(Entrée)" in name or "(Entree)" in name else "side"
    if section in SIDE_SECTIONS:
        return "side"
    if section in DRINK_SECTIONS:
        return "drink"
    if section in COMPONENT_SECTIONS:
        lowered = name.lower()
        return "condiment" if any(w in lowered for w in CONDIMENT_WORDS) else "component"
    # Unknown section: never assume it is a meal.
    return "component"


def serving_note_for(section, name):
    if section in SLICE_SECTIONS:
        slices, size = SLICE_SECTIONS[section]
        return f"per slice (1 of {slices}) of a {size} pizza"
    if section == "Take Two (Half Pizza)":
        return "per half pizza"
    if section == "Simple Salads":
        return "per entree salad" if "Entrée" in name or "Entree" in name else "per side salad"
    if section in DRINK_SECTIONS:
        match = re.search(r"(\d+ oz)", section)
        return f"per {match.group(1)}" if match else "per serving"
    if section in COMPONENT_SECTIONS:
        return "per pizza portion of this ingredient"
    return "per serving"


def parse_menu(page):
    """Yield (section, name, values) for every published Nutritionix row."""
    for block in re.split(r'<tr class="subCategory"', page)[1:]:
        section = clean(re.search(r"<h3>(.*?)</h3>", block, re.S).group(1))
        for row in ROW_RE.findall(block):
            name_match = NAME_RE.search(row)
            if not name_match:
                continue
            values = parse_cells(row)
            if not all(f in values for f in ("calories", "protein_g", "carbs_g", "fat_g")):
                continue
            yield section, clean(name_match.group(1)), values


def sf_locations():
    directory = fetch(DIRECTORY_URL)
    locations = []
    for city_path in sorted(set(re.findall(r'href="(/us/ca/[a-z0-9-]+)"', directory))):
        if not city_path.endswith("/san-francisco"):
            continue
        city_page = fetch(f"https://locations.blazepizza.com{city_path}")
        for store_path in sorted(set(re.findall(rf'href="({city_path}/[a-z0-9-]+)"', city_page))):
            store = fetch(f"https://locations.blazepizza.com{store_path}")
            data = json.loads(
                re.search(r'"address"\s*:\s*(\{.*?\})', store, re.S).group(1)
            )
            geo = re.search(r'"latitude"\s*:\s*([-\d.]+).*?"longitude"\s*:\s*([-\d.]+)', store, re.S)
            if data.get("addressLocality") != "San Francisco":
                continue
            locations.append({
                "address": f"{data['streetAddress']}, San Francisco, CA {data.get('postalCode', '')}".strip(),
                "lat": float(geo.group(1)),
                "lng": float(geo.group(2)),
                "neighborhood": None,
            })
    return locations


def main():
    page = fetch(NUTRITION_URL)
    items = []
    slices = {}

    for section, name, values in parse_menu(page):
        category = category_for(section, name)
        base_name = SLICE_RE.sub("", name).strip()
        item_id = slug(f"{section}-{name}")
        items.append({
            "id": item_id,
            "name": name,
            "description": None,
            "category": category,
            "serving_note": serving_note_for(section, name),
            "is_estimate": False,
            "source": {"type": "vendor", "url": NUTRITION_URL},
            **{field: values.get(field) for field in MACROS},
        })
        if section in SLICE_SECTIONS:
            slices.setdefault(section, []).append((base_name, values))

    # Whole pizzas are not published; Blaze sells them whole, so derive them
    # from the published per-slice rows.
    for section, rows in slices.items():
        count, size = SLICE_SECTIONS[section]
        for base_name, values in rows:
            totals = {f: (values.get(f) or 0) * count for f in MACROS}
            items.append({
                "id": slug(f"{base_name}-whole-{size}-pizza"),
                "name": f"{base_name} ({size.title()} Pizza, whole)",
                "description": (
                    f"Whole {size} pizza: Blaze publishes this pizza per slice; "
                    f"this row is {count} x the published slice."
                ),
                "category": "meal",
                "serving_note": f"per whole {size} pizza ({count} slices)",
                "is_estimate": True,
                "source": {"type": "derived", "url": NUTRITION_URL},
                **totals,
            })

    save_restaurant({
        "id": "blaze-pizza",
        "name": "Blaze Pizza",
        "website": "https://www.blazepizza.com",
        "nutrition_source": {
            "type": "vendor",
            "url": NUTRITION_URL,
            "vendor": "nutritionix",
            "retrieved": TODAY,
        },
        "locations": sf_locations(),
        "items": items,
    })


if __name__ == "__main__":
    main()
