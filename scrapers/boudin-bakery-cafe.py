"""Scraper for Boudin Bakery Cafe published nutrition and SF locations."""

from __future__ import annotations

import datetime
import html
import io
import re
import sys
import urllib.request
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402


PDF_URL = "https://boudinbakery.com/wp-content/uploads/2017/06/Boudin-Nutritional-Brochure-2.pdf"
LOCATOR_URL = "https://boudinbakery.com/locations/"
SITE = "https://boudinbakery.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126"}
TODAY = datetime.date.today().isoformat()

SECTIONS = {
    "BREAKFAST": "meal",
    "BREAKFAST SANDWICHES": "meal",
    "SCRAMBLES": "meal",
    "SANDWICHES": "meal",
    "CLASSICS": "meal",
    "ARTISAN": "meal",
    "HOT SANDWICHES": "meal",
    "PIZZA": "meal",
    "SIDES": "side",
    "BREADS": "component",
    "COOKIES": "side",
}


def get(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def num(value):
    text = str(value or "").replace(",", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return None if not match else float(match.group()) if "." in match.group() else int(match.group())


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def item(name, values, category, serving):
    return {
        "id": slug(name) + "-" + slug(serving),
        "name": name,
        "description": None,
        "category": category,
        "calories": num(values[0]),
        "fat_g": num(values[2]),
        "protein_g": num(values[10]),
        "carbs_g": num(values[7]),
        "fiber_g": num(values[8]),
        "sodium_mg": num(values[6]),
        "serving_note": serving,
        "is_estimate": False,
        "source": {"type": "published", "url": PDF_URL},
    }


def parse_nutrition(pdf_bytes):
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        table = pdf.pages[0].extract_tables()[0]
    items = []
    section = None
    for row in table:
        cells = [re.sub(r"\s+", " ", str(cell or "").replace("\n", " ")).strip() for cell in row]
        name = cells[0] if cells else ""
        if name in SECTIONS:
            section = name
            continue
        if section and name and num(name) is None and num(cells[1] if len(cells) > 1 else "") is not None:
            values = cells[1:12]
            if len(values) == 11:
                serving = "per entrée" if section in {"SANDWICHES", "CLASSICS", "ARTISAN", "HOT SANDWICHES", "PIZZA"} else "per serving"
                items.append(item(name, values, SECTIONS[section], serving))

        # The PDF's center column contains salad and soup rows. Use the
        # bread-bowl/entrée values before the slash, preserving the labeled row.
        if (
            len(cells) > 12
            and cells[12]
            and not re.fullmatch(r"[\d,.\s/]+", cells[12])
            and num(cells[13].split("/")[0]) is not None
        ):
            middle_name = cells[12]
            middle_name = re.split(r"\s+(?:/|--)\s+", middle_name, maxsplit=1)[0].strip()
            if "salad" in middle_name.lower():
                category, serving = "meal", "per entrée salad"
            elif "bread bowl" in middle_name.lower():
                category, serving = "meal", "per sourdough bread bowl"
            else:
                category = "component"
                serving = "per serving"
            values = [part.split("/")[0].strip() for part in cells[13:24]]
            if len(values) == 11:
                items.append(item(middle_name, values, category, serving))
    return items


def parse_locations(html_text):
    pattern = (
        r'"address":\s*"([^"]*San Francisco[^"]*)"'
        r'.*?"latitude":\s*([-0-9.]+)\s*,\s*"longitude":\s*([-0-9.]+)'
    )
    locations = []
    seen = set()
    for address, lat, lng in re.findall(pattern, html_text, flags=re.DOTALL):
        address = html.unescape(re.sub(r"\s+", " ", address).strip())
        if "International Terminal" in address:
            continue
        if address in seen:
            continue
        seen.add(address)
        locations.append(
            {
                "address": address,
                "lat": float(lat),
                "lng": float(lng),
                "neighborhood": None,
            }
        )
    if not locations:
        raise ValueError("No San Francisco locations found in official locator")
    return locations


def spot_check(items):
    item = next(
        (
            i for i in items
            if i["name"].startswith("Clam Chowder with Sourdough Bread Bowl Top")
            and i["calories"] == 575
        ),
        None,
    )
    if item is None:
        raise ValueError("Boudin clam chowder bread-bowl spot check failed: expected 575 kcal")


def main():
    items = parse_nutrition(get(PDF_URL))
    spot_check(items)
    save_restaurant(
        {
            "id": "boudin-bakery-cafe",
            "name": "Boudin Bakery Cafe",
            "website": SITE,
            "nutrition_source": {
                "type": "published",
                "url": PDF_URL,
                "vendor": None,
                "retrieved": TODAY,
            },
            "locations": parse_locations(get(LOCATOR_URL).decode("utf-8")),
            "items": items,
        }
    )


if __name__ == "__main__":
    main()
