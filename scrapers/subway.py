"""Subway scraper: published U.S. nutrition PDF + Yext store locator.

Nutrition comes from Subway's own "U.S. NUTRITION INFORMATION" PDF, linked
from https://www.subway.com/en-us/menunutrition/nutrition. The PDF is a text
layer (no OCR needed) with one row per item and a fixed 16-value numeric tail;
rows are attributed to a menu section from the section/sub-section headers
above them, so nothing is categorised by guesswork.

TRAP: media.subway.com (Akamai) hangs forever for requests that spoof a
desktop Chrome User-Agent, and www.subway.com refuses scripted requests
outright. The PDF downloads fine with a plain, honest User-Agent.

Locations come from the official locator at restaurants.subway.com, whose
per-store pages carry schema.org lat/lng — no geocoding needed.
"""

from __future__ import annotations

import datetime
import html
import io
import re
import sys
import time
import urllib.request
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

NUTRITION_PAGE = "https://www.subway.com/en-us/menunutrition/nutrition"
PDF_URL = (
    "https://media.subway.com/dam/urn:aaid:aem:2278372c-147b-42f2-8edc-7d8d94d1f07e/"
    "original/as/us-nutrition-en.pdf"
)
LOCATOR_CITY_URL = "https://restaurants.subway.com/united-states/ca/san-francisco"
LOCATOR_BASE = "https://restaurants.subway.com/united-states/ca/san-francisco/"
# Akamai stalls on spoofed browser UAs; an honest client string is served fine.
HEADERS = {"User-Agent": "sf-meal-finder/1.0 (nutrition scraper)"}
TODAY = datetime.date.today().isoformat()

# Order of the numeric tail on every PDF data row (headers are rotated 90° in
# the PDF, so they are unusable as text; the order is asserted by the famous-
# item spot check in `spot_check`).
COLUMNS = [
    "serving_g",
    "calories",
    "fat_g",
    "sat_fat_g",
    "trans_fat_g",
    "cholesterol_mg",
    "sodium_mg",
    "carbs_g",
    "fiber_g",
    "sugars_g",
    "added_sugars_g",
    "protein_g",
    "vit_a_dv",
    "vit_c_dv",
    "calcium_dv",
    "iron_dv",
]
NUM = r"(?:<?\d+(?:\.\d+)?)"
ROW_RE = re.compile(r"^(.*?)\s+(" + NUM + r"(?:\s+" + NUM + r"){15})\s*$")
SECTION_RE = re.compile(r"^[A-Z][A-Z0-9&'\"\s\.]+$")

# Top-level PDF sections -> how their rows are served.
SECTIONS = {
    "SANDWICHES": ("meal", 'per 6" sandwich (double for footlong)'),
    "WRAPS": ("meal", "per wrap"),
    "SALADS": ("meal", "per salad, no dressing unless noted"),
    "PROTEIN BOWLS": ("meal", "per bowl, no dressing or cheese unless noted"),
    "BREAKFAST & PIZZA & SLIDERS": ("meal", "per item as listed"),
    "BREADS & INGREDIENTS": ("component", 'amount on a 6" sandwich or wrap'),
    "DESSERTS & SIDES": ("side", "per serving"),
}
# Every sub-section header the PDF uses, mapped to (category, serving_note) or
# None to inherit the section default. A sub-section header that is not listed
# here raises rather than silently inheriting "meal".
SUBSECTIONS = {
    '6" sandwiches': None,
    "cheesesteaks": None,
    "chicken": None,
    "italians": None,
    "deli classics": None,
    "clubs": None,
    "local favorites": None,
    "fresh fit": None,
    "fresh fit®": None,
    "wraps": None,
    "salads": None,
    "kids' mini sub": ("meal", "per mini sub"),
    "protein pockets": ("meal", 'per 9" protein pocket'),
    'egg patty on 6" artisan italian': ("meal", 'per 6" breakfast sandwich'),
    'egg patty on 12" wrap': ("meal", 'per 12" breakfast wrap'),
    '8" pizza': ("meal", 'per whole 8" pizza'),
    "sliders": ("meal", "per slider"),
    "breads": ("component", 'per 6" bread (double for footlong)'),
    "sandwich condiments and toppings": ("condiment", 'amount on a 6" sandwich or wrap'),
    "seasonings and spices": ("condiment", 'amount on a 6" sandwich or wrap'),
    "vegetables": ("component", 'amount on a 6" sandwich or wrap'),
    "cheese": ("component", 'amount on a 6" sandwich, salad or wrap'),
    "individual proteins": ("component", 'amount on a 6" sub or salad'),
    "cookies & sides": ("side", "per serving"),
    "soup": ("side", "per 8 oz. bowl"),
}


def match_subsection(header):
    """Return (label, override) for a sub-section header line, or None if the
    line is footnote prose. Matching is on whole labels: 'Cheesesteaks' must
    not match the 'cheese' sub-section."""
    lowered = header.lower()
    for label, override in SUBSECTIONS.items():
        if lowered == label or (
            lowered.startswith(label) and lowered[len(label)] in " (*,"
        ):
            return label, override
    return None


def is_prose(line):
    lowered = line.lower()
    return (
        len(line) > 45
        or line[:1].islower()  # wrapped continuation of a footnote sentence
        or "calories a day" in lowered
        or lowered.startswith(("values", "amount", "*", "dressing", "footlong"))
    )


def get_bytes(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def slug(value):
    value = value.replace('"', "in").replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def number(token):
    """'<1' means 'less than one gram' on the label -> treat as 0.5."""
    if token.startswith("<"):
        return 0.5
    value = float(token)
    return int(value) if value.is_integer() else value


def parse_nutrition(pdf_bytes):
    items, ids = [], set()
    section = None
    subsection = None
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        lines = []
        for page in pdf.pages:
            lines.extend((page.extract_text() or "").split("\n"))

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        match = ROW_RE.match(line)
        if not match:
            header = line.split("  ")[0].strip()
            if header in SECTIONS:
                section, subsection = header, None
                continue
            if (
                section is not None
                and header.isupper()
                and SECTION_RE.match(header)
                and len(header.split()) <= 6
            ):
                raise ValueError(f"Unmapped Subway PDF section: {header!r}")
            found = match_subsection(header)
            if found:
                subsection = found
            elif not is_prose(header) and section is not None:
                raise ValueError(f"Unmapped Subway PDF sub-section: {header!r}")
            continue
        if section is None:
            continue

        name = re.sub(r"\s+", " ", html.unescape(match.group(1))).strip()
        if not name:
            continue
        values = dict(zip(COLUMNS, (number(t) for t in match.group(2).split())))

        category, serving = SECTIONS[section]
        label = None
        if subsection is not None:
            label, override = subsection
            if override is not None:
                category, serving = override

        item_id = slug(name)
        if item_id in ids:  # same name under a different build (e.g. wrap vs sub)
            item_id = f"{item_id}-{slug(section)}"
        ids.add(item_id)
        items.append(
            {
                "id": item_id,
                "name": name,
                "description": f"{section.title()} — {label.title()}" if label else section.title(),
                "category": category,
                "calories": values["calories"],
                "protein_g": values["protein_g"],
                "carbs_g": values["carbs_g"],
                "fat_g": values["fat_g"],
                "fiber_g": values["fiber_g"],
                "sodium_mg": values["sodium_mg"],
                "serving_note": f"{serving} ({values['serving_g']} g)",
                "is_estimate": False,
                "source": {"type": "published", "url": PDF_URL},
            }
        )
    if not items:
        raise ValueError("No nutrition rows parsed from the Subway PDF")
    return items


def spot_check(items):
    """Verify the column mapping against independently known Subway numbers."""
    by_name = {item["name"]: item for item in items}
    checks = [
        ('6" Sweet Onion Teriyaki Chicken®', 430, 29, 11),
        ('6" Grilled Chicken', 510, 31, 24),
    ]
    for name, calories, protein, fat in checks:
        item = by_name.get(name)
        if item is None:
            raise ValueError(f"Spot-check item {name!r} missing from parse")
        if (item["calories"], item["protein_g"], item["fat_g"]) != (calories, protein, fat):
            raise ValueError(
                f"Spot check failed for {name}: parsed {item['calories']} kcal / "
                f"{item['protein_g']} g protein / {item['fat_g']} g fat"
            )


def parse_store(path):
    page = get_bytes(LOCATOR_BASE + path).decode("utf-8", "replace")
    city = re.search(r'<span class="c-address-city">([^<]+)</span>', page)
    if not city or city.group(1).strip() != "San Francisco":
        return None  # locator city pages can carry neighbouring-city stores
    street = re.search(r'itemprop="streetAddress" content="([^"]+)"', page)
    postal = re.search(r'"postalCode">([^<]+)</span>', page)
    lat = re.search(r'itemprop="latitude" content="([-\d\.]+)"', page)
    lng = re.search(r'itemprop="longitude" content="([-\d\.]+)"', page)
    if not (street and lat and lng):
        raise ValueError(f"Could not parse store page {path}")
    address = html.unescape(street.group(1)).strip()
    zip_code = postal.group(1).strip() if postal else ""
    return {
        "address": f"{address}, San Francisco, CA {zip_code}".strip(),
        "lat": float(lat.group(1)),
        "lng": float(lng.group(1)),
        "neighborhood": None,
    }


def sf_locations():
    page = get_bytes(LOCATOR_CITY_URL).decode("utf-8", "replace")
    paths = sorted(
        {
            html.unescape(match)
            for match in re.findall(r'href="\.\./\.\./united-states/ca/san-francisco/([^"]+)"', page)
        }
    )
    if not paths:
        raise ValueError("Subway locator returned no San Francisco stores")
    locations = []
    for index, path in enumerate(paths):
        if index:
            time.sleep(0.3)
        location = parse_store(path)
        if location:
            locations.append(location)
    return locations


def main():
    items = parse_nutrition(get_bytes(PDF_URL))
    spot_check(items)
    save_restaurant(
        {
            "id": "subway",
            "name": "Subway",
            "website": "https://www.subway.com",
            "nutrition_source": {
                "type": "published",
                "url": PDF_URL,
                "vendor": None,
                "retrieved": TODAY,
            },
            "locations": sf_locations(),
            "items": items,
        }
    )


if __name__ == "__main__":
    main()
