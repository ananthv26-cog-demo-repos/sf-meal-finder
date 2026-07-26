"""McDonald's nutrition and San Francisco location scraper.

Nutrition comes from the same JSON API the public nutrition calculator uses:

  - product/category listing: the calculator page
    https://www.mcdonalds.com/us/en-us/about-our-food/nutrition-calculator.html
    embeds a ``data-product-data`` JSON blob with the category -> productId map
    and the size variants (itemIds) of every product.
  - per-item nutrition: GET /dnaapp/itemDetails?country=US&language=en&
    showLiveData=true&item=<itemId>, read from labeled ``nutrient_name_id``
    fields, never by position.

TRAP: combo rows ("Egg McMuffin Meal", "The McDouble Meal Deal Bundle") come
back with an empty ``nutrient_facts`` — their nutrition is not published as a
single row. They are derived here as the sum of their published components
(source "derived", is_estimate=True) rather than saved as zeroes.

Locations use the restaurant locator API (/googleappsv2/geolocation, the
endpoint in data-gls-search-api on the locator page), filtered on the city
field: Daly City and South San Francisco stores are excluded even though they
carry SF-adjacent zips. Chain-provided lat/lng is used as-is.
"""

import datetime
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

CALCULATOR_URL = (
    "https://www.mcdonalds.com/us/en-us/about-our-food/nutrition-calculator.html"
)
ITEM_URL = (
    "https://www.mcdonalds.com/dnaapp/itemDetails"
    "?country=US&language=en&showLiveData=true&item={item}"
)
LOCATION_URL = (
    "https://www.mcdonalds.com/googleappsv2/geolocation"
    "?method=searchLocation&latitude={lat}&longitude={lng}"
    "&radius={radius}&maxResults=250&country=us&language=en-us"
)
UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )
}
TODAY = datetime.date.today().isoformat()

# Independently known Big Mac figures, used to prove the parse before trusting it.
BIG_MAC_ID = "200463"
BIG_MAC_EXPECTED = {"calories": 580, "protein_g": 25, "carbs_g": 45, "fat_g": 34}

# Menu-section -> category. Sections not listed here fall through to name rules
# and finally to "component"; nothing defaults to "meal".
SECTION_CATEGORY = {
    "Burgers": "meal",
    "Chicken & Fish Sandwiches": "meal",
    "Snack Wrap®": "meal",
    "McNuggets® & McCrispy® Strips": "meal",
    "Breakfast": "meal",
    "Fries & Sides": "side",
    "Sweets & Treats": "side",
    "McCafé®": "drink",
    "Drinks": "drink",
}
# Rows whose section is ambiguous or wrong for them individually.
NAME_CATEGORY = {
    "hash browns": "side",
    "apple slices": "side",
    "bagel plain": "side",
    "caesar dip cup": "condiment",
}
NAME_KEYWORD_CATEGORY = (
    # LTO sections are named after a sauce ("Caesar Sauce"), so the sandwiches
    # in them have no usable section — match them by name.
    ("mccrispy", "meal"),
    ("snack wrap", "meal"),
    ("burrito", "meal"),
    ("shake", "drink"),
    ("smoothie", "drink"),
    ("dip cup", "condiment"),
    ("sauce", "condiment"),
)

NUTRIENTS = {
    "calories": "calories",
    "protein_g": "protein",
    "carbs_g": "carbohydrate",
    "fat_g": "fat",
    "fiber_g": "fibre",
    "sodium_mg": "sodium",
}


def get_bytes(url, attempts=5):
    """Akamai throttles bursts with a 403; back off and retry rather than dying
    part-way through a few hundred item lookups."""
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers=dict(UA))
            return urllib.request.urlopen(request, timeout=60).read()
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            if attempt == attempts - 1:
                raise
            print(f"  retrying {url} after {exc}")
            time.sleep(3 * (attempt + 1))


def get_json(url):
    return json.loads(get_bytes(url))


def get_text(url):
    return get_bytes(url).decode("utf-8", "replace")


def product_catalog():
    """Return (item id -> [section titles]) from the nutrition calculator page."""
    page = get_text(CALCULATOR_URL)
    match = re.search(r"data-product-data='(.*?)'\s", page, re.S)
    if not match:
        raise RuntimeError("nutrition calculator product data blob not found")
    data = json.loads(html.unescape(match.group(1)))
    sections = {}
    for section in data["categoryList"]:
        for product_id in section["productId"]:
            variants = data["products"].get(product_id, {}).get("sizes") or []
            for item_id in [product_id] + [v["itemId"] for v in variants]:
                titles = sections.setdefault(str(item_id), [])
                if section["title"] not in titles:
                    titles.append(section["title"])
    for product_id in data["products"]:
        sections.setdefault(str(product_id), [])
    return sections


def fetch_items(item_ids):
    def one(item_id):
        return item_id, get_json(ITEM_URL.format(item=item_id)).get("item")

    with ThreadPoolExecutor(4) as pool:
        return {i: item for i, item in pool.map(one, item_ids) if item}


def macros(item):
    """Pull labeled nutrient values; return None if the row has no nutrition."""
    labeled = {
        n["nutrient_name_id"]: n.get("value")
        for n in (item.get("nutrient_facts") or {}).get("nutrient", [])
    }
    values = {}
    for field, key in NUTRIENTS.items():
        raw = labeled.get(key)
        values[field] = float(raw) if isinstance(raw, str) and raw.strip() else None
    if any(values[f] is None for f in ("calories", "protein_g", "carbs_g", "fat_g")):
        return None
    return values


def categorize(name, sections):
    lowered = name.lower().strip()
    if lowered in NAME_CATEGORY:
        return NAME_CATEGORY[lowered]
    for keyword, category in NAME_KEYWORD_CATEGORY:
        if keyword in lowered:
            return category
    for section in sections:
        if section in SECTION_CATEGORY:
            return SECTION_CATEGORY[section]
    print(f"  unmapped section for {name!r} ({sections}) -> component")
    return "component"


def spot_check(items):
    big_mac = macros(items[BIG_MAC_ID])
    got = {k: big_mac[k] for k in BIG_MAC_EXPECTED}
    print(f"Big Mac spot-check: {got}")
    if got != BIG_MAC_EXPECTED:
        raise RuntimeError(
            f"Big Mac parse {got} does not match known {BIG_MAC_EXPECTED}"
        )


def published_items(items, sections):
    out = {}
    for item_id, item in items.items():
        values = macros(item)
        if values is None:
            continue
        name = item["item_name"].strip()
        out[item_id] = {
            "id": f"item-{item_id}",
            "name": name,
            "description": item.get("description") or None,
            "category": categorize(name, sections.get(item_id, [])),
            "serving_note": f"per 1 {name} as listed on the nutrition calculator",
            "is_estimate": False,
            "source": {"type": "published", "url": ITEM_URL.format(item=item_id)},
            **values,
        }
    return out


def combo_items(items, published):
    """Derive combo rows (empty nutrition upstream) as sums of their components."""
    derived = []
    for item_id, item in items.items():
        if macros(item) is not None:
            continue
        components = (item.get("components") or {}).get("component") or []
        parts = [published.get(str(c.get("item_id"))) for c in components]
        if not parts or any(p is None for p in parts):
            unknown = [
                c["item_name"]
                for c, p in zip(components, parts)
                if p is None
            ]
            print(
                f"  skipping combo {item['item_name']!r}: no published nutrition "
                f"for {unknown or 'its components'}"
            )
            continue
        totals = {}
        for field in NUTRIENTS:
            values = [p[field] for p in parts]
            totals[field] = (
                None if any(v is None for v in values) else sum(values)
            )
        recipe = " + ".join(p["name"] for p in parts)
        derived.append(
            {
                "id": f"combo-{item_id}",
                "name": item["item_name"].strip(),
                "description": (
                    f"Combo meal derived as the sum of McDonald's published "
                    f"nutrition for its components: {recipe}. McDonald's does not "
                    f"publish a single nutrition row for the combo."
                ),
                "category": "meal",
                "serving_note": f"per combo meal ({recipe})",
                "is_estimate": True,
                "source": {"type": "derived", "url": ITEM_URL.format(item=item_id)},
                **totals,
            }
        )
    return derived


def locations():
    seen = {}
    # The locator caps each response at ~20 stores, so sweep a grid over the
    # city instead of one wide query.
    centers = [
        (lat, lng, 6)
        for lat in (37.71, 37.74, 37.77, 37.80)
        for lng in (-122.51, -122.47, -122.43, -122.39)
    ]
    for lat, lng, radius in centers:
        payload = get_json(LOCATION_URL.format(lat=lat, lng=lng, radius=radius))
        for feature in payload.get("features", []):
            props = feature["properties"]
            if (props.get("addressLine3") or "").strip() != "San Francisco":
                continue
            lng_, lat_ = feature["geometry"]["coordinates"]
            seen[props.get("identifierValue")] = {
                "address": (
                    f"{props['addressLine1'].strip()}, San Francisco, CA "
                    f"{props.get('postcode', '')}"
                ).strip(),
                "lat": float(lat_),
                "lng": float(lng_),
                "neighborhood": None,
            }
    return sorted(seen.values(), key=lambda loc: loc["address"])


def component_ids(items):
    """Component ids referenced by combo rows but absent from the catalog."""
    referenced = set()
    for item in items.values():
        if macros(item) is not None:
            continue
        for component in (item.get("components") or {}).get("component") or []:
            referenced.add(str(component.get("item_id")))
    return sorted(referenced - set(items))


def main():
    sections = product_catalog()
    items = fetch_items(sorted(sections))
    items.update(fetch_items(component_ids(items)))
    spot_check(items)
    published = published_items(items, sections)
    all_items = list(published.values()) + combo_items(items, published)
    save_restaurant(
        {
            "id": "mcdonalds",
            "name": "McDonald's",
            "website": "https://www.mcdonalds.com",
            "nutrition_source": {
                "type": "published",
                "url": ITEM_URL.format(item="<itemId>"),
                "vendor": None,
                "retrieved": TODAY,
            },
            "locations": locations(),
            "items": all_items,
        }
    )


if __name__ == "__main__":
    main()
