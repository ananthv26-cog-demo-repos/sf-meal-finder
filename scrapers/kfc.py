"""Fetch KFC's Nutritionix grid and official KFC locator directory."""

import datetime
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

VENDOR_URL = "https://www.nutritionix.com/kfc/menu/premium"
LOCATOR_URL = "https://locations.kfc.com/ca/san-francisco"
TODAY = datetime.date.today().isoformat()

DRINK_WORDS = (r"\bpepsi\b", r"\b7up\b", r"\bdr pepper\b", r"\btea\b", r"\bcoffee\b", r"\blemonade\b", r"\bjuice\b", r"\bcapri sun\b", r"\bbeverage\b", r"\bwater\b")
CONDIMENT_WORDS = (r"\bsauce\b", r"\bdressing\b", r"\bgravy\b", r"\bhoney\b", r"\bcondiment\b")
SIDE_WORDS = (r"\bside\b", r"\bfries\b", r"\bbeans\b", r"\bbiscuit\b", r"\bcoleslaw\b", r"\bpotatoes\b", r"\bmac & cheese\b", r"\bcorn\b", r"\bcookie\b", r"\bpie\b", r"\bapplesauce\b", r"\bcrouton\b", r"\bwedge")
MEAL_WORDS = (r"\bsandwich\b", r"\bpot pie\b", r"\bbowl\b", r"\bbucket\b", r"\bbox\b", r"\bcombo\b", r"\bmeal\b", r"\bfill up\b", r"\btwister\b", r"\bsnacker\b", r"\bwings?\b", r"\bsteak\b")


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(request, timeout=60).read().decode("utf-8", "replace")


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def num(value):
    match = re.search(r"\d+(?:\.\d+)?", clean(value).replace(",", ""))
    return float(match.group()) if match else None


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80]


def category(section, name):
    text = f"{section} {name}".lower()
    if re.search(r"\(\s*1\s*\)", name):
        return "component"
    if section == "Kids Meal Applesauce":
        return "side"
    if section in ("Sandwiches", "Pot Pie and Bowls", "Kids Meal"):
        return "meal" if "applesauce" not in text else "side"
    if section in ("Limited Time Offers", "Regional Menu Items"):
        if any(re.search(word, text) for word in MEAL_WORDS):
            return "meal"
        if any(re.search(word, text) for word in CONDIMENT_WORDS):
            return "condiment"
        if any(re.search(word, text) for word in SIDE_WORDS):
            return "side"
        if re.search(r"\bfried pickles?\b|\bpopcorn chicken\b", text):
            return "side"
        if re.search(r"\bdip cup\b", text):
            return "condiment"
    if section in ("Beverages", "Kids Drinks"):
        return "drink"
    if section in ("Dipping Sauces & Condiments", "Dressing and Croutons"):
        return "condiment"
    if section in ("Homestyle Sides (Family)", "Homestyle Sides (Individual)", "Desserts", "Salads"):
        return "side"
    if any(re.search(word, text) for word in MEAL_WORDS):
        return "meal"
    if any(re.search(word, text) for word in CONDIMENT_WORDS):
        return "condiment"
    if any(re.search(word, text) for word in SIDE_WORDS):
        return "side"
    if any(re.search(word, text) for word in DRINK_WORDS):
        return "drink"
    return "component"


def serving_note(name):
    match = re.search(r"\(([^)]+)\)", name)
    if match:
        return f"per {match.group(1)}"
    if re.search(r"\beach\b", name, re.I):
        return "per each"
    if re.search(r"\bfamily\b", name, re.I):
        return "per family serving"
    return "per listed serving"


def parse_grid(page):
    headers = {}
    for hid, inner in re.findall(r'<th id="(inmGrid_c\d+)"[^>]*>(.*?)</th>', page, re.S):
        headers[hid] = clean(re.sub(r"Sort by.*", "", inner))
    wanted = {
        "Calories": "calories", "Total Fat (g)": "fat_g",
        "Total Carbohydrates (g)": "carbs_g", "Protein (g)": "protein_g",
        "Dietary Fiber (g)": "fiber_g", "Sodium (mg)": "sodium_mg",
    }
    field_by_id = {hid: wanted[label] for hid, label in headers.items() if label in wanted}
    if set(field_by_id.values()) != set(wanted.values()):
        raise SystemExit("Nutritionix grid labels changed")
    rows, section = [], "UNKNOWN"
    for cls, row in re.findall(r'<tr class="(subCategory|odd|even)">(.*?)</tr>', page[page.find("<tbody>"):], re.S):
        if cls == "subCategory":
            heading = re.search(r"<h3>(.*?)</h3>", row, re.S)
            section = clean(heading.group(1)) if heading else "UNKNOWN"
            continue
        name_match = re.search(r'class="nmItem"[^>]*>(.*?)</a>', row, re.S)
        if not name_match:
            continue
        cells = dict(re.findall(r'<td[^>]*headers="(inmGrid_c\d+)"[^>]*>(.*?)</td>', row, re.S))
        values = {field: num(cells.get(hid, "")) for hid, field in field_by_id.items()}
        if values["calories"] is None or values["fat_g"] is None:
            continue
        rows.append({"section": section, "name": clean(name_match.group(1)), **values})
    return rows


def locations():
    page = fetch(LOCATOR_URL)
    stores, seen = [], set()
    for block in re.findall(r'<article class="Teaser[^>]*>.*?</article>', page, re.S):
        city = re.search(r'class="c-address-city">(.*?)</span>', block, re.S)
        street = re.search(r'class="c-address-street-1">(.*?)</span>', block, re.S)
        postal = re.search(r'class="c-address-postal-code"[^>]*>(.*?)</span>', block, re.S)
        if not city or not street or clean(city.group(1)) != "San Francisco":
            continue
        address = f"{clean(street.group(1))}, San Francisco, CA {clean(postal.group(1)) if postal else ''}".strip()
        if address in seen:
            continue
        seen.add(address)
        query = urllib.parse.quote(address)
        request = urllib.request.Request(
            "https://nominatim.openstreetmap.org/search?format=json&q=" + query,
            headers={"User-Agent": "sf-meal-finder/1.0 (research)"},
        )
        geo = json.load(urllib.request.urlopen(request, timeout=45))
        if geo:
            stores.append({"address": address, "lat": float(geo[0]["lat"]), "lng": float(geo[0]["lon"]), "neighborhood": None})
        time.sleep(1.05)
    return stores


def main():
    rows = parse_grid(fetch(VENDOR_URL))
    print(f"Nutritionix grid parsed rows: {len(rows)}")
    check = next(row for row in rows if "Original Recipe" in row["section"] and "Chicken Breast" in row["name"])
    print(f"Original Recipe Chicken Breast parsed spot-check: {check['calories']:.0f} kcal")
    if check["calories"] != 390:
        raise SystemExit("Original Recipe Chicken Breast calories disagree with known value")
    items, seen, unmatched = [], set(), []
    for row in rows:
        iid = slug(row["name"])
        if iid in seen:
            continue
        seen.add(iid)
        cat = category(row["section"], row["name"])
        if cat == "component" and row["section"] not in (
            "Original Recipe Chicken", "Extra Crispy Chicken",
            "Kentucky Grilled Chicken", "Spicy Crispy Chicken",
            "Original Recipe® Tenders", "Kentucky Fried Nuggets",
        ):
            unmatched.append(f"{row['section']} / {row['name']}")
        items.append({
            "id": iid, "name": row["name"], "description": f"KFC menu section: {row['section']}.",
            "category": cat, "calories": row["calories"], "protein_g": row["protein_g"] or 0,
            "carbs_g": row["carbs_g"] or 0, "fat_g": row["fat_g"], "fiber_g": row["fiber_g"],
            "sodium_mg": row["sodium_mg"], "serving_note": serving_note(row["name"]),
            "is_estimate": False, "source": {"type": "vendor", "url": VENDOR_URL},
        })
    if unmatched:
        print(f"{len(unmatched)} row(s) defaulted to component:")
        for row in unmatched:
            print("  ", row)
    save_restaurant({
        "id": "kfc", "name": "KFC", "website": "https://www.kfc.com",
        "nutrition_source": {"type": "vendor", "url": VENDOR_URL, "vendor": "nutritionix", "retrieved": TODAY},
        "locations": locations(), "items": items,
    })


if __name__ == "__main__":
    main()
