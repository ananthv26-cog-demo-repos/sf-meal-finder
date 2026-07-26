"""The Cheese Steak Shop menu with conservative FatSecret fallback matches."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from _fatsecret import TODAY, food
from save import save_restaurant

MENU_URL = "https://www.cheesesteakshop.com/wp-content/uploads/2025/06/21490_CSS_TOMenu_HR-1.pdf"


def main():
    locs = [{
        "address": "1716 Divisadero St., San Francisco, CA 94115",
        "lat": 37.7855821,
        "lng": -122.4396991,
        "neighborhood": "Pacific Heights",
    }]
    specs = [
        ("classic-philly", "Classic Philly Cheese Steak", 2775, "generic steak-and-cheese sandwich"),
        ("king-of-philly", "The King of Philly", 2775, "generic steak-and-cheese sandwich"),
        ("motown-philly", "Motown Philly", 2775, "generic steak-and-cheese sandwich"),
        ("smoky-bbq", "Smoky BBQ", 2775, "generic steak-and-cheese sandwich"),
        ("philly-joes", "Philly Joe's", 2775, "generic steak-and-cheese sandwich"),
        ("pizza-steak", "Pizza Steak", 2775, "generic steak-and-cheese sandwich"),
        ("western", "Western", 2775, "generic steak-and-cheese sandwich"),
        ("sizzlin-pig", "Sizzlin' Pig", 2775, "generic steak-and-cheese sandwich"),
        ("pepper-steak", "Pepper Steak", 2775, "generic steak-and-cheese sandwich"),
        ("mushroom-steak", "Mushroom Steak", 2775, "generic steak-and-cheese sandwich"),
        ("chicken-cheese-steak", "Chicken Cheese Steak", 2776, "generic cheese submarine"),
        ("steak-hoagie", "Steak Hoagie", 2776, "generic steak-and-cheese submarine"),
        ("philly-salad", "Philly Salad", 2774, "generic steak-and-cheese submarine salad"),
    ]
    items = []
    nutrition_cache = {}
    for iid, name, food_id, match_note in specs:
        if food_id not in nutrition_cache:
            nutrition_cache[food_id] = food(food_id=food_id)
        item = nutrition_cache[food_id].copy()
        items.append({
            "id": iid,
            "name": name,
            "description": (
                f"Official menu item; no Cheese Steak Shop-branded FatSecret row "
                f"was available, so this uses the closest {match_note} crowd row. "
                f"Menu/calorie reference: {MENU_URL}"
            ),
            "category": "meal",
            "is_estimate": True,
            **item,
        })
    save_restaurant({
        "id": "cheese-steak-shop",
        "name": "The Cheese Steak Shop",
        "website": "https://www.cheesesteakshop.com",
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
