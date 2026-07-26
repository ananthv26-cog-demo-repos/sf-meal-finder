"""Taco Bell scraper.

tacobell.com's own /nutrition/info page is an empty shell: the nutrition table
is an iframe onto Taco Bell's contracted vendor, Nutritionix
(https://www.nutritionix.com/taco-bell/menu/premium), which serves the full
grid as server-rendered HTML (readable from curl). Source type is therefore
"vendor" / nutritionix. The tacobell.com ordering menu
(/tacobellwebservices/v4/tacobell/products/menu/<storeId>) publishes calories
only -- no macros -- so it is used purely to cross-check the vendor parse.

Locations: /tacobellwebservices/v2/tacobell/stores?latitude=&longitude=
returns nearByStores with chain-provided geoPoint lat/lng. Its radius is small,
so SF is swept with a grid of query points and de-duplicated by store number.

TRAP: the vendor grid mixes real menu sections with regional Cantina beer/wine/
spirits lists. Alcohol rows fail the macro undershoot check by design (7 kcal/g
of alcohol is not in the macros) and are correctly quarantined.
"""

import datetime
import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

VENDOR_URL = "https://www.nutritionix.com/taco-bell/menu/premium"
STORES_URL = "https://www.tacobell.com/tacobellwebservices/v2/tacobell/stores?latitude={lat}&longitude={lng}&_=0"
MENU_URL = "https://www.tacobell.com/tacobellwebservices/v4/tacobell/products/menu/0000"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
TODAY = datetime.date.today().isoformat()

# Query points covering San Francisco (the locator returns a short radius list).
SWEEP = [
    (37.808, -122.415), (37.795, -122.394), (37.784, -122.408), (37.775, -122.418),
    (37.765, -122.432), (37.752, -122.410), (37.735, -122.395), (37.723, -122.435),
    (37.760, -122.470), (37.780, -122.470), (37.740, -122.480), (37.712, -122.470),
]

DRINK_SECTIONS = {
    "Drinks", "Live Mas Cafe", "Cantina Menu", "Cantina Beer, Wine and Spirits",
    "Las Vegas Cantina Menu", "Dirty Sodas", "Fountain Beverages (16 oz)",
    "Fountain Beverages (20 oz)", "Fountain Beverages (30 oz)",
}

# Substrings that identify a row regardless of the section it appears in.
DRINK_WORDS = (
    "freeze", "refresca", "limonada", "coffee", "cold brew", "chiller", "frost",
    "matcha", "milk", "orange juice", "water", "soda", "lemonade", "iced tea",
)
CONDIMENT_WORDS = ("sauce packet", "salsa packet", "salsa verde packet", "creamer")
SIDE_WORDS = (
    "cinnabon", "cinnamon twists", "hash brown", "black beans", "pintos n cheese",
    "cheesy fiesta potatoes", "nacho fries", "chips and", "cheesy roll up",
    "crispy chicken strips", "crème brulee crunchwrap", "creme brulee crunchwrap",
)
MEAL_WORDS = (
    "taco", "burrito", "chalupa", "gordita", "crunchwrap", "quesadilla", "nachos",
    "mexican pizza", "stacker", "bowl", "flatbread melt", "taco salad", "griller",
)


def get(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    data = urllib.request.urlopen(req, timeout=45).read()
    return data if binary else data.decode("utf-8", "replace")


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:70]


def categorize(section, name):
    n = name.lower()
    if any(w in n for w in CONDIMENT_WORDS):
        return "condiment"
    if section in DRINK_SECTIONS or any(w in n for w in DRINK_WORDS):
        return "drink"
    if any(w in n for w in SIDE_WORDS):
        return "side"
    if section == "Sides & Sweets":
        return "side"
    if any(w in n for w in MEAL_WORDS):
        return "meal"
    return "component"


def serving_note(name):
    m = re.search(r"\((\d+)\s*(?:fl\s*)?oz\)", name, re.I)
    if m:
        return f"per {m.group(1)} oz cup, as served"
    if "serves 4" in name.lower():
        return "per 12-piece pack (serves 4)"
    if "(2 pk)" in name.lower() or "(2 pack)" in name.lower():
        return "per 2-piece order"
    return "per item, as sold"


def num(cell):
    t = re.sub(r"<[^>]+>", "", cell)
    t = html.unescape(t).replace(",", "").strip()
    if t in ("", "-", "N/A", "n/a"):
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    return float(m.group()) if m else None


def parse_vendor_grid(page):
    """Parse the Nutritionix grid by labeled header ids, never by position."""
    header_by_id = {}
    for hid, inner in re.findall(r'<th id="(inmGrid_c\d+)"[^>]*>(.*?)</th>', page, re.S):
        label = html.unescape(re.sub(r"<[^>]+>", " ", inner))
        label = re.sub(r"Sort by.*", "", label)
        header_by_id[hid] = re.sub(r"\s+", " ", label).strip()

    wanted = {
        "Calories": "calories", "Total Fat (g)": "fat_g",
        "Total Carbohydrates (g)": "carbs_g", "Protein (g)": "protein_g",
        "Dietary Fiber (g)": "fiber_g", "Sodium (mg)": "sodium_mg",
    }
    field_by_id = {hid: wanted[lab] for hid, lab in header_by_id.items() if lab in wanted}
    missing = set(wanted.values()) - set(field_by_id.values())
    if missing:
        raise SystemExit(f"vendor grid is missing labeled columns: {sorted(missing)}")

    body = page[page.find("<tbody>"):]
    rows = re.findall(r'<tr class="(subCategory|odd|even)">(.*?)</tr>', body, re.S)
    section, out = None, []
    for cls, row in rows:
        if cls == "subCategory":
            section = html.unescape(re.search(r"<h3>(.*?)</h3>", row, re.S).group(1)).strip()
            continue
        name_m = re.search(r'class="nmItem"[^>]*>(.*?)</a>', row, re.S)
        if not name_m:
            continue
        name = html.unescape(re.sub(r"<[^>]+>", "", name_m.group(1))).strip()
        cells = dict(re.findall(r'<td[^>]*headers="(inmGrid_c\d+)"[^>]*>(.*?)</td>', row, re.S))
        vals = {field: num(cells.get(hid, "")) for hid, field in field_by_id.items()}
        out.append((section, name, vals))
    return out


def sf_locations():
    seen, locs = set(), []
    for lat, lng in SWEEP:
        data = json.loads(get(STORES_URL.format(lat=lat, lng=lng)))
        for store in data.get("nearByStores", []):
            addr = store.get("address") or {}
            if (addr.get("town") or "").strip().lower() != "san francisco":
                continue
            number = store.get("storeNumber")
            if number in seen:
                continue
            seen.add(number)
            geo = store.get("geoPoint") or {}
            if geo.get("latitude") is None:
                continue
            line = re.sub(r"\s*-\s*Mobile Order.*$", "", addr.get("line1", "")).strip()
            locs.append({
                "address": f"{line}, San Francisco, CA {addr.get('postalCode', '')}".strip(),
                "lat": geo["latitude"], "lng": geo["longitude"], "neighborhood": None,
            })
        time.sleep(0.5)
    return sorted(locs, key=lambda x: x["address"])


def ordering_menu_calories():
    """Calories-only ordering menu, used to cross-check the vendor parse."""
    data = json.loads(get(MENU_URL))
    cals = {}
    for cat in data.get("menuProductCategories", []):
        for p in cat.get("products", []):
            try:
                cals[p["name"].replace("®", "").replace("™", "").strip()] = float(p["calories"])
            except (KeyError, ValueError, AttributeError):
                continue
    return cals


def main():
    page = get(VENDOR_URL)
    rows = parse_vendor_grid(page)
    print(f"vendor grid: {len(rows)} rows")

    items, seen_ids, unmatched = [], set(), []
    for section, name, vals in rows:
        if vals["calories"] is None or vals["fat_g"] is None:
            continue
        iid = slug(name)
        if iid in seen_ids:
            continue
        seen_ids.add(iid)
        category = categorize(section, name)
        if category == "component":
            unmatched.append(f"{section} / {name}")
        items.append({
            "id": iid, "name": name, "description": f"Taco Bell menu section: {section}.",
            "category": category, "is_estimate": False,
            "serving_note": serving_note(name),
            "source": {"type": "vendor", "url": VENDOR_URL},
            "calories": vals["calories"], "protein_g": vals["protein_g"] or 0.0,
            "carbs_g": vals["carbs_g"] or 0.0, "fat_g": vals["fat_g"],
            "fiber_g": vals["fiber_g"], "sodium_mg": vals["sodium_mg"],
        })

    # Spot check: Crunchwrap Supreme against Taco Bell's own ordering menu.
    cals = ordering_menu_calories()
    check = next(i for i in items if i["name"].startswith("Crunchwrap Supreme"))
    stated = cals.get("Crunchwrap Supreme")
    print(f"spot check Crunchwrap Supreme: vendor {check['calories']} kcal vs "
          f"tacobell.com ordering menu {stated} kcal")
    if stated is None or abs(stated - check["calories"]) > 10:
        raise SystemExit("Crunchwrap Supreme calories disagree — do not trust this parse")

    if unmatched:
        print(f"{len(unmatched)} row(s) defaulted to 'component' (extend the mapping):")
        for u in unmatched:
            print("   ", u)

    save_restaurant({
        "id": "taco-bell", "name": "Taco Bell",
        "website": "https://www.tacobell.com",
        "nutrition_source": {"type": "vendor", "url": VENDOR_URL,
                             "vendor": "nutritionix", "retrieved": TODAY},
        "locations": sf_locations(), "items": items,
    })


if __name__ == "__main__":
    main()
