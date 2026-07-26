"""Lee's Sandwiches official menu scraper."""
import datetime
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from time import sleep

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant

BASE = "https://leesandwiches.com"
MENU_SITEMAP_URL = f"{BASE}/wp-sitemap-posts-menu-1.xml"
TODAY = datetime.date.today().isoformat()
SECTIONS = {
    "asian-sandwiches": "meal", "euro-sandwiches": "meal", "breakfast": "meal",
    "appetizers": "side", "pastries": "side", "desserts": "side",
    "beverages": "drink", "lee-coffee-drink": "drink", "smoothies": "drink",
}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def main():
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; sf-meal-finder/1.0)"
    links = {}
    sitemap = session.get(MENU_SITEMAP_URL, timeout=60)
    sitemap.raise_for_status()
    for loc in BeautifulSoup(sitemap.text, "xml").select("loc"):
        href = loc.get_text(strip=True).rstrip("/")
        if re.search(r"/menu/[^/]+$", href):
            links[href] = "component"
    for section, category in SECTIONS.items():
        soup = BeautifulSoup(session.get(f"{BASE}/menu-categories/{section}/", timeout=60).text, "lxml")
        for a in soup.select("a[href*='/menu/']"):
            href = urljoin(BASE, a["href"]).rstrip("/")
            if re.search(r"/menu/[^/]+$", href) and href != f"{BASE}/menu":
                links[href] = category
    if len(links) < 100:
        raise RuntimeError(f"Lee's menu sitemap/category crawl found only {len(links)} item URLs")
    items = []
    fetched = 0
    for url, category in sorted(links.items()):
        response = None
        for attempt in range(4):
            response = session.get(url, timeout=60)
            if response.ok and "<h1" in response.text:
                break
            sleep(2 ** attempt)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        fetched += 1
        title = soup.select_one("h1")
        facts = {}
        for fact in soup.select(".nutritional-fact"):
            label = fact.select_one(".label").get_text(" ", strip=True).lower()
            value = fact.select_one(".value").get_text(" ", strip=True)
            number = re.search(r"\d+(?:\.\d+)?", value)
            if number:
                facts[label] = float(number.group())
        required = ["calories", "total fat", "carbs", "protein"]
        if not title or not all(k in facts for k in required):
            continue
        name = title.get_text(" ", strip=True).lstrip("#").strip()
        items.append({
            "id": slug(name), "name": name, "description": None, "category": category,
            "calories": facts["calories"], "protein_g": facts["protein"],
            "carbs_g": facts["carbs"], "fat_g": facts["total fat"],
            "fiber_g": facts.get("fiber"), "sodium_mg": facts.get("sodium"),
            "serving_note": "per menu item", "is_estimate": False,
            "source": {"type": "published", "url": url},
        })
    if fetched != len(links):
        raise RuntimeError(f"Lee's crawl fetched {fetched}/{len(links)} item pages")
    check = next((item for item in items if item["name"] == "1 Lee’s Combination"), None)
    if check is None or check["calories"] != 690:
        actual = check["calories"] if check else "missing"
        raise SystemExit(f"Lee's Combination spot check: {actual} kcal, expected published 690")
    save_restaurant({
        "id": "lees-sandwiches", "name": "Lee's Sandwiches", "website": BASE,
        "nutrition_source": {"type": "published", "url": MENU_SITEMAP_URL,
                             "vendor": None, "retrieved": TODAY},
        "locations": [{"address": "625 Larkin St, San Francisco, CA 94109",
                       "lat": 37.7836349, "lng": -122.4178775, "neighborhood": None}],
        "items": items,
    })
    print(f"Lee's items: {len(items)}")


if __name__ == "__main__":
    main()
