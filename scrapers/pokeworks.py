"""Pokeworks nutrition scraper.

The nutrition guide is a PDF whose table cells are positioned text rather
than reliably delimited rows.  Numeric values are therefore assigned to the
published columns by their x coordinates; blank cells stay blank.
"""

import datetime
import json
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

NUTRITION_URL = "https://pokeworks.com/wp-content/uploads/2026/03/Pokeworks-Nutrition-Guide-v.2.0-BGA.pdf"
LOCATOR_URL = "https://pokeworks.com/wp-admin/admin-ajax.php?action=asl_load_stores&load_all=1&layout=1"
TODAY = datetime.date.today().isoformat()
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}

# Addresses/coords from Pokeworks' Agile Store Locator API
# (https://pokeworks.com/wp-admin/admin-ajax.php?action=asl_load_stores&load_all=1&layout=1;
#  75 stores, filtered city == "San Francisco"); coords cross-checked against Nominatim.
LOCATIONS = [
    {"address": "50 Fremont St #R2A, San Francisco, CA 94105", "lat": 37.790749, "lng": -122.397131, "neighborhood": "SoMa"},
]

# Centers of the rotated table headers, from the PDF's table grid/header cells.
COLUMN_CENTERS = (151, 171, 192, 212, 232, 252, 272, 292, 312, 332, 352)
COLUMN_NAMES = (
    "portion", "calories", "fat_g", "saturated_fat_g", "trans_fat_g",
    "cholesterol_mg", "sodium_mg", "carbs_g", "sugar_g", "protein_g", "fiber_g",
)
NUMBER_RE = re.compile(r"^(?:<|[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)$")
SECTIONS = {
    "PROTEIN": ("component", "protein"),
    "BASE": ("component", "base"),
    "MIX-INS": ("component", "mix-ins"),
    "TOPPINGS": ("component", "toppings"),
    "CRUNCH": ("component", "crunch"),
    "SAUCE": ("condiment", "sauce"),
    "SIGNATURE WORKS": ("meal", "bowl"),
    "HAWAIIAN HOT PLATES": ("meal", "plate"),
    "BURRITOS": ("meal", "burrito"),
    "SIDES": ("side", "side"),
    "DESSERTS": ("side", "dessert"),
    "POKE BOMBS": ("side", "poke-bomb"),
    "BEVERAGES": ("drink", "beverage"),
    "SIGNATURE DRINKS": ("drink", "signature-drink"),
    "ADD-INS": ("component", "add-in"),
}
MEAL_SECTIONS = {"SIGNATURE WORKS", "HAWAIIAN HOT PLATES", "BURRITOS"}
NEIGHBORHOODS = {"50 fremont st #r2a": "SoMa"}


def _download_pdf():
    request = urllib.request.Request(NUTRITION_URL, headers=HEADERS)
    response = urllib.request.urlopen(request, timeout=30)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as output:
        output.write(response.read())
        return output.name


def _number(text):
    if text == "<":
        # The guide's "< 1" cells are represented by two words; use 0.5.
        return 0.5
    return float(text.replace(",", ""))


def _row_value(words, center):
    cells = [w["text"] for w in words if abs((w["x0"] + w["x1"]) / 2 - center) <= 9]
    if not cells:
        return None
    if cells[0] == "<":
        return 0.5
    return _number(cells[0])


def _section_for_line(text, current):
    upper = text.upper()
    if "SIGNATURE WORKS" in upper:
        return "SIGNATURE WORKS"
    for heading in SECTIONS:
        if upper == heading or upper.startswith(f"{heading} "):
            return heading
    return current


def _rows(pdf_path):
    current = None
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            grouped = []
            words = [word for word in page.extract_words() if word["upright"]]
            for word in sorted(words, key=lambda w: w["top"]):
                if not grouped or word["top"] - grouped[-1][0] > 1.0:
                    grouped.append((word["top"], [word]))
                else:
                    grouped[-1][1].append(word)
            for _, words in grouped:
                row_words = sorted(words, key=lambda w: w["x0"])
                line = " ".join(w["text"] for w in row_words)
                current = _section_for_line(line, current)
                if current is None or current == "POKE BOWLS":
                    continue
                numeric = [
                    w for w in row_words
                    if 140 <= w["x0"] <= 360 and NUMBER_RE.match(w["text"])
                ]
                if len(numeric) < 8:
                    continue
                values = [_row_value(numeric, center) for center in COLUMN_CENTERS]
                if values[1] is None or values[2] is None:
                    continue
                name_words = [w["text"] for w in row_words if w["x0"] < 140]
                name = " ".join(name_words).strip()
                if not name:
                    continue
                portion_words = [
                    w["text"] for w in row_words
                    if 140 <= w["x0"] < 165 and w["text"] not in {"<"}
                ]
                portion_text = " ".join(portion_words).strip()
                # PDF text extraction can join the beverage name and its portion,
                # e.g. "Green Tea10.5 oz". Preserve the drink name and recover
                # the glued numeric portion.
                glued = re.search(r"(Tea|Fresca|Lemonade|Latte)(\d+(?:\.\d+)?)$", name)
                if glued:
                    name = name[:glued.start()] + glued.group(1)
                    if portion_text == "oz":
                        portion_text = f"{glued.group(2)} oz"
                if not portion_text:
                    match = re.match(r"^(.*) (\d+(?:\.\d+)?\s*oz)$", name)
                    if match:
                        name, portion_text = match.groups()
                yield current, name, portion_text, values, line


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _serving_note(section, portion):
    if section == "PROTEIN":
        return f"per {portion} oz scoop"
    if section == "BASE":
        return f"per {portion} portion"
    if section == "SAUCE":
        pumps = {"Light": "1 pump", "Medium": "2 pumps", "Heavy": "3 pumps"}
        return f"per {pumps.get(portion, portion)}"
    if re.fullmatch(r"\d+(?:\.0)?", portion or ""):
        return "per single piece"
    if section in MEAL_SECTIONS:
        return f"per {portion}"
    return f"per {portion} portion" if portion else None


def _display_name(section, name, portion):
    if section == "SIGNATURE WORKS":
        return f"{name} Bowl"
    if section == "BURRITOS":
        return f"{name} Burrito"
    if section == "POKE BOMBS":
        return f"{name} Poke Bomb"
    if portion and not re.fullmatch(r"\d+(?:\.0)?", portion):
        return f"{name} ({portion})"
    return name


def parse_pdf(pdf_path, rows=None):
    items = []
    source_rows = rows if rows is not None else _rows(pdf_path)
    for section, name, portion, values, _ in source_rows:
        data = dict(zip(COLUMN_NAMES, values))
        if data["calories"] is None or data["fat_g"] is None or data["carbs_g"] is None or data["protein_g"] is None:
            raise ValueError(f"missing required nutrition cell for {section}/{name} ({values})")
        category, prefix = SECTIONS[section]
        if section in MEAL_SECTIONS:
            item_id = f"{prefix}-{_slug(name)}"
        elif section == "PROTEIN":
            item_id = f"component-protein-{_slug(name)}"
        else:
            item_id = f"{prefix}-{_slug(name)}-{_slug(portion)}" if portion else f"{prefix}-{_slug(name)}"
        display_name = _display_name(section, name, portion)
        items.append({
            "id": item_id,
            "name": display_name,
            "description": None,
            "category": category,
            "calories": data["calories"],
            "protein_g": data["protein_g"],
            "carbs_g": data["carbs_g"],
            "fat_g": data["fat_g"],
            "fiber_g": data["fiber_g"],
            "sodium_mg": data["sodium_mg"],
            "serving_note": _serving_note(section, portion),
            "is_estimate": False,
            "source": {"type": "published", "url": NUTRITION_URL},
        })
    return items


def _locations():
    request = urllib.request.Request(LOCATOR_URL, headers=HEADERS)
    try:
        raw = urllib.request.urlopen(request, timeout=30).read().decode()
        # The endpoint has returned both a JSON array and JSON wrapped in HTML
        # in different locator versions; find the store objects conservatively.
        payload = json.loads(raw)
        if isinstance(payload, dict):
            payload = payload.get("stores") or payload.get("data") or payload.get("markers") or []
        found = []
        for store in payload:
            city = str(store.get("city") or store.get("asl_city") or "").strip()
            if city.lower() != "san francisco":
                continue
            address = store.get("address") or store.get("asl_address") or ""
            if not address and store.get("street"):
                address = ", ".join(
                    part for part in (
                        store.get("street"),
                        city,
                        store.get("state"),
                        store.get("postal_code") or store.get("postalCode"),
                    ) if part
                )
            lat = store.get("lat") or store.get("latitude") or store.get("asl_lat")
            lng = store.get("lng") or store.get("longitude") or store.get("asl_lng")
            if address and lat is not None and lng is not None:
                key = re.sub(r"\s+", " ", address.lower().replace(".", "")).strip()
                neighborhood = next(
                    (value for known, value in NEIGHBORHOODS.items() if known in key),
                    None,
                )
                found.append({
                    "address": address, "lat": float(lat), "lng": float(lng),
                    "neighborhood": neighborhood,
                })
        if found:
            return found
    except (OSError, ValueError, TypeError):
        pass
    return LOCATIONS


def main():
    pdf_path = _download_pdf()
    try:
        rows = list(_rows(pdf_path))
        items = parse_pdf(pdf_path, rows)
        wanted = {("SIGNATURE WORKS", "Spicy Ahi Tuna (Regular)"), ("PROTEIN", "Ahi Tuna")}
        for section, name, portion, values, raw_line in rows:
            if (section, name) in wanted:
                print(
                    f"spot-check {section}/{name}: raw pdfplumber line: {raw_line} || "
                    f"parsed columns: {dict(zip(COLUMN_NAMES, values))}"
                )
        print(f"parsed {len(items)} items; unique ids: {len({item['id'] for item in items})}")
        print("parsed drink rows:")
        for item in items:
            if item["category"] == "drink":
                print(f"  {item['name']} | {item['serving_note']}")
        save_restaurant({
            "id": "pokeworks",
            "name": "Pokeworks",
            "website": "https://pokeworks.com",
            "nutrition_source": {"type": "published", "url": NUTRITION_URL, "vendor": None, "retrieved": TODAY},
            "locations": _locations(),
            "items": items,
        })
    finally:
        Path(pdf_path).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
