"""Panda Express nutrition and San Francisco location scraper.

Panda's public site is protected by DataDome for non-browser clients.  The
nutrition table is rendered in the page HTML, so this scraper uses the real
Chrome instance over CDP (via a small Node/Playwright subprocess) to obtain
that HTML.  The location finder exposes a JSON endpoint that can be fetched
directly after the browser discovery step.

Nutrition rows are parsed by their labeled ``title`` fields, never by column
position.  Published component rows are retained, while canonical Bowl and
Plate builds are derived from one standard side plus one or two portions of
the same entree.
"""

import datetime
import html
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

NUTRITION_URL = "https://www.pandaexpress.com/nutritioninformation"
LOCATION_URL = (
    "https://maps.locations.pandaexpress.com.prod.rioseo.com/api/"
    "getAsyncLocations?"
    "template=search&level=search&search=San%20Francisco%2C%20CA"
)
TODAY = datetime.date.today().isoformat()
SF_LAT = (37.60, 37.86)
SF_LNG = (-122.55, -122.33)

STANDARD_SIDES = {
    "white steamed rice",
    "fried rice",
    "chow mein",
    "super greens",
}
POPULAR_ENTREES = {
    "black pepper chicken",
    "grilled teriyaki chicken",
    "hot orange chicken",
    "kung pao chicken",
    "mushroom chicken",
    "orange chicken",
    "teriyaki chicken",
    "honey sesame chicken breast",
    "string bean chicken breast",
    "sweet & sour chicken breast",
    "sweetfire chicken breast",
    "beijing beef",
    "black pepper sirloin steak",
    "broccoli beef",
    "honey walnut shrimp",
    "steamed ginger fish",
    "wok-fired shrimp",
    "eggplant tofu",
}


def browser_html():
    """Return nutrition page HTML from Chrome connected to localhost:29229."""
    js = r"""
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.connectOverCDP('http://localhost:29229');
  const page = await browser.contexts()[0].newPage();
  await page.goto('https://www.pandaexpress.com/nutritioninformation',
                  {waitUntil: 'domcontentloaded', timeout: 90000});
  await page.waitForTimeout(5000);
  process.stdout.write(await page.content());
  await browser.close();
})().catch(err => { console.error(err.stack || err); process.exit(1); });
"""
    candidates = [
        str(Path(__file__).resolve().parent.parent / "node_modules"),
        "/tmp/node_modules",
    ]
    for node_path in candidates:
        if (Path(node_path) / "playwright").exists():
            result = subprocess.run(
                ["node", "-e", js],
                env={**__import__("os").environ, "NODE_PATH": node_path},
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode:
                raise RuntimeError(result.stderr.strip())
            return result.stdout
    raise RuntimeError(
        "Playwright is required to read Panda's "
        "DataDome-protected nutrition page"
    )


def clean_text(value):
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def parse_nutrition(page_html):
    """Parse labeled nutrition values from the table rows."""
    rows = []
    category = ""
    for block in re.findall(
        r"<tr\b[^>]*>.*?</tr>", page_html, flags=re.IGNORECASE | re.DOTALL
    ):
        if "row-category" in block:
            category = clean_text(block)
            continue
        if "row-nutrition" not in block:
            continue
        first = re.search(r"<td\b[^>]*>(.*?)</td>", block, re.I | re.S)
        if not first:
            continue
        name = clean_text(first.group(1)).lower()
        values = {}
        for title, value in re.findall(
            r'<span[^>]*class="value"[^>]*title="([^"]+)"[^>]*>(.*?)</span>',
            block,
            flags=re.I | re.S,
        ):
            values[html.unescape(title)] = clean_text(value)
        if not name or not values.get("Calories"):
            continue
        try:
            def number(key):
                return float(values[key])
            row = {
                "name": name,
                "portion_oz": number("Portion (oz)"),
                "calories": number("Calories"),
                "protein_g": number("Protein (g)"),
                "carbs_g": number("Total carb (g)"),
                "fat_g": number("Total fat (g)"),
                "fiber_g": number("Dietary fiber (g)"),
                "sodium_mg": number("Sodium (mg)"),
                "category_source": category.lower(),
            }
        except (KeyError, ValueError):
            continue
        rows.append(row)
    return rows


def item_category(row):
    name = row["name"]
    source_category = row["category_source"]
    if source_category == "beverages":
        return "drink"
    if source_category == "more":
        if any(x in name for x in ("sauce", "mustard")):
            return "condiment"
        return "side"
    if source_category in ("appetizers", "soup"):
        return "side"
    if source_category == "cub meals":
        return "meal"
    if name in STANDARD_SIDES or name.endswith(" - cub meal"):
        return "component"
    if any(
        x in name
        for x in (
            "egg roll", "potsticker", "rangoon", "pie roll", "cookie",
            "apple crisps",
        )
    ):
        return "side"
    return "component"


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def published_items(rows):
    items = []
    for row in rows:
        category = item_category(row)
        name = row["name"].title()
        items.append(
            {
                "id": f"published-{slug(row['name'])}",
                "name": name,
                "description": None,
                "category": category,
                "calories": row["calories"],
                "protein_g": row["protein_g"],
                "carbs_g": row["carbs_g"],
                "fat_g": row["fat_g"],
                "fiber_g": row["fiber_g"],
                "sodium_mg": row["sodium_mg"],
                "serving_note": f"per {row['portion_oz']:g} oz serving",
                "is_estimate": False,
                "source": {"type": "published", "url": NUTRITION_URL},
            }
        )
    return items


def derived_items(rows):
    by_name = {r["name"]: r for r in rows}
    entrees = [by_name[n] for n in POPULAR_ENTREES if n in by_name]
    sides = [by_name[n] for n in STANDARD_SIDES if n in by_name]
    output = []
    for entree in sorted(entrees, key=lambda r: r["name"]):
        for side in sorted(sides, key=lambda r: r["name"]):
            for meal_type, entree_count in (("bowl", 1), ("plate", 2)):
                totals = {}
                for key in (
                    "calories", "protein_g", "carbs_g",
                    "fat_g", "fiber_g", "sodium_mg",
                ):
                    totals[key] = side[key] + entree_count * entree[key]
                label = "Bowl" if meal_type == "bowl" else "Plate"
                output.append(
                    {
                        "id": (
                            f"{slug(entree['name'])}-{slug(side['name'])}-"
                            f"{meal_type}"
                        ),
                        "name": (
                            f"{entree['name'].title()} {label} with "
                            f"{side['name'].title()}"
                        ),
                        "description": (
                            f"Derived canonical {label.lower()}: one standard "
                            "serving of "
                            f"{side['name']} plus {entree_count} standard "
                            "serving(s) of "
                            f"{entree['name']}; summed from Panda's "
                            "published nutrition."
                        ),
                        "category": "meal",
                        "serving_note": (
                            f"per {label.lower()} "
                            f"({side['portion_oz']:g} oz side + "
                            f"{entree_count} x "
                            f"{entree['portion_oz']:g} oz entree)"
                        ),
                        "is_estimate": True,
                        "source": {"type": "derived", "url": NUTRITION_URL},
                        **totals,
                    }
                )
    return output


def get_locations():
    request = urllib.request.Request(
        LOCATION_URL, headers={"User-Agent": "Mozilla/5.0"}
    )
    payload = json.load(urllib.request.urlopen(request, timeout=30))
    locations = []
    for marker in payload.get("markers", []):
        info = re.search(
            r">\s*(\{.*\})\s*</div>", marker.get("info", ""), re.S
        )
        if not info:
            continue
        record = json.loads(info.group(1))
        if record.get("city") != "San Francisco":
            continue
        lat, lng = float(record["lat"]), float(record["lng"])
        if not (
            SF_LAT[0] <= lat <= SF_LAT[1]
            and SF_LNG[0] <= lng <= SF_LNG[1]
        ):
            continue
        address = (
            f"{record['address_1'].strip()}, San Francisco, CA "
            f"{record.get('post_code', '')}"
        ).strip()
        locations.append(
            {"address": address, "lat": lat, "lng": lng, "neighborhood": None}
        )
    return locations


def main():
    rows = parse_nutrition(browser_html())
    if not rows:
        raise RuntimeError("Panda nutrition table was not found")
    orange = next((r for r in rows if r["name"] == "orange chicken"), None)
    if orange:
        print(
            "Orange Chicken spot-check: "
            f"{orange['portion_oz']:g} oz, {orange['calories']:g} kcal, "
            f"{orange['protein_g']:g} g protein, "
            f"{orange['carbs_g']:g} g carbs, "
            f"{orange['fat_g']:g} g fat"
        )
        if (
            orange["portion_oz"],
            orange["calories"],
            orange["protein_g"],
            orange["carbs_g"],
            orange["fat_g"],
        ) != (5.7, 490, 25, 51, 23):
            print(
                "Orange Chicken spot-check differs from requested historical "
                "figures; labeled fields used."
            )
    items = published_items(rows)
    items.extend(derived_items(rows))
    save_restaurant(
        {
            "id": "panda-express",
            "name": "Panda Express",
            "website": "https://www.pandaexpress.com",
            "nutrition_source": {
                "type": "published",
                "url": NUTRITION_URL,
                "vendor": None,
                "retrieved": TODAY,
            },
            "locations": get_locations(),
            "items": items,
        }
    )


if __name__ == "__main__":
    main()
