"""Mr. Charlie's San Francisco scraper from the restaurant's nutrition page."""

import datetime
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

NUTRITION_URL = "https://mrcharlies.co/nutrition"
LOCATIONS_URL = "https://mrcharlies.co/locations"
TODAY = datetime.date.today().isoformat()


def fetch():
    request = urllib.request.Request(NUTRITION_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def parse(html):
    # The published page stores each item as a heading followed by labeled
    # nutrition lines.  Parsing labels avoids depending on their DOM layout.
    pattern = re.compile(
        r'class="font_[^"]*"[^>]*>([^<]+)</span>.*?Calories:\s*([0-9.]+).*?'
        r'Total Fat:\s*([<0-9.]+)g.*?Sodium:\s*([<0-9.]+)mg.*?'
        r'Total Carbs:\s*([0-9.]+)g.*?Dietary Fiber:\s*([0-9.]+)g.*?'
        r'Protein:\s*([0-9.]+)g',
        re.S,
    )
    rows = []
    known_names = {
        "Not a Cheeseburger", "Double Not", "Not a Chicken Sandwich",
        "Mr.Sunday", "Not Chicken Nuggets (7)",
    }
    for match in pattern.finditer(html):
        name = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        if name not in known_names:
            print(f"Warning: ignoring non-menu nutrition heading {name!r}")
            continue
        values = match.groups()[1:]
        if name in {row["name"] for row in rows}:
            continue
        calories, fat, sodium, carbs, fiber, protein = map(float, values)
        lower = name.lower()
        if "nugget" in lower or "fries" in lower:
            category = "side"
        elif any(word in lower for word in ("shake", "drink", "juice", "milk")):
            category = "drink"
        elif name in {"Not a Cheeseburger", "Double Not", "Not a Chicken Sandwich", "Mr.Sunday"}:
            category = "meal"
        else:
            print(f"Warning: unmapped Mr. Charlie's item {name!r}; using component")
            category = "component"
        rows.append({
            "id": re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"),
            "name": name,
            "description": None,
            "category": category,
            "calories": calories,
            "protein_g": protein,
            "carbs_g": carbs,
            "fat_g": fat,
            "fiber_g": fiber,
            "sodium_mg": sodium,
            "serving_note": "per menu item",
            "is_estimate": False,
            "source": {"type": "published", "url": NUTRITION_URL},
        })
    if not rows:
        raise RuntimeError("Mr. Charlie's nutrition page yielded no labeled rows")
    return rows


def main():
    items = parse(fetch())
    famous = next(row for row in items if row["name"] == "Not a Cheeseburger")
    print(
        "Not a Cheeseburger spot-check: "
        f"{famous['calories']:g} kcal, {famous['fat_g']:g} g fat, "
        f"{famous['carbs_g']:g} g carbs, {famous['protein_g']:g} g protein"
    )
    save_restaurant({
        "id": "mr-charlies",
        "name": "Mr. Charlie's",
        "website": "https://mrcharlies.co",
        "nutrition_source": {"type": "published", "url": NUTRITION_URL, "vendor": None, "retrieved": TODAY},
        "locations": [{
            "address": "432 Sutter St, San Francisco, CA 94108",
            "lat": 37.789956,
            "lng": -122.407116,
            "neighborhood": "Union Square",
        }],
        "items": items,
    })


if __name__ == "__main__":
    main()
