import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from _fatsecret import TODAY, food
from save import save_restaurant

def main():
    locs = [{"address": "601 Mission Bay Boulevard North, San Francisco, CA 94158", "lat": 37.7707779, "lng": -122.3914399, "neighborhood": "Mission Bay"}]
    specs = [
        ("original-koja", "The Original KoJa", "The Original KoJa", "meal"),
        ("teriyaki-zen-koja", "Teriyaki Zen KoJa", "Teriyaki Zen KoJa", "meal"),
        ("beef-koja", "Beef KoJa", "Beef KoJa", "meal"),
        ("chicken-koja", "Chicken KoJa", "Chicken KoJa", "meal"),
        ("braised-pork-koja", "Braised Pork KoJa", "Braised Pork KoJa", "meal"),
        ("short-rib-bowl", "Short Rib Bowl", "Short Rib Bowl", "meal"),
        ("teriyaki-zen-bowl", "Teriyaki Zen Bowl", "Teriyaki Zen Bowl", "meal"),
        ("beef-bowl", "Beef Bowl", "Beef Bowl", "meal"),
        ("ahi-tuna-salad", "Ahi Tuna Salad", "Ahi Tuna Salad", "meal"),
        ("chicken-bowl", "Chicken Bowl", "Chicken Bowl", "meal"),
        ("ahi-tuna-bowl", "Ahi Tuna Bowl", "Ahi Tuna Bowl", "meal"),
        ("braised-pork-bowl", "Braised Pork Bowl", "Braised Pork Bowl", "meal"),
        ("beef-taco", "Beef Taco", "Beef Taco", "meal"),
        ("chicken-taco", "Chicken Taco", "Chicken Taco", "meal"),
        ("braised-pork-taco", "Braised Pork Taco", "Braised Pork Taco", "meal"),
        ("zen-taco", "Zen Taco", "Zen Taco", "meal"),
        ("crispy-chicken-bowl", "Crispy Chicken Bowl", "Crispy Chicken Bowl", "meal"),
        ("crispy-chicken-burger", "Crispy Chicken Burger", "Crispy Chicken Burger", "meal"),
        ("kamikaze-fries", "Kamikaze Fries", "Kamikaze Fries", "side"),
        ("signature-musubi", "Signature Musubi", "Signature Musubi", "side"),
        ("umami-fries", "Umami Fries", "Umami Fries", "side"),
        ("korean-buffalo-wings", "Korean Buffalo Wings", "Korean Buffalo Wings", "side"),
        ("soy-garlic-wings", "Soy Garlic Wings", "Soy Garlic Wings", "side"),
        ("strawberry-mango-mint-lemonade", "Strawberry Mango Mint Lemonade", "Strawberry Mango Mint Lemonade", "drink"),
    ]
    items = []
    for iid, name, query, category in specs:
        try:
            item = food(query, "KoJa")
        except RuntimeError as error:
            print(f"skip {name}: no exact FatSecret match ({error})", file=sys.stderr)
            continue
        items.append({"id": iid, "name": name, "description": "Crowd fallback from FatSecret; KoJa does not publish nutrition values.", "category": category, "is_estimate": True, **item})
    save_restaurant({"id": "koja-kitchen", "name": "KoJa Kitchen", "website": "https://www.kojakitchen.com", "nutrition_source": {"type": "crowd", "url": "https://platform.fatsecret.com/rest/server.api (foods.search/food.get)", "vendor": None, "retrieved": TODAY}, "locations": locs, "items": items})

if __name__ == "__main__":
    main()
