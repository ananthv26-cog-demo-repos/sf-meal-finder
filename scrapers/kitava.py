"""Kitava nutrition scraper.

Kitava publishes complete per-serving nutrition in its nutrition PDF, so this
scraper saves the published meals and components directly without deriving
builds. The PDF has a short Wild Rice Blend row and an OCR-ish ``o`` in the
Picadillo Beef row; rows are parsed by pdfplumber word coordinates rather than
positional splitting so missing cells remain missing.
"""

import datetime
import json
import re
import statistics
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

PDF_URL = (
    "https://drive.usercontent.google.com/download?id="
    "1qvcWmJjT0oXq9dyjquepuwKjdnEVSR9w&export=download&confirm=t"
)
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
TODAY = datetime.date.today().isoformat()

HEADER_COLUMNS = [
    ("Serving", "(g)"),
    ("Calories",),
    ("Protein", "(g)"),
    ("Total", "Fat", "(g)"),
    ("Sat", "Fat", "(g)"),
    ("Trans", "Fat", "(g)"),
    ("Cholesterol", "(mg)"),
    ("Sodium", "(mg)"),
    ("Total", "Carbs", "(g)"),
    ("Dietary", "Fiber", "(g)"),
    ("Sugars", "(g)"),
    ("Net", "Carbs", "(g)"),
]
SECTION_CATEGORIES = {
    "Signature Bowls": "meal",
    "Protein Plate": "meal",
    "Small Plates": "side",
    "Dessert": "side",
    "PROTEINS": "component",
    "BASES": "component",
    "VEGGIES": "component",
    "Sauces": "condiment",
    "Smoothie": "drink",
}
SMALL_PLATES = {
    "Chicken Nuggets",
    "Crispy Brussels Sprouts",
    "Fried Plantains",
    "Za'atar Cauliflower & Hummus",
    "Cauliflower Bites with Herb Ranch",
}
NUMERIC_RE = re.compile(r"^-?(?:\d+(?:\.\d*)?|\.\d+)$")


def download_pdf():
    """Download the published PDF to a temporary file and return its path."""
    request = urllib.request.Request(
        PDF_URL, headers={"User-Agent": "Mozilla/5.0"}
    )
    response = urllib.request.urlopen(request, timeout=60)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as output:
        output.write(response.read())
        return output.name


def data_column_centers(pages):
    """Cluster numeric data-word centers into the twelve PDF columns."""
    x_centers = []
    for page in pages:
        for word in page.extract_words(keep_blank_chars=False):
            if word["top"] > 88 and word["x0"] >= 180:
                if NUMERIC_RE.match(word["text"]):
                    x_centers.append((word["x0"] + word["x1"]) / 2)
    clusters = []
    for x_center in sorted(x_centers):
        if not clusters or x_center - clusters[-1][-1] > 15:
            clusters.append([x_center])
        else:
            clusters[-1].append(x_center)
    if len(clusters) != len(HEADER_COLUMNS):
        raise ValueError(
            f"expected {len(HEADER_COLUMNS)} numeric columns, "
            f"found {len(clusters)}"
        )
    return [statistics.mean(cluster) for cluster in clusters]


def parse_number_rows(page, centers):
    """Yield (label, values, missing_columns) from numeric PDF rows."""
    words = page.extract_words(keep_blank_chars=False)
    by_top = {}
    for word in words:
        by_top.setdefault(round(word["top"], 1), []).append(word)

    for row_words in by_top.values():
        row_words.sort(key=lambda word: word["x0"])
        numeric = []
        label_words = []
        for word in row_words:
            if word["x0"] < 180:
                label_words.append(word["text"])
            elif NUMERIC_RE.match(word["text"]):
                numeric.append(word)
        row_name = " ".join(label_words)
        if row_name in SECTION_CATEGORIES or row_name == "A la Carte Sides":
            yield row_name, {}, []
            continue
        if not label_words or not numeric:
            continue
        values = {}
        for word in numeric:
            x_center = (word["x0"] + word["x1"]) / 2
            column, center = min(
                enumerate(centers), key=lambda pair: abs(pair[1] - x_center)
            )
            distance = abs(center - x_center)
            if distance > 15:
                raise ValueError(
                    f"{row_name}: numeric value {word['text']!r} is "
                    f"{distance:.1f} px from column {column}"
                )
            if column in values:
                raise ValueError(
                    f"{row_name}: numeric values collide in column {column}"
                )
            values[column] = float(word["text"])
        if 0 not in values or 1 not in values:
            continue
        missing = [
            index for index in range(len(centers)) if index not in values
        ]
        yield " ".join(label_words), values, missing


def slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug


def geocode():
    query = urllib.parse.urlencode(
        {"format": "json", "q": "2011 Mission St, San Francisco, CA 94110"}
    )
    request = urllib.request.Request(
        f"{NOMINATIM_URL}?{query}",
        headers={"User-Agent": "sf-meal-finder-kitava-scraper/1.0"},
    )
    results = json.load(urllib.request.urlopen(request, timeout=30))
    if not results:
        raise RuntimeError("Nominatim returned no result for Kitava's address")
    lat, lng = float(results[0]["lat"]), float(results[0]["lon"])
    if not (37.60 <= lat <= 37.86 and -122.55 <= lng <= -122.33):
        raise ValueError(
            f"geocoded coordinates outside San Francisco bounds: {lat}, {lng}"
        )
    return lat, lng


def main():
    pdf_path = download_pdf()
    items = []
    current_category = None
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages = [pdf.pages[page_number] for page_number in (12, 13)]
            centers = data_column_centers(pages)
            for page in pages:
                rows = parse_number_rows(page, centers)
                for row_name, values, missing in rows:
                    if row_name in SECTION_CATEGORIES:
                        current_category = SECTION_CATEGORIES[row_name]
                        continue
                    if row_name in {"A la Carte Sides"}:
                        continue
                    if current_category is None:
                        continue
                    category = current_category
                    if row_name in SMALL_PLATES:
                        category = "side"
                    if category == "component":
                        serving_note = (
                            f"per a-la-carte side portion, "
                            f"{values.get(0, 0.0):g} g"
                        )
                    else:
                        serving_note = (
                            f"per {values.get(0, 0.0):g} g serving (as served)"
                        )
                    missing_names = {
                        0: "Serving",
                        1: "Calories",
                        2: "Protein",
                        3: "Total Fat",
                        7: "Sodium",
                        8: "Total Carbs",
                        9: "Dietary Fiber",
                    }
                    missing_text = [
                        label
                        for index, label in missing_names.items()
                        if index in missing
                    ]
                    description = (
                        "Published nutrition; missing PDF columns: "
                        f"{', '.join(missing_text)}."
                        if missing_text
                        else None
                    )
                    items.append(
                        {
                            "id": slugify(row_name),
                            "name": row_name,
                            "description": description,
                            "category": category,
                            "calories": values.get(1, 0.0),
                            "protein_g": values.get(2, 0.0),
                            "fat_g": values.get(3, 0.0),
                            "carbs_g": values.get(8, 0.0),
                            "fiber_g": values.get(9),
                            "sodium_mg": values.get(7),
                            "serving_note": serving_note,
                            "is_estimate": False,
                            "source": {"type": "published", "url": PDF_URL},
                        }
                    )
    finally:
        Path(pdf_path).unlink(missing_ok=True)

    lat, lng = geocode()
    save_restaurant(
        {
            "id": "kitava",
            "name": "Kitava",
            "website": "https://www.kitava.com",
            "nutrition_source": {
                "type": "published",
                "url": PDF_URL,
                "vendor": None,
                "retrieved": TODAY,
            },
            "locations": [
                {
                    "address": "2011 Mission St, San Francisco, CA 94110",
                    "lat": lat,
                    "lng": lng,
                    "neighborhood": "Mission",
                }
            ],
            "items": items,
        }
    )


if __name__ == "__main__":
    main()
