import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from _crowd import fatsecret_items
from save import save_restaurant

BRAND = "https://foods.fatsecret.com/calories-nutrition/eriks-delicafe"


def main():
    save_restaurant({
        "id": "eriks-delicafe", "name": "Erik's DeliCafé",
        "website": "https://www.eriksdelicafe.com",
        "nutrition_source": {"type": "crowd", "url": BRAND, "vendor": "fatsecret", "retrieved": "2026-07-26"},
        "locations": [{"address": "425 Mission St, San Francisco, CA 94105", "lat": 37.7897, "lng": -122.3969, "neighborhood": "SoMa"}],
        "items": fatsecret_items(BRAND),
    })


if __name__ == "__main__":
    main()
