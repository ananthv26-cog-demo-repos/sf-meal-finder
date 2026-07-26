"""Build the compact JSON documents consumed by the web app."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "data" / "restaurants"
OUTPUT_DIR = ROOT / "app" / "public" / "data"


def build_distribution() -> tuple[Path, Path]:
    source_paths = sorted(SOURCE_DIR.glob("*.json"))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not source_paths:
        restaurants_path = OUTPUT_DIR / "restaurants.json"
        meals_path = OUTPUT_DIR / "meals.json"
        if restaurants_path.exists() and meals_path.exists():
            print("No source restaurants found; keeping existing app fixture data.")
            return restaurants_path, meals_path

    restaurants = []
    meals = []
    for path in source_paths:
        document = json.loads(path.read_text())
        nutrition_source = document.get("nutrition_source") or {}
        restaurants.append(
            {
                "id": document["id"],
                "name": document["name"],
                "website": document["website"],
                "nutrition_source": nutrition_source,
                "locations": document["locations"],
            }
        )
        for item in document.get("items", []):
            source = item.get("source") or nutrition_source
            meals.append(
                {
                    "id": item["id"],
                    "restaurant_id": document["id"],
                    "name": item["name"],
                    "description": item.get("description"),
                    "category": item["category"],
                    "calories": item["calories"],
                    "protein_g": item["protein_g"],
                    "carbs_g": item["carbs_g"],
                    "fat_g": item["fat_g"],
                    "fiber_g": item.get("fiber_g"),
                    "sodium_mg": item.get("sodium_mg"),
                    "serving_note": item.get("serving_note"),
                    "is_estimate": item["is_estimate"],
                    "source_type": source.get("type"),
                    "source_url": source.get("url"),
                }
            )

    restaurants_path = OUTPUT_DIR / "restaurants.json"
    meals_path = OUTPUT_DIR / "meals.json"
    restaurants_path.write_text(json.dumps(restaurants, indent=2, ensure_ascii=False) + "\n")
    meals_path.write_text(json.dumps(meals, indent=2, ensure_ascii=False) + "\n")
    return restaurants_path, meals_path


if __name__ == "__main__":
    restaurant_path, meals_path = build_distribution()
    print(f"Wrote {restaurant_path} and {meals_path}")
