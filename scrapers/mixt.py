"""Mixt scraper.

Mixt's nutrition calculator (https://www.mixt.com/nutrition-calculator/) is a
static WordPress page: every ingredient's full macros ship in the HTML as
data-* attributes on `.ingredient_list_item` rows, and each chef-crafted
salad/bowl is a `.menu_item` anchor whose `data-tags` lists its default
ingredient ids. There is no separate API.

  - ingredients -> category "component" ("condiment" for DRESSINGS),
    source "published" (the page itself)
  - named salads/bowls -> DERIVED sums of their default ingredients:
    source "derived", is_estimate=True, recipe in description
    (same pattern as scrapers/chipotle.py)

Locations: https://www.mixt.com/locations/ links per-store pages, each of
which embeds schema.org JSON-LD with PostalAddress + geo lat/lng. Filter
addressLocality == "San Francisco".
"""

import datetime
import json
import re
import sys
import urllib.request
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

CALC_URL = "https://www.mixt.com/nutrition-calculator/"
LOCATIONS_URL = "https://www.mixt.com/locations/"
HEADERS = {"User-Agent": "Mozilla/5.0 Chrome/126"}
TODAY = datetime.date.today().isoformat()


def get(url):
    req = urllib.request.Request(url, headers=dict(HEADERS))
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8")


class CalcParser(HTMLParser):
    """Pulls ingredient rows (with macros) and menu items (with recipes)."""

    def __init__(self):
        super().__init__()
        self.ingredients = {}  # id -> {name, group, macros...}
        self.meals = []  # {name, section, tag_ids}
        self._h = None
        self._group = None  # current h3 (BASE / PROTEIN / DRESSINGS ...)
        self._section = None  # current h2 (Chef Crafted Salads / Warm Bowls ...)
        self._pending_ing = None  # ingredient awaiting its <span> name
        self._in_name_span = False
        self._pending_meal = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("h2", "h3"):
            self._h = tag
        elif tag == "li" and "ingredient_list_item" in (a.get("class") or ""):
            self._pending_ing = {"id": a.get("id"), **{k: v for k, v in attrs}}
        elif tag == "a" and "menu_item" in (a.get("class") or "") and a.get("data-tags"):
            self._pending_meal = {
                "section": self._section,
                "tag_ids": [t for t in a["data-tags"].split(",") if t.strip()],
            }
        elif tag == "span" and self._pending_ing is not None and "class" not in a:
            self._in_name_span = True

    def handle_endtag(self, tag):
        if tag in ("h2", "h3"):
            self._h = None
        elif tag == "span":
            self._in_name_span = False

    def handle_data(self, data):
        text = unescape(data).strip()
        if not text:
            return
        if self._h == "h3":
            self._group = text
        elif self._h == "h2":
            self._section = text
        elif self._pending_meal is not None:
            self._pending_meal["name"] = text
            self.meals.append(self._pending_meal)
            self._pending_meal = None
        elif self._in_name_span and self._pending_ing is not None:
            row = self._pending_ing

            def num(key):
                return float(re.sub(r"[^0-9.]", "", row[key]) or 0)

            self.ingredients[row["id"]] = {
                "name": text,
                "group": self._group,
                "calories": num("data-calories"),
                "protein_g": num("data-protein"),
                "carbs_g": num("data-carbs"),
                "fat_g": num("data-totalfat"),
                "fiber_g": num("data-fiber"),
                "sodium_mg": num("data-sodium"),
            }
            self._pending_ing = None
            self._in_name_span = False


def slugify(name):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")


def scrape_locations():
    index = get(LOCATIONS_URL)
    urls = sorted(set(re.findall(r'href="(https://www\.mixt\.com/locations/[^"]+/)"', index)))
    locs = []
    for url in urls:
        if url == LOCATIONS_URL:
            continue
        try:
            page = get(url)
        except Exception as e:  # noqa: BLE001
            print(f"  skip {url}: {e}", file=sys.stderr)
            continue
        for m in re.finditer(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
            try:
                data = json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
            nodes = data.get("@graph", [data]) if isinstance(data, dict) else data
            for node in nodes:
                addr = node.get("address") if isinstance(node, dict) else None
                geo = node.get("geo") if isinstance(node, dict) else None
                if not (isinstance(addr, dict) and isinstance(geo, dict)):
                    continue
                if addr.get("addressLocality") != "San Francisco":
                    continue
                address = f"{addr['streetAddress']}, San Francisco, CA {addr.get('postalCode', '')}".strip()
                if any(l["address"] == address for l in locs):
                    continue
                locs.append({
                    "address": address,
                    "lat": float(geo["latitude"]),
                    "lng": float(geo["longitude"]),
                    "neighborhood": url.rstrip("/").rsplit("/", 1)[-1].replace("-", " "),
                })
    return locs


def main():
    parser = CalcParser()
    parser.feed(get(CALC_URL))
    ings, meals = parser.ingredients, parser.meals
    print(f"parsed {len(ings)} ingredients, {len(meals)} named items")

    items = []
    for iid, ing in ings.items():
        category = "condiment" if ing["group"] == "DRESSINGS" else "component"
        items.append({
            "id": f"component-{iid}-{slugify(ing['name'])}",
            "name": ing["name"],
            "description": None,
            "category": category,
            "calories": ing["calories"],
            "protein_g": ing["protein_g"],
            "carbs_g": ing["carbs_g"],
            "fat_g": ing["fat_g"],
            "fiber_g": ing["fiber_g"],
            "sodium_mg": ing["sodium_mg"],
            "serving_note": "per calculator serving (one '+' in Mixt's nutrition calculator)",
            "is_estimate": False,
            "source": {"type": "published", "url": CALC_URL},
        })

    for meal in meals:
        missing = [t for t in meal["tag_ids"] if t not in ings]
        if missing:
            print(
                f"  SKIP {meal['name']}: ingredient ids {missing} not in the "
                "calculator's ingredient list — sum would be incomplete",
                file=sys.stderr,
            )
            continue
        parts = [ings[t] for t in meal["tag_ids"] if t in ings]
        total = {k: 0.0 for k in ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sodium_mg")}
        for p in parts:
            for k in total:
                total[k] += p[k]
        recipe = ", ".join(p["name"] for p in parts)
        kind = "warm bowl" if "bowl" in (meal["section"] or "").lower() else "salad"
        items.append({
            "id": slugify(meal["name"]),
            "name": meal["name"].title(),
            "description": f"{meal['section']}. Standard build: {recipe}. "
                           "Sum of Mixt's published per-ingredient calculator values.",
            "category": "meal",
            **{k: round(v, 1) for k, v in total.items()},
            "serving_note": f"per whole {kind} (default build, no modifications)",
            "is_estimate": True,
            "source": {"type": "derived", "url": CALC_URL},
        })

    locs = scrape_locations()

    save_restaurant({
        "id": "mixt",
        "name": "Mixt",
        "website": "https://www.mixt.com",
        "nutrition_source": {"type": "published", "url": CALC_URL, "vendor": None, "retrieved": TODAY},
        "locations": locs,
        "items": items,
    })


if __name__ == "__main__":
    main()
