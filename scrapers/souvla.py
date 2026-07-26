"""Scraper for Souvla's published nutrition and San Francisco locations."""

from __future__ import annotations

import datetime
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402


PDF_URL = (
    "https://media-cdn.getbento.com/accounts/5a6ea86dc04d2c5de0b36e28812fa3b3/"
    "media/aVigbS9lS4aECVTnoic6_Souvla%20Nutritional%20Information.pdf"
)
SITE = "https://www.souvla.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126"}
TODAY = datetime.date.today().isoformat()

LOCATION_PAGES = [
    ("/location/souvla-hayes-valley/", "Hayes Valley"),
    ("/location/souvla-nopa/", "NoPa"),
    ("/location/souvla-the-mission/", "Mission"),
    ("/location/souvla-the-marina/", "Marina"),
    ("/location/the-dogpatch/", "Dogpatch"),
]


def get_bytes(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def serving_note(value):
    return f"per {value.lower()}"


def parse_nutrition(pdf_bytes):
    items = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        tables = pdf.pages[0].extract_tables()
    main = tables[0]
    headers = [str(cell or "").strip() for cell in main[4]]
    indexes = {header: i for i, header in enumerate(headers) if header}
    meals = {
        "Pork Shoulder Sandwich",
        "Pork Shoulder Salad",
        "Free Range Chicken Sandwich",
        "Free Range Chicken Salad",
        "Lamb Leg Sandwich",
        "Lamb Leg Salad",
        "Roasted Sweet Potato Sandwich",
        "Roasted Sweet Potato Salad",
    }
    sides = {"Juicy Potatoes", "Greek Side Salad"}
    condiments = {
        "Lemon Vinaigrette",
        "Garlic Yogurt Sauce",
        "Granch Yogurt Sauce",
        "Harissa Yogurt Sauce",
        "Minted Yogurt Sauce",
    }
    components = {
        "Housemade Pita",
        "Free Range Chicken",
        "Lamb Leg",
        "Pork Shoulder",
        "Roasted Sweet Potatoes",
    }
    for row in main[5:]:
        if not row or not row[0]:
            continue
        values = [str(cell or "").strip() for cell in row]
        name = values[indexes["Dish Name"]]
        # pdfplumber can merge a final character of a long name into the digit.
        name = re.sub(r"Sandwic(?:1h)?$", "Sandwich", name)
        values[indexes["Serving Size"]] = re.sub(
            r"^1h Sandwich$", "1 Sandwich", values[indexes["Serving Size"]]
        )
        if name in meals:
            category = "meal"
        elif name in sides:
            category = "side"
        elif name in condiments:
            category = "condiment"
        elif name in components:
            category = "component"
        else:
            raise ValueError(f"Unexpected main nutrition row: {name!r}")
        items.append(
            {
                "id": slug(name),
                "name": name,
                "description": None,
                "category": category,
                "calories": int(values[indexes["Calories"]]),
                # Map by header, rather than relying on the PDF's column order.
                "carbs_g": int(values[indexes["Carbs (g)"]]),
                "protein_g": int(values[indexes["Protein (g)"]]),
                "fat_g": int(values[indexes["Fat (g)"]]),
                "fiber_g": None,
                "sodium_mg": None,
                "serving_note": serving_note(values[indexes["Serving Size"]]),
                "is_estimate": False,
                "source": {"type": "published", "url": PDF_URL},
            }
        )

    frozen = tables[1]
    frozen_indexes = {str(cell or "").strip(): i for i, cell in enumerate(frozen[0]) if cell}
    for row in frozen[1:]:
        values = [str(cell or "").strip() for cell in row]
        name = values[frozen_indexes["Yogurt Type/Topping"]]
        items.append(
            {
                "id": f"frozen-yogurt-{slug(name)}",
                "name": f"Frozen Yogurt - {name}",
                "description": None,
                "category": "side",
                "calories": int(values[frozen_indexes["Calories"]]),
                "carbs_g": int(values[frozen_indexes["Carbs (g)"]]),
                "protein_g": int(values[frozen_indexes["Protein (g)"]]),
                "fat_g": int(values[frozen_indexes["Fat (g)"]]),
                "fiber_g": None,
                "sodium_mg": None,
                "serving_note": serving_note(values[frozen_indexes["Serving Size"]]),
                "is_estimate": False,
                "source": {"type": "published", "url": PDF_URL},
            }
        )
    return items


def parse_location_page(path, neighborhood):
    html = get_bytes(f"{SITE}{path}").decode("utf-8")
    match = re.search(
        r'"streetAddress"\s*:\s*"([^"]+)".*?"addressLocality"\s*:\s*"([^"]+)".*?'
        r'"addressRegion"\s*:\s*"([^"]+)".*?"postalCode"\s*:\s*"([^"]+)"',
        html,
        flags=re.DOTALL,
    )
    if not match:
        raise ValueError(f"Could not find address on {path}")
    street, locality, region, postal = match.groups()
    address = f"{street}, {locality}, {region} {postal}"
    query = urllib.parse.quote(address)
    url = f"https://nominatim.openstreetmap.org/search?format=json&limit=1&q={query}"
    request = urllib.request.Request(
        url, headers={"User-Agent": "sf-meal-finder/1.0 (nutrition scraper)"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        results = json.load(response)
    if not results:
        raise ValueError(f"Nominatim returned no result for {address}")
    result = results[0]
    return {
        "address": address,
        "lat": float(result["lat"]),
        "lng": float(result["lon"]),
        "neighborhood": neighborhood,
    }


def main():
    items = parse_nutrition(get_bytes(PDF_URL))
    locations = []
    for index, (path, neighborhood) in enumerate(LOCATION_PAGES):
        if index:
            time.sleep(1.1)
        locations.append(parse_location_page(path, neighborhood))
    save_restaurant(
        {
            "id": "souvla",
            "name": "Souvla",
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
