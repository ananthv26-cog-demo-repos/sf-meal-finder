import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from _crowd import fatsecret_items
from save import save_restaurant

BRAND = "https://foods.fatsecret.com/calories-nutrition/la-boulangerie"


def main():
    save_restaurant({
        "id": "la-boulangerie", "name": "La Boulangerie de San Francisco",
        "website": "https://laboulangeriesf.com",
        "nutrition_source": {"type": "crowd", "url": BRAND, "vendor": "fatsecret", "retrieved": "2026-07-26"},
        "locations": [
            {"address": "2325 Pine St, San Francisco, CA 94115", "lat": 37.7876, "lng": -122.4344, "neighborhood": "Lower Pacific Heights"},
            {"address": "1000 Cole St, San Francisco, CA 94117", "lat": 37.7655, "lng": -122.4490, "neighborhood": "Cole Valley"},
            {"address": "3898 24th St, San Francisco, CA 94114", "lat": 37.7512, "lng": -122.4301, "neighborhood": "Noe Valley"},
            {"address": "500 Hayes St, San Francisco, CA 94102", "lat": 37.7770, "lng": -122.4246, "neighborhood": "Hayes Valley"},
        ],
        "items": fatsecret_items(BRAND),
    })


if __name__ == "__main__":
    main()
