"""Scraper for Wetzel's Pretzels' published nutrition information."""

from __future__ import annotations

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


PDF_URL = "https://www.wetzels.com/assets/pdf/Nutrition-Info.pdf"
SITE = "https://www.wetzels.com"
TODAY = datetime.date.today().isoformat()
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126"}


def get_bytes(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def normalize_address(address):
    address = " ".join(address.replace(", USA", "").split())
    match = re.match(
        r"^(.*?)(?:,\s*|\s+)(San Francisco),\s*(CA)\s+(\d{5})$",
        address,
        re.IGNORECASE,
    )
    if not match:
        return address
    street, city, region, postal = match.groups()
    street = re.sub(
        r"\s+space\s+([A-Za-z0-9-]+)",
        lambda m: f", Space {m.group(1).upper()}",
        street,
        flags=re.IGNORECASE,
    )
    street = re.sub(r"(?<![,])\s+(#\w+)$", r", \1", street)
    return f"{street}, {city.title()}, {region.upper()} {postal}"


def get_locations():
    url = (
        "https://storemapper-herokuapp-com.global.ssl.fastly.net/"
        "api/users/13346/stores.js?callback=SMcallback2"
    )
    payload = get_bytes(url).decode("utf-8", "replace")
    records = json.loads(payload[payload.find("(") + 1 : payload.rfind(")")])
    locations = []
    for record in records.get("stores", []):
        address = record.get("address", "")
        if not re.search(r"\bSan Francisco\b", address, re.IGNORECASE):
            continue
        locations.append(
            {
                "address": normalize_address(address),
                "lat": record.get("latitude"),
                "lng": record.get("longitude"),
                "neighborhood": "San Francisco",
            }
        )
    return locations


def number(value):
    text = re.sub(r"\s+", "", str(value))
    return float(text) if "." in text else int(text)


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def category_for(section, name):
    section = section.lower()
    name = name.lower()
    if "dip" in section:
        return "condiment"
    if "beverage" in section:
        return "drink"
    if "dog" in name and "bite" not in name:
        return "meal"
    if section in {"pretzels", "bitz", "loaded bitz", "dogs & bites", "stickz", "twistz"}:
        return "side"
    raise ValueError(f"Unmapped Wetzel's section/item: {section!r} / {name!r}")


def parse_nutrition(pdf_bytes):
    items = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            table = page.extract_tables()[0]
            section = ""
            for row in table[1:]:
                if not row or not row[0]:
                    continue
                name = str(row[0]).replace("\n", " ").strip()
                if row[2] is None:
                    section = name
                    continue
                if len(row) < 14 or any(value is None for value in row[3:14]):
                    raise ValueError(f"Unexpected Wetzel's row: {row!r}")
                values = [number(value) for value in row[3:14]]
                serving = str(row[2]).strip()
                items.append(
                    {
                        "id": slug(f"{name}-{serving}"),
                        "name": f"{name} ({serving})",
                        "description": None,
                        "category": category_for(section, name),
                        "calories": values[0],
                        "protein_g": values[10],
                        "carbs_g": values[6],
                        "fat_g": values[1],
                        "fiber_g": values[7],
                        "sodium_mg": values[5],
                        "serving_note": f"per {serving.lower()}",
                        "is_estimate": False,
                        "source": {"type": "published", "url": PDF_URL},
                    }
                )
    famous = next(item for item in items if item["name"].startswith("Original Pretzel (with butter, salted)"))
    print(
        "Wetzel's spot check — "
        f"{famous['name']}: {famous['calories']} kcal, "
        f"{famous['protein_g']} g protein (published guide; expected about 360 kcal)"
    )
    return items


def main():
    items = parse_nutrition(get_bytes(PDF_URL))
    locations = get_locations()
    if not locations:
        print("Wetzel's official locator reports zero San Francisco locations; skipping.")
        return
    save_restaurant(
        {
            "id": "wetzels-pretzels",
            "name": "Wetzel's Pretzels",
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
