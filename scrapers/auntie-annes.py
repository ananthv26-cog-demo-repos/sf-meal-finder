"""Scraper for Auntie Anne's published nutrition guide."""

from __future__ import annotations

import datetime
import io
import json
import re
import sys
import urllib.request
import uuid
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402


PDF_URL = (
    "https://assets.ctfassets.net/zqt8tllj2cy0/2jjVNaTNGDoMGd4QVucpSy/"
    "3c4afc16510a8a90368d67559422025e/Auntie-Annes-Nutrition-Guide.pdf"
)
SITE = "https://www.auntieannes.com"
TODAY = datetime.date.today().isoformat()
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126"}


def get_bytes(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def get_locations():
    url = (
        "https://apiprd.auntieannes.com/prod/v1/location/nearby"
        "?lat=37.7749295&long=-122.4194155&handoff=PickUp&limit=100"
    )
    headers = {
        **HEADERS,
        "accept": "application/json",
        "x-focus-app": "web",
        "x-focus-app-v": "v1",
        "x-focus-brand": "auntieannes",
        "x-focus-session-id": str(uuid.uuid4()),
        "x-focus-app-deviceid": str(uuid.uuid4()),
    }
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read())
    locations = []
    for record in payload.get("data", []):
        if record.get("city") != "San Francisco":
            continue
        coords = record.get("geoCoordinates") or {}
        locations.append(
            {
                "address": (
                    f"{record['address']}, San Francisco, {record['state']} "
                    f"{record['zipCode']}"
                ),
                "lat": coords.get("latitude"),
                "lng": coords.get("longitude"),
                "neighborhood": "Union Square",
            }
        )
    return locations


def number(value):
    return float(value) if "." in str(value) else int(value)


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def category_for(title, name):
    title = title.lower()
    name = name.lower()
    if "dip" in title:
        return "condiment"
    if "breakfast" in title or "sandwich" in name:
        return "meal"
    if "pretzel dog" in name:
        return "meal"
    if any(word in title for word in ("lemonade", "spritz", "smooth", "fountain")):
        return "drink"
    if "pretzel" in title or "nugget" in title:
        return "side"
    raise ValueError(f"Unmapped Auntie Anne's section/item: {title!r} / {name!r}")


def parse_nutrition(pdf_bytes):
    items = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        # The guide's headers are rotated 90 degrees. pdfplumber therefore
        # exposes the first three labeled columns and the ten macro columns
        # as separate tables; join rows by their shared y-position/order.
        for page in pdf.pages[1:6]:
            tables = page.extract_tables()
            for index in range(0, len(tables), 2):
                labels, macros = tables[index], tables[index + 1]
                title = str(labels[0][0] or "").replace("\n", " ").strip()
                previous_name = None
                for label_row, macro_row in zip(labels[1:], macros[1:]):
                    if len(label_row) < 3 or len(macro_row) < 10:
                        raise ValueError("Unexpected Auntie Anne's table row shape")
                    raw_name = str(label_row[0] or "").replace("\n", " ").strip()
                    if raw_name:
                        previous_name = raw_name
                    if not previous_name or label_row[2] is None:
                        continue
                    name = previous_name
                    serving = str(label_row[1]).strip()
                    item_name = f"{name} — {title} ({serving})"
                    values = [number(value) for value in macro_row[:10]]
                    items.append(
                        {
                            "id": slug(f"{title}-{item_name}"),
                            "name": item_name,
                            "description": None,
                            "category": category_for(title, name),
                            "calories": number(label_row[2]),
                            "protein_g": values[9],
                            "carbs_g": values[5],
                            "fat_g": values[0],
                            "fiber_g": values[6],
                            "sodium_mg": values[4],
                            "serving_note": f"per {serving.lower()}",
                            "is_estimate": False,
                            "source": {"type": "published", "url": PDF_URL},
                        }
                    )
    famous = next(item for item in items if item["name"].startswith("Original Pretzel"))
    print(
        "Auntie Anne's spot check — "
        f"{famous['name']}: {famous['calories']} kcal, "
        f"{famous['protein_g']} g protein (published guide; expected about 340 kcal)"
    )
    return items


def main():
    items = parse_nutrition(get_bytes(PDF_URL))
    locations = get_locations()
    if not locations:
        print("Auntie Anne's official locator reports zero San Francisco locations; skipping.")
        return
    save_restaurant(
        {
            "id": "auntie-annes",
            "name": "Auntie Anne's",
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
