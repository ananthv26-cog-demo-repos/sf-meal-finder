"""TOGO'S published nutrition PDF and official San Francisco locator."""

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

NUTRITION_URL = "https://togos.com/wp-content/uploads/2024/05/TOGOS-Nutritional-Allergen-Information_April-2024.pdf"
LOCATOR_URL = "https://locations.togos.com/ca/san-francisco/2300-16th-st-ste-275"
TODAY = datetime.date.today().isoformat()
NUM = re.compile(r"^-?\d+(?:\.\d+)?$")


def items(pdf):
    output = []
    with pdfplumber.open(io.BytesIO(pdf)) as book:
        for page in book.pages:
            for line in (page.extract_text(layout=True) or "").splitlines():
                t = line.split()
                if len(t) < 12 or not all(NUM.fullmatch(x) for x in t[-10:]):
                    continue
                vals = [float(x) for x in t[-10:]]
                name = " ".join(t[:-10]).strip()
                if not name or name[0].isdigit() and len(name.split()) < 2:
                    continue
                name = re.sub(r"^\d+\s+", "", name).strip()
                cal, fat, _sat, _trans, chol, sodium, carbs, fiber, sugar, protein = vals
                low = name.lower()
                component = "pepita" in low
                condiment = not component and (any(x in low for x in ("mayo", "mayonnaise", "dressing", "vinaigrette", "sauce")) or (
                    any(x in low for x in ("ranch", "caesar")) and not any(x in low for x in ("salad", "wrap"))
                ))
                entree_salad = "chicken caesar" in low or ("salad" in low and not condiment)
                cat = "component" if component else ("meal" if entree_salad else ("condiment" if condiment else ("meal" if (
                    any(x in low for x in ("sandwich", "melt", "wrap", "salad", "roast beef", "pastrami", "dip", "steak", "turkey", "chicken", "italian", "tuna", "veggie", "ham", "avocado", "bacon", "caprese", "bbq", "meatball", "reuben", "club"))
                    or (name[:1].isdigit() and not any(x in low for x in ("cookie", "chips", "pickle")))
                ) else "side")))
                output.append({
                    "id": re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"),
                    "name": name, "description": None, "category": cat,
                    "calories": cal, "protein_g": protein, "carbs_g": carbs,
                    "fat_g": fat, "fiber_g": fiber, "sodium_mg": sodium,
                    "serving_note": "per listed serving", "is_estimate": False,
                    "source": {"type": "published", "url": NUTRITION_URL},
                })
    return list({x["id"]: x for x in output}.values())


def main():
    req = urllib.request.Request(NUTRITION_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        pdf = r.read()
    save_restaurant({
        "id": "togos", "name": "TOGO'S", "website": "https://togos.com/",
        "nutrition_source": {"type": "published", "url": NUTRITION_URL, "vendor": None, "retrieved": TODAY},
        "locations": [{"address": "2300 16th St, 275, San Francisco, CA 94103", "lat": 37.76646, "lng": -122.40958, "neighborhood": None}],
        "items": items(pdf),
    })


if __name__ == "__main__":
    main()
