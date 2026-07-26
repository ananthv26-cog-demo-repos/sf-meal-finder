"""Round Table Pizza nutrition PDF scraper."""

import datetime
import re
import sys
import urllib.request
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

PDF_URL = (
    "https://www.roundtablepizza.com/wp-content/uploads/2024/08/"
    "Round-Table-Pizza-Nutritional-Information-Guide-August.pdf"
)
LOCATIONS_URL = "https://ordering.roundtablepizza.com/site/rtp/locations"
TODAY = datetime.date.today().isoformat()
HEADERS = {"User-Agent": "Mozilla/5.0"}

PIZZA_NAMES = {
    "BBQ Chicken", "Cheese", "Chicken & Garlic Gourmet™", "Gourmet Veggie™",
    "Guinevere’s Garden Delight®", "Hawaiian™", "Italian Garlic Supreme®",
    "King Arthur’s Supreme®", "Maui Zaui™", "Montague’s All Meat Marvel®",
    "Pepperoni",
}
CRUSTS = ("ORIGINAL", "THIN", "PAN", "STUFFED", "CAULIFLOWER")


def get_pdf_rows():
    raw = urllib.request.urlopen(
        urllib.request.Request(PDF_URL, headers=HEADERS), timeout=60
    ).read()
    rows = []
    with pdfplumber.open(__import__("io").BytesIO(raw)) as pdf:
        section = "component"
        crust = "original"
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                upper = line.upper()
                if upper in CRUSTS or any(upper.startswith(x + " CRUST") for x in CRUSTS):
                    crust = upper.split()[0].lower()
                if upper.startswith(("SAUCE", "DIPPING")) or "DRESSING" in upper:
                    section = "condiment"
                elif any(x in upper for x in ("DESSERT", "BREAD", "APPS", "CHIPS", "WINGS")):
                    section = "side"
                elif any(x in upper for x in ("DRINK", "BEVERAGE")):
                    section = "drink"
                elif any(x in upper for x in ("SALAD", "SANDWICH", "BURGER", "PASTA")):
                    section = "meal"
                if line.startswith(("Total", "Servings", "NUTRITION")) or upper in CRUSTS:
                    continue
                # A row is recognized by a serving-count/size token followed by
                # the 11 labeled nutrition columns. Keep missing slash cells as
                # missing rather than shifting the remaining columns left.
                m = re.match(r"^(.+?)\s+(\d+(?:/\d+)+(?:\s+Slices)?)\s+(.+)$", line)
                if m:
                    name, serving, tail = m.groups()
                    groups = tail.split()
                    if len(groups) < 11:
                        continue
                    def vals(g):
                        a = g.split("/")
                        if a[0] == "":
                            a[0] = "-"
                        if len(a) > 5:
                            a = a[:5]
                        return a
                    parsed = [vals(g) for g in groups[:11]]
                    if not all(len(x) == len(parsed[0]) for x in parsed):
                        continue
                    if name in PIZZA_NAMES:
                        sizes = ("personal", "small", "medium", "large", "x-large")[-len(parsed[0]):]
                        for idx, size in enumerate(sizes):
                            required = (0, 2, 6, 7, 10)
                            if any(
                                parsed[field][idx] in ("-", "<1", "")
                                or not re.match(r"^\d+(?:\.\d+)?$", parsed[field][idx])
                                for field in required
                            ):
                                continue
                            if float(parsed[0][idx]) < 90:
                                continue
                            rows.append({
                                "name": f"{name} ({size}, {crust} crust)",
                                "category": "component",
                                "calories": float(parsed[0][idx]),
                                "fat_g": float(parsed[2][idx]),
                                "sodium_mg": float(parsed[6][idx]),
                                "carbs_g": float(parsed[7][idx]),
                                "fiber_g": (
                                    float(parsed[8][idx])
                                    if re.match(r"^\d+(?:\.\d+)?$", parsed[8][idx])
                                    else None
                                ),
                                "protein_g": float(parsed[10][idx]),
                                "serving_note": f"per slice of {size} {crust}-crust pizza",
                                "slices": int(serving.split("/")[idx]),
                            })
                    continue
                # Fixed-size additional-menu rows have one serving token and
                # eleven scalar nutrition values.
                m = re.match(r"^(.+?)\s+(\d+(?:\.\d+)?\s*(?:oz|Slice|Slices|count|Cup|Egg|tbsp\.?)?)\s+(.+)$", line)
                if not m:
                    continue
                name, serving, tail = m.groups()
                nums = tail.split()
                if len(nums) < 11:
                    continue
                try:
                    n = [0.0 if x in ("<1", "<5") else float(x) for x in nums[:11]]
                except ValueError:
                    continue
                rows.append({
                    "name": name, "category": section, "calories": n[0],
                    "fat_g": n[2], "sodium_mg": n[6], "carbs_g": n[7],
                    "fiber_g": n[8], "protein_g": n[10],
                    "serving_note": f"per {serving.strip()} serving",
                })
    return rows


def get_locations():
    html = urllib.request.urlopen(
        urllib.request.Request(LOCATIONS_URL, headers=HEADERS), timeout=60
    ).read().decode("utf-8", "ignore")
    rows = []
    for attrs in re.findall(r'<div class="coordinatos"([^>]+)>', html):
        def attr(name):
            m = re.search(rf'data-{name}="([^"]*)"', attrs)
            return m.group(1) if m else ""
        address2 = attr("address2").replace("  ", " ").strip()
        if not re.match(r"^San Francisco\s+CA\b", address2, re.I):
            continue
        rows.append({
            "address": f"{attr('address1').strip()}, {address2}",
            "lat": float(attr("latitude")),
            "lng": float(attr("longitude")),
            "neighborhood": None,
        })
    return rows


def main():
    items = []
    for i, row in enumerate(get_pdf_rows()):
        items.append({
            "id": f"pizza-{i+1}",
            "name": row["name"],
            "description": None,
            "category": row["category"],
            "is_estimate": False,
            "source": {"type": "published", "url": PDF_URL},
            **{k: row[k] for k in (
                "calories", "protein_g", "carbs_g", "fat_g", "fiber_g",
                "sodium_mg", "serving_note",
            )},
        })
    # Whole pizza meals are derived only when the PDF publishes slice counts.
    derived = []
    for item in items:
        if item["category"] != "component" or "per slice" not in item["serving_note"]:
            continue
        slices = next((r.get("slices") for r in get_pdf_rows() if r["name"] == item["name"]), None)
        if not slices:
            continue
        total = dict(item)
        for key in ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sodium_mg"):
            if total[key] is not None:
                total[key] = round(total[key] * slices, 1)
        total.update({
            "id": "derived-" + item["id"], "name": item["name"].replace("per slice", "whole pizza"),
            "category": "meal", "is_estimate": True,
            "description": f"Derived whole pizza from {slices} published slices; base values are per-slice published nutrition.",
            "serving_note": f"per whole pizza ({slices} x per-slice nutrition)",
            "source": {"type": "derived", "url": PDF_URL},
        })
        derived.append(total)
    items.extend(derived)
    king = next(x for x in items if "King Arthur" in x["name"] and "large" in x["name"] and "per slice" in x["serving_note"])
    assert all(
        x["calories"] >= 90
        for x in items
        if x["category"] == "component" and "per slice" in x["serving_note"]
    )
    print("King Arthur's Supreme large original slice spot-check:", king["calories"], "kcal")
    save_restaurant({
        "id": "round-table-pizza",
        "name": "Round Table Pizza",
        "website": "https://www.roundtablepizza.com",
        "nutrition_source": {
            "type": "published", "url": PDF_URL, "vendor": None, "retrieved": TODAY,
        },
        "locations": get_locations(),
        "items": items,
    })


if __name__ == "__main__":
    main()
