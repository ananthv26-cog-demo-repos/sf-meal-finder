"""Domino's Pizza scraper.

Nutrition comes from Domino's own published nutrition guide PDF, linked from
https://www.dominos.com/en/pages/content/nutritional/nutrition as
"Nutrition Details (PDF)".  The link is only present in the rendered (JS) page;
the file itself is a plain CDN asset and fetches fine with urllib:

    https://cache.dominos.com/olo/6_168_0/assets/build/market/US/_en/pdf/DominosNutritionGuide.pdf

Everything in that guide is published PER SERVING, and for pizza a serving is a
FRACTION OF A PIZZA that changes with size and crust (1/2 of an 8", 1/3 of a
10" hand tossed, 1/8 of a 14" large, ...).  The page heading states the
fraction, so:

  - published rows are saved as `component` with the fraction in serving_note
  - whole pizzas (the actually-orderable thing) are DERIVED by multiplying the
    per-serving component rows by the slice count: source "derived",
    is_estimate=True, recipe and slice count in the description

Columns are mapped by their (rotated) header labels and x positions, never by
position in the row: the guide's column order is
weight / calories / total fat / sat fat / trans fat / cholesterol / sodium /
carbs / fiber / total sugars / added sugars / protein, and blind positional
parsing silently shifts sodium into carbs.

SF locations come from the public store locator; it returns the ~50 nearest
stores for a seed address, so several SF seeds are unioned by StoreID and
filtered on the city line of AddressDescription ("South San Francisco" and
"Daly City" carry SF-adjacent zips, so filtering on zip is wrong).
"""

import datetime
import io
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

PDF_URL = (
    "https://cache.dominos.com/olo/6_168_0/assets/build/market/US/_en/pdf/"
    "DominosNutritionGuide.pdf"
)
LOCATOR_URL = "https://order.dominos.com/power/store-locator"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
TODAY = datetime.date.today().isoformat()

# Seed addresses spread across the city; the locator caps its result list.
SF_SEEDS = [
    "728 Geary St",
    "1 Market St",
    "2000 Judah St",
    "3800 Mission St",
    "5000 Geary Blvd",
    "1700 3rd St",
    "1500 Sloat Blvd",
]

FIELD_BY_HEADER = {
    "Calories": "calories",
    "(g) Fat Total": "fat_g",
    "(g) Carbohydrates": "carbs_g",
    "(g) Protein": "protein_g",
    "(g) Fiber": "fiber_g",
    "(mg) Sodium": "sodium_mg",
}

# Nutrition tables; the remaining pages are contents and allergen grids.
BYO_PAGES = range(1, 14)          # per-size build-your-own component tables
SPECIALTY_PAGE = 14
BREAKFAST_PAGE = 15
SIDES_PAGES = (16, 18)            # page 18 is a duplicate of 17, deduped by id

# Section heading (as printed) -> category, for the non-pizza tables.
SECTION_CATEGORY = {
    "BREADS": "side",
    "CHICKEN": "side",
    "DESSERTS": "side",
    "LOADED TOTS": "side",
    "OVEN-BAKED SANDWICHES": "meal",
    "PENNE PASTA": "meal",
    "PASTA": "meal",
    "SALADS": "side",
    "SALAD DRESSINGS": "condiment",
    "DIPPING CUPS": "condiment",
    "DIPPING SAUCES": "condiment",
    "SAUCES": "condiment",
    "*STANDARD BUILDS": "meal",
}
# Sections whose item names are only unique with the section appended
# ("Italian" is both a sandwich and a hoagie; "Ranch" is a dipping cup).
SECTION_SUFFIX = {
    "OVEN-BAKED SANDWICHES": "Oven-Baked Sandwich",
    "*STANDARD BUILDS": "Hoagie",
    "DIPPING CUPS": "Dipping Cup",
}
# Items whose category differs from their section default.
ITEM_CATEGORY = {
    "chicken caesar salad": "meal",
    "croutons": "component",
}

SLICE_RE = re.compile(r"of 1/(\d+) of Pizza")
FRACTION_OF_RE = re.compile(r"of 1/(\d+) of (\w+)")
# Label-only rows that qualify the rows beneath them ("Pizza Sauce" is listed
# once for a one-sauce hoagie and again, halved, for a two-sauce hoagie).
QUALIFIER_RE = re.compile(r"^(One \(1\) Sauce|Two \(2\) Sauces|\d+\s*-\s*\d+ Toppings)$", re.I)
FRACTION_RE = re.compile(r"^([SMLX]+) \(1/(\d+) pizza\)$", re.I)
NUM_RE = re.compile(r"^\d+(\.\d+)?$")


def fetch(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=60).read()


def columns(page):
    """Map header label -> x centre, read from the rotated column headings."""
    by_x = {}
    for word in page.extract_words(extra_attrs=["upright"]):
        if word["upright"]:
            continue
        by_x.setdefault(round(word["x0"]), []).append((word["top"], word["text"][::-1]))
    return {
        " ".join(text for _, text in sorted(parts)): x + 3.5
        for x, parts in by_x.items()
    }


def rows(page):
    """Group upright words into visual rows (labels and numbers can sit a
    point apart vertically, so cluster rather than round).

    Only the Arial table font is kept: the disclaimer paragraph at the foot of
    each page (set in OneDotCd) overlaps the last table rows and otherwise gets
    interleaved into them word by word.
    """
    words = sorted(
        (
            w
            for w in page.extract_words(extra_attrs=["upright", "fontname"])
            if w["upright"] and "Arial" in w["fontname"]
        ),
        key=lambda w: w["top"],
    )
    out, current = [], []
    for word in words:
        if current and word["top"] - current[0]["top"] > 5:
            out.append(sorted(current, key=lambda w: w["x0"]))
            current = []
        current.append(word)
    if current:
        out.append(sorted(current, key=lambda w: w["x0"]))
    return out


def parse_table(page):
    """Yield (top, label, serving_label, values) for every data row on a page.

    `values` maps schema field -> number, taken from the column whose header
    centre is nearest each numeric cell.
    """
    cols = columns(page)
    if "Calories" not in cols:
        return
    serving_x = cols.pop("Size Serving", None)
    numeric_left = min(cols.values()) - 17
    for row in rows(page):
        label_parts, serving_parts, cells = [], [], []
        for word in row:
            centre = (word["x0"] + word["x1"]) / 2
            if centre < numeric_left:
                if serving_x is not None and centre > serving_x - 30:
                    serving_parts.append(word["text"])
                else:
                    label_parts.append(word["text"])
            elif NUM_RE.match(word["text"]):
                header = min(cols, key=lambda h: abs(cols[h] - centre))
                cells.append((header, float(word["text"])))
            else:
                serving_parts.append(word["text"])
        top = row[0]["top"]
        if not cells:
            # Section headings sit in the serving-size column on some pages.
            yield top, " ".join(label_parts + serving_parts), "", None
            continue
        # "Garlic Bread Bites 4 pieces": the serving count sits left of the
        # serving-size column centre, so pull a trailing count back into it.
        if serving_parts and label_parts and NUM_RE.match(label_parts[-1]):
            serving_parts.insert(0, label_parts.pop())
        values = {
            FIELD_BY_HEADER[h]: v for h, v in cells if h in FIELD_BY_HEADER
        }
        if len(values) != len(FIELD_BY_HEADER):
            continue
        yield top, " ".join(label_parts), " ".join(serving_parts), values


def slug(*parts):
    text = "-".join(parts).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return re.sub(r"-+", "-", text).strip("-")


def is_section(label):
    letters = [c for c in label if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def scaled(values, factor):
    return {k: round(v * factor, 1) for k, v in values.items()}


def summed(rows_):
    total = {k: 0.0 for k in FIELD_BY_HEADER.values()}
    for values in rows_:
        for k in total:
            total[k] += values[k]
    return {k: round(v, 1) for k, v in total.items()}


def parse_pdf(pdf):
    """Return (items, byo) where byo[page_title][section][name] = values."""
    items = []
    byo = {}
    seen = set()

    def add(item):
        if item["id"] in seen:
            return
        seen.add(item["id"])
        items.append(item)

    for index, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        title = text.split("\n")[0].strip()

        if index in BYO_PAGES:
            match = SLICE_RE.search(text)
            if not match:
                raise RuntimeError(f"page {index + 1}: no serving fraction in heading")
            slices = int(match.group(1))
            serving_note = f"per 1/{slices} of a {title.replace(' Pizza', '')} pizza"
            table = byo.setdefault(title, {"slices": slices, "sections": {}})
            section = ""
            for _top, label, _, values in parse_table(page):
                if values is None:
                    if label and is_section(label):
                        section = label
                    continue
                table["sections"].setdefault(section, {})[label] = values
                add({
                    "id": slug(title, section, label),
                    "name": f"{label} — {title} ({section.title()})",
                    "description": (
                        f"Published per-serving nutrition for {label} on a {title}."
                    ),
                    "category": "component",
                    "serving_note": serving_note,
                    "is_estimate": False,
                    "source": {"type": "published", "url": PDF_URL},
                    **values,
                })

        elif index == SPECIALTY_PAGE:
            for item in specialty_rows(page):
                add(item)

        elif index == BREAKFAST_PAGE:
            match = SLICE_RE.search(text)
            slices = int(match.group(1)) if match else None
            section = size_section = ""
            for _top, label, _, values in parse_table(page):
                if values is None:
                    if label and is_section(label):
                        section = label
                        if "HAND TOSSED" in label:
                            size_section = label
                    continue
                size = size_section.replace("- BREAKFAST PIZZA", "").strip("* ").title()
                note = f"per 1/{slices} of pizza" if slices else "per serving"
                whole = "BUILD YOUR OWN" not in section
                add({
                    "id": slug("breakfast", size_section, section, label),
                    "name": f"{label} ({size} breakfast pizza)"
                            + (" build component" if not whole else ""),
                    "description": f"Domino's breakfast pizza table, {size_section}.",
                    "category": "component",
                    "serving_note": note,
                    "is_estimate": False,
                    "source": {"type": "published", "url": PDF_URL},
                    **values,
                })
                if whole and slices:
                    add({
                        "id": slug("breakfast", size_section, label, "whole"),
                        "name": f"{label.title()} — whole {size} breakfast pizza",
                        "description": (
                            f"Whole pizza: {slices} x the published 1/{slices}-of-pizza "
                            f"row for {label} ({size_section})."
                        ),
                        "category": "meal",
                        "serving_note": f"per whole pizza ({slices} slices)",
                        "is_estimate": True,
                        "source": {"type": "derived", "url": PDF_URL},
                        **scaled(values, slices),
                    })

        elif index in SIDES_PAGES:
            section = qualifier = ""
            fraction = FRACTION_OF_RE.search(text)
            unit = fraction.group(2).lower() if fraction else None
            parts = int(fraction.group(1)) if fraction else None
            table = list(parse_table(page))
            # Rows whose dish name is printed on its own line between the two
            # serving rows it covers (the pasta block).
            floating = [
                (top, label)
                for top, label, _, values in table
                if values is None and label and not is_section(label)
                and not QUALIFIER_RE.match(label)
            ]
            for top, label, serving, values in table:
                if values is None:
                    if label and is_section(label):
                        section, qualifier = label, ""
                    elif label and QUALIFIER_RE.match(label):
                        qualifier = label
                    continue
                if not label and floating:
                    label = min(floating, key=lambda f: abs(f[0] - top))[1]
                if not label:
                    continue
                category = ITEM_CATEGORY.get(
                    label.lower(), SECTION_CATEGORY.get(section, "component")
                )
                name = f"{label} {SECTION_SUFFIX[section]}" if section in SECTION_SUFFIX else label
                if qualifier:
                    name = f"{name} ({qualifier})"
                note = f"per {serving}" if serving else (
                    f"per 1/{parts} of {unit}" if parts else "per serving"
                )
                # Pages published per half unit (hoagies): the half is not
                # orderable, so the published row is a component and the whole
                # sandwich is derived from it.
                half = parts and not serving
                add({
                    "id": slug(section, qualifier, label, serving),
                    "name": name,
                    "description": f"{section.title()} — Domino's nutrition guide." if section else None,
                    "category": "component" if half else category,
                    "serving_note": note,
                    "is_estimate": False,
                    "source": {"type": "published", "url": PDF_URL},
                    **values,
                })
                if half and category == "meal":
                    add({
                        "id": slug(section, qualifier, label, "whole"),
                        "name": f"{name} — whole {unit}",
                        "description": (
                            f"Whole {unit}: {parts} x Domino's published "
                            f"1/{parts}-of-{unit} row for the {label} {unit}."
                        ),
                        "category": "meal",
                        "serving_note": f"per whole {unit}",
                        "is_estimate": True,
                        "source": {"type": "derived", "url": PDF_URL},
                        **scaled(values, parts),
                    })

    return items, byo


def specialty_rows(page):
    """Specialty pizzas: four size rows per pizza, with the pizza name printed
    once, vertically centred in its block.  Rows are grouped by size order and
    the name is the label that falls inside the block's vertical span."""
    blocks, labels = [], []
    current = None
    for top, label, serving, values in parse_table(page):
        match = FRACTION_RE.match(serving.strip())
        if values is not None and match:
            size, denominator = match.group(1).upper(), int(match.group(2))
            if size == "S" or current is None:
                current = []
                blocks.append(current)
            current.append((top, size, denominator, values))
        elif values is None and label and not is_section(label):
            labels.append((top, label))

    # The pizza name is printed once, vertically inside its block of size rows;
    # page titles and footnotes fall outside every block and are ignored.
    named = []
    for block in blocks:
        low, high = block[0][0] - 6, block[-1][0] + 6
        inside = [text for top, text in labels if low <= top <= high]
        if len(inside) != 1:
            raise RuntimeError(f"specialty page: {len(inside)} names for block {inside}")
        named.append((inside[0], [row[1:] for row in block]))

    sizes = {"S": 'small 10"', "M": 'medium 12"', "L": 'large 14"', "XL": 'extra large 16"'}
    for name, block in named:
        for size, denominator, values in block:
            label = sizes.get(size, size)
            yield {
                "id": slug("specialty", name, size),
                "name": f"{name} ({label}, hand tossed) slice",
                "description": (
                    f"Published nutrition for one 1/{denominator} serving of a "
                    f"{label} {name} on hand tossed crust."
                ),
                "category": "component",
                "serving_note": f"per 1/{denominator} of a {label} pizza",
                "is_estimate": False,
                "source": {"type": "published", "url": PDF_URL},
                **values,
            }
            yield {
                "id": slug("specialty", name, size, "whole"),
                "name": f"{name} — whole {label} pizza (hand tossed)",
                "description": (
                    f"Whole pizza: {denominator} x Domino's published "
                    f"1/{denominator}-of-pizza row for the {label} {name}."
                ),
                "category": "meal",
                "serving_note": f"per whole {label} pizza ({denominator} slices)",
                "is_estimate": True,
                "source": {"type": "derived", "url": PDF_URL},
                **scaled(values, denominator),
            }


def byo_pizzas(byo):
    """Derive whole build-your-own cheese and pepperoni pizzas from the
    published per-serving crust / sauce / cheese / topping rows."""
    items = []
    for title, table in byo.items():
        sections, slices = table["sections"], table["slices"]

        def find(section_key, name_key):
            for section, entries in sections.items():
                if section_key not in section:
                    continue
                for name, values in entries.items():
                    if name.lower().startswith(name_key):
                        return values
            return None

        sauce = find("SAUCE", "pizza sauce")
        cheese_only = find("CHEESE ONLY", "regular cheese")
        cheese_with = find("ALONG WITH OTHER TOPPINGS", "regular cheese")
        pepperoni = find("TOPPING", "pepperoni")
        if not (sauce and cheese_only):
            continue

        size = title.replace(" Pizza", "").split(" Hand Tossed")[0]
        for crust_name, crust in sections.get("CRUST", {}).items():
            # The CRUST block also lists add-ons (garlic oil, parmesan shake);
            # no real crust serving is under 50 kcal.
            if "Garlic Oil" in crust_name or crust["calories"] < 50:
                continue
            # A crust row can restate its own serving size (a page can carry two
            # crusts cut differently); fall back to the page heading.
            own = re.search(r"Serving Size is 1/(\d+)", crust_name)
            cuts = int(own.group(1)) if own else slices
            crust_label = re.sub(r"\s*\(.*\)|\s*Pizza$", "", crust_name).strip()
            pizza = size if crust_label in size else f"{size} {crust_label}"
            items.append({
                "id": slug("byo", title, crust_label, "cheese", "whole"),
                "name": f"Cheese Pizza — whole {pizza}",
                "description": (
                    f"Standard cheese pizza: {cuts} x (crust + pizza sauce + regular "
                    "cheese) from Domino's published per-serving rows."
                ),
                "category": "meal",
                "serving_note": f"per whole pizza ({cuts} slices)",
                "is_estimate": True,
                "source": {"type": "derived", "url": PDF_URL},
                **scaled(summed([crust, sauce, cheese_only]), cuts),
            })
            if cheese_with and pepperoni:
                items.append({
                    "id": slug("byo", title, crust_label, "pepperoni", "whole"),
                    "name": f"Pepperoni Pizza — whole {pizza}",
                    "description": (
                        f"Standard one-topping pepperoni pizza: {cuts} x (crust + pizza "
                        "sauce + regular cheese for a topped pizza + pepperoni) from "
                        "Domino's published per-serving rows."
                    ),
                    "category": "meal",
                    "serving_note": f"per whole pizza ({cuts} slices)",
                    "is_estimate": True,
                    "source": {"type": "derived", "url": PDF_URL},
                    **scaled(summed([crust, sauce, cheese_with, pepperoni]), cuts),
                })
    return items


def sf_locations():
    stores = {}
    for seed in SF_SEEDS:
        query = urllib.parse.urlencode(
            {"s": seed, "c": "San Francisco, CA", "type": "Carryout"}
        )
        payload = json.loads(fetch(f"{LOCATOR_URL}?{query}"))
        for store in payload.get("Stores", []):
            stores[store["StoreID"]] = store

    locations = []
    for store in stores.values():
        lines = [l.strip() for l in store["AddressDescription"].split("\n") if l.strip()]
        if len(lines) < 2:
            continue
        city = lines[1].split(",")[0].strip()
        if city != "San Francisco":  # excludes South San Francisco / Daly City
            continue
        coords = store.get("StoreCoordinates") or {}
        locations.append({
            "address": f"{lines[0]}, {lines[1]}",
            "lat": float(coords["StoreLatitude"]),
            "lng": float(coords["StoreLongitude"]),
            "neighborhood": None,
        })
    return sorted(locations, key=lambda l: l["address"])


def spot_check(items):
    """Ultimate Pepperoni, large (14") hand tossed, is 360 kcal per 1/8 slice
    in every Domino's listing; fail loudly if the parse disagrees."""
    row = next(i for i in items if i["id"] == "specialty-ultimate-pepperoni-l")
    assert row["calories"] == 360, row
    assert (row["protein_g"], row["carbs_g"], row["fat_g"]) == (15, 34, 18), row


def main():
    with pdfplumber.open(io.BytesIO(fetch(PDF_URL))) as pdf:
        items, byo = parse_pdf(pdf)
    items += byo_pizzas(byo)
    spot_check(items)

    save_restaurant({
        "id": "dominos",
        "name": "Domino's Pizza",
        "website": "https://www.dominos.com",
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
