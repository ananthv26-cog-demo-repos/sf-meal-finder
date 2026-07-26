"""Papa John's published nutrition guide and ordering locator.

The locator response was captured in Chrome from stores.getDeliveryStores.
The nutrition PDF is the company's published allergen/nutrition guide; pizza
rows in this guide are whole-pizza totals, not per-slice values.
"""

from __future__ import annotations

import datetime
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

NUTRITION_URL = "https://www.papajohns.com/allergens/pdf/papa-johns-allergen-guide.pdf"
LOCATOR_URL = "https://www.papajohns.com/api/trpc/stores.getDeliveryStores"
TODAY = datetime.date.today().isoformat()
NUTRITION_PAGE = "https://www.papajohns.com/company/nutritional-details/"


def num(values, idx):
    if idx >= len(values):
        return 0.0
    m = re.search(r"[\d.]+", values[idx] or "")
    return float(m.group()) if m else 0.0


def parse_page(html, page_category, source_url):
    out = []
    soup = BeautifulSoup(html, "html.parser")
    for heading in soup.find_all("h5"):
        name = heading.get_text(" ", strip=True)
        if name in {"Nutritional Details", "US – Nutritional Information", "Open A Franchise"}:
            continue
        if any(x in name.lower() for x in ("no longer available", "(canada)", "canada)", "regional only")):
            continue
        tables = heading.find_all_next("table", limit=2)
        if len(tables) < 2:
            continue
        rows = {}
        for tr in tables[0].find_all("tr"):
            cells = [x.get_text(" ", strip=True) for x in tr.find_all(["th", "td"])]
            if cells:
                rows[cells[0].lower()] = cells[1:]
        nutrition = {}
        for tr in tables[1].find_all("tr"):
            cells = [x.get_text(" ", strip=True) for x in tr.find_all(["th", "td"])]
            if cells:
                nutrition[cells[0].lower()] = cells[1:]
        calories = nutrition.get("total calories")
        if not calories:
            continue
        sizes = rows.get("pizza size", []) or rows.get("crust size", []) or rows.get("order size", [])
        serving = rows.get("serving size", [])
        is_pizza = bool(rows.get("pizza size") or rows.get("crust size"))
        for idx, cal in enumerate(calories):
            if not cal.isdigit() or not serving:
                continue
            size = sizes[idx] if idx < len(sizes) else ""
            if is_pizza and (not size or size.upper() == "N/A" or size.lower() in {"listed size", "pizza for one"}):
                continue
            label_values = rows.get(name.lower()) or rows.get("dipping sauces")
            display_name = (
                label_values[idx] if label_values and idx < len(label_values)
                else (f"{name} - {size}" if size else name)
            )
            note = (serving[idx] if idx < len(serving) else serving[0]) or "per listed serving"
            count = None
            if is_pizza:
                m = re.search(r"(\d+)\s+slices?\s+per", note)
                if not m:
                    continue
                count = int(m.group(1))
                note = f"per slice (1/{count} of {size.lower()} pizza)"
            elif len(calories) > 1 and size:
                note = f"per {size.lower()} serving"
            item = {
                "id": re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-"),
                "name": display_name, "description": None,
                "category": "component" if is_pizza else page_category,
                "calories": float(cal), "protein_g": num(nutrition.get("protein", []), idx),
                "carbs_g": num(nutrition.get("total carbohydrate", []), idx),
                "fat_g": num(nutrition.get("total fat", []), idx),
                "fiber_g": num(nutrition.get("dietary fiber", []), idx),
                "sodium_mg": num(nutrition.get("sodium", []), idx),
                "serving_note": note, "is_estimate": False,
                "source": {"type": "published", "url": source_url},
            }
            item["protein_g"] = num(nutrition.get("protein", []), idx)
            out.append(item)
            if is_pizza and count and size.lower() in {"small", "medium", "large"}:
                whole = dict(item)
                whole["id"] = item["id"] + "-whole"
                whole["name"] = f"{name} - Whole {size}"
                whole["category"] = "meal"
                whole["calories"] *= count
                for field in ("protein_g", "carbs_g", "fat_g", "fiber_g", "sodium_mg"):
                    whole[field] *= count
                whole["serving_note"] = f"per whole {size.lower()} pizza"
                whole["description"] = f"{count} × published per-slice values, {size.lower()} original crust"
                whole["source"] = {"type": "derived", "url": source_url}
                whole["is_estimate"] = True
                out.append(whole)
    return list({x["id"]: x for x in out}.values())


def number(values, idx):
    return num(values, idx)


def main():
    def fetch(url):
        html = subprocess.check_output(["curl", "-L", "-sS", "-A", "Mozilla/5.0", url], timeout=90)
        if len(html) < 30000:
            script = (
                "const {chromium}=require('/tmp/sf-playwright/node_modules/playwright-core');"
                "(async()=>{const b=await chromium.connectOverCDP('http://localhost:29229');"
                "const p=await b.contexts()[0].newPage();await p.goto(process.argv[1],"
                "{waitUntil:'domcontentloaded',timeout:90000});process.stdout.write(await p.content());"
                "await b.close()})().catch(e=>{console.error(e);process.exit(1)})"
            )
            html = subprocess.check_output(["node", "-e", script, url], timeout=150)
        return html
    pages = [
        (NUTRITION_PAGE, "component"),
        ("https://www.papajohns.com/company/nutritional-details/papadias.html", "meal"),
        ("https://www.papajohns.com/company/nutritional-details/sandwiches.html", "meal"),
        ("https://www.papajohns.com/company/nutritional-details/wings.html", "meal"),
        ("https://www.papajohns.com/company/nutritional-details/sides.html", "side"),
        ("https://www.papajohns.com/company/nutritional-details/desserts.html", "side"),
        ("https://www.papajohns.com/company/nutritional-details/dipping-sauces.html", "condiment"),
        ("https://www.papajohns.com/company/nutritional-details/extras.html", "component"),
    ]
    all_items = []
    for url, category in pages:
        all_items.extend(parse_page(fetch(url), category, url))
    save_restaurant({
        "id": "papa-johns",
        "name": "Papa John's",
        "website": "https://www.papajohns.com/",
        "nutrition_source": {
            "type": "published", "url": NUTRITION_PAGE, "vendor": None, "retrieved": TODAY,
        },
        "locations": [{
            "address": "969 Sutter St, San Francisco, CA 94109",
            "lat": 37.78809, "lng": -122.41632, "neighborhood": "Lower Nob Hill",
        }],
        "items": all_items,
    })


if __name__ == "__main__":
    main()
