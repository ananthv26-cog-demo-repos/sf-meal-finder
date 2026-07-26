"""Extreme Pizza published nutrition guide scraper."""
import datetime
import io
import json
import re
import sys
import urllib.request
import urllib.parse
import time
from pathlib import Path
import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

PDF_URL = "https://media-cdn.getbento.com/accounts/f26197ccf036932f404d45389d32707a/media/accounts/media/RzZFagkTTZGaLLEgFjaK_Extreme%20Pizza%20-%20Nutritional%20Information-1%20%281%29.pdf"
LOCATIONS_URL = "https://www.extremepizza.com/store-locator/"

def main():
    raw = urllib.request.urlopen(PDF_URL, timeout=60).read()
    rows = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        current = ""
        for page in pdf.pages:
            for line in (page.extract_text() or "").splitlines():
                m = re.match(r"^(?:(.+?)\s+)?(Indee-8\"|M-12\"|L-14\"|XL-16\"|Huge-18\")\s+(\d+)\s+([\d.]+)\s+([\d.]+)g\s+([\d.]+)g\s+([\d.]+)mg$", line)
                if not m:
                    if line.strip() and not any(x in line for x in ("Servings", "Calories", "Disclaimer", "HEALTHY", "Signature")):
                        current = line.strip()
                    continue
                name, size, slices, calories, sat, carbs, sodium = m.groups()
                if not name or name in ("Indee-8\"", "M-12\""):
                    name = current
                try:
                    rows.append((name, size, int(slices), float(calories), float(carbs), float(sodium)))
                except ValueError:
                    continue
    # Per-slice rows are components; derive whole pizzas using the published
    # slices-per-pizza count.
    items = []
    for n, (name, size, slices, kcal, carbs, sodium) in enumerate(rows):
        base = {
            "id": f"slice-{n+1}", "name": f"{name} ({size}, per slice)",
            "description": None, "category": "component", "is_estimate": False,
            "source": {"type": "published", "url": PDF_URL},
            "calories": kcal, "protein_g": 0, "carbs_g": carbs, "fat_g": 0,
            "fiber_g": None, "sodium_mg": sodium,
            "serving_note": f"per slice of {size} pizza",
        }
        items.append(base)
        whole = dict(base)
        whole.update({
            "id": f"derived-{n+1}", "name": f"{name} ({size}, whole pizza)",
            "category": "meal", "is_estimate": True,
            "description": f"Derived from {slices} published slices at {size}.",
            "source": {"type": "derived", "url": PDF_URL},
            "serving_note": f"per whole {size} pizza ({slices} x published per-slice values)",
        })
        for k in ("calories", "carbs_g", "sodium_mg"):
            whole[k] = round(whole[k] * slices, 1)
        items.append(whole)
    # Store locator JSON-LD exposes city/address but not coordinates. These
    # are official city-proper pages; coordinates are official-address
    # geocodes obtained from Nominatim at scrape time.
    addresses = [
        "1980 Union Street, San Francisco, CA 94123",
        "1062 Folsom Street, Suite 100, San Francisco, CA 94103",
        "3911 Alemany Blvd, Ste 1001, San Francisco, CA 94132",
    ]
    locations = []
    for address in addresses:
        query = urllib.parse.urlencode({"format": "json", "q": address, "limit": 1})
        req = urllib.request.Request(
            "https://nominatim.openstreetmap.org/search?" + query,
            headers={"User-Agent": "sf-meal-finder/1.0"},
        )
        result = []
        for attempt in range(4):
            try:
                result = json.load(urllib.request.urlopen(req, timeout=60))
            except Exception:
                result = []
            if result:
                break
            if attempt < 3:
                time.sleep(2 ** attempt)
        if not result:
            short = address.split(",")[0] + ", San Francisco, CA"
            q2 = urllib.parse.urlencode({"format": "json", "q": short, "limit": 1})
            result = json.load(urllib.request.urlopen(
                urllib.request.Request(
                    "https://nominatim.openstreetmap.org/search?" + q2,
                    headers={"User-Agent": "sf-meal-finder/1.0"},
                ), timeout=60
            ))
        if result:
            locations.append({"address": address, "lat": float(result[0]["lat"]),
                              "lng": float(result[0]["lon"]), "neighborhood": None})
        time.sleep(1)
    spot = next(x for x in items if "Screamin" in x["name"] and "M-12" in x["name"])
    print("Extreme Pizza Screamin's Tomato spot-check:", spot["calories"], "kcal per slice")
    save_restaurant({
        "id": "extreme-pizza", "name": "Extreme Pizza",
        "website": "https://www.extremepizza.com",
        "nutrition_source": {"type": "published", "url": PDF_URL, "vendor": None,
                             "retrieved": datetime.date.today().isoformat()},
        "locations": locations, "items": items,
    })

if __name__ == "__main__":
    main()
