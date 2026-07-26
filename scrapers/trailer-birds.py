"""Trailer Birds menu nutrition with conservative tender derivations."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from _fatsecret import TODAY, food
from save import save_restaurant

MENU_URL = "https://www.trailerbirds.com/static/docs/trailer-birds-menu-at-a-glance.pdf"


def scaled(base, count):
    fields = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sodium_mg")
    return {key: round(base[key] * count, 2) for key in fields}


def main():
    locs = [
        {"address": "590 Van Ness Avenue, San Francisco, CA 94102", "lat": 37.7807130, "lng": -122.4201840, "neighborhood": "Civic Center"},
        {"address": "5155 3rd Street, San Francisco, CA 94124", "lat": 37.7314584, "lng": -122.3917507, "neighborhood": "Bayview"},
    ]
    items = []
    one_tender = food(food_id=1735)
    for count in (1, 2, 3, 4, 6):
        values = scaled(one_tender, count)
        items.append({
            "id": f"{count}-tenders",
            "name": f"{count} Tender{'s' if count != 1 else ''}",
            "description": (
                f"Derived as {count} × one 100 g breaded chicken tender crowd row. "
                f"Official menu calorie range reference: {MENU_URL}"
            ),
            "category": "component" if count in (1, 2) else "meal",
            "is_estimate": True,
            "serving_note": f"{count} tenders, derived from one 100 g tender-equivalent serving",
            "source": {"type": "derived", "url": one_tender["source"]["url"]},
            **values,
        })
    print("skip Hot Chicken Sandwich: generic crowd result failed official calorie sanity check", file=sys.stderr)
    for name in ("Crispy Tots", "Hand-Cut Fries", "Coleslaw", "Texas Toast", "Ranch", "Big Yellow Cup"):
        print(f"skip {name}: no exact permitted crowd match", file=sys.stderr)
    save_restaurant({
        "id": "trailer-birds",
        "name": "Trailer Birds",
        "website": "https://www.trailerbirds.com",
        "nutrition_source": {
            "type": "crowd",
            "url": "https://platform.fatsecret.com/rest/server.api (foods.search/food.get)",
            "vendor": None,
            "retrieved": TODAY,
        },
        "locations": locs,
        "items": items,
    })


if __name__ == "__main__":
    main()
