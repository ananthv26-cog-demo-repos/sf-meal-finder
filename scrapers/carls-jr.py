"""Carl's Jr. published nutrition PDF and official SF location.

The current US site exposes a nutrition poster image
(`Nutritional-Poster_4-2-26.jpg`) rather than a machine-readable feed. The
poster was captured through Chrome/CDP, but its raster text is not reliably
extractable here. The usable PDF below is a franchise-hosted mirror of the
US values, retained with that provenance limitation rather than silently
presenting it as a first-party US PDF.
"""

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

NUTRITION_URL = "https://carlsjr.com.my/wp-content/uploads/2023/07/USNutritionValuesCarlsjr.pdf"
LOCATOR_URL = "https://locations.carlsjr.com/ca/san-francisco/1-hallidie-plaza"
TODAY = datetime.date.today().isoformat()
NUM = re.compile(r"^-?\d+(?:\.\d+)?$")


def parse(pdf):
    out = []
    with pdfplumber.open(io.BytesIO(pdf)) as book:
        for page in book.pages:
            for line in (page.extract_text(layout=True) or "").splitlines():
                t = line.split()
                if len(t) < 14 or not all(NUM.fullmatch(x) for x in t[-12:]):
                    continue
                v = [float(x) for x in t[-12:]]
                name = " ".join(t[:-12]).strip()
                if not name or name.lower().startswith(("serving", "calories", "total")):
                    continue
                _serving, cal, _calfat, fat, _sat, _trans, chol, sodium, carbs, fiber, _sugar, protein = v
                name = re.sub(r"\s+[A-Z](?:[,\.\s]+[A-Z])*(?:[,\.\s]*\+)?[,\.\s]*$", "", name).strip(" -")
                low = name.lower()
                if (
                    "hardee" in low
                    or "grits" in low
                    or "green beans" in low
                    or "made from scratch" in low
                    or "pork chop 'n' gravy" in low
                ):
                    continue
                meal_terms = ("burger", "sandwich", "burrito", "omelet", "chicken", "tender", "breakfast", "frisco", "star", "roast beef", "sunrise", "croissant")
                biscuit_meal = "biscuit" in low and any(x in low for x in ("sausage", "egg", "bacon", "chicken", "monster", "omelet", "steak", "ham", "gravy"))
                category = "meal" if any(x in low for x in meal_terms) or biscuit_meal else "side"
                if category in {"side", "condiment"} and cal > 400 and any(
                    x in low for x in ("bowl", "nacho", "quesadilla", "taco salad", "hot ham", "snack", "biscuit 'n' gravy", "hot dog", "8 pc.")
                ):
                    category = "meal"
                if any(x in low for x in ("sauce", "dressing", "gravy")):
                    category = "condiment"
                if any(x in low for x in ("shake", "coffee", "tea", "lemonade", "drink")):
                    category = "drink"
                out.append({
                    "id": re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"),
                    "name": name, "description": None, "category": category,
                    "calories": cal, "protein_g": protein, "carbs_g": carbs,
                    "fat_g": fat, "fiber_g": fiber, "sodium_mg": sodium,
                    "serving_note": f"per {v[0]:g} g serving", "is_estimate": False,
                    "source": {"type": "published", "url": NUTRITION_URL},
                })
    return list({x["id"]: x for x in out}.values())


def main():
    req = urllib.request.Request(NUTRITION_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        pdf = r.read()
    save_restaurant({
        "id": "carls-jr", "name": "Carl's Jr.", "website": "https://www.carlsjr.com/",
        "nutrition_source": {"type": "published", "url": NUTRITION_URL, "vendor": None, "retrieved": TODAY},
        "locations": [{"address": "1 Hallidie Plaza, San Francisco, CA 94102", "lat": 37.78412, "lng": -122.40886, "neighborhood": "Union Square"}],
        "items": parse(pdf),
    })


if __name__ == "__main__":
    main()
