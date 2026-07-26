import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _crowd import mynetdiary_item
from save import save_restaurant

BRAND = "https://orenshummus.com/locations/restaurants/san-francisco/"
ITEM_URLS = [
    "https://www.mynetdiary.com/food/calories-in-plain-israeli-hummus-by-oren-s-hummus-shop-serving-14264333-0.html",
    "https://www.mynetdiary.com/food/calories-in-eggplant-babaganoush-by-oren-s-hummus-shop-serving-14264337-0.html",
    "https://www.mynetdiary.com/food/calories-in-marinated-beets-by-orens-hummus-serving-22540501-0.html",
    "https://www.mynetdiary.com/food/calories-in-chicken-pita-sandwich-by-oren-s-hummus-meal-43743146-0.html",
    "https://www.mynetdiary.com/food/calories-in-labane-by-oren-s-hummus-serving-30469702-0.html",
]


def main():
    save_restaurant({
        "id": "orens-hummus", "name": "Oren's Hummus",
        "website": "https://orenshummus.com",
        "nutrition_source": {"type": "crowd", "url": BRAND, "vendor": "mynetdiary", "retrieved": "2026-07-26"},
        "locations": [{"address": "71 3rd St, San Francisco, CA 94103", "lat": 37.7866, "lng": -122.4024, "neighborhood": "SoMa"}],
        "items": [
            mynetdiary_item(
                url,
                category=(
                    "meal" if "sandwich" in url else
                    "side" if "marinated-beets" in url else
                    "condiment"
                ),
            )
            for url in ITEM_URLS
        ],
    })


if __name__ == "__main__":
    main()
