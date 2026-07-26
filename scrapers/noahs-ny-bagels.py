"""Scraper for Noah's NY Bagels published nutrition and SF locations."""

from __future__ import annotations

import datetime
import io
import json
import re
import urllib.request
import urllib.parse
from pathlib import Path

import pdfplumber

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402


PDF_URL = "https://www.noahs.com/wp-content/uploads/NNYB-Nutrition-Guide-Master-2026-2.pdf"
LOCATOR_URL = "https://locations.noahs.com/us/ca/san-francisco"
SITE = "https://www.noahs.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126"}
TODAY = datetime.date.today().isoformat()

SECTION_CATEGORIES = {
    "Bagels": "component",
    "Gourmet Bagels and Specialty Bread": "component",
    "Regular Whipped Cream Cheese Shmear": "component",
    "Reduced Fat Whipped Cream Cheese Shmear": "component",
    "Other Spreads": "condiment",
    "Cheese": "component",
    "Eggs": "component",
    "Meats": "component",
    "Sauces": "condiment",
    "Veggies": "component",
    "Egg Sandwiches One Egg": "meal",
    "Egg Sandwich Two Eggs": "meal",
    "Egg Sandwich Egg White": "meal",
    "Gourmet": "meal",
    "Lunch Sandwiches - Deli": "meal",
    "Lunch Sandwiches - Hot": "meal",
    "Sides": "side",
    "Sweets": "side",
    "Classic Coffee Drinks (With 2% Milk)": "drink",
    "Signature Coffee Drinks (With 2% Milk)": "drink",
    "Cold Brew Frozen Shakes": "drink",
    "Hot Chocolate (With 2% Milk)": "drink",
    "Coffee, Hot/Iced Tea": "drink",
    "Juice": "drink",
    "Creamers and Milk": "component",
}


def get_bytes(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def number(value):
    value = str(value or "").replace(",", "").strip()
    return None if not value else float(value) if "." in value else int(value)


def category_for_limited(name):
    if any(word in name.lower() for word in ("cooler", "spritz", "nectar", "sunrise")):
        return "drink"
    if "sandwich" in name.lower() or "bagel" in name.lower():
        return "meal"
    if any(word in name.lower() for word in ("cookie", "hash brown")):
        return "side"
    raise ValueError(f"Unmapped limited-offering section row: {name!r}")


def category_for_continuation(name):
    lowered = name.lower()
    if any(
        word in lowered
        for word in ("coffee", "cold brew", "tea", "latte", "mocha", "cappuccino", "americano",
                     "macchiato", "shake", "lemonade", "juice", "chocolate")
    ):
        return "drink"
    if any(
        word in lowered
        for word in ("sandwich", "bagel dog", "pizza bagel", "avocado on", "ham and swiss",
                     "santa fe on", "power egg")
    ):
        return "meal"
    if any(word in lowered for word in ("hash brown", "cookie", "muffin", "cinnamon roll", "pastry")):
        return "side"
    raise ValueError(f"Unmapped continuation row: {name!r}")


def parse_nutrition(pdf_bytes):
    items = []
    section = None
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        tables = [table for page in pdf.pages for table in page.extract_tables()]
    for table in tables:
        header = None
        inferred_category = None
        start = 0
        for index, row in enumerate(table):
            cells = [str(cell or "").replace("\n", " ").strip() for cell in row]
            if cells and cells[0] == "Item":
                header = cells
                start = index + 1
                break
        if header is not None:
            first = next(
                (str(row[0] or "").replace("\n", " ").strip() for row in table[:start] if row and row[0]),
                "",
            )
            if first and first != "Item" and not first.startswith("Last Updated") and not first.startswith("Limited Time"):
                section = first
        if header is None:
            if section is None:
                raise ValueError("Nutrition table has no section or header")
            start = 0
            inferred_category = category_for_continuation(
                str(table[0][0] or "").replace("\n", " ").strip()
            )
            if inferred_category == "drink":
                header = [
                    "Item", "Serving Size", "Calories", "Total Fat (g)",
                    "Saturated Fat (g)", "Trans Fats (g)", "Cholesterol (mg)",
                    "Sodium (mg)", "Total Carbs (g)", "Dietary Fiber (g)",
                    "Sugars (g)", "Added Sugars (g)", "Protein (g)",
                ]
            else:
                header = [
                    "Item", "Serving Size", "Weight", "Calories", "Total Fat (g)",
                    "Saturated Fat (g)", "Trans Fats (g)", "Cholesterol (mg)",
                    "Sodium (mg)", "Total Carbs (g)", "Dietary Fiber (g)",
                    "Sugars (g)", "Added Sugars (g)", "Protein (g)",
                ]
        columns = {name: index for index, name in enumerate(header)}
        required = {"Item", "Serving Size", "Calories", "Total Fat (g)", "Sodium (mg)",
                    "Total Carbs (g)", "Dietary Fiber (g)", "Protein (g)"}
        if not required <= columns.keys():
            raise ValueError(f"Unexpected nutrition headers: {header!r}")
        for row in table[start:]:
            cells = [str(cell or "").replace("\n", " ").strip() for cell in row]
            if not cells or not cells[0] or cells[0] == "Item":
                continue
            if len(cells) <= max(columns.values()):
                continue
            name = re.sub(r"\s+", " ", cells[columns["Item"]]).strip()
            serving = re.sub(r"\s+", " ", cells[columns["Serving Size"]]).strip()
            if not name or not number(cells[columns["Calories"]]):
                continue
            category = (
                SECTION_CATEGORIES.get(section)
                if section
                else category_for_limited(name)
            )
            if inferred_category is not None:
                category = inferred_category
            if category is None:
                category = category_for_continuation(name)
            items.append(
                {
                    "id": slug(name) + "-" + slug(serving),
                    "name": name,
                    "description": None,
                    "category": category,
                    "calories": number(cells[columns["Calories"]]),
                    "protein_g": number(cells[columns["Protein (g)"]]),
                    "carbs_g": number(cells[columns["Total Carbs (g)"]]),
                    "fat_g": number(cells[columns["Total Fat (g)"]]),
                    "fiber_g": number(cells[columns["Dietary Fiber (g)"]]),
                    "sodium_mg": number(cells[columns["Sodium (mg)"]]),
                    "serving_note": f"per {serving.lower()}",
                    "is_estimate": False,
                    "source": {"type": "published", "url": PDF_URL},
                }
            )
    return items


def parse_locations(html):
    paths = sorted(set(re.findall(r'href="([^"]+/us/ca/san-francisco/[^"]+)"', html)))
    if not paths:
        raise ValueError("No San Francisco locations found in official locator")
    locations = []
    for path in paths:
        path = urllib.parse.urljoin(LOCATOR_URL, path)
        page = get_bytes(path).decode("utf-8")
        match = re.search(
            r'"address":\{"@type":"PostalAddress","streetAddress":"([^"]+)"'
            r'.*?"addressLocality":"San Francisco".*?"postalCode":"([^"]+)"'
            r'.*?"geo":\{"@type":"GeoCoordinates","latitude":([^,]+),"longitude":([^}]+)',
            page,
            flags=re.DOTALL,
        )
        if not match:
            raise ValueError(f"Could not parse official location page {path}")
        street, postal, lat, lng = match.groups()
        locations.append(
            {
                "address": f"{street.replace(chr(10), ', ')}, San Francisco, CA {postal}",
                "lat": float(lat),
                "lng": float(lng),
                "neighborhood": None,
            }
        )
    return locations


def spot_check(items):
    item = next(
        (
            i for i in items
            if i["name"] == "Plain"
            and i["serving_note"] == "per 1 bagel"
            and i["calories"] == 270
        ),
        None,
    )
    if item is None:
        raise ValueError("Noah's plain bagel spot check failed: expected 270 kcal")


def main():
    items = parse_nutrition(get_bytes(PDF_URL))
    spot_check(items)
    locations = parse_locations(get_bytes(LOCATOR_URL).decode("utf-8"))
    save_restaurant(
        {
            "id": "noahs-ny-bagels",
            "name": "Noah's NY Bagels",
            "website": SITE,
            "nutrition_source": {
                "type": "published",
                "url": PDF_URL,
                "vendor": None,
                "retrieved": TODAY,
            },
            "locations": locations,
            "items": items,
        }
    )


if __name__ == "__main__":
    main()
