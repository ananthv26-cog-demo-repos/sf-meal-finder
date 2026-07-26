"""Scraper for Sarku Japan's published nutrition tables."""

from __future__ import annotations

import datetime
import json
import re
import sys
import urllib.request
from pathlib import Path

from lxml import html

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402


NUTRITION_URL = "https://www.sarkujapan.com/nutrition/"
SITE = "https://www.sarkujapan.com"
TODAY = datetime.date.today().isoformat()
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126"}


def get_bytes(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def get_locations():
    url = "https://www.sarkujapan.com/core/views/sarku/json/map.json"
    records = json.loads(get_bytes(url))
    locations = []
    for record in records:
        address = re.sub(r"<[^>]+>", " ", record.get("address", ""))
        address = " ".join(address.split())
        if "San Francisco" not in address:
            continue
        locations.append(
            {
                "address": address,
                "lat": record.get("dataLat"),
                "lng": record.get("dataLng"),
                "neighborhood": "Union Square",
            }
        )
    return locations


def text(node):
    return " ".join(node.text_content().split())


def number(value):
    value = str(value).strip().replace(",", ".")
    if value.startswith("<"):
        return None
    return float(value) if "." in value else int(value)


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def category_for(section, name):
    section = section.lower()
    if "beverage" in section:
        return "drink"
    if "side" in section or "individual sushi" in section:
        return "side"
    if any(word in section for word in ("meal", "bento", "roll", "combo", "tray")):
        return "meal"
    return "component"


def parse_nutrition(page_bytes):
    document = html.fromstring(page_bytes)
    items = []
    counts = {}
    for table in document.xpath("//table"):
        header = table.xpath(".//th")[0]
        section = text(header)
        base_name = None
        for row in table.xpath(".//tr")[1:]:
            cells = row.xpath("./th|./td")
            if len(cells) != 12:
                continue
            name = text(cells[0])
            if not name:
                continue
            if name.lower().startswith(("with ", "(")) or name.lower() == "entire tray":
                if not base_name:
                    continue
                item_name = f"{base_name} {name}"
            else:
                base_name = name
                item_name = name
            values = [text(cell) for cell in cells[1:]]
            # The page uses comma decimals in some cells (for example 3,5).
            macros = [number(value) for value in values]
            base_id = slug(f"{section}-{item_name}")
            counts[base_id] = counts.get(base_id, 0) + 1
            item_id = base_id if counts[base_id] == 1 else f"{base_id}-{counts[base_id]}"
            items.append(
                {
                    "id": item_id,
                    "name": item_name,
                    "description": None,
                    "category": category_for(section, item_name),
                    "calories": macros[0],
                    "protein_g": macros[10],
                    "carbs_g": macros[7],
                    "fat_g": macros[2],
                    "fiber_g": macros[8],
                    "sodium_mg": macros[6],
                    "serving_note": "per listed menu serving",
                    "is_estimate": False,
                    "source": {"type": "published", "url": NUTRITION_URL},
                }
            )
    famous = next(item for item in items if item["name"] == "Chicken Teriyaki with Steamed White Rice")
    print(
        "Sarku Japan spot check — "
        f"{famous['name']}: {famous['calories']} kcal, "
        f"{famous['protein_g']} g protein"
    )
    return items


def main():
    items = parse_nutrition(get_bytes(NUTRITION_URL))
    locations = get_locations()
    if not locations:
        print("Sarku Japan official locator reports zero San Francisco locations; skipping.")
        return
    save_restaurant(
        {
            "id": "sarku-japan",
            "name": "Sarku Japan",
            "website": SITE,
            "nutrition_source": {
                "type": "published",
                "url": NUTRITION_URL,
                "vendor": None,
                "retrieved": TODAY,
            },
            "locations": locations,
            "items": items,
        }
    )


if __name__ == "__main__":
    main()
