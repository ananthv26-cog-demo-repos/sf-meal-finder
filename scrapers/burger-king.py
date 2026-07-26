"""Burger King US scraper using the live public Sanity menu graph."""

import datetime
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant  # noqa: E402

SANITY_URL = "https://kjfd81ul.apicdn.sanity.io/v2021-09-01/data/query/prod_bk_us"
MENU_ID = "menu_5492"
NUTRITION_URL = SANITY_URL
TODAY = datetime.date.today().isoformat()
UA = {"User-Agent": "Mozilla/5.0"}
RESTAURANT_URL = "https://use1-prod-bk-gateway.rbictg.com/graphql?operationName=GetNearbyRestaurants"
RESTAURANT_QUERY = """query GetNearbyRestaurants($input: NearbyRestaurantsInput!) {
  restaurantsV2 { nearby(input: $input) { nodes {
    _id storeId id name latitude longitude status
    physicalAddress { address1 address2 city stateProvince postalCode }
  } } }
}"""


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def localized(value):
    return value.get("en", "") if isinstance(value, dict) else (value or "")


def sanity(query):
    url = SANITY_URL + "?" + urllib.parse.urlencode({"query": query})
    request = urllib.request.Request(url, headers=UA)
    return json.loads(urllib.request.urlopen(request, timeout=60).read())["result"]


def fetch_graph():
    root = sanity(f'*[_type=="menu" && _id=="{MENU_ID}"][0]')
    docs = {root["_id"]: root}
    pending = [o["_ref"] for o in root.get("options", []) if o.get("_ref")]
    while pending:
        ids = []
        while pending and len(ids) < 75:
            ref = pending.pop()
            if ref not in docs and ref not in ids:
                ids.append(ref)
        if not ids:
            continue
        query = "*[_id in [" + ",".join(json.dumps(ref) for ref in ids) + "]]"
        for doc in sanity(query):
            docs[doc["_id"]] = doc
            if doc["_type"] == "item":
                continue
            for option in doc.get("options", []):
                if option.get("_ref"):
                    pending.append(option["_ref"])
                if option.get("option", {}).get("_ref"):
                    pending.append(option["option"]["_ref"])
            if doc.get("mainItem", {}).get("_ref"):
                pending.append(doc["mainItem"]["_ref"])
    return docs, root


def item_nutrition(doc):
    # nutrition is the unmodified base and intentionally must not be used.
    row = doc.get("nutritionWithModifiers")
    if not isinstance(row, dict):
        return None
    fields = {
        "calories": row.get("calories"),
        "protein_g": row.get("proteins"),
        "carbs_g": row.get("carbohydrates"),
        "fat_g": row.get("fat"),
        "fiber_g": row.get("fiber"),
        "sodium_mg": row.get("sodium"),
        "weight": row.get("weight"),
    }
    if any(fields[key] is None for key in ("calories", "protein_g", "carbs_g", "fat_g")):
        return None
    return fields


def category(name, section):
    lower = name.lower()
    section_lower = section.lower()
    if any(word in lower for word in ("sauce", "dip", "packet", "syrup", "salt", "pepper")):
        return "condiment"
    if any(word in lower for word in (
        "shake", "juice", "water", "milk", "coca-cola", "coke", "drink", "powerade",
        "lemonade", "mello yello", "fanta", "sprite", "barq", "tea",
        "freezee", "coffee",
    )):
        return "drink"
    if any(word in lower for word in (
        "fries", "hash browns", "applesauce", "pie", "sundae", "cookie",
        "soft serve", "onion rings", "tots", "have-sies",
    )):
        return "side"
    if section_lower in {"sweets", "sides"}:
        return "side"
    if section_lower in {"drinks & coffee", "beverages"}:
        return "drink"
    if section_lower in {"condiments", "dipping sauces", "sandwich sauces", "other"}:
        return "condiment"
    if any(word in lower for word in (
        "burger", "whopper", "sandwich", "wrap", "burrito", "croissan",
        "biscuit", "nugget", "chicken fries", "taco", "platter", "meal",
    )):
        return "meal"
    if section_lower in {
        "flame grilled burgers", "chicken & fish", "breakfast meals",
        "breakfast sandwiches", "burritos", "limited time only",
        "king jr. kids meals", "digital exclusives", "burgers for breakfast",
        "meals", "meals ",
    }:
        return "meal"
    print(f"Warning: unmapped Burger King section {section!r} for {name!r}; using component")
    return "component"


def section_priority(section):
    return {
        "flame grilled burgers": 0,
        "chicken & fish": 1,
        "breakfast sandwiches": 2,
        "breakfast meals": 3,
        "burritos": 4,
        "limited time only": 5,
        "sides": 6,
        "drinks & coffee": 7,
        "condiments": 8,
    }.get(section.casefold(), 50)


def locations():
    stores = {}
    for lat in (37.70, 37.77, 37.84):
        for lng in (-122.50, -122.42, -122.35):
            variables = {"input": {
                "pagination": {"first": 50},
                "radiusStrictMode": False,
                "status": "OPEN",
                "coordinates": {
                    "searchRadius": 10,
                    "userLat": lat,
                    "userLng": lng,
                },
            }}
            payload = json.dumps({
                "operationName": "GetNearbyRestaurants",
                "variables": variables,
                "query": RESTAURANT_QUERY,
            }).encode()
            request = urllib.request.Request(
                RESTAURANT_URL, data=payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": UA["User-Agent"],
                    "x-ui-language": "en",
                    "x-ui-region": "US",
                    "x-ui-version": "7.78.0",
                    "x-ui-platform": "web",
                    "apollographql-client-version": "7.78.0-7.78.0-no-uid-76f08e7",
                    "apollographql-client-name": "wl-rn-web",
                },
            )
            result = json.loads(urllib.request.urlopen(request, timeout=60).read())
            for store in result["data"]["restaurantsV2"]["nearby"]["nodes"]:
                address = store.get("physicalAddress") or {}
                if (address.get("city") or "").strip().casefold() != "san francisco":
                    continue
                location_text = " ".join(
                    str(store.get(field) or "") for field in ("name",)
                ) + " " + " ".join(
                    str(address.get(field) or "") for field in ("address1", "address2")
                )
                if any(term in location_text.casefold() for term in ("airport", "terminal")):
                    print(
                        f"Excluding non-city-proper airport/terminal store "
                        f"{store.get('storeId')}: {location_text.strip()}"
                    )
                    continue
                stores[store["storeId"]] = store

    def normalized_address(store):
        address = store["physicalAddress"]
        street = address.get("address1", "").strip()
        for full, short in (
            ("Boulevard", "Blvd"),
            ("Avenue", "Ave"),
            ("Street", "St"),
            ("Drive", "Dr"),
            ("Road", "Rd"),
        ):
            street = re.sub(rf"\b{full}\b", short, street, flags=re.IGNORECASE)
        city = (address.get("city") or "").title()
        state = address.get("stateProvinceShort") or {
            "california": "CA",
        }.get((address.get("stateProvince") or "").casefold(), address.get("stateProvince", ""))
        postal = (address.get("postalCode") or "").split("-")[0]
        return f"{street}, {city}, {state} {postal}"

    return [{
        "address": normalized_address(store),
        "lat": store["latitude"],
        "lng": store["longitude"],
        "neighborhood": None,
    } for store in sorted(stores.values(), key=lambda item: item["storeId"])]


def main():
    docs, root = fetch_graph()
    items = []
    combos = []
    seen_items = set()
    sections = {}
    for option in root.get("options", []):
        section = docs.get(option.get("_ref"))
        if not section or section.get("hiddenFromMainMenu"):
            continue
        section_name = localized(section.get("name")) or section.get("internalName", "")
        sections[section["_id"]] = section_name
        stack = list(section.get("options", []))
        while stack:
            ref = stack.pop().get("_ref")
            doc = docs.get(ref)
            if not doc:
                continue
            if doc["_type"] == "item":
                nutrition = item_nutrition(doc)
                name = localized(doc.get("name")).strip()
                if nutrition and doc["_id"] not in seen_items:
                    if any(bad in name.lower() for bad in (
                        "delivery bundles", "offers", "donation", "build your own",
                    )):
                        continue
                    seen_items.add(doc["_id"])
                    items.append((doc, name, section_name, nutrition))
                continue
            if doc["_type"] == "combo":
                combos.append((doc, section_name))
            stack.extend(doc.get("options", []))
            for option in doc.get("options", []):
                if option.get("option", {}).get("_ref"):
                    stack.append(option["option"])
            if doc.get("mainItem", {}).get("_ref"):
                stack.append(doc["mainItem"])

    # The same product is reachable through multiple picker/combo paths.
    # Collapse identical name/nutrition rows, retaining the most canonical
    # main-menu section.
    canonical = {}
    for record in items:
        doc, name, section_name, nutrition = record
        key = (name, tuple(nutrition.get(field) for field in (
            "calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sodium_mg", "weight",
        )))
        previous = canonical.get(key)
        if previous is None or section_priority(section_name) < section_priority(previous[2]):
            canonical[key] = record

    grouped_names = {}
    for record in canonical.values():
        grouped_names.setdefault(record[1], []).append(record)
    output = []
    for doc, name, section_name, nutrition in canonical.values():
        variants = grouped_names[name]
        display_name = name
        if len(variants) > 1:
            same_section = sum(variant[2] == section_name for variant in variants) > 1
            suffix = f"{section_name}, {doc['_id']}" if same_section else section_name
            display_name = f"{name} ({suffix})"
        output.append({
            "id": slug(display_name) + "-" + slug(doc["_id"]),
            "name": display_name,
            "description": None,
            "category": category(name, section_name),
            "calories": nutrition["calories"],
            "protein_g": nutrition["protein_g"],
            "carbs_g": nutrition["carbs_g"],
            "fat_g": nutrition["fat_g"],
            "fiber_g": nutrition["fiber_g"],
            "sodium_mg": nutrition["sodium_mg"],
            "serving_note": (
                f"per {nutrition['weight']:g} g serving"
                if nutrition.get("weight") is not None else "per menu item"
            ),
            "is_estimate": False,
            "source": {"type": "published", "url": NUTRITION_URL},
        })
    def reachable_items(ref, visited=None):
        visited = set() if visited is None else visited
        if ref in visited:
            return set()
        visited.add(ref)
        doc = docs.get(ref)
        if not doc:
            return set()
        if doc["_type"] == "item":
            return {ref} if item_nutrition(doc) else set()
        refs = set()
        for option in doc.get("options", []):
            child = option.get("_ref") or option.get("option", {}).get("_ref")
            if child:
                refs |= reachable_items(child, visited)
        if doc.get("mainItem", {}).get("_ref"):
            refs |= reachable_items(doc["mainItem"]["_ref"], visited)
        return refs

    used_combo_names = set()
    for combo, section_name in combos:
        name = localized(combo.get("name")).strip()
        if not name or name in used_combo_names:
            continue
        component_refs = []
        main_ref = combo.get("mainItem", {}).get("_ref")
        if main_ref:
            component_refs.append(main_ref)
        valid = True
        for option in combo.get("options", []):
            ref = option.get("_ref")
            if not ref:
                continue
            candidates = reachable_items(ref)
            if len(candidates) != 1:
                valid = False
                break
            component_refs.extend(candidates)
        if not valid or not component_refs:
            continue
        component_refs = list(dict.fromkeys(component_refs))
        component_docs = [docs[ref] for ref in component_refs if ref in docs]
        nutrition_rows = [item_nutrition(doc) for doc in component_docs]
        if any(row is None for row in nutrition_rows):
            continue
        total = {key: sum(row.get(key) or 0 for row in nutrition_rows) for key in (
            "calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sodium_mg",
        )}
        recipe = ", ".join(localized(doc.get("name")) for doc in component_docs)
        output.append({
            "id": "derived-" + slug(name),
            "name": name,
            "description": f"Derived combo: {recipe}.",
            "category": "meal",
            **total,
            "serving_note": "per orderable combo",
            "is_estimate": True,
            "source": {"type": "derived", "url": NUTRITION_URL},
        })
        used_combo_names.add(name)
    whopper = next(
        item for item in output
        if item["name"].startswith("Whopper")
        and item["calories"] == 710
        and item["fat_g"] == 42
        and item["carbs_g"] == 57
        and item["protein_g"] == 34
    )
    expected = {"calories": 670, "fat_g": 40, "carbs_g": 49, "protein_g": 31}
    print(
        f"{whopper['name']} spot-check: "
        f"{whopper['calories']:g} kcal, {whopper['fat_g']:g} g fat, "
        f"{whopper['carbs_g']:g} g carbs, {whopper['protein_g']:g} g protein "
        f"(BK published comparison: {expected})"
    )
    save_restaurant({
        "id": "burger-king",
        "name": "Burger King",
        "website": "https://www.bk.com",
        "nutrition_source": {"type": "published", "url": NUTRITION_URL, "vendor": None, "retrieved": TODAY},
        "locations": locations(),
        "items": output,
    })


if __name__ == "__main__":
    main()
