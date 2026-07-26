"""Scraper for Ben's Fast Food's published nutrition table and SF location."""

from __future__ import annotations

import datetime
import html
import io
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import pytesseract
from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402


PAGE_URL = "https://bensfastfood.com/nutrition"
LOCATION_URL = "https://bensfastfood.com/locations/san-francisco"
IMAGE_MARKER = "bens-fast-food-nutrition-facts"
TODAY = datetime.date.today().isoformat()
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
SECTIONS = {
    "BOWLS": ("meal", "per bowl (plain without sauce)"),
    "SIMPLE BOWLS": ("meal", "per bowl (plain without sauce)"),
    "SAUCES": ("condiment", "per sauce portion"),
    "ADD ONS": ("component", "per add-on portion"),
    "8 OZ SIDES": ("side", "per 8 oz"),
    "SWEET THINGS": ("side", "per portion"),
    "SMOOTHIES": ("drink", "per smoothie"),
}
HEADER_LABELS = [
    ("Calories", ("CALORIES",)),
    ("Total Fat", ("TOTAL", "FAT")),
    ("Sat Fat", ("SAT", "FAT")),
    ("Unsat Fat", ("UNSAT", "FAT")),
    ("Chol", ("CHOL",)),
    ("Sodium", ("SODIUM",)),
    ("Carbs", ("CARBS",)),
    ("Fiber", ("FIBER",)),
    ("Sugars", ("SUGARS",)),
    ("Protein", ("PROTEIN",)),
]


def get_bytes(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def image_url(page):
    text = get_bytes(page).decode("utf-8", "replace")
    urls = set(
        html.unescape(match)
        for match in re.findall(r'https?[^"\']+' + IMAGE_MARKER + r'[^"\']*', text)
    )
    urls = {url.split("?")[0] + "?format=2500w" for url in urls}
    if len(urls) != 1:
        raise ValueError(f"Expected exactly one nutrition image, found {sorted(urls)!r}")
    return next(iter(urls))


def _number(token):
    token = token.replace(",", "").replace("O", "0").replace("I", "1")
    token = re.sub(r"[^0-9.]", "", token)
    if not token:
        raise ValueError(f"Unparseable nutrition cell: {token!r}")
    return float(token)


def _header_centers(words):
    tokens = [
        (re.sub(r"[^A-Z0-9]", "", word.upper()), left, width)
        for left, word, width in words
    ]
    centers = []
    start = 0
    for _, expected in HEADER_LABELS:
        found = None
        for index in range(start, len(tokens)):
            if [token[0] for token in tokens[index:index + len(expected)]] == list(expected):
                first = tokens[index]
                last = tokens[index + len(expected) - 1]
                found = (first[1] + last[1] + last[2]) / 2
                start = index + len(expected)
                break
        if found is None:
            return None
        centers.append(found)
    return centers


def _rows(image, scale, reread_names=True):
    prepared = ImageOps.autocontrast(image.convert("L").resize(
        (int(image.width * scale), int(image.height * scale))
    ))
    data = pytesseract.image_to_data(
        prepared, config="--psm 6", output_type=pytesseract.Output.DICT
    )
    lines = []
    for i, text in enumerate(data["text"]):
        if not text.strip():
            continue
        top = data["top"][i] / scale
        for line_top, words in lines:
            if abs(line_top - top) <= 12:
                words.append((data["left"][i] / scale, text, data["width"][i] / scale))
                break
        else:
            lines.append((top, [(data["left"][i] / scale, text, data["width"][i] / scale)]))
    section = None
    column_centers = None
    rows = []
    for line_top, words in lines:
        words.sort()
        joined = " ".join(word for _, word, _ in words)
        upper = re.sub(r"[^A-Z0-9 ]", "", joined.upper()).strip()
        matched = next((name for name in SECTIONS if upper.startswith(name)), None)
        header = _header_centers(words)
        if header is not None:
            if column_centers is None:
                column_centers = header
            elif any(abs(left - right) > 20 for left, right in zip(column_centers, header)):
                raise ValueError("Inconsistent Ben's Fast Food header column centers")
            if matched:
                section = matched
            continue
        if matched:
            section = matched
            continue
        if column_centers is None:
            continue
        if section is None or any(
            key in upper for key in ("CALORIES", "TOTAL FAT", "SATFAT", "PROTEIN")
        ):
            continue
        cells = [[] for _ in column_centers]
        names = []
        for x, word, _ in words:
            if x < column_centers[0] - 30:
                names.append(word)
                continue
            index = min(range(len(column_centers)), key=lambda n: abs(x - column_centers[n]))
            cells[index].append(word)
        if not names or any(not cell for cell in cells):
            continue
        try:
            values = [_number("".join(cell)) for cell in cells]
        except ValueError:
            continue
        name = " ".join(names)
        if "!" in name and reread_names:
            name_crop = prepared.crop(
                (
                    0,
                    max(0, int((line_top - 4) * scale)),
                    int((column_centers[0] - 30) * scale),
                    int((line_top + 30) * scale),
                )
            )
            reread = pytesseract.image_to_string(name_crop, config="--psm 6").strip()
            if reread and "!" not in reread:
                name = reread
            else:
                raise ValueError(f"Unreliable OCR item name: {name!r}")
        rows.append((section, name, values))
    if column_centers is None:
        raise ValueError("Ben's Fast Food nutrition header row not found")
    return rows


def parse_table(image_bytes, source_url):
    image = Image.open(io.BytesIO(image_bytes))
    parsed = [_rows(image, 3), _rows(image, 2.5, reread_names=False)]
    first = [(section, name, values) for section, name, values in parsed[0]]
    second = parsed[1]
    if len(first) != len(second):
        raise ValueError("Two-resolution OCR returned different row counts")
    for (section, name, values), (other_section, _, other) in zip(first, second):
        if section != other_section or any(
            abs(left - right) > max(2, abs(left) * 0.05)
            for left, right in zip(values, other)
        ):
            raise ValueError(f"Two-resolution OCR disagreement for {section}/{name}")
    expected = {"BOWLS": 12, "SIMPLE BOWLS": 12, "SAUCES": 5, "ADD ONS": 6,
                "8 OZ SIDES": 5, "SWEET THINGS": 1, "SMOOTHIES": 1}
    counts = {section: sum(row[0] == section for row in first) for section in expected}
    if counts != expected:
        raise ValueError(f"Unexpected Ben's Fast Food section counts: {counts!r}")
    return [
        {
            "id": re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"),
            "name": name,
            "description": None,
            "category": SECTIONS[section][0],
            "calories": values[0],
            "fat_g": values[1],
            "carbs_g": values[6],
            "fiber_g": values[7],
            "protein_g": values[9],
            "sodium_mg": values[5],
            "serving_note": SECTIONS[section][1],
            "is_estimate": False,
            "source": {"type": "published", "url": source_url},
        }
        for section, name, values in first
    ]


def parse_location(page_html):
    match = re.search(
        r'"streetAddress"\s*:\s*"([^"]+)"[^}]*"addressLocality"\s*:\s*"([^"]+)"'
        r'[^}]*"addressRegion"\s*:\s*"([^"]+)"[^}]*"postalCode"\s*:\s*"([^"]+)"',
        page_html,
    )
    if not match or match.group(2) != "San Francisco":
        raise ValueError("Ben's Fast Food SF address missing or outside San Francisco")
    address = ", ".join(match.groups())
    query = urllib.parse.urlencode({"q": address, "format": "json", "limit": 1})
    request = urllib.request.Request(
        f"https://nominatim.openstreetmap.org/search?{query}",
        headers={"User-Agent": "sf-meal-finder/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        results = json.load(response)
    if not results:
        raise ValueError(f"Nominatim returned no result for {address}")
    return [{"address": address, "lat": float(results[0]["lat"]),
             "lng": float(results[0]["lon"]), "neighborhood": "SoMa"}]


def main():
    source_url = image_url(PAGE_URL)
    items = parse_table(get_bytes(source_url), source_url)
    for expected, values in {
        "Chicken Hearty Bowl": (610, 25, 63, 27, 9, 699),
        "Chickpea & Potato Hearty Bowl": (750, 30, 99, 20, 15, 769),
    }.items():
        item = next(row for row in items if row["name"] == expected)
        actual = (item["calories"], item["fat_g"], item["carbs_g"],
                  item["protein_g"], item["fiber_g"], item["sodium_mg"])
        print(f"{expected} spot check: {actual}")
        if actual != values:
            raise ValueError(f"Spot check failed for {expected}: {actual!r}")
    locations = parse_location(get_bytes(LOCATION_URL).decode("utf-8", "replace"))
    save_restaurant({
        "id": "bens-fast-food",
        "name": "Ben's Fast Food",
        "website": "https://bensfastfood.com",
        "nutrition_source": {"type": "published", "url": source_url,
                             "vendor": None, "retrieved": TODAY},
        "locations": locations,
        "items": items,
    })


if __name__ == "__main__":
    main()
