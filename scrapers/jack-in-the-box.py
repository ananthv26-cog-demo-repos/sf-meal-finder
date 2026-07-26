"""Jack in the Box nutrition scraper using the chain's current nutrition guide."""

import datetime
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

NUTRITION_URL = (
    "https://images.ctfassets.net/5hs630wuugof/5YPXJN6p8U0Esf31agJxUK/"
    "05534c155563a67b239740ef0bc51866/Nutrition_Information_2026.PDF"
)
TODAY = datetime.date.today().isoformat()


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _number(value):
    if value is None or value in {"", "--", "—"}:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    return float(match.group()) if match else None


def _clean_name(name):
    return re.sub(r"\s+", " ", name.replace("®", "").replace("™", "")).strip(" ^")


def _category(name, section):
    lower = name.lower()
    section_lower = section.lower()
    if "salad" in lower and "chicken" in lower:
        return "meal"
    if any(word in lower for word in ("fries", "rings", "hash brown", "egg roll", "churro", "cheesecake", "cake", "salad")):
        return "side"
    if any(word in lower for word in ("shake", "coffee", "tea", "juice", "water", "milk", "red bull", "infusion")):
        return "drink"
    if any(word in lower for word in ("sauce", "dressing", "dipping", "dip cup", "ketchup", "mustard", "spread", "butter")):
        return "condiment"
    if any(word in lower for word in ("burger", "sandwich", "bowl", "burrito", "taco", "wrap", "chicken club", "jack")):
        return "meal"
    if section_lower in {"beverages", "drinks & coffee"}:
        return "drink"
    if section_lower in {"condiments", "dipping sauces", "sandwich sauces", "other"}:
        return "condiment"
    if section_lower in {"sweets", "snacks & sides", "sides", "old-fashioned shakes & desserts"}:
        if "shake" in lower:
            return "drink"
        return "side"
    if section_lower in {
        "better for you", "burgers & more", "chicken & more", "breakfast",
        "breakfast meals", "breakfast sandwiches", "jack's munchie meals",
        "burritos", "flame grilled burgers", "limited time only",
        "king jr. kids meals", "digital exclusives",
    }:
        return "meal"
    if any(word in lower for word in ("shake", "coffee", "tea", "juice", "water", "milk")):
        return "drink"
    print(f"Warning: unmapped Jack in the Box section {section!r} for {name!r}; using component")
    return "component"


def _word_rows(page):
    words = page.extract_words()
    groups = []
    for word in sorted(words, key=lambda item: item["top"]):
        if not groups or word["top"] - groups[-1][0] > 0.8:
            groups.append([word["top"], [word]])
        else:
            groups[-1][1].append(word)
    return groups


def _parse_column(page, side):
    if side == "left":
        name_min, name_max, min_x, max_x = 0, 240, 240, 630
        centers = [286, 314, 344, 375, 404, 428, 453, 482, 513, 543, 570, 591, 614]
    else:
        name_min, name_max, min_x, max_x = 660, 835, 835, 1230
        centers = [879, 909, 938, 969, 997, 1022, 1048, 1076, 1108, 1137, 1164, 1185, 1210]

    section_starts = (
        [(257.0, "Better for You"), (335.0, "Burgers & More"),
         (521.0, "Chicken & More"), (720.0, "Salads"),
         (868.0, "Snacks & Sides"), (1082.0, "Breakfast"),
         (1324.0, "Jack's Munchie Meals")]
        if side == "left" else
        [(163.0, "Old-Fashioned Shakes & Desserts"), (315.0, "Kids"),
         (652.0, "Cheeses"), (706.0, "Dipping Sauces"),
         (850.0, "Sandwich Sauces"), (948.0, "Other"),
         (1089.0, "Beverages")]
    )
    rows = {}
    for top, group in _word_rows(page):
        name_words = [word for word in group if name_min <= word["x0"] < name_max]
        name = _clean_name(" ".join(
            word["text"] for word in sorted(name_words, key=lambda item: item["x0"])
        ))
        if not name or not re.search("[A-Za-z]", name):
            continue
        if re.search(r"\d{3,}", name) or re.match(r"^[A-Z]{1,6}\s+\d", name):
            continue
        values = []
        for index, center in enumerate(centers):
            lower = min_x if index == 0 else (centers[index - 1] + center) / 2
            upper = max_x if index == len(centers) - 1 else (center + centers[index + 1]) / 2
            values.append("".join(
                word["text"].replace(" ", "")
                for word in sorted(group, key=lambda item: item["x0"])
                if lower <= word["x0"] < upper
            ))
        if _number(values[1]) is None:
            continue
        serving_match = re.search(r"(\d+(?:\.\d+)?)\s*$", values[0])
        serving = float(serving_match.group(1)) if serving_match else None
        nutrition = [_number(value) for value in values[1:]]
        if serving is None or any(value is None for value in nutrition):
            continue
        section = max(
            (label for start, label in section_starts if top >= start),
            key=lambda label: next(start for start, candidate in section_starts if candidate == label),
            default="",
        )
        row = {
            "name": name,
            "serving": serving,
            "calories": nutrition[0],
            "fat_g": nutrition[2],
            "carbs_g": nutrition[8],
            "fiber_g": nutrition[9],
            "protein_g": nutrition[11],
            "sodium_mg": nutrition[6],
            "section": section,
        }
        key = (name.lower(), tuple(row[field] for field in (
            "serving", "calories", "fat_g", "carbs_g", "protein_g",
        )))
        rows[key] = row
    return list(rows.values())


def published_rows():
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("pdfplumber is required to parse the Jack in the Box PDF") from exc
    request = urllib.request.Request(NUTRITION_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        pdf_bytes = response.read()
    with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
        handle.write(pdf_bytes)
        handle.flush()
        with pdfplumber.open(handle.name) as pdf:
            page = pdf.pages[0]
            return _parse_column(page, "left") + _parse_column(page, "right")


def get_locations():
    # A grid sweep of the official city directory (37.70–37.84 N,
    # -122.52–-122.36 W) returned these same three canonical store pages at
    # every query point. The city field on each official page is San Francisco.
    return [
        {"address": "366 Bayshore Blvd, San Francisco, CA 94124", "lat": 37.74195, "lng": -122.40585, "neighborhood": None},
        {"address": "400 Geary St, San Francisco, CA 94102", "lat": 37.787232, "lng": -122.409985, "neighborhood": None},
        {"address": "4649 Geary Blvd, San Francisco, CA 94118", "lat": 37.78071, "lng": -122.469109, "neighborhood": None},
    ]


def main():
    rows = published_rows()
    items = []
    used_ids = set()
    for row in rows:
        display_name = row["name"]
        item_id = slug(display_name)
        if item_id in used_ids:
            display_name = f"{display_name} ({row['serving']:g} g)"
            item_id = slug(display_name)
        used_ids.add(item_id)
        items.append({
            "id": item_id,
            "name": display_name,
            "description": None,
            "category": _category(row["name"], row["section"]),
            "calories": row["calories"],
            "protein_g": row["protein_g"],
            "carbs_g": row["carbs_g"],
            "fat_g": row["fat_g"],
            "fiber_g": row["fiber_g"],
            "sodium_mg": row["sodium_mg"],
            "serving_note": f"per {row['serving']:g} g serving",
            "is_estimate": False,
            "source": {"type": "published", "url": NUTRITION_URL},
        })
    for section in sorted({row["section"] for row in rows}):
        print(f"Jack in the Box section {section}:")
        print("  " + ", ".join(row["name"] for row in rows if row["section"] == section))
    jumbo = next(row for row in rows if row["name"] == "Jumbo Jack")
    print(
        "Jumbo Jack spot-check: "
        f"{jumbo['calories']:g} kcal, {jumbo['fat_g']:g} g fat, "
        f"{jumbo['carbs_g']:g} g carbs, {jumbo['protein_g']:g} g protein "
        "(official 2026 guide)"
    )
    save_restaurant({
        "id": "jack-in-the-box",
        "name": "Jack in the Box",
        "website": "https://www.jackinthebox.com",
        "nutrition_source": {"type": "published", "url": NUTRITION_URL, "vendor": None, "retrieved": TODAY},
        "locations": get_locations(),
        "items": items,
    })


if __name__ == "__main__":
    main()
