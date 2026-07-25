"""Tender Greens scraper for the published nutrition PDF.

The PDF is an OCR-flattened scan.  Numeric-column OCR occasionally turns
digits into letters, so correction is deliberately limited to numeric columns
and documented below.  Names and sections are kept in an explicit table
because the section headings themselves are also OCR-damaged.
"""

import datetime
import difflib
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402


PDF_URL = "https://www.tendergreens.com/wp-content/uploads/2026/03/TG-Nutrition-03.11.26.pdf"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
TODAY = datetime.date.today().isoformat()
PDF_PATH = Path("/tmp/tg.pdf")

# (item, field) -> (printed value, corrected value).  The printed value is
# retained here so a future PDF revision cannot silently change the policy.
CORRECTIONS = {
    ("seasonal vegetables", "fat_g"): (
        41,
        11,
        "calories-from-fat is 101, which reconciles to 11 g fat; 41 g is OCR noise",
    ),
}

LEFT_COLUMNS = [126, 142, 158, 174, 188, 203, 215, 233, 248, 263, 278]
RIGHT_COLUMNS = [414, 430, 446, 462, 477, 491, 504, 521, 537, 552, 566]
FIELDS = (
    "calories",
    "calories_from_fat",
    "fat_g",
    "sat_fat_g",
    "trans_fat_g",
    "cholesterol_mg",
    "sodium_mg",
    "carbs_g",
    "fiber_g",
    "sugar_g",
    "protein_g",
)

# Canonical name -> section.  This table is intentionally the source of
# sectioning rather than the garbled all-caps headings in the PDF.
ITEM_SECTIONS = {
    "country-style fried chicken": "PROTEIN",
    "chipotle bbq chicken": "PROTEIN",
    "chipotle bbq chicken salad": "SALADS",
    "chicken katsu": "PROTEIN",
    "grilled shrimp": "PROTEIN",
    "salt & pepper chicken": "PROTEIN",
    "seared tuna": "PROTEIN",
    "grilled steak": "PROTEIN",
    "baked falafel": "PROTEIN",
    "grilled sea bass": "PROTEIN",
    "short rib": "PROTEIN",
    "short rib special": "SPECIALS",
    "fried chicken": "SANDWICHES",
    "avocado toast": "SANDWICHES",
    "baby arugula": "GREENS & SIDES",
    "baby greens": "GREENS & SIDES",
    "baby spinach": "GREENS & SIDES",
    "romaine hearts": "GREENS & SIDES",
    "mashed potatoes": "GREENS & SIDES",
    "mashed potatoes w/gravy": "GREENS & SIDES",
    "roasted potatoes": "GREENS & SIDES",
    "seasonal vegetables": "GREENS & SIDES",
    "seasoned fries": "GREENS & SIDES",
    "brown rice": "GREENS & SIDES",
    "sushi rice": "GREENS & SIDES",
    "farro salad": "GREENS & SIDES",
    "mac & cheese": "GREENS & SIDES",
    "crostini": "GREENS & SIDES",
    "braised beans": "GREENS & SIDES",
    "roasted beets": "GREENS & SIDES",
    "bolognese sauce": "GREENS & SIDES",
    "tuna nicoise": "SALADS",
    "mediterranean steak": "SALADS",
    "italian chop": "SALADS",
    "grilled salmon": "PROTEIN",
    "grilled salmon salad": "SALADS",
    "tomato mozzarella": "SALADS",
    "grilled chicken cobb": "SALADS",
    "harvest chicken": "SALADS",
    "roasted tomato: cup": "SOUPS",
    "roasted tomato: bowl": "SOUPS",
    "rustic chicken: cup": "SOUPS",
    "rustic chicken: bowl": "SOUPS",
    "green pozole cup": "SOUPS",
    "green pozole bowl": "SOUPS",
    "burger patty": "PROTEIN",
    "tender burger": "SANDWICHES",
    "chipotle bbq chicken sandwich": "SANDWICHES",
    "chicken pesto": "SANDWICHES",
    "salami provolone": "SANDWICHES",
    "kids: salt & pepper chicken": "JUST FOR KIDS",
    "kids: chicken tenders": "JUST FOR KIDS",
    "kids: steak": "JUST FOR KIDS",
    "kids: bolognese": "JUST FOR KIDS",
    "kids: nonna's pasta": "JUST FOR KIDS",
    "kids: mac & cheese": "JUST FOR KIDS",
    "grilled cheese": "JUST FOR KIDS",
    "california: chipotle bbq chicken": "BOWLS",
    "california: grilled salmon": "BOWLS",
    "pacific: katsu chicken": "BOWLS",
    "pacific: grilled salmon": "BOWLS",
    "thai: grilled shrimp": "BOWLS",
    "thai: grilled steak": "BOWLS",
    "happier vegan": "BOWLS",
    "longevity: braised beans": "SPECIALS",
    "longevity: grilled sea bass": "SPECIALS",
    "bolognese pasta": "SPECIALS",
    "chicken pesto pasta": "SPECIALS",
    "tender burger plate": "SPECIALS",
    "mint lemonade": "BEVERAGES",
    "the greens": "BEVERAGES",
    "hibiscus tea": "BEVERAGES",
    "pineapple basil agua fresca": "BEVERAGES",
    "chocolate chunk cookie": "DESSERTS",
    "salted caramel cookie": "DESSERTS",
    "carrot cupcake": "DESSERTS",
    "olive oil cake": "DESSERTS",
    "hostess chocolate cake": "DESSERTS",
    "sherry vinaigrette": "DRESSINGS",
    "roasted garlic vinaigrette": "DRESSINGS",
    "lemon vinaigrette": "DRESSINGS",
    "tarragon dressing": "DRESSINGS",
    "caesar dressing": "DRESSINGS",
    "cabernet vinaigrette": "DRESSINGS",
    "cilantro lime dressing": "DRESSINGS",
    "balsamic vinaigrette": "DRESSINGS",
    "sesame peanut dressing": "DRESSINGS",
    "limecrema": "DRESSINGS",
    "ginger dressing": "DRESSINGS",
    "spicy mayo": "DRESSINGS",
    "garlic aioli": "DRESSINGS",
}

ALIASES = {
    "mostess chocolate cake": "hostess chocolate cake",
    "mac&cheese": "mac & cheese",
    "cabemet vinaigrette": "cabernet vinaigrette",
    "califomia chipotle bbq chicken": "california: chipotle bbq chicken",
    "califomia grilled salmon": "california: grilled salmon",
    "pacific katsu chicken": "pacific: katsu chicken",
    "pacific grilled salmon": "pacific: grilled salmon",
    "thai grilled shrimp": "thai: grilled shrimp",
    "thai grilled steak": "thai: grilled steak",
    "kids salt & pepper chicken": "kids: salt & pepper chicken",
    "kids chicken tenders": "kids: chicken tenders",
    "kids steak": "kids: steak",
    "kids bolognese": "kids: bolognese",
    "kids nonna's pasta": "kids: nonna's pasta",
    "kids mac & cheese": "kids: mac & cheese",
    "longevity braised beans": "longevity: braised beans",
    "longevity grilled sea bass": "longevity: grilled sea bass",
    "roasted tomato cup": "roasted tomato: cup",
    "roasted tomato bowl": "roasted tomato: bowl",
    "rustic chicken cup": "rustic chicken: cup",
    "rustic chicken bowl": "rustic chicken: bowl",
    "green pozole cup": "green pozole cup",
    "green pozole bowl": "green pozole bowl",
}

CATEGORY_MAP = {
    "PROTEIN": "component",
    "GREENS & SIDES": "side",
    "SOUPS": "side",
    "DESSERTS": "side",
    "BEVERAGES": "drink",
    "DRESSINGS": "condiment",
    "SALADS": "meal",
    "BOWLS": "meal",
    "SANDWICHES": "meal",
    "SPECIALS": "meal",
    "JUST FOR KIDS": "meal",
}


def normalize_name(text):
    text = text.lower().replace(":", " ").replace("/", " ")
    text = re.sub(r"[^a-z0-9&']+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonical_name(text):
    normalized = normalize_name(text)
    if normalized in ALIASES:
        return ALIASES[normalized]
    for name in ITEM_SECTIONS:
        if normalize_name(name) == normalized:
            return name
    choices = list(ITEM_SECTIONS)
    match = difflib.get_close_matches(normalized, [normalize_name(x) for x in choices], n=1, cutoff=0.84)
    if match:
        return choices[[normalize_name(x) for x in choices].index(match[0])]
    return None


def numeric_token(text):
    # Apply the OCR letter map only after a token has been selected by its
    # position in a numeric column.
    corrected = text.translate(str.maketrans({"s": "5", "S": "5", "l": "1", "I": "1", "O": "0", "o": "0"}))
    if not re.fullmatch(r"\d+(?:\.\d+)?", corrected):
        return None
    return float(corrected) if "." in corrected else int(corrected)


def extract_table(pdf_path):
    rows = {}
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages[:2]):
            words = page.extract_words(x_tolerance=1, y_tolerance=3)
            for side, (xmin, xmax, columns) in {
                "left": (0, 310, LEFT_COLUMNS),
                "right": (310, 620, RIGHT_COLUMNS),
            }.items():
                numeric = []
                names = []
                for word in words:
                    x, y = word["x0"], word["top"]
                    if not (xmin <= x < xmax and 75 <= y <= 740):
                        continue
                    if (side == "left" and x < 115) or (side == "right" and 315 <= x < 405):
                        if not numeric_token(word["text"]):
                            names.append((y, x, word["text"]))
                    if any(abs(x - c) <= 9 for c in columns):
                        value = numeric_token(word["text"])
                        if value is not None:
                            column = min(range(len(columns)), key=lambda i: abs(x - columns[i]))
                            numeric.append((y, column, value))

                name_lines = []
                for y, x, text in sorted(names):
                    if name_lines and abs(y - name_lines[-1][0]) <= 3:
                        name_lines[-1][1].append((x, text))
                    else:
                        name_lines.append([y, [(x, text)]])
                name_lines = [(y, " ".join(t for _, t in sorted(parts))) for y, parts in name_lines]

                clusters = []
                for y, column, value in sorted(numeric):
                    if clusters and y - clusters[-1][0] <= 6:
                        clusters[-1][1][column] = value
                    else:
                        clusters.append([y, {column: value}])

                for value_y, values in clusters:
                    if len(values) < 8:
                        continue
                    nearby = [(abs(value_y - y), y, text) for y, text in name_lines if -3 <= value_y - y <= 15]
                    if not nearby:
                        continue
                    _, name_y, raw_name = min(nearby)
                    name = canonical_name(raw_name)
                    if not name:
                        continue
                    if side == "right" and name == "chipotle bbq chicken":
                        name = "chipotle bbq chicken salad" if value_y < 200 else "chipotle bbq chicken sandwich"
                    elif side == "right" and name == "grilled salmon":
                        name = "grilled salmon salad"
                    elif side == "right" and name == "short rib":
                        name = "short rib special"
                    # A name can occur in both columns on a page, so page and
                    # side are part of the key while assembling the document.
                    key = (page_number, side, name)
                    rows[key] = (value_y, values)
    return rows


def geocode():
    query = urllib.parse.urlencode({"format": "json", "q": "30 Fremont St, San Francisco, CA 94105"})
    request = urllib.request.Request(
        f"{NOMINATIM_URL}?{query}",
        headers={"User-Agent": "sf-meal-finder/1.0 (nutrition scraper)"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        results = json.load(response)
    if not results:
        raise RuntimeError("Nominatim returned no result for 30 Fremont St")
    return {
        "address": "30 Fremont St, San Francisco, CA 94105",
        "lat": float(results[0]["lat"]),
        "lng": float(results[0]["lon"]),
        "neighborhood": "Financial District",
    }


def download_pdf():
    if PDF_PATH.exists():
        return
    request = urllib.request.Request(
        PDF_URL,
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        PDF_PATH.write_bytes(response.read())


def main():
    download_pdf()
    parsed = extract_table(PDF_PATH)
    items = []
    seen = set()
    for (_, side, name), (_, values) in parsed.items():
        if name in seen:
            continue
        if len(values) < len(FIELDS):
            continue
        seen.add(name)
        macros = dict(zip(FIELDS, [values[i] for i in range(len(FIELDS))]))
        for field in ("calories", "fat_g", "carbs_g", "fiber_g", "sodium_mg", "protein_g"):
            if isinstance(macros[field], float) and macros[field].is_integer():
                macros[field] = int(macros[field])
        if (name, "fat_g") in CORRECTIONS:
            _, corrected, _ = CORRECTIONS[(name, "fat_g")]
            macros["fat_g"] = corrected
        section = ITEM_SECTIONS[name]
        category = CATEGORY_MAP[section]
        if section == "SOUPS":
            serving_note = f"per {name.rsplit(':', 1)[-1].strip()}"
        elif section == "DESSERTS":
            serving_note = "per dessert item"
        elif section == "GREENS & SIDES":
            serving_note = "per serving; greens include dressing and toppings"
        elif section == "PROTEIN":
            serving_note = "per protein portion"
        elif section == "DRESSINGS":
            serving_note = "per serving"
        elif section == "BEVERAGES":
            serving_note = "per beverage"
        else:
            serving_note = "per menu item as served"
        item = {
            "id": re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"),
            "name": name,
            "description": None,
            "category": category,
            "calories": macros["calories"],
            "protein_g": macros["protein_g"],
            "carbs_g": macros["carbs_g"],
            "fat_g": macros["fat_g"],
            "fiber_g": macros["fiber_g"],
            "sodium_mg": macros["sodium_mg"],
            "serving_note": serving_note,
            "is_estimate": False,
            "source": {"type": "published", "url": PDF_URL},
        }
        items.append(item)

    proteins = [i for i in items if i["category"] == "component"]
    side_map = {i["name"]: i for i in items if i["category"] == "side"}
    mashed = side_map["mashed potatoes"]
    greens = side_map["baby greens"]
    for protein in proteins:
        total = {}
        for field in ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sodium_mg"):
            total[field] = sum((x.get(field) or 0) for x in (protein, mashed, greens))
        plate_name = f"{protein['name']} plate"
        items.append({
            "id": re.sub(r"[^a-z0-9]+", "-", plate_name.lower()).strip("-"),
            "name": plate_name,
            "description": (
                f"Standard plate build: {protein['name']} with mashed potatoes "
                "and baby greens (simply dressed). Sum of published component nutrition."
            ),
            "category": "meal",
            **total,
            "serving_note": "per plate: one protein portion, mashed potatoes, and baby greens",
            "is_estimate": True,
            "source": {"type": "derived", "url": PDF_URL},
        })

    save_restaurant({
        "id": "tender-greens",
        "name": "Tender Greens",
        "website": "https://www.tendergreens.com",
        "nutrition_source": {"type": "published", "url": PDF_URL, "vendor": None, "retrieved": TODAY},
        "locations": [geocode()],
        "items": items,
    })


if __name__ == "__main__":
    main()
