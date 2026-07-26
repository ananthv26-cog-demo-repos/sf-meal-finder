"""Scrape Benihana's published U.S. nutrition PDFs and SF location."""

from __future__ import annotations

import datetime
import io
import re
import sys
import urllib.request
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

FOOD_URL = "https://www.benihana.com/wp-content/uploads/2025/02/c114d5a3-benihana-food-nutritional-info-1.2025_d.pdf"
BEVERAGE_URL = "https://www.benihana.com/wp-content/uploads/2025/02/ee8328ff-benihana-beverage-nutritional-info-1.2025_d.pdf"
LOCATOR_URL = "https://www.benihana.com/locations/"
SITE = "https://www.benihana.com"
TODAY = datetime.date.today().isoformat()
HEADERS = {"User-Agent": "sf-meal-finder/1.0 (nutrition scraper)"}

SECTIONS = {
    "APPETIZERS": ("side", "per serving"),
    "SMALL PLATES": ("side", "per serving"),
    "FRIED RICE": ("side", "per serving"),
    "SOUP & SALAD": ("side", "per serving"),
    "SUSHI ENTRÉES": ("meal", "per entrée"),
    "SASHIMI": ("meal", "per serving"),
    "NIGIRI WITH RICE ADDED IN": ("meal", "per serving"),
    "ROLLS": ("meal", "per roll"),
    "SPECIALTY SUSHI": ("meal", "per serving"),
    "NOODLES & TOFU": ("meal", "per entrée"),
    "DESSERTS": ("side", "per serving"),
    "TO GO SAUCES": ("condiment", "per 1 oz"),
    "CHILDRENS MENU FOOD": ("meal", "per item"),
    "ENTRÉES": ("meal", "per entrée"),
    "COMBINATIONS": ("meal", "per combination"),
    "SIDE ORDERS": ("side", "per side order"),
    "PICK UP MENU": ("meal", "per entrée"),
    "ENTRÉE COMPLEMENTS": ("component", "per serving"),
    "5 COURSE ENTRÉE HEADER": ("component", "per serving"),
    "6 COURSE ENTRÉE HEADER": ("component", "per serving"),
    "GROUP MENU HEADER": ("component", "per serving"),
    "LUNCH BOAT HEADER": ("component", "per serving"),
    "POKE BOWL HEADER": ("component", "per serving"),
    "SUSHI ENTRÉES HEADER": ("meal", "per entrée"),
    "CHILDRENS MENU HEADER": ("meal", "per item"),
    "STEAK AND CHICKEN": ("meal", "per entrée"),
    "SEAFOOD": ("meal", "per entrée"),
    "LUNCH ENTREES": ("meal", "per entrée"),
    "LUNCH BOAT (CHOOSE ONE)": ("meal", "per entrée"),
    "POKE BOWL": ("meal", "per bowl"),
}

NUM = r"<?\d+(?:\.\d+)?"
TAIL_RE = re.compile(r"^(.*?)\s+((?:" + NUM + r"\s+){11}" + NUM + r")\s*$")
BEV_TAIL_RE = re.compile(r"^(.*?)\s+((?:" + NUM + r"\s+){10}" + NUM + r")\s*$")


def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()


def number(value):
    value = value.lstrip("<")
    n = float(value)
    return int(n) if n.is_integer() else n


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def classify(name, section, default_category):
    lowered = name.lower()
    if "sauce" in lowered or "dressing" in lowered or "yum yum" in lowered:
        return "condiment"
    if lowered in {"rice", "steamed rice"}:
        return "component" if lowered == "rice" else (
            "side" if section == "SIDE ORDERS" else "component"
        )
    if any(word in lowered for word in ("soup", "salad", "ice cream", "sherbet", "fruit")):
        return "side"
    if "for yakisoba" in lowered or "yakisoba)" in lowered:
        return "component"
    if "nigiri" in lowered or "sashimi" in lowered:
        if "assortment" not in lowered and "combination" not in lowered:
            return "component"
    if section in {"SASHIMI", "NIGIRI WITH RICE ADDED IN"}:
        return "component"
    if section == "SUSHI ENTRÉES" and not (
        "combination" in lowered or "assortment" in lowered
    ):
        return "component"
    if section == "SPECIALTY SUSHI" and name in {
        "Crispy Rice", "Spicy Tuna", "Spicy Yellowtail", "Spicy Salmon"
    }:
        return "component"
    return default_category


def parse_pdf(pdf_bytes, source_url, beverage=False):
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        lines = []
        for page in pdf.pages:
            lines.extend((page.extract_text() or "").splitlines())
    section = None
    items = []
    for raw in lines:
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or line.isdigit() or line.startswith(("Nutritional Information", "Menu Items")):
            continue
        upper = line.upper()
        if upper.startswith("ENTRÉE COMPLEMENTS"):
            section = "ENTRÉE COMPLEMENTS"
            continue
        if upper in SECTIONS:
            section = upper
            continue
        if beverage:
            if upper in {"SAKE", "JAPANESE ARTISANAL SAKE", "PREMIUM COLD SAKE", "CLASSIC COCKTAILS",
                         "WINE", "BOTTLED BEER", "SPECIALTY COCKTAILS", "MOJITOS", "MARGARITAS",
                         "SANGRIAS", "MARTINIS", "PUNCH BOWLS", "ALCOHOL FREE"}:
                section = "BEVERAGE"
                continue
        match = (BEV_TAIL_RE if beverage else TAIL_RE).match(line)
        if not match:
            continue
        name, tail = match.groups()
        values = [number(v) for v in tail.split()]
        if len(values) != (11 if beverage else 12):
            continue
        serving = re.search(r"(\d+(?:\.\d+)?(?:\s*(?:EA|oz|pc|each|serving|roll|pieces?))?)\s*$", name, re.I)
        if serving:
            serving_note = f"per {serving.group(1)}"
            name = name[: serving.start()].strip()
        else:
            serving_note = "per serving"
        if not name or section is None:
            continue
        if beverage:
            category, serving_note = "drink", f"per {serving.group(1) if serving else 'serving'}"
        else:
            category, default_note = SECTIONS[section]
            category = classify(name, section, category)
            serving_note = default_note if not serving else serving_note
        item_id = slug(name) + "-" + slug(serving_note)
        if any(existing["id"] == item_id for existing in items):
            item_id = f"{item_id}-{slug(section)}"
        if any(existing["id"] == item_id for existing in items):
            item_id = f"{item_id}-{len(items)}"
        items.append(
            {
                "id": item_id,
                "name": name,
                "description": None,
                "category": category,
                "calories": values[1],
                "fat_g": values[3],
                "protein_g": values[10] if beverage else values[11],
                "carbs_g": values[7] if beverage else values[8],
                "fiber_g": values[8] if beverage else values[9],
                "sodium_mg": values[6] if beverage else values[7],
                "serving_note": serving_note,
                "is_estimate": False,
                "source": {"type": "published", "url": source_url},
            }
        )
    return items


def spot_check(items):
    item = next(
        (
            i for i in items
            if i["name"] == "Hibachi Chicken"
            and i["calories"] == 280
            and i["protein_g"] == 44
            and i["fat_g"] == 11
        ),
        None,
    )
    if item is None:
        raise ValueError("Benihana Hibachi Chicken spot check failed: expected 280 kcal / 44 g protein / 11 g fat")


def parse_locations(html):
    match = re.search(
        r'"title":"San Francisco".*?"latitude":"([^"]+)".*?"longitude":"([^"]+)".*?'
        r'"address_html":"<p>(.*?)<\\/p>',
        html,
        re.DOTALL,
    )
    if not match:
        raise ValueError("No San Francisco Benihana location in official locator")
    lat, lng, address = match.groups()
    address = re.sub(r"<br ?/?>", ", ", address)
    address = re.sub(r"\\n|\s+", " ", address).strip(" ,")
    return [{"address": address, "lat": float(lat), "lng": float(lng), "neighborhood": "Japantown"}]


def main():
    items = parse_pdf(get(FOOD_URL), FOOD_URL) + parse_pdf(get(BEVERAGE_URL), BEVERAGE_URL, beverage=True)
    spot_check(items)
    save_restaurant(
        {
            "id": "benihana",
            "name": "Benihana",
            "website": SITE,
            "nutrition_source": {"type": "published", "url": FOOD_URL, "vendor": None, "retrieved": TODAY},
            "locations": parse_locations(get(LOCATOR_URL).decode("utf-8")),
            "items": items,
        }
    )


if __name__ == "__main__":
    main()
