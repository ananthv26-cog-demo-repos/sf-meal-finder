"""Philz Coffee scraper.

Nutrition comes from the PDFs linked off https://philzcoffee.com/menu, one per
cup size plus a limited-time-offer sheet:

    https://cdn.philz.us/nutritional-info/drinks/12-oz.pdf
    https://cdn.philz.us/nutritional-info/drinks/16-oz.pdf
    https://cdn.philz.us/nutritional-info/drinks/20-oz.pdf
    https://cdn.philz.us/nutritional-info/drinks/Limited-Time-Offerings.pdf

Every row is a beverage, so every item is category "drink"; the row is per cup
of the sheet's size (LTO rows carry their own size in the product name).

TRAPS:
  - The menu page also links `nutritional-info//hot-foods.pdf` and
    `nutritional-info//pastries.pdf` (note the double slash). Both 404 on the
    CDN with and without the doubled slash, so Philz currently publishes no
    food nutrition at all — drinks only.
  - Several rows publish RANGES ("330-400" cal, "21-23" g fat) because the
    build varies by store. Those are saved as midpoints with source type
    "derived" + is_estimate=True rather than silently picking an endpoint.
  - "<1" appears in fiber/protein cells; it is 0.5, not 0 and not 1.
  - The 16-oz sheet repeats the LTO table, so items are de-duplicated by id.
  - Locations: the /locations page embeds the whole chain as JSON with
    chain-provided lat/lng. Filter on `city`, not `region` — the region field
    says "San Francisco" for Colma and other Mid-Peninsula stores.
"""

from __future__ import annotations

import datetime
import html
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

TODAY = datetime.date.today().isoformat()
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
BASE = "https://cdn.philz.us/nutritional-info/drinks"
MENU_URL = "https://philzcoffee.com/menu"
LOCATIONS_URL = "https://philzcoffee.com/locations"
PDFS = [
    (f"{BASE}/12-oz.pdf", 12),
    (f"{BASE}/16-oz.pdf", 16),
    (f"{BASE}/20-oz.pdf", 20),
    (f"{BASE}/Limited-Time-Offerings.pdf", None),  # size is in each product name
]

# Column order asserted against the header row of every table.
COLUMNS = [
    "CALORIES",
    "TOTAL FAT (g)",
    "SATURATED FAT (g)",
    "TRANS FAT (g)",
    "CHOLESTEROL (mg)",
    "SODIUM (mg)",
    "TOTAL CARBOHYDRATES (g)",
    "DIETARY FIBER (g)",
    "SUGARS (g)",
    "PROTEIN (g)",
]
NUMERIC = re.compile(r"^<?\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?$")
SIZE_IN_NAME = re.compile(r"\b(\d{2})\s*oz\b", re.I)


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=60).read()


def parse_value(token: str):
    """Return (value, is_range). '<1' -> 0.5; '290-310' -> midpoint."""
    token = token.strip()
    if token.startswith("<"):
        return float(token[1:]) / 2, False
    if "-" in token:
        low, high = (float(x) for x in token.split("-", 1))
        return round((low + high) / 2, 1), True
    return float(token), False


def split_row(text: str):
    """Split a collapsed table cell into (name, [10 value tokens]).

    Rows arrive either as one line ("Mint Mojito (sweet & creamy) 330 27 ...")
    or with the numbers on their own line between two name fragments. Values
    are taken as the trailing run of exactly ten numeric tokens on one line.
    """
    name_parts, values = [], None
    for line in text.split("\n"):
        tokens = line.split()
        if not tokens:
            continue
        run = []
        while tokens and NUMERIC.match(tokens[-1]) and len(run) < len(COLUMNS):
            run.insert(0, tokens.pop())
        if len(run) == len(COLUMNS) and values is None:
            values = run
            if tokens:
                name_parts.append(" ".join(tokens))
        else:
            name_parts.append(line.strip())
    if values is None:
        return None, None
    return " ".join(p for p in name_parts if p).strip(), values


def header_columns(row):
    cells = [re.sub(r"\s+", " ", c).strip() for c in row if c]
    return cells[1:] if len(cells) == len(COLUMNS) + 1 else None


def slug(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def parse_pdf(url: str, size: int | None):
    items = []
    with pdfplumber.open(io.BytesIO(fetch(url))) as pdf:
        section = None
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    cells = [c for c in row if c]
                    if not cells:
                        continue
                    columns = header_columns(row)
                    if columns:
                        if columns != COLUMNS:
                            raise SystemExit(f"{url}: unexpected columns {columns}")
                        section = re.sub(r"\s+", " ", cells[0]).strip()
                        continue
                    name, values = split_row("\n".join(cells))
                    if not name or not section:
                        continue
                    parsed = [parse_value(v) for v in values]
                    numbers = dict(zip(COLUMNS, (v for v, _ in parsed)))
                    ranged = any(is_range for _, is_range in parsed)

                    row_size = size
                    if row_size is None:
                        match = SIZE_IN_NAME.search(name)
                        if not match:
                            raise SystemExit(f"{url}: no cup size in row {name!r}")
                        row_size = int(match.group(1))
                    name = SIZE_IN_NAME.sub("", name).replace("  ", " ").strip(" ,-")

                    description = section.title()
                    source = {"type": "published", "url": url}
                    if ranged:
                        description += (
                            f" — Philz publishes a per-store range for this drink; "
                            f"midpoint of the published range used"
                        )
                        source = {"type": "derived", "url": url}
                    items.append({
                        "id": f"{slug(name)}-{row_size}oz",
                        "name": f"{name} ({row_size} oz)",
                        "description": description,
                        "category": "drink",
                        "calories": numbers["CALORIES"],
                        "protein_g": numbers["PROTEIN (g)"],
                        "carbs_g": numbers["TOTAL CARBOHYDRATES (g)"],
                        "fat_g": numbers["TOTAL FAT (g)"],
                        "fiber_g": numbers["DIETARY FIBER (g)"],
                        "sodium_mg": numbers["SODIUM (mg)"],
                        "serving_note": f"per {row_size} oz cup, standard build",
                        "is_estimate": ranged,
                        "source": source,
                    })
    return items


def sf_locations():
    page = fetch(LOCATIONS_URL).decode("utf-8", "replace")
    blobs = re.findall(r'"(\[\{&quot;id&quot;.*?\}\])"', page, re.S)
    if not blobs:
        raise SystemExit("philz: embedded store JSON not found on /locations")
    stores = json.loads(html.unescape(max(blobs, key=len)))
    locations = []
    for store in stores:
        if (store.get("city") or "").strip() != "San Francisco":
            continue
        if (store.get("state") or "").strip() != "CA":
            continue
        if all(day["is_closed"] for day in store.get("hours") or [{"is_closed": True}]):
            continue  # listed but not trading
        locations.append({
            "address": store["address"],
            "lat": float(store["latitude"]),
            "lng": float(store["longitude"]),
            "neighborhood": store["name"],
        })
    if not locations:
        raise SystemExit("philz: no San Francisco city-proper stores in the locator")
    return locations


def spot_check(items):
    """Hot or Iced Coffee (sweet & creamy), 12 oz: 330 cal / 27 f / 21 c / 2 p."""
    by_id = {i["id"]: i for i in items}
    got = by_id.get("hot-or-iced-coffee-sweet-creamy-12oz")
    want = {"calories": 330, "fat_g": 27, "carbs_g": 21, "protein_g": 2}
    if not got or any(got[k] != v for k, v in want.items()):
        raise SystemExit(f"philz: spot check failed — {got}")
    print("spot check ok:", got["name"], want)


def main():
    items, seen = [], set()
    for url, size in PDFS:
        for item in parse_pdf(url, size):
            if item["id"] in seen:
                continue  # LTO table is repeated on the 16-oz sheet
            seen.add(item["id"])
            items.append(item)
    spot_check(items)
    save_restaurant({
        "id": "philz-coffee",
        "name": "Philz Coffee",
        "website": "https://philzcoffee.com",
        "nutrition_source": {
            "type": "published",
            "url": f"{BASE}/12-oz.pdf",
            "vendor": None,
            "retrieved": TODAY,
        },
        "locations": sf_locations(),
        "items": items,
    })


if __name__ == "__main__":
    main()
