"""Applebee's scraper.

Nutrition: Applebee's publishes through Nutritionix under contract — the
branded "Applebee's - Interactive Nutrition Menu" grid at
https://www.nutritionix.com/applebees/menu/premium (source type "vendor",
vendor "nutritionix"). Rows are per menu item as served, fully server-rendered,
read by column label (see scrapers/_nutritionix.py).

TRAP: applebees.com (and ihop.com) hard-block this VM's IP at Cloudflare — 403
in curl AND in real Chrome over CDP, so the brand-side link could not be
loaded. The vendor page is verified instead by Nutritionix's branded portal
(https://www.nutritionix.com/applebees/portal/), the same structure that
pizzahut.com/nutrition links to directly.

Locations: official locator restaurants.applebees.com (RIO SEO, ships lat/lng).
Exactly ONE Applebee's is in SF city proper (2770 Taylor St, Fisherman's
Wharf); the sitemap confirms no other /ca/san-francisco/ store pages exist.

Categories: mapped from the grid's own menu sections, with name-level rules for
the sections that mix formats (Limited Time Offers, Kids Menu, Catering).
Unknown sections fall back to "component", never "meal".
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

BRAND = "applebees"
MENU_URL = nx.menu_url(BRAND)
LOCATOR_URL = "https://restaurants.applebees.com/en-us/ca/san-francisco/"

# Sections whose category is unambiguous.
SECTION_CATEGORY = {
    "Appetizers": "side",
    "Side Salads & Soups": "side",
    "Steaks & Ribs": "meal",
    "Chicken": "meal",
    "Seafood": "meal",
    "Salads": "meal",          # entree salads; side salads live in their own section
    "Pasta": "meal",
    "Bowls": "meal",
    "Burgers": "meal",
    "Sandwiches & More": "meal",
    "Desserts": "side",
    "Sides & Extras": "side",
    "Beverages": "drink",
    "Alcoholic Beverages": "drink",
}

_DRINK_RE = re.compile(
    r"margarita|dollarita|mucho|bacardi|patron|patr[oó]n|grey goose|woodford|"
    r"still g\.i\.n|tito|vibe drop|poppi|shirley|sunshine|lemonade|iced tea|"
    r"smoothie|shake|\bmilk\b|juice|soda|\bcola\b|coke|pepsi|water|coffee|"
    r"\bbeer\b|\bwine\b|cocktail|mojito|sangria|punch|zero sugar|dew|gallon",
    re.I,
)
# Standalone sauces/flavors/add-ons. Only applied inside the mixed sections —
# matching names globally turns "Breadsticks with Alfredo Sauce" (an appetizer)
# and "Butter Pecan Blondie" (a dessert) into condiments.
_CONDIMENT_RE = re.compile(
    r"dipping sauce|\bsauce -|\bflavor -|dressing|make it spicy|^add ", re.I
)
_KIDS_MEAL_RE = re.compile(
    r"cheeseburger|burger|pizza|quesadilla|taco|tenders|corn dog|alfredo|"
    r"macaroni|mac & cheese",
    re.I,
)


def categorize(section: str, name: str) -> str:
    """Category for one grid row. Ambiguous/unknown -> 'component', never 'meal'.

    Sections drive the category; name-level rules only run for the sections
    that genuinely mix formats.
    """
    if section in SECTION_CATEGORY:
        cat = SECTION_CATEGORY[section]
        if cat == "meal" and re.search(r"breadstick", name, re.I):
            return "side"       # appetizer that lives in the Pasta section
        if cat == "drink" and name.lower().startswith("add "):
            return "condiment"  # "Add Dirty Fountain Soda Topping"
        return cat
    if section == "Limited Time Offers":
        if _CONDIMENT_RE.search(name):
            return "condiment"
        if _DRINK_RE.search(name):
            return "drink"
        if "sampler" in name.lower() or "fries" in name.lower():
            return "side"       # appetizer-sampler portions, not entrees
        return "component"
    if section == "Kids Menu":
        if _DRINK_RE.search(name):
            return "drink"
        if _KIDS_MEAL_RE.search(name):
            return "meal"       # kids entrees are real orderable meals
        return "side"
    if section == "Catering":
        if _CONDIMENT_RE.search(name):
            return "condiment"
        if _DRINK_RE.search(name):
            return "drink"
        return "component"      # party trays / bulk pans, not single meals
    return "component"


def serving_note(section: str, name: str) -> str:
    if section == "Catering":
        m = re.search(r"\(([^)]*(?:Serves|Gallon|Each|Pieces|Slices)[^)]*)\)", name, re.I)
        return f"per catering order {m.group(1)}" if m else "per catering order"
    if section == "Kids Menu":
        return "per kids-menu serving"
    return "per item as served"


def main() -> None:
    html = nx.fetch(BRAND)
    retrieved = nx.last_updated(html)
    if not retrieved:
        raise SystemExit("applebees: no 'Last Updated' date on the vendor page")

    items, seen = [], set()
    for row in nx.parse_rows(html):
        if row.get("calories") is None:
            continue  # nutrition not published for this row; nothing to save
        name = row["name"]
        section = row["section"] or ""
        items.append({
            "id": nx.dedupe_id(nx.slug(name), seen),
            "name": name,
            "description": f"Applebee's menu section: {section}." if section else None,
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
        "id": "applebees",
        "name": "Applebee's Grill + Bar",
        "website": "https://www.applebees.com",
        "nutrition_source": {
            "type": "vendor",
            "url": MENU_URL,
            "vendor": "nutritionix",
            "retrieved": retrieved,
        },
        "locations": _locator.sf_locations(LOCATOR_URL),
        "items": items,
    })


# Famous-item sanity check before trusting the parse: the Quesadilla Burger is
# the widely-cited Applebee's calorie bomb (~1,400 kcal). Fail loudly if the
# parse lands somewhere else entirely (i.e. we grabbed the wrong column).
def spot_check(items) -> None:
    hit = next((i for i in items if i["id"] == "quesadilla-burger"), None)
    if hit is None:
        raise SystemExit("applebees: spot-check item 'Quesadilla Burger' missing")
    if not 1100 <= hit["calories"] <= 1700:
        raise SystemExit(f"applebees: spot check failed — Quesadilla Burger {hit['calories']} kcal")
    print(
        f"spot check: Quesadilla Burger {hit['calories']} kcal / {hit['protein_g']}g protein / "
        f"{hit['carbs_g']}g carbs / {hit['fat_g']}g fat"
    )


if __name__ == "__main__":
    main()
