"""Five Guys USA nutrition scraper.

The current USA guide publishes ingredients/components rather than assembled
burger totals.  This scraper keeps those rows and derives a few canonical
orderable builds from their published components.
"""

import datetime
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

NUTRITION_URL = (
    "https://www.fiveguys.com/wp-content/uploads/2025/07/"
    "five-guys-us-nutrition-allergen-guide-english-1-final.pdf"
)
LOCATIONS_URL = "https://restaurants.fiveguys.com/ca/san-francisco"
TODAY = datetime.date.today().isoformat()
NUTRITION_COLUMNS = {
    "serving": 0,
    "calories": 1,
    "calories_from_fat": 2,
    "fat_g": 3,
    "saturated_fat_g": 4,
    "trans_fat_g": 5,
    "cholesterol_mg": 6,
    "sodium_mg": 7,
    "carbs_g": 8,
    "fiber_g": 9,
    "sugar_g": 10,
    "protein_g": 11,
}


def _number(value):
    if value is None or value == "":
        return 0.0
    return float(str(value).replace("<", ""))


def published_rows():
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("pdfplumber is required to parse the Five Guys PDF") from exc
    request = urllib.request.Request(NUTRITION_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        pdf_bytes = response.read()
    with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
        handle.write(pdf_bytes)
        handle.flush()
        with pdfplumber.open(handle.name) as pdf:
            tables = pdf.pages[0].extract_tables()
            tables += pdf.pages[1].extract_tables()[:1]
    rows = []
    section = "component"
    for table in tables:
        for row in table:
            if not row or not row[0]:
                continue
            label = str(row[0]).strip()
            upper = label.upper()
            if (
                not row[1]
                and (
                    upper in {"MEAT", "BUN", "TOPPINGS", "MILKSHAKES", "OTHER ITEMS"}
                    or upper.startswith(("FRIES", "MIX-INS"))
                )
            ):
                section = upper
                continue
            if len(row) < 13 or not row[1] or not row[2]:
                continue
            try:
                serving = _number(row[NUTRITION_COLUMNS["serving"] + 1])
                calories = _number(row[NUTRITION_COLUMNS["calories"] + 1])
                fat = _number(row[NUTRITION_COLUMNS["fat_g"] + 1])
                sodium = _number(row[NUTRITION_COLUMNS["sodium_mg"] + 1])
                carbs = _number(row[NUTRITION_COLUMNS["carbs_g"] + 1])
                fiber = _number(row[NUTRITION_COLUMNS["fiber_g"] + 1])
                protein = _number(row[NUTRITION_COLUMNS["protein_g"] + 1])
            except (TypeError, ValueError):
                continue
            category = "component"
            if section.startswith("FRIES"):
                category = "side"
            elif section.startswith("MILKSHAKES"):
                category = "drink" if "Shake Base" not in label and "Whipped Cream" not in label else "component"
            elif section.startswith(("TOPPINGS", "MIX-INS")):
                category = "condiment" if any(
                    word in label.lower() for word in ("sauce", "ketchup", "mustard", "mayonnaise", "relish")
                ) else "component"
            elif section.startswith("OTHER") and any(
                word in label.lower() for word in ("sauce", "vinegar", "salt", "butter")
            ):
                category = "condiment"
            rows.append(
                {
                    "label": label,
                    "serving": serving,
                    "calories": calories,
                    "protein_g": protein,
                    "carbs_g": carbs,
                    "fat_g": fat,
                    "fiber_g": fiber,
                    "sodium_mg": sodium,
                    "category": category,
                }
            )
    return rows


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def get_locations():
    # The chain's directory page supplies this coordinate in its directory JSON.
    return [{
        "address": "90 Charter Oak Avenue, San Francisco, CA 94124",
        "lat": 37.736831300629646,
        "lng": -122.40535357668648,
        "neighborhood": None,
    }]


def main():
    rows = published_rows()
    by_label = {row["label"]: row for row in rows}
    items = []
    for row in rows:
        items.append({
            "id": f"published-{slug(row['label'])}",
            "name": row["label"],
            "description": None,
            "category": row["category"],
            "serving_note": f"per {row['serving']:g} g serving",
            "is_estimate": False,
            "source": {"type": "published", "url": NUTRITION_URL},
            **{key: row[key] for key in (
                "calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sodium_mg"
            )},
        })

    def build(name, recipe):
        total = {key: 0 for key in (
            "calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sodium_mg"
        )}
        for label, count in recipe:
            row = by_label[label]
            for key in total:
                total[key] += row[key] * count
        items.append({
            "id": slug(name),
            "name": name,
            "description": "Derived standard build: " + ", ".join(
                f"{count:g} x {label}" for label, count in recipe
            ) + ". Sum of Five Guys published component nutrition.",
            "category": "meal",
            "serving_note": "per standard assembled order",
            "is_estimate": True,
            "source": {"type": "derived", "url": NUTRITION_URL},
            **total,
        })

    build("Little Hamburger", [("Hamburger Patty", 1), ("Bun", 1)])
    build("Hamburger", [("Hamburger Patty", 2), ("Bun", 1)])
    build("Cheeseburger", [("Hamburger Patty", 2), ("Bun", 1), ("Cheese (1 slice) (Supplier S)", 2)])
    build("Bacon Cheeseburger", [
        ("Hamburger Patty", 2), ("Bun", 1),
        ("Cheese (1 slice) (Supplier S)", 2), ("Bacon (2 pieces) (Supplier S)", 1),
    ])
    build("Cheese Dog", [("Hot Dog (Supplier H)", 1), ("Bun", 1), ("Cheese (1 slice) (Supplier S)", 1)])
    build("Vanilla Milkshake", [
        ("Vanilla Shake Base", 1), ("Whipped Cream (Supplier S)", 1),
    ])
    build("Chocolate Milkshake", [
        ("Vanilla Shake Base", 1), ("Whipped Cream (Supplier S)", 1),
        ("Chocolate", 1),
    ])
    build("Oreo Milkshake", [
        ("Vanilla Shake Base", 1), ("Whipped Cream (Supplier S)", 1),
        ("Oreo® Cookie Pieces", 1),
    ])
    for item in items:
        if item["name"].endswith("Milkshake"):
            item["category"] = "drink"
    regular_fries = by_label["Regular Five Guys Style"]
    print(
        "Regular Fries spot-check: "
        f"{regular_fries['calories']:g} kcal, {regular_fries['fat_g']:g} g fat, "
        f"{regular_fries['carbs_g']:g} g carbs, {regular_fries['protein_g']:g} g protein "
        "(official guide: 953 kcal)"
    )
    save_restaurant({
        "id": "five-guys",
        "name": "Five Guys",
        "website": "https://www.fiveguys.com",
        "nutrition_source": {
            "type": "published", "url": NUTRITION_URL, "vendor": None, "retrieved": TODAY
        },
        "locations": get_locations(),
        "items": items,
    })


if __name__ == "__main__":
    main()
