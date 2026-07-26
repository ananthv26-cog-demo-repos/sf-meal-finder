"""Starbucks official menu nutrition and San Francisco location scraper.

The ordering menu and store locator are first-party JSON APIs.  Starbucks'
locator API rejects ordinary scripted requests, so the locator response is
captured from the real Chrome instance over CDP.
"""

from __future__ import annotations

import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

MENU_URL = "https://www.starbucks.com/apiproxy/v1/ordering/menu"
LOCATOR_URL = (
    "https://www.starbucks.com/apiproxy/v1/locations?"
    "place=San%20Francisco%2C%20CA%2C%20USA&lat=37.7749295&lng=-122.4194155"
)
TODAY = datetime.date.today().isoformat()


def browser_payload():
    """Capture menu and locator JSON using the Chrome CDP instance."""
    js = r"""
const {chromium} = require(process.env.PW_MODULE || 'playwright');
const fs = require('fs');
const path = require('path');
const cachePath = process.env.CACHE_PATH;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
(async () => {
  const browser = await chromium.connectOverCDP('http://localhost:29229');
  const page = await browser.contexts()[0].newPage();
  let menu;
  for (let attempt = 0; attempt < 5 && !menu; attempt++) {
    await page.goto('https://www.starbucks.com/menu',
      {waitUntil: 'domcontentloaded', timeout: 90000});
    await page.waitForTimeout(3000 + attempt * 3000);
    try {
      menu = await page.evaluate(async () => {
        const r = await fetch('/apiproxy/v1/ordering/menu');
        if (!r.ok) throw new Error(`menu HTTP ${r.status}`);
        return await r.json();
      });
    } catch (_) {
      await page.reload({waitUntil: 'domcontentloaded', timeout: 90000});
    }
  }
  if (!menu) throw new Error('Starbucks menu remained blocked after retries');
  const products = [];
  const walk = node => {
    for (const product of (node.products || [])) products.push(product);
    for (const child of (node.children || [])) walk(child);
  };
  for (const root of (menu.menus || [])) walk(root);
  let cache = {};
  try { cache = JSON.parse(fs.readFileSync(cachePath, 'utf8')); } catch (_) {}
  for (const product of products) {
    const key = `${product.productNumber}-${product.formCode.toLowerCase()}`;
    if (Object.prototype.hasOwnProperty.call(cache, key)) continue;
    let success = false;
    for (let attempt = 0; attempt < 4 && !success; attempt++) {
      await sleep(300 + Math.floor(Math.random() * 501));
      try {
        const response = await page.evaluate(async ({number, form}) => {
          const r = await fetch(`/apiproxy/v1/ordering/${number}/${form}`);
          return {status: r.status, text: await r.text()};
        }, {number: product.productNumber, form: product.formCode.toLowerCase()});
        if (response.status === 200 && response.text.trim().startsWith('{')) {
          cache[key] = JSON.parse(response.text);
          success = true;
        } else {
          await page.reload({waitUntil: 'domcontentloaded', timeout: 90000});
          await page.waitForTimeout(4000 + attempt * 2000);
        }
      } catch (_) {
        await page.reload({waitUntil: 'domcontentloaded', timeout: 90000});
        await page.waitForTimeout(4000 + attempt * 2000);
      }
    }
    fs.mkdirSync(path.dirname(cachePath), {recursive: true});
    fs.writeFileSync(cachePath, JSON.stringify(cache));
  }
  let locator = null;
  page.on('response', async response => {
    if (response.url().includes('/apiproxy/v1/locations?')) {
      try { locator = await response.json(); } catch (_) {}
    }
  });
  await page.goto('https://www.starbucks.com/store-locator',
    {waitUntil: 'domcontentloaded', timeout: 90000});
  const input = page.locator('input[placeholder="Find a store"]');
  await input.waitFor({state: 'visible', timeout: 60000});
  await input.fill('San Francisco');
  await page.waitForTimeout(1500);
  await input.press('ArrowDown');
  await input.press('Enter');
  for (let i = 0; i < 30 && !locator; i++) await page.waitForTimeout(500);
  if (!locator) throw new Error('Starbucks locator response was not captured');
  process.stdout.write(JSON.stringify({menu, locator}));
  await browser.close();
})().catch(error => { console.error(error.stack || error); process.exit(1); });
"""
    candidates = [
        str(Path(__file__).resolve().parent.parent / "node_modules"),
        "/tmp/node_modules",
        "/tmp/sf-playwright/node_modules",
    ]
    for node_path in candidates:
        module_name = "playwright" if (Path(node_path) / "playwright").exists() else (
            "playwright-core" if (Path(node_path) / "playwright-core").exists() else None
        )
        if module_name:
            result = subprocess.run(
                ["node", "-e", js],
                env={
                    **__import__("os").environ,
                    "NODE_PATH": node_path,
                    "PW_MODULE": module_name,
                    "CACHE_PATH": str(
                        Path(__file__).resolve().parent.parent
                        / "data/cache/starbucks_products.json"
                    ),
                },
                capture_output=True,
                text=True,
                timeout=600,
            )
            if result.returncode:
                raise RuntimeError(result.stderr.strip())
            return json.loads(result.stdout)
    raise RuntimeError("Playwright is required to capture Starbucks locator data")


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def facts(nutrition):
    if not nutrition:
        return {}
    values = {}
    for fact in nutrition.get("additionalFacts", []):
        ident = fact.get("id")
        if ident == "totalFat":
            values["fat_g"] = fact.get("value", 0)
        elif ident == "totalCarbs":
            values["carbs_g"] = fact.get("value", 0)
            values["fiber_g"] = (fact.get("dietaryFiber") or {}).get("value")
        elif ident == "protein":
            values["protein_g"] = fact.get("value", 0)
        elif ident == "sodium":
            values["sodium_mg"] = fact.get("value")
    return values


def category(product):
    if str(product.get("productType", "")).lower() == "food":
        name = product.get("name", "").lower()
        if any(x in name for x in ("cake", "cookie", "brownie", "danish", "scone", "muffin", "donut", "dessert")):
            return "side"
        return "meal"
    if "shopping bag" in product["name"].lower():
        return "side"
    return "drink"


def menu_items(menu, details):
    products = {}
    def walk(node):
        for product in node.get("products", []):
            products[(product["productNumber"], product["formCode"])] = product
        for child in node.get("children", []):
            walk(child)
    for root in menu.get("menus", []):
        walk(root)

    items = []
    for (number, form), product in sorted(products.items(), key=lambda pair: pair[1]["name"]):
        endpoint = f"https://www.starbucks.com/apiproxy/v1/ordering/{number}/{form.lower()}"
        raw = details.get(f"{number}-{form.lower()}")
        if not raw:
            print(f"skipping unavailable Starbucks product {number}", file=sys.stderr)
            continue
        detail = raw.get("products", [{}])[0]
        for size in detail.get("sizes", []):
            n = size.get("nutrition", {})
            values = facts(n)
            if not n or not n.get("calories") or not values:
                continue
            size_name = size.get("name") or size.get("sizeCode") or "listed"
            name = f"{product['name']} ({size_name})"
            if size_name.lower() == "1 serving":
                serving_note = "per serving"
            elif size_name.lower().endswith(" serving"):
                serving_note = f"per {size_name[:-8].strip()}"
            else:
                serving_note = f"per {size_name} serving"
            items.append({
                "id": f"{number}-{slug(form)}-{slug(size_name)}",
                "name": name,
                "description": product.get("description"),
                "category": category(product),
                "calories": n["calories"].get("displayValue", 0),
                "protein_g": values.get("protein_g", 0),
                "carbs_g": values.get("carbs_g", 0),
                "fat_g": values.get("fat_g", 0),
                "fiber_g": values.get("fiber_g"),
                "sodium_mg": values.get("sodium_mg"),
                "serving_note": serving_note,
                "is_estimate": False,
                "source": {"type": "published", "url": endpoint},
            })
    return items


def fetch_json(url):
    import urllib.request
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def locations(payload):
    output = []
    for row in payload:
        store = row.get("store", {})
        address = store.get("address", {})
        if address.get("city", "").strip().lower() != "san francisco":
            continue
        coordinates = store.get("coordinates", {})
        if "latitude" not in coordinates or "longitude" not in coordinates:
            continue
        output.append({
            "address": address.get("singleLine") or ", ".join(address.get("lines", [])),
            "lat": coordinates["latitude"],
            "lng": coordinates["longitude"],
            "neighborhood": None,
        })
    unique = {loc["address"]: loc for loc in output}
    return list(unique.values())


def main():
    payload = browser_payload()
    menu = payload["menu"]
    cache_path = Path(__file__).resolve().parent.parent / "data/cache/starbucks_products.json"
    details = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    doc = {
        "id": "starbucks",
        "name": "Starbucks",
        "website": "https://www.starbucks.com/",
        "nutrition_source": {
            "type": "published",
            "url": MENU_URL,
            "vendor": None,
            "retrieved": TODAY,
        },
        "locations": locations(payload["locator"]),
        "items": menu_items(menu, details),
    }
    save_restaurant(doc)


if __name__ == "__main__":
    main()
