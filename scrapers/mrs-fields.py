"""Mrs. Fields official nutrition pages scraper."""
import datetime
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant

URL = "https://www.mrsfields.com/pages/nutrition-information"
TODAY = datetime.date.today().isoformat()


def main():
    # The linked cookie pages publish ingredients but no nutrition values. The
    # "other" page is the only page with labeled numeric nutrition facts.
    url = "https://www.mrsfields.com/pages/nutrition-details-other"
    soup = BeautifulSoup(requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60).text, "lxml")
    items = []
    # The official cookie and Nibbler pages publish ingredients and label
    # images, but no recoverable numeric cookie nutrition check is available.
    names = ["Chocolate Covered Almonds 2oz Bag", "Chocolate Covered Pretzels 4oz Bag",
             "Kettle Corn 2oz Bag", "Yogurt Covered Almonds 2oz Bag", "Yogurt Pretzels 4oz Bags"]
    fact_rows = [r for r in soup.select("tr") if "Calories Calories from Fat" in r.get_text(" ", strip=True)]
    for name, row in zip(names, fact_rows):
        values = list(map(float, re.findall(r"\d+(?:\.\d+)?", row.select("td")[1].get_text(" ", strip=True))))
        cal, fat, sodium, carbs, fiber, protein = values[0], values[2], values[5], values[6], values[7], values[9]
        items.append({
            "id": re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"), "name": name,
            "description": None, "category": "side", "calories": cal,
            "protein_g": protein, "carbs_g": carbs, "fat_g": fat,
            "fiber_g": fiber, "sodium_mg": sodium,
            "serving_note": "per package serving", "is_estimate": False,
            "source": {"type": "published", "url": url},
        })
    save_restaurant({
        "id": "mrs-fields", "name": "Mrs. Fields", "website": "https://www.mrsfields.com",
        "nutrition_source": {"type": "published", "url": URL, "vendor": None, "retrieved": TODAY},
        "locations": [{"address": "Pier 39 Bldg B-06, San Francisco, CA 94133",
                       "lat": 37.8076399, "lng": -122.4157933, "neighborhood": None}],
        "items": items,
    })
    print(f"Mrs. Fields items: {len(items)}")


if __name__ == "__main__":
    main()
