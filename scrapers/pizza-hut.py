"""Pizza Hut scraper.

Nutrition: pizzahut.com/nutrition links straight out to Pizza Hut's contracted
Nutritionix pages — the grid used here is
https://www.nutritionix.com/pizza-hut/menu/premium (source "vendor", vendor
"nutritionix"), verified by loading pizzahut.com/nutrition in real Chrome over
CDP (curl gets nothing from pizzahut.com; the page is bot-blocked).

TRAP — everything pizza is PER SLICE, and the denominator is only in the
*section header*, not the row: "Medium Chicago Tavern-Style Slices 1 serving =
1 slice = 1/16 of pizza" vs "1/8" for hand tossed vs "1/4" for Personal Pan and
"1/12" for buffet. Worse, the Express sections are named for whole pizzas
("Bacon - Express Personal Pan Pizza®") but the section header still says
1 serving = 1 slice = 1/4 of pizza. So:
  - published slice rows -> category "component", serving_note "per slice
    (1/N of pizza)"
  - whole pizzas are DERIVED as N x the published slice (source "derived",
    is_estimate=True, recipe in description) -> those are the "meal" rows
  - buffet slices are not derived (a 12-slice buffet pizza isn't an order)
  - "Big New Yorker Slices" carries no denominator; its sibling component
    section ("Cheese - Big New Yorker ... 1 slice = 1/6th of pizza") does, so 6
    is used explicitly
  - "Deep Dish Pizza" rows are labelled "Slice" with no denominator published,
    so they stay components and no whole pizza is derived.

TRAP: Wings rows are per SINGLE wing ("Buffalo Mild Bone-Out Wing" = 1 wing),
and "Wing Sauces & Rubs" rows are the sauce for one wing — components and
condiments, not sides.

Locations: official Yext locator locations.pizzahut.com. Exactly one Pizza Hut
in SF city proper — 233 Winston Dr. (a Pizza Hut Express in Stonestown), which
is why the Express menu sections matter here. Coordinates come from the store
page's own geocodedCoordinate, so no geocoding.
"""

from __future__ import annotations

import datetime
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE))

import _nutritionix as nx  # noqa: E402
from save import save_restaurant  # noqa: E402

BRAND = "pizza-hut"
MENU_URL = nx.menu_url(BRAND)
LOCATOR_CITY_URL = "https://locations.pizzahut.com/ca/san-francisco"
LOCATOR_BASE = "https://locations.pizzahut.com/"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0.0.0 Safari/537.36"}

# Per-slice building blocks published so guests can add up their own pizza.
COMPONENT_SECTION_PREFIXES = (
    "Cheese - ", "Crust - ", "Sauce - ", "Toppings - ",
    "Drizzles & Finishers", "Crust Finisher",
)

SECTION_CATEGORY = {
    "Pasta": "meal",
    "P'Zone": "meal",
    "Sandwich": "meal",
    "Express Sandwiches": "meal",
    "Soup": "side",
    "Sides": "side",
    "Express Sides": "side",
    "Dessert": "side",
    "Dipping Sauce": "condiment",
    "Wing Sauces & Rubs": "condiment",
    "Salad Dressing": "condiment",
    "Drinks": "drink",
    "Beer and Wine": "drink",
    "Wings": "component",      # each row is ONE wing
}

_PACKET_RE = re.compile(r"\bpacket\b|dipping cup|icing", re.I)
_SIDE_SALAD_RE = re.compile(r"side salad|side/small salad", re.I)


def slices_per_pizza(section: str):
    """Slices in a whole pizza for a pizza-slice section, else None."""
    m = re.search(r"1 slice = 1/(\d+)(?:th)? of pizza", section)
    if m:
        return int(m.group(1))
    if section.startswith("Big New Yorker Slices"):
        return 6  # stated in the "Cheese - Big New Yorker" section header
    return None


def is_component_section(section: str) -> bool:
    return section.startswith(COMPONENT_SECTION_PREFIXES)


def categorize(section: str, name: str) -> str:
    if section in SECTION_CATEGORY:
        cat = SECTION_CATEGORY[section]
        if cat == "side" and _PACKET_RE.search(name):
            return "condiment"
        return cat
    if section.startswith("Salad Dressing"):
        return "condiment"
    if section.startswith(("Salad", "Express Salads")):
        return "side" if _SIDE_SALAD_RE.search(name) else "meal"
    if section.startswith("Buffet Pasta"):
        return "side"
    if section == "Pizza Hut Melts":
        # A "Half Melt" is half of one Melt order, not an order by itself.
        return "component" if "Half Melt" in name else "meal"
    if section == "Express Breakfast":
        return "side" if "hashbrown" in name.lower() else "component"
    if is_component_section(section) or slices_per_pizza(section) or section == "Deep Dish Pizza":
        return "component"
    return "component"


def serving_note(section: str, name: str) -> str:
    n = slices_per_pizza(section)
    if is_component_section(section):
        what = section.split(" - ")[0].lower()
        return f"per slice, {what} only" + (f" (1/{n} of pizza)" if n else "")
    if n:
        buffet = " from the buffet" if "Buffet" in section else ""
        return f"per slice (1/{n} of pizza){buffet}"
    if section == "Deep Dish Pizza":
        return "per slice (fraction of pizza not published)"
    if section == "Wings":
        return "per 1 wing"
    if section.startswith("Wing Sauces"):
        m = re.search(r"\(per ([^)]+)\)", name)
        return f"per {m.group(1)}" if m else "per 1 wing"
    if section.startswith("Buffet Pasta"):
        return "per 4 oz buffet serving"
    if section == "Pizza Hut Melts" and "Half Melt" in name:
        return "per half melt (half of one Melt order)"
    if section == "Express Breakfast":
        return "per serving as published (slice vs whole pizza not stated)"
    if section.startswith("Salad") and _SIDE_SALAD_RE.search(name):
        return "per side salad, without dressing"
    if section.startswith(("Salad", "Express Salads")):
        return "per salad, without dressing"
    return "per item as served"


def sf_locations():
    """SF-city-proper stores from the official Yext locator, with the store
    page's own coordinates. The city page embeds its store list as
    URL-encoded JSON under `dm_directoryChildren`."""
    page = urllib.request.urlopen(
        urllib.request.Request(LOCATOR_CITY_URL, headers=UA), timeout=60
    ).read().decode("utf-8", "replace")
    decoded = urllib.parse.unquote(page)
    m = re.search(r'"dm_directoryChildren":(\[.*?\}\])', decoded, re.S)
    if not m:
        raise SystemExit("pizza-hut: dm_directoryChildren not found on the city page")
    stores = json.loads(m.group(1))

    locations = []
    for s in stores:
        addr = s.get("address") or {}
        if (addr.get("city") or "").strip() != "San Francisco" or addr.get("region") != "CA":
            continue
        slug = (s.get("slug") or "").rstrip(".")
        store_page = urllib.request.urlopen(
            urllib.request.Request(LOCATOR_BASE + slug, headers=UA), timeout=60
        ).read().decode("utf-8", "replace")
        c = re.search(
            r'"geocodedCoordinate":\{"latitude":(-?[\d.]+),"longitude":(-?[\d.]+)\}',
            urllib.parse.unquote(store_page),
        )
        if not c:
            raise SystemExit(f"pizza-hut: no coordinates on store page {slug}")
        street = addr["line1"].rstrip(".")
        locations.append({
            "address": f"{street}, San Francisco, CA {addr.get('postalCode', '')}".strip(),
            "lat": float(c.group(1)),
            "lng": float(c.group(2)),
            "neighborhood": None,
        })
    return locations


def main() -> None:
    html = nx.fetch(BRAND)
    retrieved = nx.last_updated(html) or datetime.date.today().isoformat()

    items, seen = [], set()
    for row in nx.parse_rows(html):
        if row.get("calories") is None:
            continue
        name, section = row["name"], row["section"] or ""
        macros = {
            "calories": row["calories"],
            "protein_g": row.get("protein_g") or 0,
            "carbs_g": row.get("carbs_g") or 0,
            "fat_g": row.get("fat_g") or 0,
            "fiber_g": row.get("fiber_g"),
            "sodium_mg": row.get("sodium_mg"),
        }
        items.append({
            "id": nx.dedupe_id(nx.slug(name), seen),
            "name": name,
            "description": f"Pizza Hut menu section: {section.split(' 1 serving')[0]}." if section else None,
            "category": categorize(section, name),
            "serving_note": serving_note(section, name),
            "is_estimate": False,
            "source": {"type": "vendor", "url": MENU_URL},
            **macros,
        })

        n = slices_per_pizza(section)
        derivable = (
            n
            and not is_component_section(section)
            and "Buffet" not in section
        )
        if derivable:
            whole_name = re.sub(r"\s*Slice\b", "", name).strip(" -")
            items.append({
                "id": nx.dedupe_id(nx.slug(whole_name) + f"-whole-{n}", seen),
                "name": f"{whole_name} (whole pizza)",
                "description": (
                    f"Whole pizza: {n} x Pizza Hut's published per-slice nutrition "
                    f"for \"{name}\" ({n} slices per pizza per the vendor's section header)."
                ),
                "category": "meal",
                "serving_note": f"per whole pizza ({n} slices)",
                "is_estimate": True,
                "source": {"type": "derived", "url": MENU_URL},
                **{
                    k: (None if v is None else round(v * n, 1))
                    for k, v in macros.items()
                },
            })

    spot_check(items)

    save_restaurant({
        "id": "pizza-hut",
        "name": "Pizza Hut",
        "website": "https://www.pizzahut.com",
        "nutrition_source": {
            "type": "vendor",
            "url": MENU_URL,
            "vendor": "nutritionix",
            "retrieved": retrieved,
        },
        "locations": sf_locations(),
        "items": items,
    })


# Famous item: a slice of Large Original Pan Cheese, independently published at
# ~350-370 kcal. Also asserts the derived whole pizza is 8x the slice, which is
# the check that catches a per-slice/per-pizza mix-up.
def spot_check(items) -> None:
    by_id = {i["id"]: i for i in items}
    sl = by_id.get("cheese-large-original-pan-slice")
    whole = by_id.get("cheese-large-original-pan-whole-8")
    if sl is None or whole is None:
        raise SystemExit("pizza-hut: spot-check rows for Large Original Pan Cheese missing")
    if not 300 <= sl["calories"] <= 420:
        raise SystemExit(f"pizza-hut: spot check failed — pan cheese slice {sl['calories']} kcal")
    if whole["calories"] != sl["calories"] * 8:
        raise SystemExit("pizza-hut: derived whole pizza is not 8x the slice")
    print(
        f"spot check: Cheese - Large Original Pan Slice {sl['calories']} kcal "
        f"({sl['serving_note']}); derived whole pizza {whole['calories']} kcal"
    )


if __name__ == "__main__":
    main()
