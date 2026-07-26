"""Scrape The Halal Guys' published nutrition guide and San Francisco store.

The nutrition guide is an HTML table whose first row labels the macro columns;
this scraper maps those columns by header text and ignores the allergens table.
The guide publishes some proteins twice with different numbers, without labels:
one row has a site-logo image marker and the other does not.  Both rows are
kept as components, while derived meals choose the variant passing the
pipeline's macro check (preferring the marked row when both pass).  A literal
"*" means the nutrient was not analyzed: required macros become 0.0 and
optional fiber and sodium remain None.
"""

import datetime
import html
import json
import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402
from validate import macro_check  # noqa: E402

NUTRITION_URL = "https://thehalalguys.com/nutritional-guide/"
LOCATION_URL = (
    "https://thehalalguys.com/stat/api/locations/search"
    "?lat=37.7749&lng=-122.4194&kilometers=100&limit=200&fields=all"
)
HEADERS = {"User-Agent": "Mozilla/5.0 Chrome/126"}
TODAY = datetime.date.today().isoformat()
REQUIRED_MACROS = ("calories", "protein_g", "carbs_g", "fat_g")
OPTIONAL_MACROS = ("fiber_g", "sodium_mg")


def get(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


class NutritionParser(HTMLParser):
    """Collect rows from tablepress-17 while retaining the logo marker."""

    def __init__(self):
        super().__init__()
        self.in_table = False
        self.rows = []
        self.row = None
        self.cell = None
        self.category_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table" and attrs.get("id") == "tablepress-17":
            self.in_table = True
        if not self.in_table:
            return
        if tag == "tr":
            self.row = []
        elif tag in ("th", "td"):
            self.cell = {
                "text": "",
                "colspan": attrs.get("colspan"),
                "logo": False,
                "category": False,
            }
        elif tag == "span" and self.cell is not None:
            classes = attrs.get("class", "").split()
            if "category-header" in classes:
                self.cell["category"] = True
                self.category_depth += 1
        elif tag == "img" and self.cell is not None:
            src = attrs.get("data-src", "") or attrs.get("src", "")
            if "site-logo-2x.png" in src:
                self.cell["logo"] = True

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"] += data

    def handle_endtag(self, tag):
        if not self.in_table:
            return
        if tag in ("th", "td") and self.cell is not None:
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag == "span" and self.category_depth:
            self.category_depth -= 1
        elif tag == "table":
            self.in_table = False


def clean(value):
    return " ".join(html.unescape(value).split())


def number(value, optional=False):
    value = clean(value)
    if not value or (value == "*" and optional):
        return None
    if value == "*":
        return 0.0
    try:
        result = float(value)
    except ValueError:
        return None
    return int(result) if result.is_integer() else result


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def parse_rows(raw):
    parser = NutritionParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    if not parser.rows:
        raise RuntimeError("tablepress-17 was not found")

    header = [clean(cell["text"]).upper() for cell in parser.rows[0]]
    columns = {name: i for i, name in enumerate(header) if name}
    required_headers = {
        "TOTAL CALORIES (KCAL)": "calories",
        "TOTAL FAT (G)": "fat_g",
        "TOTAL CARBOHYDRATES (G)": "carbs_g",
        "PROTEIN (G)": "protein_g",
        "DIETARY FIBER (G)": "fiber_g",
        "SODIUM (MG)": "sodium_mg",
        "SERVING SIZE (OZ)": "serving_oz",
        "SERVING SIZE (G)": "serving_g",
        "CALORIES FROM FAT (KCAL)": "calories_from_fat",
    }
    missing = set(required_headers) - set(columns)
    if missing:
        raise RuntimeError(f"nutrition headers missing: {sorted(missing)}")
    columns = {required_headers[k]: v for k, v in columns.items() if k in required_headers}

    sections = []
    section = None
    for row in parser.rows[1:]:
        if not row:
            continue
        category_cell = next((cell for cell in row if cell["category"]), None)
        if category_cell is not None:
            section = clean(category_cell["text"])
            continue
        if section is None:
            continue
        name = clean(row[0]["text"])
        if not name:
            continue
        item = {
            "section": section,
            "name": name,
            "logo_marked": row[0]["logo"],
            "calories_from_fat": number(row[columns["calories_from_fat"]]["text"], optional=True),
            "serving_oz": clean(row[columns["serving_oz"]]["text"]),
            "serving_g": clean(row[columns["serving_g"]]["text"]),
        }
        for key in REQUIRED_MACROS:
            item[key] = number(row[columns[key]]["text"])
        for key in OPTIONAL_MACROS:
            item[key] = number(row[columns[key]]["text"], optional=True)
        sections.append(item)
    return sections


def choose_variant(rows):
    """Choose a duplicate row according to the documented macro rule."""
    if len(rows) == 1:
        return rows[0]
    checked = []
    for row in rows:
        ok, _, _ = macro_check(row)
        fat_delta = abs(9 * row["fat_g"] - (row["calories_from_fat"] or 0))
        checked.append((row, ok, fat_delta))
    passing = [entry for entry in checked if entry[1]]
    if passing:
        marked = [entry for entry in passing if entry[0]["logo_marked"]]
        return (marked or passing)[0][0]
    return min(checked, key=lambda entry: entry[2])[0]


def item_macros(row):
    return {key: row[key] for key in REQUIRED_MACROS + OPTIONAL_MACROS}


def serving_note(row, section):
    size = f"{row['serving_oz']} oz"
    if row["serving_g"]:
        size += f" ({row['serving_g']} g)"
    if section in ("Platters Regular", "Platters Small"):
        platter_size = "regular" if section == "Platters Regular" else "small"
        return f"per {size} portion as served in a {platter_size} platter"
    if section == "SANDWICHES":
        return f"per {size} sandwich portion"
    if section in ("FOUNTAIN", "CRAFT BEVERAGE"):
        return f"per {size} cup"
    return f"per {size} portion"


def build_items(rows):
    categories = {
        "Platters Regular": "component",
        "Platters Small": "component",
        "SANDWICHES": "component",
        "SIDES": "side",
        "TOPPINGS": "condiment",
        "SAUCE": "condiment",
        "DESSERTS": "side",
        "FOUNTAIN": "drink",
        "CRAFT BEVERAGE": "drink",
    }
    grouped = {}
    for row in rows:
        grouped.setdefault((row["section"], row["name"]), []).append(row)

    items = []
    for row in rows:
        key = (row["section"], row["name"])
        variants = grouped[key]
        occurrence = variants.index(row) + 1
        duplicate_note = None
        duplicate_trap = row["section"] in (
            "Platters Regular",
            "Platters Small",
            "SANDWICHES",
            "SIDES",
        )
        if len(variants) > 1 and duplicate_trap:
            marker = "carries the site-logo marker" if row["logo_marked"] else "does not carry the site-logo marker"
            duplicate_note = (
                f"The source publishes two unlabeled rows for {row['name']}; "
                f"this is row {occurrence}, which {marker}."
            )
        source_note = None
        if row["section"] == "SIDES" and row["name"].lower().startswith("chicken wings"):
            source_note = (
                "The published chicken-wings quantities scale non-linearly "
                "(4 to 330 kcal, 8 to 1320 kcal, 12 to 2970 kcal); values are "
                "kept as published."
            )
        elif row["section"] == "DESSERTS" and row["name"] in (
            "Baklava Cheesecake",
            "Chocolate chip Cookie (4oz)",
        ):
            source_note = (
                "The published value is implausibly large for the stated portion "
                "and appears to represent a whole cake or batch; it is kept as published."
            )
        elif row["section"] == "CRAFT BEVERAGE" and row["serving_oz"] == "24":
            source_note = (
                "The 24 oz row repeats the 16 oz published numbers; values are "
                "kept as published."
            )
        description = " ".join(note for note in (duplicate_note, source_note) if note) or None
        name = row["name"]
        if row["section"] == "CRAFT BEVERAGE":
            name = f"{name.title()} ({row['serving_oz']} oz)"
        item = {
            "id": f"{slug(row['section'])}-{slug(row['name'])}-{occurrence}",
            "name": name,
            "description": description,
            "category": categories[row["section"]],
            "is_estimate": False,
            "serving_note": serving_note(row, row["section"]),
            "source": {"type": "published", "url": NUTRITION_URL},
            **item_macros(row),
        }
        if len(variants) == 1:
            item["id"] = f"{slug(row['section'])}-{slug(row['name'])}"
        items.append(item)

    def component(section, name):
        return choose_variant(grouped[(section, name)])

    def total(parts):
        result = {key: 0 for key in REQUIRED_MACROS + OPTIONAL_MACROS}
        for row, multiplier in parts:
            for key in result:
                result[key] += (row[key] or 0) * multiplier
        return result

    def chosen_text(section, name):
        rows_for_name = grouped[(section, name)]
        chosen = component(section, name)
        if len(rows_for_name) == 1:
            return f"{name} ({chosen['serving_oz']} oz row)"
        marker = "logo-marked" if chosen["logo_marked"] else "logo-less"
        return f"{name} ({chosen['serving_oz']} oz {marker} row)"

    proteins = ("Chicken", "Beef Gyro", "Falafel", "BBQ Chicken")
    for section, label in (("Platters Regular", "Regular"), ("Platters Small", "Small")):
        for protein in proteins:
            protein_row = component(section, protein)
            parts = [
                (protein_row, 1),
                (component(section, "Rice"), 1),
                (component(section, "Lettuce"), 1),
                (component(section, "Tomatoes"), 1),
                (component(section, "Pita"), 1),
                (component("SAUCE", "White Sauce"), 1),
            ]
            totals = total(parts)
            recipe = ", ".join(
                chosen_text(*part)
                for part in (
                    (section, protein),
                    (section, "Rice"),
                    (section, "Lettuce"),
                    (section, "Tomatoes"),
                    (section, "Pita"),
                    ("SAUCE", "White Sauce"),
                )
            )
            items.append({
                "id": f"{slug(protein)}-rice-{slug(label)}-platter",
                "name": f"{protein} & Rice {label} Platter",
                "description": (
                    f"Derived recipe: {recipe}. White sauce is included as served; "
                    "hot sauce is excluded. Component variants were selected using "
                    "the published macro check."
                ),
                "category": "meal",
                "is_estimate": True,
                "serving_note": f"per {label.lower()} platter as built from published portions",
                "source": {"type": "derived", "url": NUTRITION_URL},
                **totals,
            })
        half_parts = [
            (component(section, "Chicken"), 0.5),
            (component(section, "Beef Gyro"), 0.5),
            (component(section, "Rice"), 1),
            (component(section, "Lettuce"), 1),
            (component(section, "Tomatoes"), 1),
            (component(section, "Pita"), 1),
            (component("SAUCE", "White Sauce"), 1),
        ]
        totals = total(half_parts)
        recipe = ", ".join(
            chosen_text(*part)
            for part in (
                (section, "Chicken"), (section, "Beef Gyro"), (section, "Rice"),
                (section, "Lettuce"), (section, "Tomatoes"), (section, "Pita"),
                ("SAUCE", "White Sauce"),
            )
        )
        items.append({
            "id": f"combo-rice-{slug(label)}-platter",
            "name": f"Combo & Rice {label} Platter",
            "description": (
                f"Derived recipe: half Chicken, half Beef Gyro, plus {recipe}. "
                "White sauce is included as served; hot sauce is excluded. "
                "Component variants were selected using the published macro check."
            ),
            "category": "meal",
            "is_estimate": True,
            "serving_note": f"per {label.lower()} platter as built from published portions",
            "source": {"type": "derived", "url": NUTRITION_URL},
            **totals,
        })

    for protein in proteins:
        parts = [
            (component("SANDWICHES", protein), 1),
            (component("SANDWICHES", "Pita"), 1),
            (component("SANDWICHES", "Lettuce"), 1),
            (component("SANDWICHES", "Tomatoes"), 1),
            (component("SAUCE", "White Sauce"), 1),
        ]
        totals = total(parts)
        recipe = ", ".join(
            chosen_text(*part)
            for part in (
                ("SANDWICHES", protein), ("SANDWICHES", "Pita"),
                ("SANDWICHES", "Lettuce"), ("SANDWICHES", "Tomatoes"),
                ("SAUCE", "White Sauce"),
            )
        )
        items.append({
            "id": f"{slug(protein)}-sandwich",
            "name": f"{protein} Sandwich",
            "description": (
                f"Derived recipe: {recipe}. White sauce is included as served; "
                "hot sauce is excluded. Component variants were selected using "
                "the published macro check."
            ),
            "category": "meal",
            "is_estimate": True,
            "serving_note": "per sandwich as built from published portions",
            "source": {"type": "derived", "url": NUTRITION_URL},
            **totals,
        })
    return items


def get_location():
    data = json.loads(get(LOCATION_URL).decode("utf-8"))
    locations = []
    for location in data.get("locations", []):
        address = location.get("businessAddress", {})
        if address.get("addressLocality") != "San Francisco":
            continue
        lng, lat = location["coordinates"]
        locations.append({
            "address": (
                f"{address['streetAddress']}, San Francisco, "
                f"{address['addressRegion']} {address['postalCode']}"
            ),
            "lat": lat,
            "lng": lng,
            "neighborhood": "Union Square",
        })
    return locations


def main():
    rows = parse_rows(get(NUTRITION_URL))
    save_restaurant({
        "id": "the-halal-guys",
        "name": "The Halal Guys",
        "website": "https://thehalalguys.com",
        "nutrition_source": {
            "type": "published",
            "url": NUTRITION_URL,
            "vendor": None,
            "retrieved": TODAY,
        },
        "locations": get_location(),
        "items": build_items(rows),
    })


if __name__ == "__main__":
    main()
