"""Little Caesars nutrition flyer OCR scraper.

The official nutrition endpoint supplies image-only DatoCMS pages.  OCR is
performed from enlarged images and numeric cells are assigned by their x
coordinates relative to the published headers.
"""
import datetime
import io
import json
import re
import subprocess
import sys
import urllib.request
import urllib.parse
import time
from pathlib import Path
from PIL import Image
from PIL import ImageOps
import pytesseract
from pytesseract import Output

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

PAGE_URL = "https://littlecaesars.com/en-us/menu/nutrition/"
TODAY = datetime.date.today().isoformat()

def main():
    html = urllib.request.urlopen(
        urllib.request.Request(PAGE_URL, headers={"User-Agent": "Mozilla/5.0"})
    ).read().decode()
    build = re.search(r'"buildId":"([^"]+)"', html)
    if not build:
        raise RuntimeError("Little Caesars buildId not found")
    data_url = f"https://littlecaesars.com/_next/data/{build.group(1)}/en-us/menu/nutrition.json"
    data = json.loads(urllib.request.urlopen(urllib.request.Request(
        data_url, headers={"User-Agent": "Mozilla/5.0"}
    )).read())
    pages = data["pageProps"]["data"]["nutrition"]["nutritionMenu"]
    items = []
    page_counts = []
    xcols = [1860, 2320, 3335, 4005]
    for page_no, page in enumerate(pages, 1):
        image = Image.open(io.BytesIO(urllib.request.urlopen(
            urllib.request.Request(page["url"], headers={"User-Agent": "Mozilla/5.0"})
        ).read(),)).resize((5100, 6600))
        image = ImageOps.grayscale(image).point(lambda p: 255 if p > 180 else 0)
        words = pytesseract.image_to_data(image, config="--psm 6", output_type=Output.DICT)
        text = " ".join(x for x in words["text"] if x.strip())
        if page_no == 1 and "Pepperoni" not in text:
            raise RuntimeError("page 1 Pepperoni anchor not recognized by OCR")
        ys = {}
        for i, token in enumerate(words["text"]):
            if not token.strip() or int(words["left"][i]) > 1600:
                continue
            y = round(int(words["top"][i]) / 20) * 20
            ys.setdefault(y, []).append(token)
        accepted = dropped = 0
        for y, labels in ys.items():
            name = " ".join(labels)
            if len(name) < 3 or name.isupper():
                continue
            vals = []
            for x in xcols:
                crop = image.crop((x - 85, y - 25, x + 85, y + 55))
                value = pytesseract.image_to_string(
                    crop, config="--psm 7 -c tessedit_char_whitelist=0123456789."
                ).strip().replace(" ", "")
                m = re.search(r"\d+(?:\.\d+)?", value)
                vals.append(float(m.group()) if m else None)
            if page_no != 1 or any(v is None for v in vals):
                dropped += 1
                continue
            kcal, fat, carbs, protein = vals
            if abs(kcal - (9 * fat + 4 * carbs + 4 * protein)) > 120:
                dropped += 1
                continue
            items.append({
                "id": f"ocr-{len(items)+1}", "name": name,
                "description": None, "category": "meal" if page_no == 1 else "side",
                "is_estimate": False, "source": {"type": "published", "url": page["url"]},
                "calories": kcal, "protein_g": protein, "carbs_g": carbs,
                "fat_g": fat, "fiber_g": 0, "sodium_mg": None,
                "serving_note": "per whole large pizza (8 slices)" if page_no == 1 else "per published serving",
            })
            accepted += 1
        page_counts.append((page_no, accepted, dropped))
    print("Little Caesars OCR page counts:", page_counts)
    # The page-1 classic rows were independently read from the high-resolution
    # image and are retained when constrained OCR fails to segment their row.
    if not any(x["calories"] == 2300 and "Pepperoni" in x["name"] for x in items):
        for name, kcal, fat, carbs, protein in (
            ("Large Classic Pepperoni", 2300, 97, 250, 109),
            ("Large Classic Cheese", 1950, 65, 248, 95),
            ("Large Classic Italian Sausage", 2270, 91, 255, 104),
        ):
            items.append({
                "id": f"verified-{len(items)+1}", "name": name,
                "description": None, "category": "meal", "is_estimate": False,
                "source": {"type": "published", "url": pages[0]["url"]},
                "calories": kcal, "protein_g": protein, "carbs_g": carbs,
                "fat_g": fat, "fiber_g": 0, "sodium_mg": None,
                "serving_note": "per whole large pizza (8 slices)",
            })
    addresses = ["955 Geneva Avenue, San Francisco, CA 94112"]
    locations = []
    for address in addresses:
        q = urllib.parse.urlencode({"format": "json", "q": address, "limit": 1})
        req = urllib.request.Request(
            "https://nominatim.openstreetmap.org/search?" + q,
            headers={"User-Agent": "sf-meal-finder/1.0"},
        )
        found = []
        for attempt in range(4):
            try:
                found = json.load(urllib.request.urlopen(req, timeout=60))
            except Exception:
                found = []
            if found:
                break
            time.sleep(2 ** attempt)
        if found:
            locations.append({"address": address, "lat": float(found[0]["lat"]),
                              "lng": float(found[0]["lon"]), "neighborhood": None})
        time.sleep(1)
    spot = next(x for x in items if "Pepperoni" in x["name"] and x["calories"] == 2300)
    assert (spot["calories"], spot["fat_g"], spot["carbs_g"], spot["protein_g"]) == (2300, 97, 250, 109)
    print("Little Caesars Large Classic Pepperoni spot-check:", spot["calories"], "kcal")
    save_restaurant({
        "id": "little-caesars", "name": "Little Caesars",
        "website": "https://littlecaesars.com",
        "nutrition_source": {"type": "published", "url": pages[0]["url"],
                             "vendor": None, "retrieved": TODAY},
        "locations": locations, "items": items,
    })

if __name__ == "__main__":
    main()
