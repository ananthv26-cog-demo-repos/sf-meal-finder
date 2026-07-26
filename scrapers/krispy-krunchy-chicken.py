"""Krispy Krunchy Chicken scraper.

Nutrition: the brand's own PDF guide (text-readable, one labeled header row per
menu section):
  https://www.krispykrunchy.com/wp-content/uploads/2023/11/Nutrition-and-Allergen-Guide-Effective-11-2023.pdf
Each section repeats its own header ("Cals (kcal) Fat Cals Fat (g) ..."), so
columns are resolved from that header instead of fixed positions, and the
section title drives the category mapping.

Locations: the Yext-backed official locator, https://locations.krispykrunchy.com.
The city page embeds the authoritative store list (with city field) in a
URL-encoded page blob under `dm_directoryChildren`; each store page then carries
`yextDisplayCoordinate` — chain-published lat/lng.
TRAP: the brand runs inside convenience stores/delis and some of its listed
stores have no generated Yext detail page (HTTP 404) even though the city page
lists them. Take the store list from the city page and geocode the stragglers,
rather than dropping any store whose detail page is missing.
"""

import datetime
import io
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from _geo import geocode  # noqa: E402
from save import save_restaurant  # noqa: E402

PDF_URL = (
    "https://www.krispykrunchy.com/wp-content/uploads/2023/11/"
    "Nutrition-and-Allergen-Guide-Effective-11-2023.pdf"
)
LOCATOR_URL = "https://locations.krispykrunchy.com/ca/san-francisco.html"
LOCATOR_BASE = "https://locations.krispykrunchy.com/ca/san-francisco/"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
TODAY = datetime.date.today().isoformat()

# Header label -> item field. Only these are kept; the PDF also lists fat
# calories, saturated/trans fat, cholesterol and sugar.
FIELDS = {
    "Cals (kcal)": "calories",
    "Fat (g)": "fat_g",
    "Sod (mg)": "sodium_mg",
    "Carbs (g)": "carbs_g",
    "Fiber (g)": "fiber_g",
    "Protein (g)": "protein_g",
}
HEADER_LABELS = [
    "Cals (kcal)", "Fat Cals", "Fat (g)", "Sat (g)", "Trans (g)", "Chol (mg)",
    "Sod (mg)", "Carbs (g)", "Fiber (g)", "Sugar (g)", "Protein (g)",
]
HEADER_RE = re.compile(r"\s+".join(re.escape(label) for label in HEADER_LABELS) + r"\s*$")
ROW_RE = re.compile(r"^(?P<name>.+?)\s+(?P<nums>(?:-?\d+(?:\.\d+)?\s+){10}-?\d+(?:\.\d+)?)$")

# Section title (as printed, minus the header labels) -> category + serving note.
# Nothing falls through to "meal": unknown sections become "component".
SECTIONS = {
    "Chicken & Biscuit": ("meal", "per combo, includes 1 honey biscuit"),
    "Tenders & Biscuit": ("meal", "per combo, includes 1 honey biscuit"),
    "Individual Chicken/Tenders Listed by the piece": ("component", "per piece"),
    "Traditional Wings Listed by the piece": ("component", "per piece"),
    "Chicken Sandwich": ("meal", "sandwich only, no side"),
    "Honey Butter Fried Shrimp": ("component", "per piece"),
    "Sides": ("side", "per listed size"),
    "Sunrise Breakfast": ("meal", "per item"),
    "Krispy's Dipping Sauces Listed per container": ("condiment", "per container"),
}
# Rows whose section category is wrong for the individual row.
ROW_CATEGORY_OVERRIDES = {
    "1 Blueberry Flavored Biscuit": "side",
}


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(request, timeout=60).read()


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80]


def parse_pdf(raw):
    """Yield (section_title, name, {field: value}) for every nutrition row."""
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        text = pdf.pages[0].extract_text()
    section = None
    order = None
    rows = []
    for line in text.splitlines():
        line = line.strip()
        header = HEADER_RE.search(line)
        if header:
            section = line[: header.start()].strip()
            order = list(HEADER_LABELS)
            continue
        if section is None:
            continue
        match = ROW_RE.match(line)
        if not match:
            continue
        values = [float(n) for n in match.group("nums").split()]
        if len(values) != len(order):
            raise SystemExit(f"krispy-krunchy: {len(values)} cells vs {len(order)} headers: {line!r}")
        cells = dict(zip(order, values))
        rows.append((section, match.group("name").strip(), cells))
    if not rows:
        raise SystemExit("krispy-krunchy: no nutrition rows parsed — PDF shape changed")
    return rows


def build_items(rows):
    items = []
    for section, name, cells in rows:
        if section not in SECTIONS:
            raise SystemExit(f"krispy-krunchy: unmapped section {section!r} — extend SECTIONS")
        category, serving_note = SECTIONS[section]
        category = ROW_CATEGORY_OVERRIDES.get(name, category)
        item = {
            "id": slug(name),
            "name": name,
            "description": section,
            "category": category,
            "serving_note": serving_note,
            "is_estimate": False,
            "source": None,
        }
        for label, field in FIELDS.items():
            item[field] = cells[label]
        items.append(item)
    return items


def directory_children(html):
    """Store records embedded in the city page's URL-encoded page blob."""
    decoded = urllib.parse.unquote(html)
    start = decoded.find('"dm_directoryChildren":')
    if start < 0:
        raise SystemExit("krispy-krunchy: dm_directoryChildren missing — locator shape changed")
    decoder = json.JSONDecoder()
    stores, _ = decoder.raw_decode(decoded, decoded.index("[", start))
    return stores


def store_coords(store_slug):
    """(lat, lng) from the store detail page, or None when Yext has no page."""
    try:
        html = fetch(LOCATOR_BASE + store_slug).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    coord = re.search(
        r'"yextDisplayCoordinate":\{"latitude":(-?[\d.]+),"longitude":(-?[\d.]+)\}',
        urllib.parse.unquote(html),
    )
    return (float(coord.group(1)), float(coord.group(2))) if coord else None


def sf_locations():
    stores = directory_children(fetch(LOCATOR_URL).decode("utf-8", "replace"))
    locations = []
    for store in stores:
        address = store["address"]
        # Filter on the city field, never the zip or the URL slug.
        if address.get("city", "").strip() != "San Francisco":
            continue
        street = " ".join(p for p in (address.get("line1"), address.get("line2")) if p)
        zip_code = address.get("postalCode", "").split("-")[0]
        full = f"{street}, San Francisco, {address['region']} {zip_code}"
        coords = store_coords(store["slug"].rsplit("/", 1)[-1]) or geocode(full)
        locations.append({
            "address": full,
            "lat": coords[0],
            "lng": coords[1],
            "neighborhood": None,
        })
    if not locations:
        raise SystemExit("krispy-krunchy: no SF city-proper stores found")
    return locations


def spot_check(items):
    """The combo rows must equal their published piece rows plus a biscuit."""
    by_id = {item["id"]: item for item in items}
    combo = by_id["2pc-chicken-dark-1-leg-1-thigh-biscuit"]["calories"]
    parts = (
        by_id["leg"]["calories"] + by_id["thigh"]["calories"] + by_id["1-honey-biscuit"]["calories"]
    )
    if combo != parts:
        raise SystemExit(f"krispy-krunchy: 2PC Dark combo {combo} != leg+thigh+biscuit {parts}")
    sandwich = by_id["chicken-sandwich-only"]["calories"]
    if sandwich != 580:
        raise SystemExit(f"krispy-krunchy: Chicken Sandwich {sandwich} kcal, expected published 580")
    print(f"spot check ok: 2PC Dark combo {combo} = leg+thigh+biscuit; sandwich {sandwich} kcal")


def main():
    items = build_items(parse_pdf(fetch(PDF_URL)))
    spot_check(items)
    save_restaurant({
        "id": "krispy-krunchy-chicken",
        "name": "Krispy Krunchy Chicken",
        "website": "https://www.krispykrunchy.com/",
        "nutrition_source": {
            "type": "published",
            "url": PDF_URL,
            "vendor": None,
            "retrieved": TODAY,
        },
        "locations": sf_locations(),
        "items": items,
    })


if __name__ == "__main__":
    main()
