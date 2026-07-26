"""IHOP scraper.

Nutrition: IHOP publishes through Nutritionix under contract — branded grid at
https://www.nutritionix.com/ihop/menu/premium, reachable from IHOP's Nutritionix
brand portal (https://www.nutritionix.com/ihop/portal/). source type "vendor",
vendor "nutritionix". Rows are per menu item as served; parsed by column label
(scrapers/_nutritionix.py).

TRAP: ihop.com hard-blocks this VM's IP at Cloudflare (403 to curl AND to real
Chrome over CDP), so the brand-side nutrition page can't be loaded from here —
the official *locator* lives on a separate, unblocked host
(restaurants.ihop.com, RIO SEO, ships lat/lng).

TRAP: "Build Your Combo - X" rows are the portion of an item as served inside
a Build Your Own Combo, not a standalone order (and not simply a smaller
version — Build Your Combo buttermilk pancakes are 550 kcal vs 460 for the
standalone 3-stack), so they are components, not meals.

TRAP: Family Feasts / Catering rows are multi-serving bulk pans (Nutritionix
lists e.g. 80 pancakes in one row), also components; the biggest of them are
legitimately quarantined by the >5000 kcal / >10000 mg sodium plausibility caps.

Locations: exactly ONE IHOP in SF city proper (200 Beach St, Fisherman's
Wharf). The 316 S Airport Blvd store is South San Francisco and is excluded.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE))

import _locator  # noqa: E402
import _nutritionix as nx  # noqa: E402
from save import save_restaurant  # noqa: E402

BRAND = "ihop"
MENU_URL = nx.menu_url(BRAND)
LOCATOR_URL = "https://restaurants.ihop.com/en-us/ca/san-francisco/"

SECTION_CATEGORY = {
    "Pancakes": "meal",
    "Crepes": "meal",
    "Waffles": "meal",
    "Thick N Fluffy French Toast": "meal",
    "Combos": "meal",
    "Omelettes": "meal",
    "Anytime Tacos & Burrito": "meal",
    "Eggs Benedicts": "meal",
    "Ultimate Steakburgers": "meal",
    "Hand-Crafted Sandwiches": "meal",
    "Entrees": "meal",
    "IHOP Value Menu": "meal",
    "Platters": "meal",
    "Kids": "meal",            # kids entrees; kids drinks live under Beverages
    "55+ Menu": "meal",
    "Appetizers": "side",      # includes the soups
    "Desserts": "side",
    "Sides": "side",
    "Beverages": "drink",
    "Milkshakes": "drink",
    "Syrup Caddy": "condiment",
}

_COMBO_PART_RE = re.compile(r"^build your combo\b", re.I)
# TRAP: "chocolate" contains "cola" — an unanchored `cola` alternative silently
# files every chocolate pancake as a drink. Keep the boundaries.
_DRINK_RE = re.compile(
    r"milkshake|\bshake\b|smoothie|\bmilk\b|juice|coffee|espresso|latte|"
    r"hot chocolate|\btea\b|lemonade|soda|\bcola\b|\bcoke\b|pepsi|sprite|"
    r"starry|root beer|\bdew\b|fanta|pibb|red bull|life water|splasher|"
    r"ice blend|americano|mocha|\bpunch\b|gallon|fl oz",
    re.I,
)
_CONDIMENT_RE = re.compile(
    r"\bsyrup\b|bbq sauce|ihop sauce|ketchup|\bmayo\b|mustard|dressing", re.I
)
# Catering "Burger & Sandwich Toppings, X" rows are single garnishes.
_TOPPING_RE = re.compile(r"toppings?,", re.I)


def categorize(section: str, name: str) -> str:
    """Category for one grid row. Sections drive the category; name-level rules
    only run for the sections that genuinely mix formats. Unknown -> component."""
    if _COMBO_PART_RE.search(name):
        return "component"
    if section in SECTION_CATEGORY:
        return SECTION_CATEGORY[section]
    if section == "Biscuits":
        return "meal" if "sandwich" in name.lower() else "side"
    if section == "Fresh Salads & Soups":
        low = name.lower()
        return "side" if ("soup" in low or low.startswith("house salad")) else "meal"
    if section in ("Family Feasts", "Catering"):
        if _CONDIMENT_RE.search(name):
            return "condiment"
        if _TOPPING_RE.search(name):
            return "condiment"
        if _DRINK_RE.search(name):
            return "drink"
        return "component"     # multi-serving bulk, not one meal
    if section == "Limited Time Offers":
        # LTO here is pancakes / BreakFEAST platters plus a milkshake; anything
        # unrecognised stays a component rather than being promoted to "meal".
        if _DRINK_RE.search(name):
            return "drink"
        if re.search(r"pancake|breakfeast|french toast|waffle|combo|omelette", name, re.I):
            return "meal"
        return "component"
    return "component"


def serving_note(section: str, name: str) -> str:
    if section in ("Family Feasts", "Catering"):
        m = re.search(r"\(([^)]*(?:Each|Pieces|Slices|Pancakes|Links|Strips|Burritos|oz|Gallon)[^)]*)\)", name, re.I)
        return f"per bulk order {m.group(1)}" if m else "per bulk/catering order (multiple servings)"
    if _COMBO_PART_RE.search(name):
        return "per combo portion (as served inside a Build Your Own Combo)"
    m = re.match(r"^\((\d+)\)", name)
    if m:
        return f"per order of {m.group(1)}"
    return "per item as served"


def main() -> None:
    html = nx.fetch(BRAND)
    retrieved = nx.last_updated(html)
    if not retrieved:
        raise SystemExit("ihop: no 'Last Updated' date on the vendor page")

    items, seen = [], set()
    for row in nx.parse_rows(html):
        if row.get("calories") is None:
            continue
        name, section = row["name"], row["section"] or ""
        items.append({
            "id": nx.dedupe_id(nx.slug(name), seen),
            "name": name,
            "description": f"IHOP menu section: {section}." if section else None,
            "category": categorize(section, name),
            "calories": row["calories"],
            "protein_g": row.get("protein_g") or 0,
            "carbs_g": row.get("carbs_g") or 0,
            "fat_g": row.get("fat_g") or 0,
            "fiber_g": row.get("fiber_g"),
            "sodium_mg": row.get("sodium_mg"),
            "serving_note": serving_note(section, name),
            "is_estimate": False,
            "source": {"type": "vendor", "url": MENU_URL},
        })

    spot_check(items)

    save_restaurant({
        "id": "ihop",
        "name": "IHOP",
        "website": "https://www.ihop.com",
        "nutrition_source": {
            "type": "vendor",
            "url": MENU_URL,
            "vendor": "nutritionix",
            "retrieved": retrieved,
        },
        "locations": _locator.sf_locations(LOCATOR_URL),
        "items": items,
    })


# Famous item: the (5) Original Buttermilk Pancakes stack, long published by
# IHOP at ~590 kcal. Guards against reading the wrong column.
def spot_check(items) -> None:
    hit = next((i for i in items if i["id"] == "5-original-buttermilk-pancakes"), None)
    if hit is None:
        raise SystemExit("ihop: spot-check item '(5) Original Buttermilk Pancakes' missing")
    if not 450 <= hit["calories"] <= 750:
        raise SystemExit(f"ihop: spot check failed — 5 buttermilk pancakes {hit['calories']} kcal")
    print(
        f"spot check: (5) Original Buttermilk Pancakes {hit['calories']} kcal / "
        f"{hit['protein_g']}g protein / {hit['carbs_g']}g carbs / {hit['fat_g']}g fat"
    )


if __name__ == "__main__":
    main()
