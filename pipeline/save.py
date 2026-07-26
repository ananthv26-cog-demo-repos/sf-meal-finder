"""Shared save() for all scrapers. Import this — do not write JSON by hand.

Usage from a scraper:

    from save import save_restaurant
    save_restaurant(doc)   # doc matches schema.py

Writes:
  data/restaurants/<id>.json   validated items only
  data/rejected/<id>.json      quarantined rows with reasons (never published,
                               never silently dropped)
Raises SystemExit with a readable report on fatal document errors.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from validate import sanitize_text, validate_restaurant

ROOT = Path(__file__).resolve().parent.parent
RESTAURANTS_DIR = ROOT / "data" / "restaurants"
REJECTED_DIR = ROOT / "data" / "rejected"

_TEXT_FIELDS = ("name", "description", "serving_note")


def _sanitize_doc(doc):
    doc["name"] = sanitize_text(doc.get("name"))
    for item in doc.get("items", []):
        for f in _TEXT_FIELDS:
            if f in item:
                item[f] = sanitize_text(item[f])
    for loc in doc.get("locations", []):
        loc["address"] = sanitize_text(loc.get("address"))
        if loc.get("neighborhood") is not None:
            loc["neighborhood"] = sanitize_text(loc["neighborhood"])
    return doc


def save_restaurant(doc):
    doc = _sanitize_doc(doc)
    errors, rejected = validate_restaurant(doc)
    if errors:
        print(f"FATAL document errors for {doc.get('id')!r}:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        raise SystemExit(1)

    rejected_items = {
        id(rejected_item)
        for rejected_row in rejected
        if isinstance((rejected_item := rejected_row.get("item")), dict)
    }
    accepted = [item for item in doc["items"] if id(item) not in rejected_items]

    RESTAURANTS_DIR.mkdir(parents=True, exist_ok=True)
    REJECTED_DIR.mkdir(parents=True, exist_ok=True)

    out = dict(doc, items=accepted)
    path = RESTAURANTS_DIR / f"{doc['id']}.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")

    if rejected:
        rpath = REJECTED_DIR / f"{doc['id']}.json"
        rpath.write_text(json.dumps(rejected, indent=2, ensure_ascii=False) + "\n")
        print(f"{doc['id']}: quarantined {len(rejected)} row(s) -> {rpath}")
    else:
        rpath = REJECTED_DIR / f"{doc['id']}.json"
        rpath.unlink(missing_ok=True)

    meals = sum(1 for i in accepted if i.get("category") == "meal")
    print(
        f"{doc['id']}: saved {len(accepted)} items ({meals} meals), "
        f"{len(doc['locations'])} SF location(s) -> {path}"
    )
    return path
