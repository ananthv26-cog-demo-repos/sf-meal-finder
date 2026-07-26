"""Ladle & Leaf scraper.

Nutrition: the chain's own WordPress site publishes a labeled nutrition panel on
every item page (https://ladleandleaf.com/products/<id>/). The panel is a set of
label/value pairs (`<b>Total Fat</b><div class="float-right">20g</div>`), so
values are read by label, never by position, and soups additionally carry an
explicit `Serving Size:` line (12 oz regular).

The item list comes from the six menu pages; each page is a stack of sections
(`<h1 class="text-center title">`), and the section drives the category. Items
repeat across pages (Dressings appear under both Salads and Grain Bowls), so
ids are deduplicated on first sighting.

TRAPS:
- The site's WP REST API exposes no product post type (`/wp/v2/project` is
  empty) — the menu pages are the only index.
- The locations page lists the whole company including Oakland/Berkeley, SFO,
  and stores flagged "(Temporarily Closed)"/"(Permanently closed)" in the store
  name. Only open San Francisco city-proper stores are kept; SFO is outside the
  city proper.
- Some items publish the panel with no Calories value; those are skipped rather
  than zero-filled.
"""

import datetime
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from _geo import geocode  # noqa: E402
from save import save_restaurant  # noqa: E402

BASE = "https://ladleandleaf.com"
MENU_PAGES = ["breakfast", "salads", "grain-bowls", "soups", "sandwiches", "perfect-pairings"]
LOCATIONS_URL = f"{BASE}/locations/"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
TODAY = datetime.date.today().isoformat()

# Menu section -> category. Unknown sections abort instead of defaulting to meal.
SECTIONS = {
    "Seasonal Specials": "meal",
    "Salads": "meal",
    "Grain Bowls": "meal",
    "Sandwiches": "meal",
    "Egg Specialties – Free Range": "meal",
    "Egg Bowls – Free Range": "meal",
    "Steel Cut Oatmeal – Organic": "meal",
    "Avocado Toast": "meal",
    "Burritos": "meal",
    "House of Bagels": "side",
    "Signature Soups": "side",
    "Daily Soups": "side",
    "Dressings": "condiment",
    "Salad Dressing": "condiment",
}

# Nutrition panel label -> item field.
LABELS = {
    "Total Fat": "fat_g",
    "Sodium": "sodium_mg",
    "Total Carbohydrate": "carbs_g",
    "Dietary Fiber": "fiber_g",
    "Protein": "protein_g",
}
PAIR_RE = re.compile(
    r"(?:<b>)?([A-Za-z][A-Za-z ]*?)(?:</b>)?\s*<div class=\"float-right\">([^<]*)</div>"
)
CALORIES_RE = re.compile(r"<div class=\"calories\">\s*<div>Calories\s*([^<]*)</div>")
SERVING_RE = re.compile(r"<div class=\"serving-size\"><b>Serving Size:</b>\s*([^<]*)</div>")
TITLE_RE = re.compile(r"<h1>\s*(.*?)\s*</h1>", re.S)
DESCRIPTION_RE = re.compile(r"</h1>\s*<p>\s*(.*?)\s*</p>", re.S)


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(request, timeout=60).read().decode("utf-8", "replace")


def flat(html):
    return re.sub(r"\s+", " ", html)


def strip_tags(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80]


def number(text):
    """'20g' -> 20.0, '<1g' -> 0.5, '' -> None."""
    text = text.strip()
    if not text:
        return None
    match = re.match(r"(<)?\s*([\d.]+)", text)
    if not match:
        return None
    value = float(match.group(2))
    return value / 2 if match.group(1) else value


def menu_index():
    """{product_id: (section, name)} across all menu pages, first sighting wins."""
    index = {}
    for page in MENU_PAGES:
        html = fetch(f"{BASE}/{page}/")
        for block in re.split(r"<h1 class=\"text-center title\">", html)[1:]:
            head, _, body = block.partition("</h1>")
            section = strip_tags(head)
            products = re.findall(r'href="/products/(\d+)">(.*?)</a>', body)
            if not products:
                continue  # copy-only section, e.g. the Perfect Pairings blurb
            if section not in SECTIONS:
                raise SystemExit(f"ladle-and-leaf: unmapped menu section {section!r} on /{page}/")
            for pid, name in products:
                index.setdefault(pid, (section, strip_tags(name)))
    if not index:
        raise SystemExit("ladle-and-leaf: no products found — menu page shape changed")
    return index


def parse_product(pid, section, listed_name):
    url = f"{BASE}/products/{pid}/"
    html = fetch(url)
    one_line = flat(html)
    calories = number(CALORIES_RE.search(one_line).group(1)) if CALORIES_RE.search(one_line) else None
    values = {}
    for label, raw in PAIR_RE.findall(one_line):
        field = LABELS.get(label.strip())
        if field:
            values[field] = number(raw)
    if calories is None or any(values.get(f) is None for f in ("fat_g", "carbs_g", "protein_g")):
        return None  # panel published without numbers — skip, never zero-fill
    title = TITLE_RE.search(html)
    description = DESCRIPTION_RE.search(html)
    serving = SERVING_RE.search(one_line)
    return {
        "id": f"{slug(listed_name)}-{pid}",
        "name": strip_tags(title.group(1)) if title else listed_name,
        "description": strip_tags(description.group(1)) if description else None,
        "category": SECTIONS[section],
        "calories": calories,
        "protein_g": values["protein_g"],
        "carbs_g": values["carbs_g"],
        "fat_g": values["fat_g"],
        "fiber_g": values.get("fiber_g"),
        "sodium_mg": values.get("sodium_mg"),
        "serving_note": strip_tags(serving.group(1)) if serving else "per item, as served",
        "is_estimate": False,
        "source": {"type": "published", "url": url},
    }


def sf_locations():
    html = fetch(LOCATIONS_URL)
    locations = []
    for block in html.split('<div class="location"')[1:]:
        name = strip_tags(re.search(r'<h1 class="restaurant-name">(.*?)</h1>', block, re.S).group(1))
        address_block = re.search(r'<div class="restaurant-address">(.*?)</div>', block, re.S)
        if not address_block:
            continue
        lines = [strip_tags(p) for p in re.findall(r"<p>(.*?)</p>", address_block.group(1), re.S)]
        lines = [line for line in lines if line and not line.startswith("Telephone")]
        if "closed" in name.lower():
            continue
        city_line = lines[-1] if lines else ""
        if not re.match(r"^San Francisco\s*,", city_line):
            continue
        if "SFO" in name or "Terminal" in name:
            continue  # airport counters are outside the city proper
        street = lines[0]
        address = f"{street}, San Francisco, CA"
        lat, lng = geocode(f"{street}, San Francisco, CA")
        locations.append({"address": address, "lat": lat, "lng": lng, "neighborhood": None})
    if not locations:
        raise SystemExit("ladle-and-leaf: no open SF city-proper locations found")
    return locations


# Reference rows read off the published item pages by eye, to catch a parse
# that silently shifts labels or picks up the % daily value columns.
SPOT_CHECKS = {
    "2223": ("Harvest", {"calories": 380, "fat_g": 20, "carbs_g": 29, "protein_g": 29,
                         "fiber_g": 4, "sodium_mg": 720}),
    "1988": ("Grandma Mary’s Chicken Soup", {"calories": 133, "fat_g": 4, "carbs_g": 8,
                                             "protein_g": 14, "fiber_g": 2, "sodium_mg": 701}),
}


def spot_check():
    for pid, (name, expected) in SPOT_CHECKS.items():
        item = parse_product(pid, "Salads", name)
        if item is None:
            raise SystemExit(f"ladle-and-leaf: spot-check item {pid} has no nutrition panel")
        actual = {k: item[k] for k in expected}
        if actual != expected:
            raise SystemExit(f"ladle-and-leaf: {name} parsed {actual}, expected {expected}")
        print(f"spot check ok: {name} {actual}")


def main():
    spot_check()
    index = menu_index()
    items, skipped = [], []
    for pid, (section, name) in sorted(index.items(), key=lambda kv: int(kv[0])):
        item = parse_product(pid, section, name)
        if item is None:
            skipped.append((pid, name))
        else:
            items.append(item)
        time.sleep(0.2)
    if skipped:
        print(f"ladle-and-leaf: {len(skipped)} item(s) published no nutrition numbers, skipped: "
              + ", ".join(f"{name} ({pid})" for pid, name in skipped[:10]))
    save_restaurant({
        "id": "ladle-and-leaf",
        "name": "Ladle & Leaf",
        "website": BASE + "/",
        "nutrition_source": {
            "type": "published",
            "url": f"{BASE}/products/",
            "vendor": None,
            "retrieved": TODAY,
        },
        "locations": sf_locations(),
        "items": items,
    })


if __name__ == "__main__":
    main()
