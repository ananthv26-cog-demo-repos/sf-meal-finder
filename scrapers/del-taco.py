"""Scraper for Del Taco's published June 2026 nutrition PDF."""

from __future__ import annotations

import datetime
import io
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402


PDF_URL = "https://deltaco.com/files/pdf/2026/nutritional-06-2026.pdf?v=1.1"
SITE = "https://deltaco.com"
TODAY = datetime.date.today().isoformat()
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126"}


def get_bytes(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def get_locations():
    params = urllib.parse.urlencode(
        {
            "longitude": "-122.419359",
            "latitude": "37.779238",
        }
    )
    page = get_bytes(f"https://locations.deltaco.com/results?{params}").decode(
        "utf-8", "replace"
    )
    if "There were no locations found" in page:
        return []
    # The locator renders result cards server-side; retain only exact SF cards
    # if the endpoint begins returning records in a future locator revision.
    locations = []
    for match in re.finditer(
        r'data-location-address="([^"]+)"[^>]*data-location-city="([^"]+)"'
        r'[^>]*data-location-region="([^"]+)"[^>]*data-location-zipcode="([^"]+)"',
        page,
    ):
        address, city, region, postal = match.groups()
        if city != "San Francisco":
            continue
        locations.append(
            {
                "address": f"{address}, {city}, {region} {postal}",
                "lat": None,
                "lng": None,
                "neighborhood": "San Francisco",
            }
        )
    return locations


def number(value):
    text = str(value).strip().replace(",", "")
    return float(text) if "." in text else int(text)


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def category_for(section):
    section = section.lower()
    if "sauce" in section:
        return "condiment"
    if "dessert" in section:
        return "side"
    if "side" in section:
        return "side"
    if "beverage" in section or "drink" in section:
        return "drink"
    if any(
        word in section
        for word in ("taco", "burrito", "quesadilla", "nacho", "salad", "burger", "breakfast")
    ):
        return "meal"
    return "component"


def parse_nutrition(pdf_bytes):
    items = []
    counts = {}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            table = page.extract_tables()[0]
            section = "Beverages" if page_number == 3 else ""
            for row in table:
                if len(row) < 13:
                    continue
                section_name = str(row[0] or "").replace("\n", " ").strip()
                name = str(row[1] or "").replace("\n", " ").strip()
                serving = str(row[2] or "").replace("\n", " ").strip()
                if section_name:
                    section = section_name
                if not name or not serving or row[3] is None:
                    continue
                # Meal package rows later on page 2 contain calorie ranges but
                # no macros. Keep only rows with the complete labeled columns.
                if any(value is None or not re.fullmatch(r"\s*[\d,.]+\s*", str(value)) for value in row[3:13]):
                    continue
                values = [number(value) for value in row[3:13]]
                base_id = slug(f"{section}-{name}-{serving}")
                counts[base_id] = counts.get(base_id, 0) + 1
                item_id = base_id if counts[base_id] == 1 else f"{base_id}-{counts[base_id]}"
                items.append(
                    {
                        "id": item_id,
                        "name": name,
                        "description": None,
                        "category": category_for(section),
                        "calories": values[0],
                        "protein_g": values[9],
                        "carbs_g": values[6],
                        "fat_g": values[1],
                        "fiber_g": values[7],
                        "sodium_mg": values[5],
                        "serving_note": f"per {serving.lower()}",
                        "is_estimate": False,
                        "source": {"type": "published", "url": PDF_URL},
                    }
                )
    famous = next(item for item in items if item["name"] == "The Del Taco (Crunchy)")
    print(
        "Del Taco spot check — "
        f"{famous['name']}: {famous['calories']} kcal, "
        f"{famous['protein_g']} g protein (published PDF; expected about 300 kcal)"
    )
    return items


def main():
    items = parse_nutrition(get_bytes(PDF_URL))
    locations = get_locations()
    if not locations:
        print("Del Taco official locator reports zero San Francisco locations; skipping.")
        return
    save_restaurant(
        {
            "id": "del-taco",
            "name": "Del Taco",
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
