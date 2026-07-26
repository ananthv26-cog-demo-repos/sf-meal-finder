"""Nick The Greek nutrition and San Francisco location scraper.

Nick The Greek's nutrition page (https://www.nickthegreek.com/nutrition-calculator/)
is an iframe around a vendor-built calculator hosted on Heroku.  That Heroku
document is server-rendered: every ingredient row and its macro cells are in
the HTML, so it can be fetched directly.  Columns are read from each screen's
own labeled header row ("Calories (kcal)", "Protein (g)", ...) rather than by
position.

Like Chipotle, the vendor publishes per-INGREDIENT numbers, not meals: the
calculator expects the user to add a protein to a base.  Ingredients are
therefore saved as components (sauces/dressings as condiments, the sides and
desserts screens as sides), and canonical builds — gyro pitas, bowls, plates
and entree salads, each with one protein — are derived as sums with
``source: derived`` and ``is_estimate: True``, recipe recorded in the
description.

Locations come from the official ordering backend behind
https://nickthegreek.orderexperience.net/locations (the marketing site's
JSON-LD store list is incomplete and omits the Metreon store); it carries
chain-provided coordinates, so no geocoding is needed.
"""

from __future__ import annotations

import datetime
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

CALCULATOR_PAGE = "https://www.nickthegreek.com/nutrition-calculator/"
NUTRITION_URL = "https://nutri-nickthegreek-78ba31db005e.herokuapp.com/"
LOCATIONS_URL = (
    "https://oxb.pxsweb.com/api/v1/apps/restaurants/65f468d3d61dfa2995026192"
    "?key=49ace91d8c17daf4d13e61c05883ff3edbd02d1b"
)
CROSS_CHECK_URL = "https://foods.fatsecret.com/calories-nutrition/nick-the-greek"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/133 Safari/537.36"}
TODAY = datetime.date.today().isoformat()

# Calculator column label -> our field name.  Unlisted columns are ignored.
FIELD_LABELS = {
    "Calories (kcal)": "calories",
    "Total Fat (g)": "fat_g",
    "Sodium (mg)": "sodium_mg",
    "Carbs (g)": "carbs_g",
    "Dietary Fiber (g)": "fiber_g",
    "Protein (g)": "protein_g",
}
MACROS = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sodium_mg")
REQUIRED = ("calories", "protein_g", "carbs_g", "fat_g")

CONDIMENT_WORDS = (
    "sauce", "tzatziki", "yogurt", "vinaigrette", "dressing", "hummus", "toum",
    "harissa", "chimichurri", "paprika", "mustard",
)
SIDE_SCREENS = {"sides", "desserts"}

# Canonical builds: (id, display name, screen, [component names], note).
# Each is one protein plus the base its screen publishes; alternates the
# calculator offers as either/or choices (a second sauce, fries instead of
# rice) are left out and named in the description.
PITA_BASE = ["Pita Bread", "Tomatos (Sliced)", "Red Onions", "Romaine Lettuce", "Tzatziki Sauce"]
PITA_PROTEINS = [
    "Beef/Lamb Gyro", "Chicken Gyro", "Pork Gyro", "Beefteki", "Burger",
    "Steak Souvlaki", "Chicken Souvlaki", "Falafel", "Veggies",
]
MED_BOWL_BASE = [
    "Rice", "Kale", "Grape Tomatoes", "Persian Cucumber", "Fried Chickpeas",
    "Pickled Onions", "Red Wine Vinaigrette",
]
GYRO_BOWL_BASE = [
    "Rice", "Romaine Lettuce", "Red Onions", "Feta Cheese", "Persian Cucumbers",
    "Grape Tomatoes", "Red Wine Vinaigrette", "Tzatziki",
]
BOWL_PROTEINS = [
    "Beef/Lamb Gyro", "Chicken Gyro", "Pork Gyro", "Chicken Souvlaki (2 Skewers)",
    "Steak Souvlaki (1 Skewer)", "Beefteki", "Falafel (5 Pcs)", "Veggies",
]
PLATE_BASE = ["Tomatoes (Sliced)", "Tzatziki", "Red Onions", "Pita", "Rice"]
PLATE_PROTEINS = [
    "Beef/Lamb Gyro", "Chicken Gyro", "Pork Gyro", "Falafel",
    "Steak Souvlaki (2)", "Chicken Souvlaki (2)",
]
SALADS = ["Greek Salad", "Prasini Salad", "Tahini Crunch Salad", "Chopped Salad"]
SALAD_PROTEINS = [
    "Beef/Lamb Gyro", "Chicken Gyro", "Pork Gyro", "Chicken Souvlaki",
    "Steak Souvlaki", "Falafel",
]


def fetch(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def clean(text):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text))).strip()


def slug(text):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def number(text):
    """Parse one calculator cell, or None when the vendor published nothing.

    A handful of cells carry typos from data entry: a comma decimal separator
    ("2,58") or a doubled decimal point (".0.60"). Empty cells are left as None
    rather than zero — several rows ship with an entirely blank nutrition row,
    and zeroing those would publish invented numbers.
    """
    text = clean(text).replace(",", ".")
    match = re.search(r"\d*\.\d+$|\d+$", text)
    return float(match.group(0)) if match else None


def parse_calculator(page):
    """Return {screen: [(category_title, item_name, {field: value}), ...]}.

    Each screen carries its own labeled header row; that header defines the
    order of the numeric cells for every row in the screen.
    """
    screens = {}
    boundaries = [m for m in re.finditer(r'data-label="([^"]+)" class="screen"', page)]
    for index, match in enumerate(boundaries):
        start = match.end()
        end = boundaries[index + 1].start() if index + 1 < len(boundaries) else len(page)
        block = page[start:end]

        # The header's name cell can contain an allergen-filter widget, so the
        # labels are read from its values table rather than the whole row.
        header = re.search(
            r'class="item labels".*?<div class="values"><div class="table">(.*?)</div></div>',
            block,
            re.S,
        )
        labels = [clean(v) for v in re.findall(r'<div class="val"><p>(.*?)</p>', header.group(1))]
        fields = [FIELD_LABELS.get(label) for label in labels]
        if not any(fields):
            raise SystemExit(f"nick-the-greek: unrecognised column labels {labels}")

        rows = []
        title = None
        pattern = re.compile(
            r'<div class="title"><p>(?P<title>.*?)</p></div>'
            r'|class="item"><div class="name">.*?<p>(?P<name>.*?)</p>'
            r'</div><div class="values"><div class="table">(?P<cells>.*?)</div></div>'
            r'<div class="more">',
            re.S,
        )
        for row in pattern.finditer(block):
            if row.group("title"):
                title = clean(row.group("title"))
                continue
            cells = re.findall(r'<div class="val">(.*?)</div>', row.group("cells"))
            if len(cells) != len(labels):
                raise SystemExit(
                    f"nick-the-greek: {row.group('name')} has {len(cells)} cells "
                    f"for {len(labels)} labeled columns"
                )
            values = {}
            for field, cell in zip(fields, cells):
                if field:
                    values[field] = number(cell)
            rows.append((title, clean(row.group("name")), values))
        screens[match.group(1)] = rows
    return screens


def category_for(screen, name):
    if screen in SIDE_SCREENS:
        return "side"
    lowered = name.lower()
    if any(word in lowered for word in CONDIMENT_WORDS):
        return "condiment"
    return "component"


def sf_locations():
    stores = json.loads(fetch(LOCATIONS_URL))
    locations = []
    for store in stores:
        if (store.get("city") or "").strip().lower() != "san francisco":
            continue
        lat, lng = store["loc"]
        # Addresses are entered inconsistently (all-lowercase, stray typos);
        # title-case them without mangling ordinals like "4th".
        street = re.sub(r"\s+", " ", store["address"]).strip().title()
        street = re.sub(r"(\d)(Th|St|Nd|Rd)\b", lambda m: m.group(1) + m.group(2).lower(), street)
        locations.append({
            "address": f"{street}, San Francisco, CA {store.get('zip', '')}".strip(),
            "lat": float(lat),
            "lng": float(lng),
            "neighborhood": None,
        })
    return locations


def main():
    page = fetch(NUTRITION_URL).decode("utf-8", "replace")
    screens = parse_calculator(page)

    items = []
    lookup = {}
    unpublished = []
    for screen, rows in screens.items():
        for title, name, values in rows:
            item_id = slug(f"{screen}-{title}-{name}")
            if any(values.get(field) is None for field in REQUIRED):
                # The calculator ships some rows with an entirely blank
                # nutrition row; publishing those as zeros would invent data.
                unpublished.append(f"{screen}/{title}/{name}")
                continue
            lookup[(screen, name)] = values
            items.append({
                "id": item_id,
                "name": name if screen in SIDE_SCREENS else f"{name} ({title}, {screen})",
                "description": f"{title} — {screen} screen of Nick The Greek's nutrition calculator.",
                "category": category_for(screen, name),
                "serving_note": "per standard portion as served",
                "is_estimate": False,
                "source": {"type": "vendor", "url": NUTRITION_URL},
                **{field: values.get(field) for field in MACROS},
            })

    def derive(item_id, name, screen, component_names, note, description):
        if any((screen, component) not in lookup for component in component_names):
            # A build whose parts are not all published cannot be summed.
            unpublished.append(f"derived {item_id}")
            return
        totals = {field: 0.0 for field in MACROS}
        for component in component_names:
            values = lookup[(screen, component)]
            for field in MACROS:
                totals[field] += values.get(field) or 0.0
        items.append({
            "id": item_id,
            "name": name,
            "description": description,
            "category": "meal",
            "serving_note": note,
            "is_estimate": True,
            "source": {"type": "derived", "url": NUTRITION_URL},
            **totals,
        })

    for protein in PITA_PROTEINS:
        derive(
            slug(f"pita-{protein}"), f"{protein} Pita", "pitas",
            PITA_BASE + [protein], "per pita as built below",
            "Standard pita: pita bread, sliced tomatoes, red onions, romaine and tzatziki, "
            f"with {protein.lower()}. Sum of the calculator's per-ingredient values; "
            "fries and alternate sauces not included.",
        )

    for base_name, base, label in (
        ("Mediterranean Bowl", MED_BOWL_BASE, "mediterranean"),
        ("Gyro Bowl", GYRO_BOWL_BASE, "gyro"),
    ):
        recipe = ", ".join(base).lower()
        for protein in BOWL_PROTEINS:
            derive(
                slug(f"bowl-{label}-{protein}"), f"{base_name} with {protein}", "bowls",
                base + [protein], "per bowl as built below",
                f"Standard {base_name.lower()}: {recipe}, with {protein.lower()}. "
                "Sum of the calculator's per-ingredient values; optional extra sauces excluded.",
            )

    for protein in PLATE_PROTEINS:
        derive(
            slug(f"plate-{protein}"), f"{protein} Plate", "plates",
            PLATE_BASE + [protein], "per plate as built below",
            "Standard plate: sliced tomatoes, tzatziki, red onions, pita and rice, with "
            f"{protein.lower()}. Sum of the calculator's per-ingredient values; fries "
            "(offered instead of rice) and the side salad are not included.",
        )

    salad_rows = {}
    for title, name, _ in screens["salads"]:
        salad_rows.setdefault(title, []).append(name)
    for salad in SALADS:
        components = salad_rows[salad]
        derive(
            slug(f"salad-{salad}"), salad, "salads", components,
            "per entree salad",
            f"{salad} as listed by the calculator: {', '.join(components).lower()}. "
            "Sum of the calculator's per-ingredient values.",
        )
        for protein in SALAD_PROTEINS:
            derive(
                slug(f"salad-{salad}-{protein}"), f"{salad} with {protein}", "salads",
                components + [protein], "per entree salad",
                f"{salad} plus {protein.lower()}. Sum of the calculator's per-ingredient values.",
            )

    if unpublished:
        print(f"nick-the-greek: {len(unpublished)} row(s) with no published nutrition, "
              f"not saved: {', '.join(unpublished)}")

    save_restaurant({
        "id": "nick-the-greek",
        "name": "Nick The Greek",
        "website": "https://www.nickthegreek.com",
        "nutrition_source": {
            "type": "vendor",
            "url": NUTRITION_URL,
            "vendor": "simmer",
            "retrieved": TODAY,
        },
        "locations": sf_locations(),
        "items": items,
    })


if __name__ == "__main__":
    main()
