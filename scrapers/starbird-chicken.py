"""Starbird Chicken scraper.

Starbird publishes complete-meal nutrition in a PDF linked from
https://www.starbirdchicken.com/starbird-chicken-nutrition-and-allergy-information
(the PDF filename carries a revision date, so the link is resolved from that
page at run time rather than hard-coded).

The PDF is a real ruled table: extracting text alone interleaves item names
with the number rows and drops the row->name association, so the grid is
rebuilt from the page's ruling lines (horizontal rules = rows, vertical rules
= columns) and every word is placed by its center point. Column order is fixed
by the (rotated, mirror-rendered) header: Calories, Calories From Fat, Total
Fat, Saturated Fat, Cholesterol, Sodium, Carbs, Dietary Fiber, Sugar, Protein.

TRAP: salad and wrap rows carry TWO values per cell ("581 / 752") — grilled
chicken first, fried second — so each of those rows becomes two items. Rows
listed "by the piece" (wings, nuggets) and the "Proteins" pages (single filet /
tender) are components, not orderable meals.

SFO Terminal 1 and South San Francisco are on their locations page but are San
Mateo County, not SF proper; only 60 Morris St is a city location.
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

SITE = "https://starbirdchicken.com"
NUTRITION_PAGE = "https://www.starbirdchicken.com/starbird-chicken-nutrition-and-allergy-information"
LOCATIONS_PAGE = "https://www.starbirdchicken.com/locations-norcal"
NOMINATIM = "https://nominatim.openstreetmap.org/search?format=json&q="
UA = {"User-Agent": "sf-meal-finder/1.0 (nutrition data pipeline)"}
TODAY = datetime.date.today().isoformat()

# order of the numeric columns in the PDF table
COLUMNS = ["calories", "cal_from_fat", "fat_g", "sat_fat_g", "cholesterol_mg",
           "sodium_mg", "carbs_g", "fiber_g", "sugar_g", "protein_g"]

# section header (first row under the column header) -> default category
SECTION_CATEGORY = {
    "sandwiches": "meal", "salads": "meal", "wraps": "meal",
    "tender boxes": "meal", "kids": "meal",
    "nuggets": "component", "bone-in wings": "component",
    "boneless wings": "component", "proteins": "component",
    "sauces": "condiment", "beverages": "drink",
    "treats": "side", "sides": "side",
}
# per-item overrides inside a section (dressings sold with salads, etc.)
CONDIMENT_WORDS = ("dressing", "vinaigrette", "aioli")
# rows priced/listed per piece rather than per order
PER_PIECE_SECTIONS = ("nuggets", "bone-in wings", "boneless wings", "proteins")
# flavour names repeat across the wing sections ("Buffalo" is a bone-in row, a
# boneless row and a sauce), so those rows get the section in their name
SECTION_NOUN = {"bone-in wings": "Bone-In Wing", "boneless wings": "Boneless Wing"}
# listed under Sides but it is a plate of chicken, not an add-on
CATEGORY_OVERRIDES = {"chicken-churros": "meal"}
SERVING_RE = re.compile(r"\(([\d.]+\s*(?:fl\s*oz|oz))\)", re.IGNORECASE)

DIET_SUFFIX = re.compile(r"\s*\b(V|VG|GF|Gf)\b[,\s]*", re.IGNORECASE)


def fetch(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()


def find_pdf_url():
    html = fetch(NUTRITION_PAGE).decode("utf-8", "replace")
    urls = re.findall(r'https://[^"\']+?\.pdf', html)
    for u in urls:
        if "nutrition" in u.lower():
            return u.replace("&amp;", "&")
    raise RuntimeError("nutrition PDF link not found on " + NUTRITION_PAGE)


def num(text):
    """'<1' -> 0.5, '4.5' -> 4.5, '' -> None."""
    text = text.strip().replace(",", "")
    if not text:
        return None
    if text.startswith("<"):
        return 0.5
    m = re.match(r"-?\d+(?:\.\d+)?$", text)
    return float(m.group()) if m else None


def page_rows(page):
    """Rebuild the ruled table: (label, [cell_text, ...]) per row band."""
    h_rules = sorted({round(line["top"], 1) for line in page.lines
                      if line["x1"] - line["x0"] > 200})
    v_rules = sorted({round(line["x0"], 1) for line in page.lines
                      if line["bottom"] - line["top"] > 50})
    if len(h_rules) < 2 or len(v_rules) < 2:
        return []
    words = [w for w in page.extract_words() if w.get("upright", True)]
    rows = []
    for top, bottom in zip(h_rules, h_rules[1:]):
        cells = [[] for _ in v_rules]
        for w in words:
            y = (w["top"] + w["bottom"]) / 2
            if not (top - 1 <= y < bottom):
                continue
            x = (w["x0"] + w["x1"]) / 2
            idx = max([i for i, vx in enumerate(v_rules) if vx <= x + 1] or [0])
            cells[idx].append((round(w["top"], 1), w["x0"], w["text"]))
        joined = [" ".join(t for _, _, t in sorted(c)) for c in cells]
        rows.append((joined[0].strip(), joined[1:]))
    return rows


def split_variants(cells):
    """Salad/wrap cells hold 'grilled / fried'. Return one list per variant."""
    parsed = [re.split(r"\s*/\s*", c.strip().rstrip("/")) if "/" in c else [c.strip()]
              for c in cells]
    width = max(len(p) for p in parsed)
    if width == 1:
        return [[c.strip() for c in cells]]
    return [[p[i] if i < len(p) else p[-1] for p in parsed] for i in range(width)]


def slugify(text):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def clean_name(label):
    name = label.replace("®", "").replace("\u2019", "'")
    name = re.sub(r"\s+", " ", DIET_SUFFIX.sub(" ", name)).strip(" ,")
    return name


def parse_pdf(pdf_bytes, source_url):
    items, seen, seen_rows = [], set(), set()
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            rows = page_rows(page)
            if len(rows) < 2:
                continue
            section_label = rows[1][0]
            section = re.sub(r"\s*(pg ?\d+|\(.*\))\s*$", "", section_label.strip(),
                             flags=re.IGNORECASE).strip().lower()
            category = SECTION_CATEGORY.get(section)
            if category is None:
                continue
            per_piece = section in PER_PIECE_SECTIONS
            for label, cells in rows[2:]:
                if not label or not any(c.strip() for c in cells):
                    continue
                name_raw = re.sub(r"\(No Dressing\)", "", label, flags=re.IGNORECASE)
                serving_match = SERVING_RE.search(name_raw)
                portion = serving_match.group(1).replace(" ", " ") if serving_match else None
                base_name = clean_name(SERVING_RE.sub("", name_raw))
                if not base_name:
                    continue
                noun = SECTION_NOUN.get(section)
                if noun and not base_name.lower().endswith("wing"):
                    base_name = f"{base_name} {noun}"
                no_dressing = "no dressing" in label.lower()
                variants = split_variants(cells)
                prep = ["grilled chicken", "fried chicken"] if len(variants) == 2 else [None]
                for values, prep_label in zip(variants, prep):
                    row = dict(zip(COLUMNS, (num(v) for v in values)))
                    if any(row[k] is None for k in ("calories", "fat_g", "carbs_g", "protein_g")):
                        continue
                    name = base_name if prep_label is None else f"{base_name} ({prep_label})"
                    # the Proteins pages repeat some rows verbatim
                    row_key = (name,) + tuple(row[c] for c in COLUMNS)
                    if row_key in seen_rows:
                        continue
                    seen_rows.add(row_key)
                    item_id = slugify(name)
                    if item_id in seen:
                        item_id = f"{item_id}-{slugify(section)}"
                        if item_id in seen:
                            continue
                    seen.add(item_id)
                    item_category = category
                    if any(w in base_name.lower() for w in CONDIMENT_WORDS) and category in ("meal", "side"):
                        item_category = "condiment"
                    item_category = CATEGORY_OVERRIDES.get(item_id, item_category)
                    if portion:
                        note = f"per {portion} serving"
                    elif section == "sauces":
                        note = "per 1.5 fl oz sauce cup"
                    elif per_piece:
                        note = "per piece"
                    elif no_dressing:
                        note = "per salad, no dressing"
                    else:
                        note = "per item as served"
                    description = None
                    if no_dressing:
                        description = "Nutrition shown without dressing; dressings are listed separately."
                    items.append({
                        "id": item_id,
                        "name": name,
                        "description": description,
                        "category": item_category,
                        "calories": row["calories"],
                        "protein_g": row["protein_g"],
                        "carbs_g": row["carbs_g"],
                        "fat_g": row["fat_g"],
                        "fiber_g": row["fiber_g"],
                        "sodium_mg": row["sodium_mg"],
                        "serving_note": note,
                        "is_estimate": False,
                        "source": {"type": "published", "url": source_url},
                    })
    return items


def sf_locations():
    """Starbird's own location finder; SF proper only (SFO T1 is San Mateo Co.)."""
    html = fetch(LOCATIONS_PAGE).decode("utf-8", "replace")
    text = re.sub(r"<[^>]+>", "\n", html)
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    found = []
    for i, line in enumerate(lines):
        if re.match(r"^San Francisco, CA \d{5}$", line):
            street = lines[i - 1]
            address = f"{street}, {line}"
            if address not in found:
                found.append(address)
    locations = []
    for address in found:
        query = urllib.parse.quote(address)
        data = fetch(NOMINATIM + query)
        hits = json.loads(data)
        if not hits:
            raise RuntimeError("could not geocode " + address)
        locations.append({
            "address": address,
            "lat": float(hits[0]["lat"]),
            "lng": float(hits[0]["lon"]),
            "neighborhood": "SoMa",
        })
    return locations


def main():
    pdf_url = find_pdf_url()
    items = parse_pdf(fetch(pdf_url), pdf_url)
    doc = {
        "id": "starbird-chicken",
        "name": "Starbird Chicken",
        "website": SITE,
        "nutrition_source": {
            "type": "published",
            "url": pdf_url,
            "vendor": None,
            "retrieved": TODAY,
        },
        "locations": sf_locations(),
        "items": items,
    }
    save_restaurant(doc)


if __name__ == "__main__":
    main()
