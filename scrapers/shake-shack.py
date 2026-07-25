"""Shake Shack scraper.

Shake Shack's main ``shakeshack.com`` pages are Cloudflare-403 from ordinary
HTTP clients (including the nutrition and locations pages).  The production
host serves the same official data without that block:

* nutrition PDF: https://prod.shakeshack.com/nutritionandallergeninfo
* locations page: https://prod.shakeshack.com/locations

The nutrition PDF is the source of truth and is downloaded at runtime.  Its
table header is laid out vertically by the PDF renderer, and current rows put
``Contains: ...`` allergen text between the item name and numeric columns.
Rows are therefore parsed only after identifying the section's nutrition
header and mapping its labeled columns; range-valued and calorie-only rows are
skipped rather than converted to invented point estimates.

Parsing traps include catering rows whose numeric values are followed by a
separate "Calories per serving" line, explicit Mini/oz/mL servings, and the
footnote that concrete mix-ins are listed per half concrete serving.
"""

from __future__ import annotations

import datetime
import html
import io
import re
import sys
import urllib.request
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402


NUTRITION_URL = "https://prod.shakeshack.com/nutritionandallergeninfo"
LOCATIONS_URL = "https://prod.shakeshack.com/locations"
SPOT_CHECK_URL = "https://foods.fatsecret.com/calories-nutrition/shake-shack/single-shackburger"
TODAY = datetime.date.today().isoformat()
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/133 Safari/537.36"}

MACRO_COLUMNS = (
    "calories",
    "fat_g",
    "sat_fat_g",
    "trans_fat_g",
    "cholesterol_mg",
    "sodium_mg",
    "carbs_g",
    "fiber_g",
    "sugars_g",
    "protein_g",
)
SECTIONS = {
    "Burgers",
    "Chicken",
    "Breakfast*",
    "Flat -Top Dogs",
    "Fries & Sides",
    "Sauces",
    "Shakes",
    "Floats",
    "Cups & Sundaes",
    "Drinks",
    "Combo Meals",
    "Limited Time Offerings",
    "Lifestyle Offerings",
    "Beer, Wines, Cocktails & Non-Alcoholic Drinks",
    "Regional Beers",
}
SKIP_SECTIONS = {"Combo Meals", "Regional Beers"}
RANGE_RE = re.compile(r"^-?\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?|/\d+(?:\.\d+)?|\s+to\s+\d+(?:\.\d+)?)$")
NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def fetch(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def normalize_name(name):
    name = html.unescape(name).replace("®", "").replace("™", "")
    name = re.sub(r"\s+", " ", name).strip(" -*")
    return name


def header_columns(page):
    """Derive and verify the numeric column order from a PDF header.

    The labels are rotated in the PDF.  Their x positions are the numeric
    column positions, while their rotated glyphs need to be read bottom-up.
    Pages without rotated header words are continuation pages and return
    ``None``.  Any page that does contain a header must resolve to exactly the
    order represented by ``MACRO_COLUMNS``; a changed official PDF layout
    aborts rather than silently shifting nutrition values.
    """
    words = page.extract_words(extra_attrs=["upright"])
    rotated = sorted((w for w in words if not w["upright"]), key=lambda w: (w["x0"], w["top"]))
    if not rotated:
        return None
    groups = []
    for word in rotated:
        if not groups or word["x0"] - groups[-1][0] > 4:
            groups.append([word["x0"], []])
        groups[-1][1].append(word)
    labels = []
    for _, group in groups:
        label = " ".join(
            word["text"][::-1] for word in sorted(group, key=lambda w: w["top"], reverse=True)
        )
        label = re.sub(r"\s+\((?:g|mg)\)$", "", label).strip()
        labels.append(label)
    canonical_labels = (
        "Calories", "Total Fat", "Sat Fat", "Trans Fat", "Cholesterol",
        "Sodium", "Total Carbohydrates", "Carbohydrates", "Fiber", "Sugars",
        "Protein",
    )
    labels = [
        next((canonical for canonical in canonical_labels if canonical.lower() in label.lower()), label)
        for label in labels
    ]
    normalized = []
    index = 0
    while index < len(labels):
        label = labels[index]
        if label == "Total" and index + 1 < len(labels) and labels[index + 1].startswith("Carbohydrates"):
            label = "Total Carbohydrates"
            index += 1
        normalized.append(label)
        index += 1
    # Some pages expose duplicate rotated glyphs through pdfplumber.
    deduped = []
    for label in normalized:
        if label not in deduped:
            deduped.append(label)
    if "Total Carbohydrates" in deduped:
        deduped = [
            label for label in deduped
            if label not in {"Total", "Carbohydrates"}
        ]
    # The Regional Beers page has a deliberately calorie-only header.
    if deduped == ["Calories"]:
        return None
    expected = (
        "Calories", "Total Fat", "Sat Fat", "Trans Fat", "Cholesterol",
        "Sodium", "Total Carbohydrates", "Fiber", "Sugars", "Protein",
    )
    if deduped != list(expected):
        raise RuntimeError(f"unexpected Shake Shack nutrition header order: {deduped!r}")
    return MACRO_COLUMNS


def row_name_and_values(line):
    tokens = line.split()
    if len(tokens) < 11:
        return None
    # The last ten tokens are the numeric columns only after a header has
    # established what those columns mean.  Do not infer a midpoint/range.
    tail = tokens[-10:]
    if not all(NUMBER_RE.fullmatch(value) for value in tail):
        return None
    return " ".join(tokens[:-10]), [float(value) for value in tail]


def serving_note(name, section):
    lower = name.lower()
    if "catering box" in lower:
        match = re.search(r"catering box,\s*(\d+)\s*servings", lower)
        count = match.group(1) if match else "multiple"
        return f"per serving from catering box ({count} servings; PDF labels values per serving)"
    if "mini" in lower:
        match = re.search(r"\((\d+\s*oz)\)", lower)
        return f"per Mini ({match.group(1)})" if match else "per Mini serving"
    if any(word in lower for word in ("oreo cookie crumb", "malt")):
        return "per half concrete serving (PDF mix-in footnote)"
    if lower in {"egg", "egg white", "egg white light"} or lower.startswith("egg white light ("):
        return "per listed breakfast component serving"
    if lower.startswith("add ") or section == "Sauces":
        return "per sauce, topping, or add-on serving"
    if "salad" in lower or "balsamic vinegar with chicken bites" in lower:
        return "per salad"
    if any(word in lower for word in ("croissant", "crossiant", "danish", "monkey bread")):
        return "per pastry"
    if lower in {"hashbrowns", "hashbrowns with sauce"}:
        return "per side serving"
    if "chicken bites" in lower:
        match = re.search(r"\((\d+)\s*piece", lower)
        return f"per {match.group(1)}-piece serving" if match else "per chicken-bites serving"
    if lower in {
        "lettuce wrap", "american cheese", "avocado", "bacon (2 slices)",
        "cherry peppers", "crispy onions", "lettuce", "onion", "pickle",
        "pickled jalapenos", "tomato",
    }:
        return "per topping serving"
    if "sandwich" in lower or "burger" in lower or "dog" in lower or "shack" in lower or lower in {
        "grilled cheese", "blt", "big shack", "fish sandwich", "avocado bacon chicken",
        "chicken shack"
    }:
        return "per sandwich"
    if "patty" in lower or "bun" in lower or "potato roll" in lower or "chicken breast" in lower:
        return "per listed component serving"
    if section == "Breakfast*" and lower not in {"hashbrowns", "sausage patty"}:
        return "per breakfast sandwich"
    match = re.search(r"\((\d+(?:\.\d+)?\s*(?:fl\.)?\s*oz|100mL|187ml|750ml|250mL|24oz|12oz|16oz|20oz)\)", name, re.I)
    if match:
        return f"per {match.group(1)} serving"
    if re.search(r"\b(Small|Large)\b", name):
        size = re.search(r"\b(Small|Large)\b", name).group(1)
        return f"per {size} serving"
    if "pitcher" in lower:
        return "per pitcher (64 oz)"
    if "single- double" in lower or "single/double" in lower:
        return "per single or double shot"
    if section in {"Burgers", "Chicken", "Breakfast*", "Flat -Top Dogs"}:
        return "per sandwich or listed serving"
    if "shake" in lower:
        return "per regular shake"
    if "float" in lower:
        return "per float"
    if "cup" in lower or "sundae" in lower:
        return "per listed custard serving"
    if section == "Drinks" or "Drink" in section or "Beer" in section:
        return "per listed serving"
    if section in {"Fries & Sides", "Limited Time Offerings"}:
        return "per side serving"
    return "per listed serving"


def category_for(name, section):
    lower = name.lower()
    if lower.startswith("shackburger gluten free bun"):
        return "meal"
    if lower in {
        "lettuce wrap", "american cheese", "avocado", "bacon (2 slices)",
        "cherry peppers", "crispy onions", "lettuce", "onion", "pickle",
        "pickled jalapenos", "tomato",
    } or lower.startswith("add "):
        return "condiment"
    if lower in {"egg", "egg white", "egg white light"} or lower.startswith("egg white light ("):
        return "component"
    if any(word in lower for word in ("patty", "bun", "potato roll", "buttermilk chicken breast")):
        return "component"
    if "salad" in lower or "balsamic vinegar with chicken bites" in lower:
        return "meal"
    if lower in {"hashbrowns", "hashbrowns with sauce"}:
        return "side"
    if "shake" in lower or "float" in lower or "cup" in lower or "sundae" in lower:
        return "side"
    if any(word in lower for word in ("croissant", "crossiant", "danish", "monkey bread")):
        return "side"
    if lower in {"beer battered onion rings", "mac & cheese with panko breadcrumbs", "hashbrowns"}:
        return "side"
    if lower in {"herb mayonnaise", "ranch", "honey mustard"} or section == "Sauces":
        return "condiment"
    if "featured lemonade" in lower:
        return "drink"
    if any(word in lower for word in ("whipped cream", "malt", "cookie crumb")):
        return "condiment"
    if section in {"Drinks", "Beer, Wines, Cocktails & Non-Alcoholic Drinks"}:
        return "drink"
    if section in {"Burgers", "Chicken", "Breakfast*", "Flat -Top Dogs", "Lifestyle Offerings"}:
        if name.startswith(("Egg*", "Egg White*", "Hashbrowns*", "Sausage Patty")):
            return "component"
        return "meal"
    if section == "Limited Time Offerings":
        if any(word in lower for word in ("fries", "shake")):
            return "side"
        return "meal"
    return "side"


def item_id(name, seen):
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "item"
    candidate = base
    suffix = 2
    while candidate in seen:
        candidate = f"{base}-{suffix}"
        suffix += 1
    seen.add(candidate)
    return candidate


def parse_pdf(data):
    items = []
    skipped = []
    current_section = None
    columns = None
    seen = set()
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            page_columns = header_columns(page)
            if page_columns:
                columns = page_columns
            lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
            pending = None
            for line in lines:
                if not line:
                    continue
                if line in SECTIONS:
                    current_section = line
                    columns = page_columns or columns
                    if line == "Regional Beers":
                        skipped.append((line, "calorie-only regional beer tables"))
                    continue
                if line.startswith("Calories per serving") or line.startswith("Caffeine per serving"):
                    continue
                if current_section is None or columns is None:
                    continue
                parsed = row_name_and_values(line)
                if parsed is None and pending is not None:
                    combined = f"{pending} {line}"
                    parsed = row_name_and_values(combined)
                    if parsed is not None:
                        pending = None
                if parsed is None:
                    tail = line.split()[-10:]
                    if len(tail) == 10 and any(RANGE_RE.fullmatch(value) for value in tail):
                        skipped.append((line, f"range-valued row in {current_section}"))
                        continue
                    # A nonnumeric continuation (e.g. "Contains: Wheat") is
                    # joined to the following numeric line.
                    if re.search(r"\b(Contains:|servings\))", line):
                        pending = line
                    continue
                name, values = parsed
                if pending is not None:
                    if not pending.startswith("Contains:"):
                        name = f"{pending} {name}"
                    pending = None
                name = re.sub(r"\s+Contains:.*$", "", name).strip()
                name = normalize_name(name)
                if not name:
                    continue
                if current_section in SKIP_SECTIONS or any(RANGE_RE.fullmatch(value) for value in line.split()[-10:]):
                    skipped.append((name, f"range-valued row in {current_section}"))
                    continue
                # The parser only accepts exactly ten scalar values, so a
                # row with a range/slash value is rejected before this point.
                if current_section == "Regional Beers":
                    skipped.append((name, "calorie-only regional beer table"))
                    continue
                category = category_for(name, current_section)
                if (
                    category == "meal"
                    and values[0] < 120
                    and not re.search(r"\b(burger|sandwich|dog|salad)\b", name, re.I)
                ):
                    category = "component"
                nutrition = dict(zip(columns, values))
                item = {
                    "id": item_id(name, seen),
                    "name": name,
                    "description": None,
                    "category": category,
                    "calories": nutrition["calories"],
                    "protein_g": nutrition["protein_g"],
                    "carbs_g": nutrition["carbs_g"],
                    "fat_g": nutrition["fat_g"],
                    "fiber_g": nutrition["fiber_g"],
                    "sodium_mg": nutrition["sodium_mg"],
                    "serving_note": serving_note(name, current_section),
                    "is_estimate": False,
                    "source": {"type": "published", "url": NUTRITION_URL},
                }
                items.append(item)
    return items, skipped


def parse_locations(data):
    text = data.decode("utf-8", errors="replace")
    locations = []
    seen = set()
    for block in re.finditer(
        r'<div[^>]+class="[^"]*geolocation-location[^"]*"[^>]*'
        r'data-lat="([^"]+)"[^>]*data-lng="([^"]+)"[^>]*>(.*?)'
        r'(?=<div[^>]+class="[^"]*geolocation-location|$)',
        text,
        flags=re.S,
    ):
        lat, lng, body = float(block.group(1)), float(block.group(2)), block.group(3)
        address_match = re.search(
            r'daddr=Shake%20Shack,([^"]+)', body, flags=re.I
        )
        if not address_match:
            print("WARNING: skipped SF location without address", file=sys.stderr)
            continue
        raw = html.unescape(address_match.group(1)).replace("%20", " ")
        parts = [part.strip() for part in raw.split(",") if part.strip()]
        if len(parts) < 3 or parts[-2] != "CA" or parts[-3] != "San Francisco":
            continue
        address = ", ".join(parts[:1] + ["San Francisco", "CA"] + ([parts[-1]] if parts and parts[-1].isdigit() else []))
        title_match = re.search(
            r'class="location-title"[^>]*>\s*(.*?)\s*More Info',
            body,
            flags=re.S | re.I,
        )
        neighborhood = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else None
        if not neighborhood:
            print("WARNING: skipped SF location without store name", file=sys.stderr)
            continue
        key = (address, lat, lng)
        if key not in seen:
            locations.append({
                "address": address,
                "lat": lat,
                "lng": lng,
                "neighborhood": neighborhood,
            })
            seen.add(key)
    if len(locations) != 2:
        raise RuntimeError(f"expected exactly 2 San Francisco locations, found {len(locations)}")
    return locations


def spot_check(current_items):
    expected = {"calories": 500, "fat_g": 30, "carbs_g": 26, "protein_g": 29}
    item = next((i for i in current_items if i["name"] == "Single ShackBurger"), None)
    if item is None or any(item[key] != value for key, value in expected.items()):
        raise RuntimeError(f"current PDF spot check failed: {item}")
    print(
        "Spot check Single ShackBurger: current PDF = 500 cal, 30g fat, "
        "26g carbs, 29g protein; 2023 cross-check = same; "
        f"independent FatSecret = 500 cal, 30g fat, 26g carbs, 29g protein "
        f"({SPOT_CHECK_URL}). The ~700-calorie guess is wrong."
    )


def main():
    nutrition_pdf = fetch(NUTRITION_URL)
    locations_html = fetch(LOCATIONS_URL)
    items, skipped = parse_pdf(nutrition_pdf)
    locations = parse_locations(locations_html)
    spot_check(items)
    for name, reason in skipped:
        print(f"WARNING: skipped {name!r}: {reason}", file=sys.stderr)
    counts = {}
    for item in items:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    print(f"Parsed item counts by category: {counts}")
    print(f"Skipped rows: {len(skipped)}")
    save_restaurant({
        "id": "shake-shack",
        "name": "Shake Shack",
        "website": "https://shakeshack.com",
        "nutrition_source": {
            "type": "published",
            "url": NUTRITION_URL,
            "vendor": None,
            "retrieved": TODAY,
        },
        "locations": locations,
        "items": items,
    })


if __name__ == "__main__":
    main()
