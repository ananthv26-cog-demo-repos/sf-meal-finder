"""Cold Stone Creamery official ice-cream nutrition PDF scraper."""
import datetime
import io
import re
import sys
from pathlib import Path

import pdfplumber
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant

URL = "https://www.coldstonecreamery.com/assets/pdf/nutrition/nutrition_info_icecream.pdf"
TODAY = datetime.date.today().isoformat()
SIZES = {"Kids", "Like It", "Like It®", "Love It", "Love It®", "Gotta Have It", "Gotta Have It®"}


def main():
    r = requests.get(URL, headers={"User-Agent": "Mozilla/5.0 Chrome/126", "Referer": "https://www.coldstonecreamery.com/"}, timeout=60)
    rows = []
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        for page in pdf.pages:
            for line in (page.extract_text() or "").splitlines():
                line = re.sub(r"\s+", " ", line).strip()
                m = re.match(r"^(.*?)\s+(\d+)\s+(Kids|Like It®?|Love It®?|Gotta Have It®?)\s+(\d+(?:\.\d+)?(?:\s+\d+(?:\.\d+)?){10})$", line)
                if not m or m.group(1).startswith(("Nutrition Info", "Ice Cream and")):
                    continue
                name, weight, size, nums = m.groups()
                v = list(map(float, nums.split()))
                rows.append((name.strip(), weight, size, v))
    items, seen = [], set()
    for name, weight, size, v in rows:
        key = re.sub(r"[^a-z0-9]+", "-", f"{name}-{size}".lower()).strip("-")
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "id": key, "name": f"{name} ({size})", "description": None, "category": "side",
            "calories": v[0], "fat_g": v[2], "protein_g": v[10], "carbs_g": v[7],
            "fiber_g": v[8], "sodium_mg": v[6],
            "serving_note": f"per {size} ({weight} g) serving", "is_estimate": False,
            "source": {"type": "published", "url": URL},
        })
    check = next((x for x in items if x["name"].startswith("Sweet Cream Ice Cream (Like It")), None)
    if check is None or check["calories"] != 340:
        actual = check["calories"] if check else "missing"
        raise SystemExit(f"Cold Stone Sweet Cream Like It spot check: {actual} kcal, expected published 340")
    save_restaurant({
        "id": "cold-stone-creamery", "name": "Cold Stone Creamery",
        "website": "https://www.coldstonecreamery.com",
        "nutrition_source": {"type": "published", "url": URL, "vendor": None, "retrieved": TODAY},
        "locations": [{"address": "2737 Taylor St, San Francisco, CA 94133",
                       "lat": 37.8076399, "lng": -122.4157933, "neighborhood": None}],
        "items": items,
    })
    print(f"Cold Stone items: {len(items)}")


if __name__ == "__main__":
    main()
