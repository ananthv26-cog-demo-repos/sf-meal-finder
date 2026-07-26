import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from _crowd import mynetdiary_item
from save import save_restaurant

BRAND = "https://www.marugameudon.com/locations/stonestown/"
ITEMS = [
    ("https://www.mynetdiary.com/food/calories-in-curry-nikutama-by-marugame-bowl-42694639-0.html", "meal"),
    ("https://www.mynetdiary.com/food/calories-in-beer-curry-by-marugame-udon-portion-40460048-0.html", "component"),
    ("https://www.mynetdiary.com/food/calories-in-chicken-katsu-by-marugame-piece-46897017-0.html", "side"),
    ("https://www.mynetdiary.com/food/calories-in-regular-sukiyaki-ninja-udon-by-marugame-serving-50623950-0.html", "meal"),
]


def main():
    save_restaurant({
        "id": "marugame-udon", "name": "Marugame Udon",
        "website": "https://www.marugameudon.com",
        "nutrition_source": {"type": "crowd", "url": BRAND, "vendor": "mynetdiary", "retrieved": "2026-07-26"},
        "locations": [{"address": "3251 20th Ave, San Francisco, CA 94132", "lat": 37.7332, "lng": -122.4767, "neighborhood": "Stonestown"}],
        "items": [mynetdiary_item(url, category=category) for url, category in ITEMS],
    })


if __name__ == "__main__":
    main()
