"""Bonchon published nutrition PDF and San Francisco location."""

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

NUTRITION_URL = "https://bonchon-brand.files.svdcdn.com/production/Downloads/Nutrition-Facts_2026.pdf?dm=1771966496"
TODAY = datetime.date.today().isoformat()
NUM = re.compile(r"^-?\d+(?:\.\d+)?$")


def parse(pdf):
    out = []
    with pdfplumber.open(io.BytesIO(pdf)) as book:
        for page in book.pages:
            for table in page.extract_tables():
                unit_kind = "pcs"
                for header in table[:3]:
                    if any("oz" in (cell or "").lower() for cell in header):
                        unit_kind = "oz"
                        break
                for row in table:
                    if len(row) < 13 or not row[0]:
                        continue
                    cells = [(x or "").replace("\n", " ").strip() for x in row]
                    if cells[0].lower() in {"menu item", "flavors"}:
                        continue
                    if not all(NUM.fullmatch(x) for x in cells[1:13]):
                        continue
                    name = re.sub(r"\s+", " ", cells[0]).strip()
                    if not name or name[0].isdigit():
                        continue
                    v = [float(x) for x in cells[1:13]]
                    units, cal, _calfat, fat, _sat, _trans, chol, sodium, carbs, fiber, _sugar, protein = v
                    low = name.lower()
                    addon = low.startswith(("+", "-"))
                    category = "component" if addon else "side"
                    if any(x in low for x in (
                        "wings", "drumsticks", "strips", "boneless", "combo",
                        "bibimbap", "sandwich", "wrap", "taco", "noodle",
                        "udon", "buldak", "bulgogi", "ttekbokki", "japchae",
                        "buns", "popcorn shrimp", "chicken katsu", "potsticker",
                    )):
                        category = "meal"
                    if "sauce" in low:
                        category = "condiment"
                    unit_note = (
                        f"per {units:g} oz serving" if unit_kind == "oz"
                        else f"per {units:g} {'piece' if units == 1 else 'pieces'}"
                    )
                    if unit_kind == "oz" or any(x in low for x in ("salad", "bibimbap", "rice", "soup", "fries", "edamame", "coleslaw")):
                        unit_note = f"per {units:g} oz serving"
                    out.append({
                        "id": re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"),
                        "name": name, "description": None, "category": category,
                        "calories": cal, "protein_g": protein, "carbs_g": carbs,
                        "fat_g": fat, "fiber_g": fiber, "sodium_mg": sodium,
                        "serving_note": unit_note, "is_estimate": False,
                        "source": {"type": "published", "url": NUTRITION_URL},
                    })
    return list({x["id"]: x for x in out}.values())


def main():
    with urllib.request.urlopen(NUTRITION_URL, timeout=60) as r:
        pdf = r.read()
    save_restaurant({
        "id": "bonchon", "name": "Bonchon", "website": "https://www.bonchon.com/",
        "nutrition_source": {"type": "published", "url": NUTRITION_URL, "vendor": None, "retrieved": TODAY},
        "locations": [{"address": "135 4th St, San Francisco, CA 94103", "lat": 37.7842713, "lng": -122.4033021, "neighborhood": "South of Market"}],
        "items": parse(pdf),
    })


if __name__ == "__main__":
    main()
