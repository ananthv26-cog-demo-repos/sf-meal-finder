"""Wingstop scraper.

wingstop.com/nutrition is an Angular shell; the page body it loads
(/content/html/nutrition.html) just links Wingstop's published nutritional
guide PDF on S3, which is the actual source of numbers here.

The PDF publishes wings and tenders PER PIECE, so canonical wing/tender meals
are DERIVED as sums (per-piece x count, plus the standard combo side and dip),
source "derived", is_estimate=True, recipe in the description. Chicken
sandwiches are published per sandwich and are saved as published meals.

Cross-source spot check: Wingstop's ordering API publishes calorie RANGES per
menu product (flavor-dependent) --
GET https://ecomm.wingstop.com/menu-worker?locationId=<id>&serviceMode=Carryout
-- so every derived 10-piece classic wing build must land inside the range the
ordering menu states for "10 Classic Wings". Locations come from the same
service: POST https://ecomm.wingstop.com/location-worker?type=carryout.

TRAPS:
- The PDF's beverage table has a DIFFERENT column layout from the food tables
  (size in mL, calories-from-fat, no protein column). Parsing every table with
  one positional template silently shifts sugars into protein.
- pdfplumber's text for this PDF interleaves section titles into the header
  line ("Total Saturated Trans TENDERTSotal ..."), so sections are detected
  from the fragments, not from clean header lines.
"""

import datetime
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

NUTRITION_PAGE = "https://www.wingstop.com/content/html/nutrition.html"
PDF_URL = ("https://s3.amazonaws.com/wingstop.com/assets/static/"
           "WSR18-0009-Corporate-NutritionalGuide-JumboWings-HR_OFFICAL.pdf")
LOCATION_URL = "https://ecomm.wingstop.com/location-worker?type=carryout"
MENU_URL = ("https://ecomm.wingstop.com/menu-worker?locationId={loc}&serviceMode=Carryout")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
TODAY = datetime.date.today().isoformat()

# Section markers as they survive pdfplumber's text extraction, in page order.
SECTION_MARKERS = [
    (re.compile(r"CLASSIC WINGS"), "Classic Wings"),
    (re.compile(r"BONELESS"), "Boneless Wings"),
    (re.compile(r"TENDER"), "Chicken Tenders"),
    (re.compile(r"SANDWIC"), "Chicken Sandwich"),
    (re.compile(r"^SIDES"), "Sides"),
    (re.compile(r"^BEVERAGES"), "Beverages"),
]

# Food tables: 15 numeric columns after the serving size.
FOOD_COLUMNS = [
    "calories", "fat_g", "sat_fat_g", "trans_fat_g", "cholesterol_mg", "sodium_mg",
    "carbs_g", "fiber_g", "sugars_g", "added_sugars_g", "protein_g",
    "vitamin_d_mcg", "calcium_mg", "iron_mg", "potassium_mg",
]
# Beverage table: 8 numeric columns, a different layout with no protein.
DRINK_COLUMNS = [
    "size_ml", "calories", "calories_from_fat", "fat_g", "sat_fat_g",
    "sugars_g", "sodium_mg", "carbs_g",
]

SECTION_CATEGORY = {
    "Classic Wings": "component", "Boneless Wings": "component",
    "Chicken Tenders": "component", "Chicken Sandwich": "meal",
    "Sides": "side", "Beverages": "drink",
}
DIP_WORDS = ("dip",)

# Derived builds: label -> (section, piece count, extra published rows, blurb)
COMBO_SIDE = "Seasoned Fries Regular"
COMBO_DIP = "Ranch Dip"
DERIVED_BUILDS = [
    ("{flavor} 10 pc Classic Wings", "Classic Wings", 10, [],
     "10 classic (bone-in) wings, one flavor"),
    ("{flavor} 10 pc Classic Wing Combo", "Classic Wings", 10, [COMBO_SIDE, COMBO_DIP],
     "10 classic wings with regular seasoned fries and a ranch dip"),
    ("{flavor} 10 pc Boneless Wings", "Boneless Wings", 10, [],
     "10 boneless wings, one flavor"),
    ("{flavor} 3 pc Crispy Tender Combo", "Chicken Tenders", 3, [COMBO_SIDE, COMBO_DIP],
     "3 crispy tenders with regular seasoned fries and a ranch dip"),
]

NUM = r"-?\d+(?:\.\d+)?"


def get(url, data=None, headers=None):
    hdrs = {"User-Agent": UA}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=hdrs)
    return urllib.request.urlopen(req, timeout=60).read()


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:70]


def check_pdf_headers(text):
    """Fail loudly if the guide's column labels are not the ones parsed below."""
    food_labels = ["Calories", "Total", "Saturated", "Trans", "Cholesterol", "Sodium",
                   "Carbohydrate", "Fiber", "Sugars", "Protein", "Potassium"]
    missing = [lab for lab in food_labels if lab not in text]
    if missing:
        raise SystemExit(f"nutrition guide layout changed, missing labels {missing}")
    if "Calories from" not in text or "Total Fat (kcal)" in text:
        pass  # beverage header wording varies; the numeric-width check below guards it


def parse_pdf(pdf_bytes):
    rows = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        full = "\n".join(page.extract_text() or "" for page in pdf.pages)
    check_pdf_headers(full)

    section = None
    for line in full.splitlines():
        line = line.strip()
        if not line:
            continue
        for pattern, name in SECTION_MARKERS:
            if pattern.search(line) and not re.search(rf"{NUM}\s+{NUM}\s+{NUM}", line):
                section = name
                break
        if section is None:
            continue
        width = len(DRINK_COLUMNS) if section == "Beverages" else len(FOOD_COLUMNS)
        m = re.match(rf"^(?P<label>.*?)\s+(?P<nums>(?:{NUM}\s+){{{width - 1}}}{NUM})$", line)
        if not m:
            continue
        label = m.group("label").strip()
        if not label or label.lower().startswith(("size", "serving")):
            continue
        values = [float(v) for v in m.group("nums").split()]
        columns = DRINK_COLUMNS if section == "Beverages" else FOOD_COLUMNS
        rows.append((section, label, dict(zip(columns, values))))
    return rows


PIECE_LABEL = {
    "Classic Wings": ("{flavor} Classic Wing", "per wing"),
    "Boneless Wings": ("{flavor} Boneless Wing", "per boneless wing"),
    "Chicken Tenders": ("{flavor} Crispy Tender", "per tender"),
    "Chicken Sandwich": ("{flavor} Chicken Sandwich", "per sandwich"),
}


def base_name(section, label):
    """The flavor (wings/tenders/sandwiches) or plain item name (sides/drinks)."""
    if section == "Beverages":
        return re.sub(r"\s+\d+oz\s+(?:Regular|Large)$", "", label).strip()
    head = re.sub(r"\s*\([\d.]+\s*g\)$", "", label).strip()
    return re.sub(r"\s*(?:\d+(?:\.\d+)?\s*(?:ea|oz|Sticks))(?:\s+Cup)?$", "", head).strip()


def split_label(section, label):
    """Split a row label into (item name, serving note)."""
    if section == "Beverages":
        m = re.match(r"^(?P<name>.*?)\s+(?P<size>\d+oz)\s+(?P<cup>Regular|Large)$", label)
        if not m:
            return label, None
        return m.group("name"), f"per {m.group('size')} {m.group('cup').lower()} cup"

    m = re.match(r"^(?P<head>.+?)\s*\((?P<grams>[\d.]+)\s*g\)$", label)
    if not m:
        return label, None
    head, grams = m.group("head").strip(), m.group("grams")
    sm = re.search(r"(?P<serv>(?:\d+(?:\.\d+)?\s*(?:ea|oz|Sticks))(?:\s+Cup)?)$", head)
    name = base_name(section, label)
    serving = sm.group("serv") if sm else None

    if section in PIECE_LABEL:
        template, note = PIECE_LABEL[section]
        return template.format(flavor=name), f"{note} ({grams} g)"
    if serving and serving.strip() != "1ea":
        return name, f"per {serving} serving ({grams} g)"
    return name, f"per item ({grams} g)"


def build_item(section, label, vals):
    name, note = split_label(section, label)
    category = SECTION_CATEGORY[section]
    if section == "Sides" and any(w in name.lower() for w in DIP_WORDS):
        category = "condiment"
    return {
        "id": slug(f"{section}-{label}"),
        "name": name,
        "description": f"Wingstop nutritional guide section: {section}.",
        "category": category,
        "calories": vals["calories"],
        "protein_g": vals.get("protein_g", 0.0),
        "carbs_g": vals["carbs_g"],
        "fat_g": vals["fat_g"],
        "fiber_g": vals.get("fiber_g"),
        "sodium_mg": vals.get("sodium_mg"),
        "serving_note": note,
        "is_estimate": False,
        "source": {"type": "published", "url": PDF_URL},
    }


def sf_locations():
    body = json.dumps({"latitude": 37.7749, "longitude": -122.4194,
                       "radius": 15, "radiusUnits": "mi"}).encode()
    data = json.loads(get(LOCATION_URL, body, {"Content-Type": "application/json"}))
    out = []
    for loc in data["data"]["locations"]:
        if (loc.get("locality") or "").strip().lower() != "san francisco":
            continue
        street = re.sub(r"\s*\(.*?\)\s*", " ", loc["streetAddress"]).strip()
        out.append({
            "address": f"{street}, San Francisco, CA {loc.get('postalCode', '')}".strip(),
            "lat": loc["latitude"], "lng": loc["longitude"], "neighborhood": None,
        })
    return sorted(out, key=lambda x: x["address"]), data["data"]["locations"]


def ordering_menu_ranges(location_id):
    data = json.loads(get(MENU_URL.format(loc=location_id)))
    ranges = {}

    def walk(node):
        if isinstance(node, dict):
            if "minCalories" in node and node.get("name"):
                ranges[node["name"].strip()] = (node["minCalories"], node["maxCalories"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return ranges


def main():
    page = get(NUTRITION_PAGE).decode("utf-8", "replace")
    if PDF_URL not in page:
        raise SystemExit(f"{NUTRITION_PAGE} no longer links {PDF_URL}")

    rows = parse_pdf(get(PDF_URL))
    print(f"nutrition guide: {len(rows)} published rows")

    items, by_section = [], {}
    for section, label, vals in rows:
        item = build_item(section, label, vals)
        items.append(item)
        by_section.setdefault(section, {})[base_name(section, label)] = vals

    def total(parts):
        out = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0,
               "fiber_g": 0.0, "sodium_mg": 0.0}
        for vals, count in parts:
            for key in out:
                out[key] += (vals.get(key) or 0.0) * count
        return out

    sides = by_section["Sides"]
    derived = []
    for template, section, count, extras, blurb in DERIVED_BUILDS:
        for flavor, vals in by_section[section].items():
            parts = [(vals, count)] + [(sides[e], 1) for e in extras]
            totals = total(parts)
            name = template.format(flavor=flavor)
            recipe = f"{count} x {flavor} {section.lower()}"
            if extras:
                recipe += " + " + " + ".join(extras)
            derived.append({
                "id": slug(name), "name": name,
                "description": f"Standard build: {blurb}. Sum of Wingstop's published "
                               f"per-piece nutrition ({recipe}).",
                "category": "meal", "is_estimate": True,
                "serving_note": "per standard build",
                "source": {"type": "derived", "url": PDF_URL},
                **totals,
            })

    locations, raw_locations = sf_locations()
    if not locations:
        raise SystemExit("no Wingstop locations in San Francisco city proper")

    ranges = ordering_menu_ranges(raw_locations[0]["id"])
    lo, hi = ranges["10 Classic Wings"]
    tens = [d for d in derived if d["name"].endswith("10 pc Classic Wings")]
    out_of_range = [d["name"] for d in tens if not lo <= d["calories"] <= hi]
    print(f"spot check: derived 10 pc classic wing builds span "
          f"{min(d['calories'] for d in tens):.0f}-{max(d['calories'] for d in tens):.0f} kcal "
          f"vs ordering menu range for '10 Classic Wings' {lo}-{hi} kcal")
    if out_of_range:
        raise SystemExit(f"derived wing builds outside the published range: {out_of_range}")

    save_restaurant({
        "id": "wingstop", "name": "Wingstop",
        "website": "https://www.wingstop.com",
        "nutrition_source": {"type": "published", "url": PDF_URL, "vendor": None,
                             "retrieved": TODAY},
        "locations": locations, "items": items + derived,
    })


if __name__ == "__main__":
    main()
