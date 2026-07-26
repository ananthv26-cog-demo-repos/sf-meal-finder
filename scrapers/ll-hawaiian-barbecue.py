import json
import re
import sys
import urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from _fatsecret import TODAY, food
from save import save_restaurant

LOCATIONS_URL = "https://www.hawaiianbarbecue.com/locations"
NUTRITION_URL = "https://platform.fatsecret.com/rest/server.api (foods.search/food.get)"

def main():
    page = urllib.request.urlopen(LOCATIONS_URL, timeout=30).read().decode()
    locs = []
    for m in re.finditer(r'"city":"San Francisco".{0,500}?"lat":([0-9.-]+),"lng":([0-9.-]+)', page):
        start = page.rfind('"address"', 0, m.start())
        text = page[start:m.start()]
        addresses = re.findall(r'"text":"([^"]+)"', text)
        address = addresses[-1] if addresses else "312 Kearny St."
        locs.append({"address": f"{address}, San Francisco, CA 94108", "lat": float(m.group(1)), "lng": float(m.group(2)), "neighborhood": "Union Square"})
    if not locs:
        locs = [{"address": "312 Kearny St., San Francisco, CA 94108", "lat": 37.791016, "lng": -122.404106, "neighborhood": "Union Square"}]
    specs = [
        ("bbq-mix", "BBQ Mix", "bbq mix", "meal", None),
        ("bbq-chicken", "BBQ Chicken", "bbq chicken", "meal", 76725),
        ("chicken-katsu", "Chicken Katsu", "chicken katsu", "meal", 1684073),
        ("loco-moco", "Loco Moco", "loco moco", "meal", None),
        ("lau-lau-combo", "Lau Lau Combo", "lau lau combo", "meal", None),
        ("half-half-combo", "Half & Half Combo", "half half combo", "meal", None),
        ("bbq-short-ribs", "BBQ Short Ribs", "bbq short ribs", "meal", None),
        ("bbq-cheeseburger", "BBQ Cheeseburger", "bbq cheeseburger", "meal", None),
        ("bbq-chicken-bowl", "BBQ Chicken Bowl", "bbq chicken bowl", "meal", None),
        ("fried-shrimp", "Fried Shrimp", "fried shrimp", "meal", None),
        ("kalua-pork-with-cabbage", "Kalua Pork with Cabbage", "kalua pork cabbage", "meal", None),
        ("lighter-bbq-chicken", "Lighter BBQ Chicken", "lighter bbq chicken", "meal", None),
        ("garlic-shrimp", "Garlic Shrimp", "garlic shrimp", "meal", None),
        ("spam-musubi", "SPAM Musubi", "spam musubi", "side", 1610668),
        ("spam-saimin", "SPAM Saimin", "spam saimin", "side", None),
    ]
    items = []
    for iid, name, query, category, fid in specs:
        try:
            item = food(food_id=fid) if fid else food(query, "L&L Hawaiian Barbecue")
        except RuntimeError as error:
            print(f"skip {name}: no exact FatSecret match ({error})", file=sys.stderr)
            continue
        items.append({"id": iid, "name": name, "description": "Crowd fallback; L&L publishes an allergen guide but no nutrition values.", "category": category, "is_estimate": True, **item})
    save_restaurant({"id": "ll-hawaiian-barbecue", "name": "L&L Hawaiian Barbecue", "website": "https://www.hawaiianbarbecue.com", "nutrition_source": {"type": "crowd", "url": NUTRITION_URL, "vendor": None, "retrieved": TODAY}, "locations": locs, "items": items})

if __name__ == "__main__":
    main()
