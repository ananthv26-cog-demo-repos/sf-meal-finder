"""Extract Vitality Bowls' published nutrition PDF."""
from __future__ import annotations

import datetime
import re
import sys
import urllib.request
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant

URL = "https://vitalitybowls.com/wp-content/uploads/2025/05/Nutritional-Guide-VB_MAY-2025_new-granola.pdf"


def pdf_data():
    return urllib.request.urlopen(URL, timeout=120).read()


def parse(data):
    """Parse cells by their PDF x coordinates, never by extracted order."""
    items, seen = [], set()
    with pdfplumber.open(__import__("io").BytesIO(data)) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            words = page.extract_words()
            # These are the eight rotated header centers (the PDF uses the
            # same grid on every page, with a small page-specific x offset).
            if page.width != 612:
                raise RuntimeError("unexpected Vitality Bowls page width")
            # Resolve rotated labels from chars and assert the expected order.
            labels = {round(c["x0"]) for c in page.chars if not c["upright"] and c["top"] < 260}
            if not labels:
                raise RuntimeError("Vitality Bowls rotated nutrition header missing")
            numeric_words = [
                w for w in words
                if re.fullmatch(r"\d+(?:\.\d+)?", w["text"]) and w["top"] > 250 and w["top"] < 700
            ]
            xs = sorted((w["x0"] + w["x1"]) / 2 for w in numeric_words)
            clusters = []
            for x in xs:
                if not clusters or x - clusters[-1][-1] > 12:
                    clusters.append([x])
                else:
                    clusters[-1].append(x)
            headers = [sum(c) / len(c) for c in clusters]
            headers = [x for x in headers if 80 < x < 310 or x > 350]
            if len(headers) not in (8, 16):
                raise RuntimeError(f"unexpected Vitality Bowls numeric columns: {headers!r}")
            section = "component"
            current = None
            by_y = {}
            for w in words:
                top = w["top"]
                key = next((k for k in by_y if abs(k - top) <= 2.2), round(top))
                by_y.setdefault(key, []).append(w)
            for top in sorted(by_y):
                row = by_y[top]
                text = " ".join(w["text"] for w in row)
                if "Signature Acai Bowls" in text:
                    section = "meal"
                elif "Create Your Own" in text:
                    section = "component"
                name_words = [w for w in row if w["x0"] < 82 and not re.fullmatch(r"[()]|[SML]", w["text"])]
                if name_words and not any(re.fullmatch(r"\d+(?:\.\d+)?", w["text"]) for w in name_words):
                    candidate = " ".join(w["text"] for w in name_words)
                    if candidate not in {"NUTRITIONAL", "Food Allergy"} and len(candidate) > 2:
                        current = candidate.replace("BowlBowl", "Bowl")
                cells = [w for w in row if re.fullmatch(r"\d+(?:\.\d+)?", w["text"])]
                mapped = {}
                for w in cells:
                    offset = 8 if ((w["x0"] + w["x1"]) / 2) > 310 and len(headers) == 16 else 0
                    local_headers = headers[offset:offset + 8]
                    center = min(range(8), key=lambda i: abs(((w["x0"] + w["x1"]) / 2) - local_headers[i]))
                    if abs(((w["x0"] + w["x1"]) / 2) - local_headers[center]) < 12:
                        mapped[center] = float(w["text"])
                if current is None or 0 not in mapped or len(mapped) < 6:
                    continue
                size = next((w["text"] for w in row if w["text"] in {"S", "M", "L"}), None)
                name = current + (f" ({size})" if size else "")
                iid = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
                if iid in seen: continue
                seen.add(iid)
                low = name.lower()
                drink_names = ("pina colada", "acai elixir", "go green", "matcha madness",
                    "temptation", "tropical paradise", "power protein", "groovy guava",
                    "detoxifier", "rejuvenator", "intensifier", "invigorator",
                    "rehydrator", "me up", "sunsation", "lemonade", "juice")
                meal_prefixes = ("superseed avocado", "wholesome", "pb & chia jam",
                    "chimichurri", "supergreen", "mighty med", "power pesto", "green glow")
                if low.split(" (", 1)[0].strip() == "dragon" or any(x in low for x in drink_names):
                    cat = "drink"
                elif any(x in low for x in meal_prefixes) or "bowl" in low or any(x in low for x in ("wrap", "salad", "plate", "panini", "toast")):
                    cat = "meal"
                elif any(x in low for x in ("side", "kids")):
                    cat = "side"
                else:
                    cat = "component"
                if cat == "drink":
                    noun = "juice" if any(x in low for x in ("elixir", "go green", "rehydrator", "lemonade")) else "smoothie"
                    serving = f"per {size} {noun}" if size else f"per {noun} serving"
                else:
                    serving = f"per {size} bowl" if size else "per portion"
                items.append({"id": iid, "name": name, "description": None, "category": cat,
                    "calories": mapped[0], "protein_g": mapped.get(7, 0), "carbs_g": mapped.get(4, 0),
                    "fat_g": mapped.get(1, 0), "fiber_g": mapped.get(5), "sodium_mg": mapped.get(3),
                    "serving_note": serving, "is_estimate": False,
                    "source": {"type": "published", "url": URL}})
    # A missing size cell can leave a duplicate unsized row.  Prefer the
    # explicitly sized records, and reject impossible S/M/L calorie order.
    sized = {}
    for item in items:
        base = re.sub(r"\s+\([SML]\)$", "", item["name"])
        if re.search(r"\([SML]\)$", item["name"]):
            sized.setdefault(base, {})[item["name"][-2]] = item
    bad = set()
    for base, rows in sized.items():
        vals = [rows[s]["calories"] for s in "SML" if s in rows]
        if any(a > b for a, b in zip(vals, vals[1:])):
            for s in "SML":
                if s in rows and ((s == "L" and rows[s]["calories"] < max(v["calories"] for k,v in rows.items() if k != "L"))):
                    bad.add(rows[s]["id"])
    items = [i for i in items if i["id"] not in bad]
    sized_bases = set(sized)
    return [i for i in items if not ("(" not in i["name"] and
        re.sub(r"\s+\([SML]\)$", "", i["name"]) in sized_bases)]


def main():
    save_restaurant({"id": "vitality-bowls", "name": "Vitality Bowls", "website": "https://vitalitybowls.com",
        "nutrition_source": {"type": "published", "url": URL, "vendor": None, "retrieved": datetime.date.today().isoformat()},
        "locations": [{"address": "270 5th St, San Francisco, CA 94103", "lat": 37.7807381, "lng": -122.4041191, "neighborhood": "SoMa"}],
        "items": parse(pdf_data())})


if __name__ == "__main__":
    main()
