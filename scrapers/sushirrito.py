import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from _crowd import mynetdiary_item
from save import save_restaurant

BRAND = "https://www.sushirrito.com/"
ITEM_URLS = [
    "https://www.mynetdiary.com/food/calories-in-sumo-crunch-by-sushirrito-burrito-34601098-0.html",
    "https://www.mynetdiary.com/food/calories-in-geishas-kiss-no-cucumbers-by-sushiritto-roll-18703488-0.html",
]


def main():
    save_restaurant({
        "id": "sushirrito", "name": "Sushirrito",
        "website": BRAND,
        "nutrition_source": {"type": "crowd", "url": BRAND, "vendor": "mynetdiary", "retrieved": "2026-07-26"},
        "locations": [
            {"address": "59 New Montgomery St, San Francisco, CA 94105", "lat": 37.7888, "lng": -122.3998, "neighborhood": "SoMa"},
            {"address": "226 Kearny St, San Francisco, CA 94108", "lat": 37.7905, "lng": -122.4039, "neighborhood": "Union Square"},
        ],
        "items": [mynetdiary_item(url) for url in ITEM_URLS],
    })


if __name__ == "__main__":
    main()
