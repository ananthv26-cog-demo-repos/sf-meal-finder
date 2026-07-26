"""Ono Hawaiian BBQ scraper.

Nutrition: the chain's own printable nutrition PDF. The tables are ruled, so
`extract_tables()` returns clean cells; the header row is *mirrored* text
("seirolaC" = "Calories"), a rotated-header artefact, so column labels are
recovered by reversing the header strings and asserted against the expected
label set before any row is read — never by column position.

Almost every entree row is priced out "( Sides not included )": the published
number covers the protein alone, not the plate. Those rows are therefore
`component`, and the plate/mini meals customers actually order are derived as
sums of the published parts using the builds the menu itself states
("Plate Lunches: Includes 2 scoops of Rice, 1 scoop of our famous Macaroni
Salad and Vegetables"; Mini Meals: 1 scoop of rice, 1 scoop of Macaroni Salad,
and Vegetables) — source "derived", is_estimate=true, recipe in description.
Aloha Plate entrees stay components: the menu says "Includes Rice, Macaroni
Salad & Veggies" without stating the scoop counts, so there is no defensible
build to sum.

TRAPS:
- The Keiki (kids) rows publish calories with 0 fat/carbs/protein. Those are
  left exactly as published and land in data/rejected/ via the macro check
  rather than being patched.
"""

import datetime
import io
import re
import sys
import urllib.request
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

PDF_URL = (
    "https://onohawaiianbbq.com/wp-content/uploads/2025/02/Nutrition-Facts-To-Print_2025.pdf"
)
LOCATOR_URL = (
    "https://onohawaiianbbq.com/wp-admin/admin-ajax.php?action=store_search"
    "&lat=37.7749&lng=-122.4194&max_results=50&search_radius=25&autoload=1"
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
TODAY = datetime.date.today().isoformat()

# Reversed header text -> field. Columns the schema does not carry are mapped
# to None so an unexpected column still trips the assertion below.
HEADER_FIELDS = {
    "Menu Items": None,
    "Calories": "calories",
    "Total Fat (g)": "fat_g",
    "Saturated Fat (g)": None,
    "Trans Fat (g)": None,
    "Sodium (mg)": "sodium_mg",
    "Total Carbohydrates (g)": "carbs_g",
    "Protein (g)": "protein_g",
}

# PDF section -> (category, serving_note). Unknown sections abort.
SECTIONS = {
    "Aloha Plate - Pick One Choice ( Sides not included )":
        ("component", "entree only, Aloha Plate portion, sides not included"),
    "Aloha Plate - Pick Two Choices ( Sides not included )":
        ("component", "entree only, Aloha Plate two-choice portion, sides not included"),
    "Plate Lunches": ("component", "entree only, plate lunch portion, sides not included"),
    "Chicken ( Sides not included )":
        ("component", "entree only, plate lunch portion, sides not included"),
    "Beef / Pork ( Sides not included )":
        ("component", "entree only, plate lunch portion, sides not included"),
    "Seafood ( Sides not included )":
        ("component", "entree only, plate lunch portion, sides not included"),
    "Island Favorites ( Sides not included )":
        ("component", "entree only, plate lunch portion, sides not included"),
    "Mini Meal ( Sides not included )":
        ("component", "entree only, mini meal portion, sides not included"),
    "Family Meal ( Serves 4 People )": ("side", "family portion, serves 4 people"),
    "Gourmet Salad ( Dressing not included )": ("meal", "per salad, dressing not included"),
    "With Protein Choice ( Additional to Fresh Mix Salad Plate )":
        ("component", "protein add-on to the Fresh Mix Salad Plate"),
    "Ono Keiki Meal (Kid’s Meal)\n( with Rice + Veggies + Berry Pouch + Apple Juice Box )":
        ("meal", "kid's meal with rice, veggies, berry pouch and apple juice box"),
    "Appetizers": ("side", "per listed portion"),
    "Sides": ("side", "per listed portion"),
    "Bowls (Sauce not included)": ("meal", "per bowl, sauce not included"),
    "Sauces & Dressing": ("condiment", "per listed portion"),
}

# Sub-headers that repeat a protein name inside the Aloha Plate "Pick Two"
# block; they group rows but carry no serving change of their own.
PICK_TWO_GROUPS = {
    "Hawaiian BBQ Chicken", "Chicken Katsu", "Teriyaki Chicken*", "Grilled Chicken Breast",
    "Island Fire Chicken", "Hawaiian BBQ Beef", "Kalua Pork with Cabbage",
}

# Plate/mini builds the menu states verbatim; keys are the entree sections.
BUILDS = {
    "plate lunch": (
        ("Chicken ( Sides not included )", "Beef / Pork ( Sides not included )",
         "Seafood ( Sides not included )", "Island Favorites ( Sides not included )"),
        "Plate Lunch",
        (("Steamed Rice (1 Scoop)", 2), ("Macaroni Salad (1 Scoop)", 1), ("Cabbage (4 oz.)", 1)),
        "2 scoops of rice, 1 scoop of macaroni salad and vegetables",
    ),
    "mini meal": (
        ("Mini Meal ( Sides not included )",),
        "Mini Meal",
        (("Steamed Rice (1 Scoop)", 1), ("Macaroni Salad (1 Scoop)", 1), ("Cabbage (4 oz.)", 1)),
        "1 scoop of rice, 1 scoop of macaroni salad and vegetables",
    ),
}

NUM_FIELDS = ("calories", "fat_g", "carbs_g", "protein_g", "sodium_mg")


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80]


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(request, timeout=120).read()


def columns(header):
    """Reverse the mirrored header cells into field names, left to right."""
    fields = []
    for cell in header:
        # Only the nutrition columns are mirrored; "Menu Items" reads normally.
        text = re.sub(r"\s+", " ", (cell or "").replace("\n", " ")).strip()
        label = text if text in HEADER_FIELDS else text[::-1].strip()
        if label not in HEADER_FIELDS:
            raise SystemExit(f"ono: unexpected nutrition column {label!r} — PDF layout changed")
        fields.append(HEADER_FIELDS[label])
    if [f for f in fields if f] != ["calories", "fat_g", "sodium_mg", "carbs_g", "protein_g"]:
        raise SystemExit(f"ono: nutrition columns out of expected order: {fields}")
    return fields


def parse_pdf(data):
    """[(section, name, values)] in document order."""
    rows = []
    section = None  # sections run on across table and page breaks
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                fields = columns(table[0])
                for raw in table[1:]:
                    name = re.sub(r"\s+", " ", (raw[0] or "").strip())
                    if not name:
                        continue
                    if all(cell in (None, "") for cell in raw[1:]):
                        key = (raw[0] or "").strip()
                        if key in SECTIONS:
                            section = key
                        elif name not in PICK_TWO_GROUPS:
                            raise SystemExit(f"ono: unmapped section {key!r} — extend SECTIONS")
                        continue
                    if section is None:
                        raise SystemExit(f"ono: row {name!r} before any section header")
                    values = {}
                    for field, cell in zip(fields, raw):
                        if field:
                            values[field] = float(str(cell).replace(",", ""))
                    rows.append((section, name, values))
    if not rows:
        raise SystemExit("ono: no nutrition rows parsed — PDF layout changed")
    return rows


def build_items(rows):
    items, by_key = [], {}
    for section, name, values in rows:
        category, serving = SECTIONS[section]
        item = {
            "id": f"{slug(section)}-{slug(name)}"[:90],
            "name": name,
            "description": None,
            "category": category,
            "fiber_g": None,
            "serving_note": serving,
            "is_estimate": False,
            "source": {"type": "published", "url": PDF_URL},
            **values,
        }
        if item["id"] in by_key:
            continue  # the PDF repeats a few rows verbatim across sections
        by_key[item["id"]] = item
        items.append(item)
    return items, {(s, n): v for s, n, v in rows}


def derive_meals(values_by_key):
    """Sum published parts into the plate/mini meals the menu documents."""
    sides = {name: values for (section, name), values in values_by_key.items()
             if section == "Sides"}
    derived = []
    for sections, label, parts, recipe in BUILDS.values():
        for (section, name), entree in values_by_key.items():
            if section not in sections:
                continue
            total = dict(entree)
            for part_name, count in parts:
                part = sides[part_name]
                for field in NUM_FIELDS:
                    total[field] += count * part[field]
            derived.append({
                "id": f"derived-{slug(label)}-{slug(name)}"[:90],
                "name": f"{name} {label}",
                "description": f"{name} entree plus {recipe}, summed from the published parts.",
                "category": "meal",
                "fiber_g": None,
                "serving_note": f"one {label.lower()} as served",
                "is_estimate": True,
                "source": {"type": "derived", "url": PDF_URL},
                **total,
            })
    return derived


def spot_check(items):
    """Hawaiian BBQ Chicken, the chain's signature plate.

    Its published entree row is 460 kcal and the plate parts are published
    separately, so the derived plate must land on 460 + 2x190 + 300 + 35 = 1175.
    """
    by_id = {item["id"]: item for item in items}
    entree = by_id["chicken-sides-not-included-hawaiian-bbq-chicken"]
    if entree["calories"] != 460:
        raise SystemExit(f"ono: BBQ Chicken entree parsed {entree['calories']}, expected 460")
    plate = by_id["derived-plate-lunch-hawaiian-bbq-chicken"]
    if plate["calories"] != 1175:
        raise SystemExit(f"ono: BBQ Chicken plate summed {plate['calories']}, expected 1175")
    print(f"spot check ok: BBQ Chicken entree 460 kcal, derived plate {plate['calories']} kcal")


def sf_locations():
    stores = __import__("json").loads(fetch(LOCATOR_URL).decode("utf-8"))
    locations = []
    for store in stores:
        if store.get("city", "").strip().lower() != "san francisco":
            continue
        address = " ".join(part for part in (store["address"], store.get("address2")) if part)
        locations.append({
            "address": f"{address}, San Francisco, CA {store['zip']}",
            "lat": float(store["lat"]),
            "lng": float(store["lng"]),
            "neighborhood": None,
        })
    if not locations:
        raise SystemExit("ono: no San Francisco city-proper stores in the locator")
    return locations


def main():
    rows = parse_pdf(fetch(PDF_URL))
    items, values_by_key = build_items(rows)
    items += derive_meals(values_by_key)
    spot_check(items)
    save_restaurant({
        "id": "ono-hawaiian-bbq",
        "name": "Ono Hawaiian BBQ",
        "website": "https://onohawaiianbbq.com/",
        "nutrition_source": {
            "type": "published",
            "url": PDF_URL,
            "vendor": None,
            "retrieved": TODAY,
        },
        "locations": sf_locations(),
        "items": items,
    })


if __name__ == "__main__":
    main()
