"""Scraper for Peasant Pies' published nutrition and SF locations."""

from __future__ import annotations

import datetime
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

import pdfplumber
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402


PDF_URL = (
    "https://www.peasantpies.com/uploads/b/9bff6be0-3cd3-11ea-a066-9bdb7dbbcf14/"
    "peasant-pies-nutritional-info.pdf"
)
LOCATION_URL = (
    "https://cdn5.editmysite.com/app/store/api/v28/editor/users/130500550/"
    "sites/540629437769243381/store-locations?page=1&per_page=100&include=address"
    "&lang=en&valid=1"
)
SITE = "https://www.peasantpies.com"
TODAY = datetime.date.today().isoformat()
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

EXPECTED_NAMES = [
    [
        "Beef & Potato Pie",
        "Chicken & Potato Pie",
        "Ham, Eggs & Cheese Pie",
        "Eggs, Sausage & Potato Pie",
    ],
    ["Eggs, Veggies & Cheese Pie", "Spinach & Feta Cheese Pie", "Zucchini & Mushroom Pie"],
    ["Garbanzo Bean Curry Pie", "Lentil & Yam Pie", "Black Bean & Tofu Pie"],
]
RAPID_OCR = RapidOCR()


def get_bytes(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def pdf_names(page):
    text = page.extract_text() or ""
    expected = EXPECTED_NAMES[page.page_number - 1]
    found = []
    for name in expected:
        if name in text:
            found.append(name)
    if found != expected:
        raise ValueError(
            f"Unexpected Peasant Pies names on page {page.page_number}: {found!r}"
        )
    return found


def ocr_images(page, image):
    native = Image.frombytes("L", image["srcsize"], image["stream"].get_data())
    texts = []
    for scale in (6, 8):
        rendered = native.resize(
            (native.width * scale, native.height * scale), Image.Resampling.LANCZOS
        ).convert("RGB")
        result, _ = RAPID_OCR(rendered)
        if not result:
            raise ValueError("RapidOCR returned no text")
        texts.append("\n".join(item[1] for item in result))
    return texts

def _number(token, label):
    token = token.strip().replace(",", "").rstrip(".,;:")
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(?:g|mg)?", token, re.IGNORECASE)
    if not match:
        raise ValueError(f"{label}: OCR value {token!r} is not numeric")
    return float(match.group(1))


def _pass_value(text, pattern, label):
    values = []
    text = re.split(r"Vitamin\s+[A-Z]|Calories\s+per\s+gram", text, maxsplit=1, flags=re.I)[0]
    for line in text.splitlines():
        if re.search(
            r"vitamin|less\s*than|per\s+gram|calories\s+per|carbo.*protein",
            line,
            re.I,
        ):
            continue
        match = re.search(pattern, line, flags=re.IGNORECASE)
        if match:
            values.append(_number(match.group(1), label))
    if len(values) != 1:
        raise ValueError(f"Expected one {label} reading, found {values!r}")
    return values[0]


def _agreed(texts, pattern, label):
    values = [_pass_value(text, pattern, label) for text in texts]
    if len(values) != 2 or values[0] != values[1]:
        raise ValueError(f"OCR disagreement for {label}: {values!r}")
    return values[0]


def parse_panel(texts):
    serving_matches = []
    for text in texts:
        serving_matches.extend(
            re.findall(
                r"Serving\s+Size\s*\(\s*(\d+)\s*(?:g|9|a)?",
                text,
                re.IGNORECASE,
            )
        )
    if not serving_matches:
        raise ValueError("Missing or unparsable OCR label: Serving Size")
    serving_values = [float(x) for x in serving_matches]
    if len(serving_values) != 2 or serving_values[0] != serving_values[1]:
        raise ValueError(f"OCR disagreement for Serving Size: {serving_values!r}")
    serving_grams = serving_values[0]

    calories = _agreed(texts, r"\bCalories\s+([0-9]+)", "Calories")
    calories_from_fat = _agreed(
        texts, r"\bCalories\s+from\s+Fat\s+([0-9]+)", "Calories from Fat"
    )
    fat_value = _agreed(
        texts, r"\bTotal\s+Fat\s*([0-9]+(?:\.[0-9]+)?g?)", "Total Fat"
    )
    if abs(calories_from_fat - 9 * fat_value) > 15:
        raise ValueError(
            f"Calories-from-fat cross-check failed: calories={calories!r}, "
            f"calories_from_fat={calories_from_fat!r}, fat={fat_value!r}"
        )
    carb_value = _agreed(
        texts,
        r"\bTotal\s+Carboh\w*\s*(?:rate\s*)?([0-9]+(?:\.[0-9]+)?g?)",
        "Total Carbohydrate",
    )
    protein_value = _agreed(
        texts, r"\bProtein\s+([0-9]+(?:\.[0-9]+)?g?)", "Protein"
    )
    sodium_value = _agreed(
        texts, r"\bSodium\s+([0-9]+)", "Sodium"
    )
    fiber_value = _agreed(
        texts,
        r"\bDietary\s*Fiber\s*([0-9]+(?:\.[0-9]+)?g?)",
        "Dietary Fiber",
    )
    values = {
        "calories": calories,
        "fat_g": fat_value,
        "sodium_mg": sodium_value,
        "carbs_g": carb_value,
        "fiber_g": fiber_value,
        "protein_g": protein_value,
    }
    return values, int(serving_grams)


def parse_nutrition(pdf_bytes):
    items = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        if len(pdf.pages) != len(EXPECTED_NAMES):
            raise ValueError(f"Expected 3 nutrition pages, found {len(pdf.pages)}")
        for page in pdf.pages:
            names = pdf_names(page)
            images = sorted(page.images, key=lambda image: image["x0"])
            if len(images) != len(names):
                raise ValueError(
                    f"Expected {len(names)} nutrition panels on page "
                    f"{page.page_number}, found {len(images)}"
                )
            for name, image in zip(names, images):
                values, serving_grams = parse_panel(ocr_images(page, image))
                items.append(
                    {
                        "id": slug(name),
                        "name": name,
                        "description": None,
                        "category": "meal",
                        "calories": values["calories"],
                        "protein_g": values["protein_g"],
                        "carbs_g": values["carbs_g"],
                        "fat_g": values["fat_g"],
                        "fiber_g": values["fiber_g"],
                        "sodium_mg": values["sodium_mg"],
                        "serving_note": f"per pie ({serving_grams:g}g)",
                        "is_estimate": False,
                        "source": {"type": "published", "url": PDF_URL},
                    }
                )
    if len(items) != 10 or [item["name"] for item in items] != sum(
        EXPECTED_NAMES, []
    ):
        raise ValueError("Peasant Pies nutrition item count/name assertion failed")
    return items


def parse_locations(payload):
    locations = []
    for row in payload.get("data", []):
        address = row.get("address", {}).get("data", {})
        if address.get("city") != "San Francisco":
            continue
        postal = address["postal_code"]
        locations.append(
            {
                "address": (
                    f"{address['street']}, {address['city']}, "
                    f"{address['region_code']} {postal}"
                ),
                "lat": float(address["latitude"]),
                "lng": float(address["longitude"]),
                "neighborhood": row.get("nickname"),
            }
        )
    expected = {
        "1039 Irving St, San Francisco, CA 94122-2215",
        "550 Gene Friend Way, San Francisco, CA 94158",
    }
    if {location["address"] for location in locations} != expected:
        raise ValueError(f"Unexpected Peasant Pies SF locations: {locations!r}")
    return locations


def main():
    items = parse_nutrition(get_bytes(PDF_URL))
    spot = next(item for item in items if item["name"] == "Beef & Potato Pie")
    print(
        "Beef & Potato Pie spot check: "
        f"{spot['calories']:g} kcal / {spot['fat_g']:g} g fat / "
        f"{spot['carbs_g']:g} g carbs / {spot['protein_g']:g} g protein / "
        f"{spot['fiber_g']:g} g fiber / {spot['sodium_mg']:g} mg sodium"
    )
    locations = parse_locations(json.loads(get_bytes(LOCATION_URL)))
    save_restaurant(
        {
            "id": "peasant-pies",
            "name": "Peasant Pies",
            "website": SITE,
            "nutrition_source": {
                "type": "published",
                "url": PDF_URL,
                "vendor": None,
                "retrieved": TODAY,
            },
            "locations": locations,
            "items": items,
        }
    )


if __name__ == "__main__":
    main()
