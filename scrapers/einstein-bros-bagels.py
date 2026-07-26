"""Scraper for Einstein Bros. Bagels' published 2026 nutrition guide."""

from __future__ import annotations

import datetime
import io
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402


PDF_URL = (
    "https://www.einsteinbros.com/wp-content/uploads/2026/02/"
    "Einstein-Bros-Bagels-Nutrition-Guide-2026.pdf"
)
SITE = "https://www.einsteinbros.com"
TODAY = datetime.date.today().isoformat()
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126"}


def get_bytes(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def get_locations():
    filters = json.dumps(
        {
            "builtin.location": {
                "$near": {
                    "lat": 37.779238,
                    "lng": -122.419359,
                    "radius": 40233.6,
                    "name": "San Francisco, California, United States",
                }
            }
        },
        separators=(",", ":"),
    )
    params = {
        "experienceKey": "einstein-locator",
        "api_key": "44c9a6842a084a6e10e87282bea305bb",
        "v": "20220511",
        "version": "PRODUCTION",
        "locale": "en",
        "input": "",
        "verticalKey": "locations",
        "filters": filters,
        "offset": "0",
        "retrieveFacets": "true",
        "skipSpellCheck": "false",
        "sessionTrackingEnabled": "true",
        "sortBys": "[]",
        "source": "STANDARD",
    }
    url = (
        "https://prod-cdn.us.yextapis.com/v2/accounts/me/search/vertical/query?"
        + urllib.parse.urlencode(params)
    )
    payload = json.loads(get_bytes(url))
    results = payload.get("response", {}).get("allResultsForVertical", {}).get("results", [])
    locations = []
    for result in results:
        data = result.get("data", {})
        address = data.get("address", {})
        if address.get("city") != "San Francisco":
            continue
        coordinate = data.get("geocodedCoordinate", {})
        locations.append(
            {
                "address": ", ".join(
                    part
                    for part in (
                        address.get("line1"),
                        address.get("city"),
                        address.get("region"),
                        address.get("postalCode"),
                    )
                    if part
                ),
                "lat": coordinate.get("latitude"),
                "lng": coordinate.get("longitude"),
                "neighborhood": "San Francisco",
            }
        )
    return locations


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def number(value):
    if value is None or str(value).strip() == "":
        return None
    return float(value) if "." in str(value) else int(value)


def clean_name(value):
    return re.sub(r"\s+", " ", str(value or "").replace("*", "").replace("^", "")).strip()


def category_for(section, name):
    section = section.lower()
    name = name.lower()
    if "sandwich" in name or "burrito" in name or "wrap" in name:
        return "meal"
    if any(
        word in name
        for word in ("iced", "latte", "coffee", "tea", "lemonade", "smoothie", "hot chocolate")
    ):
        return "drink"
    if "beverage" in section or any(
        word in section for word in ("coffee", "tea", "lemonade", "smooth", "cold brew")
    ):
        return "drink"
    if any(word in section for word in ("sandwich", "burrito")):
        return "meal"
    if "sides" in section or "sweets" in section or "avocado toast" in section:
        return "side"
    if "cream cheese" in section or "spread" in section or "topping" in section:
        return "condiment"
    if any(word in section for word in ("sauce", "salsa", "mayo", "mustard")):
        return "condiment"
    if any(
        word in section
        for word in (
            "egg",
            "cheese",
            "meat",
            "protein",
            "toppings",
            "vegetable",
            "veggie",
            "produce",
        )
    ):
        return "component"
    if "topping" in name or "cream cheese" in name or "shmear" in name:
        return "condiment"
    if (
        "bagel" in name
        or "bagel" in section
        or "bread" in section
        or "bread" in name
        or "roll" in name
        or "thin" in section
    ):
        return "component"
    if "cookie" in name or "pastry" in name or "muffin" in name or "sweet" in section:
        return "side"
    raise ValueError(f"Unmapped Einstein section/item: {section!r} / {name!r}")


def parse_nutrition(pdf_bytes):
    items = []
    current_section = ""
    counts = {}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            table = page.extract_tables()[0]
            for row in table[2:]:
                if not row or not row[0]:
                    continue
                raw_name = str(row[0]).replace("\n", " ").strip()
                if row[1] is None or row[3] is None:
                    current_section = raw_name
                    continue
                # The first 15 columns are the labeled nutrition table:
                # name, serving, weight, calories, fat, sat fat, trans fat,
                # cholesterol, sodium, carbs, fiber, sugars, added sugar,
                # protein, caffeine. Allergen columns begin after column 15.
                if len(row) < 15:
                    raise ValueError(f"Unexpected Einstein row width: {row!r}")
                name = clean_name(raw_name)
                serving = str(row[1]).strip()
                category = category_for(current_section, name)
                context = clean_name(current_section)
                qualified_name = f"{name} — {context}"
                name_key = qualified_name.lower()
                counts[name_key] = counts.get(name_key, 0) + 1
                if counts[name_key] > 1:
                    qualified_name = f"{qualified_name} ({serving.lower()})"
                item_id = slug(qualified_name)
                items.append(
                    {
                        "id": item_id,
                        "name": qualified_name,
                        "description": None,
                        "category": category,
                        "calories": number(row[3]),
                        "protein_g": number(row[13]),
                        "carbs_g": number(row[9]),
                        "fat_g": number(row[4]),
                        "fiber_g": number(row[10]),
                        "sodium_mg": number(row[8]),
                        "serving_note": f"per {serving.lower()}",
                        "is_estimate": False,
                        "source": {"type": "published", "url": PDF_URL},
                    }
                )
    famous = next(item for item in items if item["name"].startswith("Plain — "))
    print(
        "Einstein spot check — Plain bagel: "
        f"{famous['calories']} kcal, {famous['protein_g']} g protein "
        "(published guide; expected about 270–290 kcal)"
    )
    return items


def main():
    items = parse_nutrition(get_bytes(PDF_URL))
    locations = get_locations()
    if not locations:
        print("Einstein Bros. official locator reports zero San Francisco locations; skipping.")
        return
    save_restaurant(
        {
            "id": "einstein-bros-bagels",
            "name": "Einstein Bros. Bagels",
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
