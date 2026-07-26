"""Kura Sushi USA nutrition PDF scraper."""
import datetime
import re
import sys
import urllib.request
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

NUTRITION_URL = "https://kurasushi.com/menu/Kura-Sushi-Nutrition-Information-May-20-2026.pdf"
TODAY = datetime.date.today().isoformat()
MEAL_SECTIONS = {
    "DONBURI", "UDON", "RAMEN", "NOODLES", "SOBA", "CURRY", "BENTO",
    "COMBOS", "ENTREES",
}
NON_MEAL_SECTIONS = {"DESSERTS", "SOFT DRINKS", "SIDE DISHES", "ALCOHOL"}


def number(value):
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse(pdf_path):
    rows, section, pending = [], "SIDES", []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for raw in table:
                    cells = [str(v).replace("\n", " ").strip() if v is not None else "" for v in raw]
                    if not cells:
                        continue
                    name_width = 1 if len(cells) == 16 else 3
                    text = " ".join(cells[:name_width]).strip()
                    upper = " ".join(cells).upper()
                    if text and all(not c for c in cells[1:]) and text.isupper() and len(text) < 40:
                        section, pending = text, []
                        continue
                    if "MENU ITEM" in upper or "CALORIES FROM FAT" in upper:
                        pending = []
                        continue
                    if len(cells) == 16:
                        starts = (1,)
                    else:
                        starts = (3, 4)
                    start = next((candidate for candidate in starts if candidate < len(cells) and number(cells[candidate]) is not None), None)
                    if start is None:
                        if text and rows:
                            rows[-1] = (rows[-1][0], f"{rows[-1][1]} {text}".strip(), rows[-1][2])
                        elif text:
                            pending.append(text)
                        continue
                    metric_columns = (
                        tuple(range(start, 48, 3)) if len(cells) >= 48
                        else tuple(range(start, len(cells)))
                    )
                    values = [number(cells[index]) or 0.0 for index in metric_columns]
                    values.extend([0.0] * (15 - len(values)))
                    values = values[:15]
                    name = " ".join(pending + [text]).strip()
                    pending = []
                    if name:
                        rows.append((section, name, values))
    return rows


def main():
    pdf_path = "/tmp/kura-nutrition.pdf"
    request = urllib.request.Request(NUTRITION_URL, headers={"User-Agent": "Mozilla/5.0 Chrome/133"})
    with urllib.request.urlopen(request, timeout=60) as response:
        Path(pdf_path).write_bytes(response.read())
    items = []
    used_ids = {}
    for section, name, values in parse(pdf_path):
        calories, _, fat, _, _, _, _, _, sodium, _, carbs, fiber, _, _, protein = values
        lower_name = name.lower()
        entree_name = any(term in lower_name for term in (" udon", " ramen", " soba", " mazemen", " curry", "bento", "donburi"))
        category = "meal" if section in MEAL_SECTIONS or entree_name else "drink" if section in {"SOFT DRINKS", "ALCOHOL"} else "side"
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        used_ids[slug] = used_ids.get(slug, 0) + 1
        item_id = slug if used_ids[slug] == 1 else f"{slug}-{used_ids[slug]}"
        items.append({
            "id": item_id,
            "name": name,
            "description": f"Official Kura Sushi nutrition PDF; section {section.title()}.",
            "category": category,
            "calories": calories,
            "protein_g": protein,
            "carbs_g": carbs,
            "fat_g": fat,
            "fiber_g": fiber,
            "sodium_mg": sodium,
            "serving_note": "per listed menu serving",
            "is_estimate": False,
            "source": {"type": "published", "url": NUTRITION_URL},
        })
    save_restaurant({
        "id": "kura-revolving-sushi",
        "name": "Kura Revolving Sushi Bar",
        "website": "https://kurasushi.com",
        "nutrition_source": {"type": "published", "url": NUTRITION_URL, "vendor": None, "retrieved": TODAY},
        "locations": [{
            "address": "3251 20th Ave, Space 220, San Francisco, CA 94132",
            "lat": 37.728694,
            "lng": -122.47523,
            "neighborhood": "Stonestown",
        }],
        "items": items,
    })


if __name__ == "__main__":
    main()
