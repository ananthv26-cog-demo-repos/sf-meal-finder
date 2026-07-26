"""Fetch and parse Popeyes' official nutrition PDF and restaurant locator."""

import datetime
import io
import json
import re
import socket
import sys
import os
import base64
import struct
import urllib.request
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

NUTRITION_URL = "https://plk-use1-prod.sites.rbictg.com/nutrition/PLK_Nutrition.pdf"
GRAPHQL_URL = "https://www.popeyes.com/graphql"
TODAY = datetime.date.today().isoformat()

SIDE_WORDS = (r"\bbiscuit\b", r"\bfries\b", r"\bmac\b", r"\bpotatoes\b", r"\bbeans\b", r"\brice\b", r"\bcoleslaw\b", r"\bjalapeño\b", r"\bpie\b", r"\bhash rounds\b")
CONDIMENT_WORDS = (r"\bsauce\b", r"\branch\b", r"\bmustard\b")
DRINK_WORDS = (r"\bcoke\b", r"\bsprite\b", r"\bfanta\b", r"\bdew\b", r"\bpepsi\b", r"\bdr pepper\b", r"\btea\b", r"\blemonade\b", r"\bcoffee\b", r"\bjuice\b")
MEAL_WORDS = (r"\bsandwich\b", r"\bwrap\b", r"\btenders?\b", r"\bwings?\b", r"\bshrimp\b", r"\bbiscuit\b")

LOCATOR_QUERY = """query GetRestaurants($input: RestaurantsInput) {
  restaurants(input: $input) {
    nodes {
      storeId latitude longitude
      physicalAddress { address1 address2 city stateProvinceShort postalCode }
    }
  }
}"""


def fetch(url, data=None, headers=None):
    request = urllib.request.Request(
        url, data=data, headers={"User-Agent": "Mozilla/5.0", **(headers or {})}
    )
    return urllib.request.urlopen(request, timeout=60).read()


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80]


def category(section, name):
    section = section.upper()
    text = name.lower()
    if re.match(r"^(tender|leg)\s+-", text):
        return "component"
    if section.startswith("BREAKFAST"):
        if any(re.search(word, text) for word in DRINK_WORDS):
            return "drink"
        return "side" if re.search(r"\bhash rounds\b", text) else "meal"
    if section.startswith(("SANDWICHES", "WRAPS", "TENDERS", "WINGS", "SEAFOOD")):
        if "tender -" in text or "leg -" in text:
            return "component"
        return "meal"
    if section.startswith(("SIGNATURE CHICKEN", "CHICKEN")):
        return "component"
    if section.startswith("BEVERAGES"):
        return "drink"
    if section.startswith(("SAUCES", "CONDIMENTS", "SIGNATURE DIPPING")):
        return "condiment"
    if section.startswith(("SIGNATURE SIDES", "DESSERTS")):
        return "side"
    if any(re.search(word, text) for word in MEAL_WORDS):
        return "meal"
    if any(re.search(word, text) for word in CONDIMENT_WORDS):
        return "condiment"
    if any(re.search(word, text) for word in DRINK_WORDS):
        return "drink"
    if any(re.search(word, text) for word in SIDE_WORDS):
        return "side"
    return "component"


def item_name(name):
    value = name.lower().title()
    for old, new in (("Bbq", "BBQ"), ("Boldbq", "BoldBQ"), ("Coke", "Coke"),
                     ("Cajun", "Cajun"), ("Mardi Gras", "Mardi Gras"),
                     ("Mac & Cheese", "Mac & Cheese")):
        value = value.replace(old, new)
    return value.replace("Tenderblackened", "Tender Blackened").replace("™", "").replace("®", "").strip()


def serving_note(serving, name):
    if serving.lower() == "reg":
        return "per regular serving"
    if serving.lower() == "lg":
        return "per large serving"
    if serving.isdigit():
        return "per piece" if serving == "1" else f"per {serving} serving"
    if "piece" in serving.lower():
        return f"per {serving.lower()}"
    return f"per {serving.lower()} serving"


def parse_pdf(blob):
    rows, section = [], "UNKNOWN"
    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        for page in pdf.pages:
            for line in (page.extract_text() or "").splitlines():
                line = re.sub(r"\s+", " ", line).strip()
                if not line or "Nutrition Facts" in line or line.isdigit():
                    continue
                match = re.match(
                    r"^(.*?)\s+(1|Reg|Lg|\d+ Pieces)\s+"
                    r"((?:\d+(?:\.\d+)?\s+){10}\d+(?:\.\d+)?)$", line
                )
                if not match:
                    if len(re.findall(r"\d+(?:\.\d+)?", line)) >= 6:
                        print(f"PDF data-like line did not match: {line}")
                    if line.upper() == line and not re.search(r"\d", line):
                        section = line
                    continue
                name, serving, numbers = match.groups()
                values = [float(value) for value in numbers.split()]
                rows.append({
                    "section": section, "name": name.strip(), "serving": serving,
                    "calories": values[0], "fat_g": values[2], "sodium_mg": values[6],
                    "carbs_g": values[7], "fiber_g": values[8], "protein_g": values[10],
                })
    return rows


def locations():
    body = json.dumps({
        "operationName": "GetRestaurants",
        "variables": {"input": {
            "filter": "NEARBY",
            "coordinates": {"userLat": 37.775, "userLng": -122.418, "searchRadius": 50000},
            "first": 100, "status": "OPEN",
        }},
        "query": LOCATOR_QUERY,
    }).encode()
    try:
        payload = json.loads(fetch(GRAPHQL_URL, body, {"Content-Type": "application/json"}))
    except Exception:
        browser_result = cdp_fetch(body.decode())
        payload = json.loads(browser_result) if isinstance(browser_result, str) else browser_result
    response = payload[0] if isinstance(payload, list) else payload
    nodes = response.get("data", {}).get("restaurants", {}).get("nodes", [])
    out = []
    for store in nodes:
        address = store.get("physicalAddress") or store.get("address") or store
        if (address.get("city") or "").strip() != "San Francisco":
            continue
        if store.get("latitude") is None or store.get("longitude") is None:
            continue
        line = address.get("address1", "").strip()
        if address.get("address2"):
            line += " " + address["address2"].strip()
        out.append({
            "address": f"{line}, San Francisco, CA {address.get('postalCode', '')}".strip(),
            "lat": float(store["latitude"]), "lng": float(store["longitude"]),
            "neighborhood": None,
        })
    return sorted({item["address"]: item for item in out}.values(), key=lambda item: item["address"])


def cdp_fetch(payload):
    """Use the already-running Chrome session when Popeyes WAF blocks curl."""
    pages = json.loads(urllib.request.urlopen("http://localhost:29229/json/list").read())
    target = next(
        (page for page in pages if page.get("type") == "page"
         and page.get("url", "").startswith("https://www.popeyes.com/")),
        None,
    )
    if target is None:
        target = json.loads(urllib.request.urlopen(
            urllib.request.Request(
                "http://localhost:29229/json/new?https://www.popeyes.com/",
                method="PUT",
            )
        ).read())
    url = target["webSocketDebuggerUrl"].replace("ws://", "")
    host, path = url.split("/", 1)
    sock = socket.create_connection(tuple(host.split(":")), timeout=30)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall((
        f"GET /{path} HTTP/1.1\r\nHost: {host}\r\n"
        f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    ).encode())
    while b"\r\n\r\n" not in (head := sock.recv(4096)):
        pass

    expression = (
        "fetch('https://www.popeyes.com/graphql',{method:'POST',"
        "headers:{'content-type':'application/json','accept':'application/json',"
        "'x-ui-language':'en','x-ui-region':'US','x-ui-platform':'web',"
        "'x-client-name':'plk-rn-web'},body:"
        + json.dumps(payload)
        + "}).then(r=>r.json())"
    )
    message = json.dumps({
        "id": 1, "method": "Runtime.evaluate",
        "params": {"expression": expression, "awaitPromise": True, "returnByValue": True},
    }).encode()
    mask = os.urandom(4)
    if len(message) < 126:
        frame = b"\x81" + bytes([0x80 | len(message)]) + mask
    else:
        frame = b"\x81\xfe" + struct.pack(">H", len(message)) + mask
    frame += bytes(a ^ mask[i % 4] for i, a in enumerate(message))
    sock.sendall(frame)
    while True:
        first = sock.recv(2)
        length = first[1] & 127
        if length == 126:
            length = struct.unpack(">H", sock.recv(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", sock.recv(8))[0]
        data = sock.recv(length)
        if first[0] & 15 == 1:
            result = json.loads(data)
            if result.get("id") == 1:
                return result["result"]["result"]["value"]


def main():
    rows = parse_pdf(fetch(NUTRITION_URL))
    print(f"official PDF parsed rows: {len(rows)}")
    check = next(row for row in rows if row["name"] == "CHICKEN SANDWICH-CLASSIC")
    print(f"Classic Chicken Sandwich parsed spot-check: {check['calories']:.0f} kcal")
    if check["calories"] != 700:
        raise SystemExit("Classic Chicken Sandwich calories disagree with known value")
    items, unmatched = [], []
    for row in rows:
        cat = category(row["section"], row["name"])
        if cat == "component" and not row["section"].upper().startswith(
            ("SIGNATURE CHICKEN", "CHICKEN")
        ):
            unmatched.append(f"{row['section']} / {row['name']}")
        items.append({
            "id": slug(f"{row['name']}-{row['serving']}"), "name": item_name(row["name"]),
            "description": f"Popeyes nutrition guide section: {row['section']}.",
            "category": cat, "calories": row["calories"],
            "protein_g": row["protein_g"], "carbs_g": row["carbs_g"], "fat_g": row["fat_g"],
            "fiber_g": row["fiber_g"], "sodium_mg": row["sodium_mg"],
            "serving_note": serving_note(row["serving"], row["name"]), "is_estimate": False,
            "source": {"type": "published", "url": NUTRITION_URL},
        })
    if unmatched:
        print(f"{len(unmatched)} row(s) defaulted to component:")
        for row in unmatched:
            print("  ", row)
    save_restaurant({
        "id": "popeyes", "name": "Popeyes", "website": "https://www.popeyes.com",
        "nutrition_source": {"type": "published", "url": NUTRITION_URL, "vendor": None, "retrieved": TODAY},
        "locations": locations(), "items": items,
    })


if __name__ == "__main__":
    main()
