"""Amici's location-only document; official site has no nutrition source."""
import datetime
import json
import time
import urllib.parse
import urllib.request
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

def main():
    addresses = [
        "1200 Market St, San Francisco, CA 94102",
        "Pier 39, San Francisco, CA 94133",
    ]
    locations = []
    for address in addresses:
        q = urllib.parse.urlencode({"format": "json", "q": address, "limit": 1})
        req = urllib.request.Request(
            "https://nominatim.openstreetmap.org/search?" + q,
            headers={"User-Agent": "sf-meal-finder/1.0"},
        )
        result = json.load(urllib.request.urlopen(req, timeout=60))
        if result:
            locations.append({"address": address, "lat": float(result[0]["lat"]),
                              "lng": float(result[0]["lon"]), "neighborhood": None})
        time.sleep(1)
    save_restaurant({
        "id": "amicis", "name": "Amici's East Coast Pizzeria",
        "website": "https://www.amicis.com",
        "nutrition_source": {
            "type": "crowd",
            "url": "https://platform.fatsecret.com/rest/server.api",
            "vendor": "FatSecret Platform REST API; no Amici's results",
            "retrieved": datetime.date.today().isoformat(),
        },
        "locations": locations,
        "items": [],
    })

if __name__ == "__main__":
    main()
