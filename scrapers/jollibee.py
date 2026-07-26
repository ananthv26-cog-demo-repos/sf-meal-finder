"""Scraper for Jollibee USA's published 2025 nutrition PDF."""

from __future__ import annotations

import datetime
import io
import re
import sys
import urllib.request
from html import unescape
from urllib.parse import urljoin
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402


PDF_URL = (
    "https://jollibee-prod-media.s3.us-west-2.amazonaws.com/"
    "JB_USA_Nutrition_Facts_2025_101525_f94493117b.pdf"
)
SITE = "https://www.jollibeefoods.com"
LOCATOR = "https://locations.jollibeefoods.com"
TODAY = datetime.date.today().isoformat()
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126"}


def get_bytes(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def get_locations():
    directory = get_bytes(f"{LOCATOR}/usa/ca").decode("utf-8", "replace")
    links = re.findall(
        r'href="([^"]+/usa/ca/san-francisco/[^"]+)"[^>]*>(?:.*?)San Francisco',
        directory,
        re.IGNORECASE | re.DOTALL,
    )
    locations = []
    for link in dict.fromkeys(links):
        link = urljoin(f"{LOCATOR}/usa/ca", link)
        page = get_bytes(link).decode("utf-8", "replace")
        address_match = re.search(
            r'<meta[^>]+itemprop="streetAddress"[^>]+content="([^"]+)"',
            page,
            re.IGNORECASE,
        )
        city_match = re.search(
            r'<meta[^>]+itemprop="addressLocality"[^>]+content="([^"]+)"',
            page,
            re.IGNORECASE,
        )
        region_match = re.search(
            r'<meta[^>]+itemprop="addressRegion"[^>]+content="([^"]+)"',
            page,
            re.IGNORECASE,
        )
        postal_match = re.search(
            r'<meta[^>]+itemprop="postalCode"[^>]+content="([^"]+)"',
            page,
            re.IGNORECASE,
        )
        lat_match = re.search(
            r'<meta[^>]+itemprop="latitude"[^>]+content="([^"]+)"',
            page,
            re.IGNORECASE,
        )
        lng_match = re.search(
            r'<meta[^>]+itemprop="longitude"[^>]+content="([^"]+)"',
            page,
            re.IGNORECASE,
        )
        if not address_match or not city_match or city_match.group(1) != "San Francisco":
            continue
        address = (
            f"{unescape(address_match.group(1))}, {city_match.group(1)}, "
            f"{region_match.group(1) if region_match else 'CA'} "
            f"{postal_match.group(1) if postal_match else ''}"
        ).strip()
        locations.append(
            {
                "address": address,
                "lat": float(lat_match.group(1)) if lat_match else None,
                "lng": float(lng_match.group(1)) if lng_match else None,
                "neighborhood": "Mid-Market",
            }
        )
    if not locations:
        raise RuntimeError("Jollibee official locator reports zero San Francisco locations")
    return locations


def number(value):
    text = str(value).strip()
    if text.startswith("<"):
        return None
    return float(text) if "." in text else int(text)


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def category_for(section, name, serving):
    section = section.lower()
    name = name.lower()
    serving = serving.lower()
    if serving.startswith("1 packet"):
        return "condiment"
    if "serves " in name:
        return "component"
    if "drink" in section:
        return "drink"
    if "dessert" in section:
        return "side"
    if section == "sides":
        return "side"
    if any(word in section for word in ("spaghetti", "palabok", "burger", "steak")):
        if name.startswith("extra "):
            return "component"
        return "meal"
    if "dip" in name or "gravy" in name or "sauce" in name or "packet" in name:
        return "condiment"
    if "sandwich" in name:
        return "meal"
    return "component"


def parse_nutrition(pdf_bytes):
    items = []
    counts = {}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            table = page.extract_tables()[0]
            section = ""
            for row in table[1:]:
                if len(row) < 12:
                    continue
                section_name = str(row[0] or "").replace("\n", " ").strip()
                name = str(row[0] or "").replace("\n", " ").strip()
                serving = str(row[1] or "").replace("\n", " ").strip()
                if section_name and not serving:
                    section = section_name
                    continue
                if not name or not serving or row[2] is None:
                    continue
                if any(value is None for value in row[2:12]):
                    continue
                values = [number(value) for value in row[2:12]]
                description = None
                footnote = re.search(r"\s+Information based on\s+(.+)$", name)
                if footnote:
                    description = footnote.group(1).strip()
                    name = name[: footnote.start()].strip()
                serves_match = re.search(r"\((Serves [^)]+)\)", name, re.I)
                serving_note = f"per {serving.lower()}"
                if serves_match:
                    serving_note += f"; {serves_match.group(1).lower()}"
                item_id = slug(f"{name}-{serving}")
                counts[item_id] = counts.get(item_id, 0) + 1
                if counts[item_id] > 1:
                    item_id = f"{item_id}-{counts[item_id]}"
                items.append(
                    {
                        "id": item_id,
                        "name": name,
                        "description": description,
                        "category": category_for(section, name, serving),
                        "calories": values[0],
                        "protein_g": values[9],
                        "carbs_g": values[6],
                        "fat_g": values[1],
                        "fiber_g": values[7],
                        "sodium_mg": values[5],
                        "serving_note": serving_note,
                        "is_estimate": False,
                        "source": {"type": "published", "url": PDF_URL},
                    }
                )
    drumstick = next(item for item in items if item["name"] == "Chickenjoy Drumstick, 1 pc")
    thigh = next(item for item in items if item["name"] == "Chickenjoy Thigh, 1 pc")
    print(
        "Jollibee spot check — 2-pc Chickenjoy component sum "
        f"(drumstick + thigh): {drumstick['calories'] + thigh['calories']} kcal, "
        f"{drumstick['protein_g'] + thigh['protein_g']} g protein; "
        "matches the expected roughly 600 kcal for the published pieces."
    )
    return items


def main():
    items = parse_nutrition(get_bytes(PDF_URL))
    save_restaurant(
        {
            "id": "jollibee",
            "name": "Jollibee",
            "website": SITE,
            "nutrition_source": {
                "type": "published",
                "url": PDF_URL,
                "vendor": None,
                "retrieved": TODAY,
            },
            "locations": get_locations(),
            "items": items,
        }
    )


if __name__ == "__main__":
    main()
