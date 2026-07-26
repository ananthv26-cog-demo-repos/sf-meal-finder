"""In-N-Out Burger scraper.

Nutrition: the single-page PDF at in-n-out.com/nutrition. It holds two tables:
  - food + shakes/hot drinks, one row per item with sub-rows for variants
    ("with mustard & ketchup instead of spread", "Protein Style")
  - fountain drinks, four sizes each, published twice: with ice and without ice

Column headers in both tables are rotated 90 deg, so pdftotext/extract_text
scrambles them; columns are located by the x-position of their (reversed)
header word and every row is mapped against those anchors rather than by
ordinal position.

TRAP: in-n-out.com is Incapsula-protected — curl/urllib get a 212-byte
JavaScript challenge page instead of the PDF. Fetched through the real Chrome
on the VM over CDP (fetch() from a page already on the origin).

Locations: https://locations.in-n-out.com/api/finder/search/ (the Angular
locator's own API, unprotected, carries lat/lng).
"""

from __future__ import annotations

import base64
import datetime
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

PDF_URL = (
    "https://www.in-n-out.com/docs/default-source/downloads/"
    "nutrition_info.pdf?sfvrsn=332aab37_31"
)
NUTRITION_PAGE = "https://www.in-n-out.com/nutrition"
LOCATIONS_URL = (
    "https://locations.in-n-out.com/api/finder/search/"
    "?latitude=37.7749&longitude=-122.4194&maxdistance=25&maxresults=100&showunopened=false"
)
CDP = "http://localhost:29229"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/137"}
TODAY = datetime.date.today().isoformat()

# Reversed header text -> column key, for the rotated headers of the food table.
FOOD_HEADERS = {
    "gnivreS": "serving",
    "loretselohC": "cholesterol_mg",
    "muidoS": "sodium_mg",
    "etardyhobraC": "carbs_g",
    "rebiF": "fiber_g",
    "sraguS": "sugars_g",
    "nietorP": "protein_g",
    "detarutaS": "sat_fat_g",
    "snarT": "trans_fat_g",
}
# The three left-hand columns share the words "Total"/"Calories"/"Fat", so they
# are anchored on the x-positions asserted against the labeled ones above.
FOOD_UNLABELED = {"calories": 221.0, "cal_from_fat": 249.0, "fat_g": 276.0}
FOOD_ORDER = [
    "serving", "calories", "cal_from_fat", "fat_g", "sat_fat_g", "trans_fat_g",
    "cholesterol_mg", "sodium_mg", "carbs_g", "fiber_g", "sugars_g", "protein_g",
]

# Fountain-drink table: same layout twice (with ice / without ice).
DRINK_COLUMNS = ["serving", "calories", "fat_g", "sodium_mg", "carbs_g", "sugars_g", "protein_g"]
DRINK_ICE_X = {"with ice": [186.0, 212.0, 239.0, 261.0, 285.0, 308.0, 333.0],
               "without ice": [351.0, 377.0, 404.0, 425.0, 448.0, 472.0, 498.0]}
SIZE_LABELS = {"Sm", "Med", "Lg", "X-Lg"}

CATEGORIES = {
    "Hamburger w/Onion": "meal",
    "Cheeseburger w/Onion": "meal",
    "Double-Double® w/Onion": "meal",
    "French Fries": "side",
    "Chocolate Shake": "drink",
    "Vanilla Shake": "drink",
    "Strawberry Shake": "drink",
    "Coffee": "drink",
    "Hot Cocoa": "drink",
    "Milk": "drink",
}
# Rows that modify the item above them rather than naming a new one.
VARIANT_ROWS = (
    "with mustard & ketchup instead of spread",
    "Protein Style® (Bun replaced with Lettuce)",
    "with Marshmallows",
)
DESCRIPTIONS = {
    "Hamburger w/Onion": "Bun, 100% beef patty, lettuce, tomato, spread, with onions.",
    "Cheeseburger w/Onion": (
        "Bun, 100% beef patty, lettuce, tomato, spread, 1 slice of American cheese, with onions."
    ),
    "Double-Double® w/Onion": (
        "Bun, 2 100% beef patties, lettuce, tomato, spread, 2 slices of American cheese, "
        "with onions."
    ),
}
# One independently known row, checked before anything is saved.
SPOT_CHECK = ("Double-Double® w/Onion", {"calories": 610, "protein_g": 34, "carbs_g": 42, "fat_g": 34})


def fetch_pdf():
    """Return the nutrition PDF bytes, going through real Chrome if Incapsula bites."""
    req = urllib.request.Request(PDF_URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read()
    if raw[:4] == b"%PDF":
        return raw

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        page = pw.chromium.connect_over_cdp(CDP).contexts[0].new_page()
        try:
            page.goto(NUTRITION_PAGE, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
            encoded = page.evaluate(
                """async (url) => {
                    const response = await fetch(url, {credentials: 'include'});
                    const bytes = new Uint8Array(await response.arrayBuffer());
                    let binary = '';
                    for (let i = 0; i < bytes.length; i += 8192) {
                        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
                    }
                    return btoa(binary);
                }""",
                PDF_URL,
            )
        finally:
            page.close()
    raw = base64.b64decode(encoded)
    if raw[:4] != b"%PDF":
        raise SystemExit("in-n-out: nutrition PDF still bot-blocked in real Chrome")
    return raw


def rows_of(words, tolerance=2.5):
    """Group words into visual rows. Numbers and their label can sit a couple of
    points apart vertically, so cluster on gaps rather than rounding."""
    grouped, current = [], []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if current and word["top"] - current[-1]["top"] > tolerance:
            grouped.append(sorted(current, key=lambda w: w["x0"]))
            current = []
        current.append(word)
    if current:
        grouped.append(sorted(current, key=lambda w: w["x0"]))
    return grouped


def number(text):
    """'1,080' -> 1080, '<1' -> 0.5, '4.5' -> 4.5."""
    text = text.replace(",", "").strip()
    if text.startswith("<"):
        return 0.5
    return float(text) if "." in text else int(text)


def is_value(text):
    return bool(re.fullmatch(r"<?\d[\d,]*(?:\.\d+)?|\d+oz\.", text.strip()))


def food_anchors(words):
    """x-position per column, taken from the rotated header words themselves."""
    anchors = dict(FOOD_UNLABELED)
    for word in words:
        key = FOOD_HEADERS.get(word["text"])
        if key and key not in anchors:
            anchors[key] = word["x0"]
    missing = [k for k in FOOD_ORDER if k not in anchors]
    if missing:
        raise SystemExit(f"in-n-out: could not locate PDF columns {missing}")
    ordered = [anchors[k] for k in FOOD_ORDER]
    if ordered != sorted(ordered):
        raise SystemExit(f"in-n-out: column anchors out of order: {anchors}")
    return anchors


def assign(values, anchors, keys):
    """Map each (x, text) value onto the nearest column anchor."""
    row = {}
    for x, text in values:
        key = min(keys, key=lambda k: abs(anchors[k] - x))
        if abs(anchors[key] - x) > 14:
            raise SystemExit(f"in-n-out: value {text!r} at x={x:.0f} matches no column")
        row[key] = text
    return row


def slug(text):
    text = text.replace("®", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def parse_food(page):
    words = page.extract_words()
    anchors = food_anchors(words)
    items, parent = [], None
    for row in rows_of(words):
        values = [(w["x0"], w["text"]) for w in row if w["x0"] > 180 and is_value(w["text"])]
        label = " ".join(w["text"] for w in row if w["x0"] <= 180).strip()
        if len(values) != len(FOOD_ORDER):
            continue
        cells = assign(values, anchors, FOOD_ORDER)

        if label in VARIANT_ROWS:
            if parent is None:
                raise SystemExit(f"in-n-out: variant row {label!r} with no parent item")
            name = f"{parent} — {label}"
            category = CATEGORIES[parent]
        elif label in CATEGORIES:
            parent, name, category = label, label, CATEGORIES[label]
        else:
            raise SystemExit(f"in-n-out: unmapped nutrition row {label!r}")

        serving = cells["serving"]
        items.append({
            "id": slug(name),
            "name": name,
            "description": DESCRIPTIONS.get(name),
            "category": category,
            "calories": number(cells["calories"]),
            "protein_g": number(cells["protein_g"]),
            "carbs_g": number(cells["carbs_g"]),
            "fat_g": number(cells["fat_g"]),
            "fiber_g": number(cells["fiber_g"]),
            "sodium_mg": number(cells["sodium_mg"]),
            "serving_note": (
                f"per {serving.replace('oz.', ' oz')} serving"
                if serving.endswith("oz.")
                else f"per serving ({serving} g)"
            ),
            "is_estimate": False,
            "source": {"type": "published", "url": PDF_URL},
        })
    return items


def parse_drinks(page):
    """Fountain drinks: a name row followed/preceded by its four size rows,
    each size published twice (with ice and without ice)."""
    words = page.extract_words()
    names, size_rows = [], []
    for row in rows_of(words):
        label = " ".join(w["text"] for w in row if w["x0"] < 140).strip()
        size = next((w["text"] for w in row if 145 < w["x0"] < 180 and w["text"] in SIZE_LABELS), None)
        if label and size is None:
            # trailing * is the "available only in select markets" footnote
            names.append((row[0]["top"], label.rstrip("*")))
        elif size is not None:
            values = [(w["x0"], w["text"]) for w in row if w["x0"] > 180 and is_value(w["text"])]
            if len(values) == 2 * len(DRINK_COLUMNS):
                size_rows.append((row[0]["top"], size, values))

    items = []
    for index in range(0, len(size_rows), len(SIZE_LABELS)):
        group = size_rows[index:index + len(SIZE_LABELS)]
        low, high = group[0][0], group[-1][0]
        candidates = [label for top, label in names if low - 6 <= top <= high + 6]
        if len(candidates) != 1:
            raise SystemExit(f"in-n-out: {len(candidates)} drink names for rows at y={low:.0f}")
        drink = candidates[0]
        for top, size, values in group:
            for ice, xs in DRINK_ICE_X.items():
                anchors = dict(zip(DRINK_COLUMNS, xs))
                half = [(x, text) for x, text in values if min(xs) - 14 <= x <= max(xs) + 14]
                cells = assign(half, anchors, DRINK_COLUMNS)
                if len(cells) != len(DRINK_COLUMNS):
                    raise SystemExit(f"in-n-out: incomplete drink row {drink} {size} {ice}")
                items.append({
                    "id": f"{slug(drink)}-{slug(size)}-{slug(ice)}",
                    "name": f"{drink} ({size})",
                    "description": None,
                    "category": "drink",
                    "calories": number(cells["calories"]),
                    "protein_g": number(cells["protein_g"]),
                    "carbs_g": number(cells["carbs_g"]),
                    "fat_g": number(cells["fat_g"]),
                    "fiber_g": None,
                    "sodium_mg": number(cells["sodium_mg"]),
                    "serving_note": f"per {size} cup ({cells['serving'].replace('oz.', ' oz')}), {ice}",
                    "is_estimate": False,
                    "source": {"type": "published", "url": PDF_URL},
                })
    return items


def spot_check(items):
    name, expected = SPOT_CHECK
    row = next((i for i in items if i["name"] == name), None)
    if row is None:
        raise SystemExit(f"in-n-out: spot-check item {name!r} missing from parse")
    actual = {k: row[k] for k in expected}
    if actual != expected:
        raise SystemExit(f"in-n-out: spot check failed for {name}: {actual} != {expected}")
    print(f"in-n-out spot check OK — {name}: {actual}")


def sf_locations():
    req = urllib.request.Request(LOCATIONS_URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as response:
        stores = json.load(response)
    locations = []
    for store in stores:
        # Filter on the locator's city field: SF-adjacent stores (Daly City,
        # South San Francisco) are close enough to show up in the radius search.
        if store.get("City") != "San Francisco" or store.get("State") != "CA":
            continue
        locations.append({
            "address": f"{store['StreetAddress'].strip()}, San Francisco, CA {store['ZipCode']}",
            "lat": store["Latitude"],
            "lng": store["Longitude"],
            "neighborhood": None,
        })
    if not locations:
        raise SystemExit("in-n-out: locator returned no San Francisco stores")
    return locations


def main():
    with pdfplumber.open(io.BytesIO(fetch_pdf())) as pdf:
        page = pdf.pages[0]
        items = parse_food(page) + parse_drinks(page)
    spot_check(items)
    save_restaurant({
        "id": "in-n-out",
        "name": "In-N-Out Burger",
        "website": "https://www.in-n-out.com",
        "nutrition_source": {"type": "published", "url": PDF_URL, "vendor": None, "retrieved": TODAY},
        "locations": sf_locations(),
        "items": items,
    })


if __name__ == "__main__":
    main()
