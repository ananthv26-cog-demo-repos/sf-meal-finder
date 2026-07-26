import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from _crowd import fatsecret_items
from save import save_restaurant

BRAND = "https://foods.fatsecret.com/calories-nutrition/joe-the-juice"


def main():
    save_restaurant({
        "id": "joe-and-the-juice", "name": "Joe & The Juice",
        "website": "https://joejuice.com",
        "nutrition_source": {"type": "crowd", "url": BRAND, "vendor": "fatsecret", "retrieved": "2026-07-26"},
        "locations": [
            {"address": "525 Market St, San Francisco, CA 94105", "lat": 37.7897, "lng": -122.4008, "neighborhood": "SoMa"},
            {"address": "50 California St, San Francisco, CA 94111", "lat": 37.7935, "lng": -122.3970, "neighborhood": "Financial District"},
        ],
        "items": fatsecret_items(BRAND),
    })


if __name__ == "__main__":
    main()
