"""Validation for sf-meal-finder data.

Macro-consistency check: 9*fat + 4*carbs + 4*protein should land near stated
calories. The tolerance is deliberately asymmetric:

- Computed ABOVE stated calories is common and mostly benign: labels compute
  net carbs (fiber subtracted, ~4 kcal/g of slack), and per-macro rounding on
  small items inflates the estimate. Allowed overshoot: 25% + 25 kcal.
- Computed BELOW stated calories means calories are coming from somewhere the
  macros don't capture (alcohol at 7 kcal/g, or simply wrong numbers). That is
  suspicious for food, so the undershoot budget is tighter: 12% + 20 kcal.

Rows that fail are quarantined (returned in `rejected`), never silently
dropped and never published.
"""

from __future__ import annotations

import re

from schema import (
    CATEGORIES,
    OPTIONAL_ITEM_FIELDS,
    REQUIRED_ITEM_FIELDS,
    REQUIRED_RESTAURANT_FIELDS,
    SF_LAT_RANGE,
    SF_LNG_RANGE,
    SOURCE_TYPES,
)

_TAG_RE = re.compile(r"<[^>]+>")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

OVERSHOOT_PCT, OVERSHOOT_ABS = 0.25, 25.0
UNDERSHOOT_PCT, UNDERSHOOT_ABS = 0.12, 20.0


def sanitize_text(value):
    """Strip HTML tags/control chars from scraped text. Called on ingest so
    nothing downstream ever needs to render markup."""
    if value is None:
        return None
    text = _TAG_RE.sub(" ", str(value))
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = _TAG_RE.sub(" ", text)  # tags revealed by entity decoding
    text = _CTRL_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def macro_check(item):
    """Return (ok, computed, delta) for the 9/4/4 consistency check."""
    cal = float(item["calories"])
    computed = 9 * float(item["fat_g"]) + 4 * float(item["carbs_g"]) + 4 * float(item["protein_g"])
    delta = computed - cal
    if delta >= 0:
        ok = delta <= max(OVERSHOOT_PCT * cal, OVERSHOOT_ABS)
    else:
        ok = -delta <= max(UNDERSHOOT_PCT * cal, UNDERSHOOT_ABS)
    return ok, computed, delta


def _type_errors(obj, spec, ctx):
    errors = []
    for field, types in spec.items():
        if field not in obj:
            errors.append(f"{ctx}: missing field '{field}'")
        elif not isinstance(obj[field], types if isinstance(types, tuple) else (types,)):
            errors.append(f"{ctx}: field '{field}' has wrong type {type(obj[field]).__name__}")
        elif types in ((int, float),) and isinstance(obj[field], bool):
            errors.append(f"{ctx}: field '{field}' is bool, expected number")
    return errors


def validate_item(item, restaurant_id):
    ctx = f"{restaurant_id}/{item.get('id', '?')}"
    errors = _type_errors(item, REQUIRED_ITEM_FIELDS, ctx)
    for field, types in OPTIONAL_ITEM_FIELDS.items():
        if field in item and not isinstance(item[field], types):
            errors.append(f"{ctx}: field '{field}' has wrong type")
    if errors:
        return errors
    if item["category"] not in CATEGORIES:
        errors.append(f"{ctx}: bad category '{item['category']}'")
    if item.get("source") is not None:
        src = item["source"]
        if src.get("type") not in SOURCE_TYPES or not src.get("url"):
            errors.append(f"{ctx}: bad per-item source {src}")
    for f in ("calories", "protein_g", "carbs_g", "fat_g"):
        if float(item[f]) < 0:
            errors.append(f"{ctx}: negative {f}")
    if float(item["calories"]) > 5000:
        errors.append(f"{ctx}: calories {item['calories']} implausibly high — check what the row is per")
    ok, computed, delta = macro_check(item)
    if not ok:
        errors.append(
            f"{ctx}: macro check failed — stated {item['calories']} kcal vs "
            f"computed {computed:.0f} (delta {delta:+.0f})"
        )
    return errors


def validate_restaurant(doc):
    """Return (errors, rejected_items). `errors` are fatal document problems;
    `rejected_items` are per-item failures to quarantine."""
    errors = _type_errors(doc, REQUIRED_RESTAURANT_FIELDS, doc.get("id", "?"))
    if errors:
        return errors, []
    rid = doc["id"]
    ns = doc["nutrition_source"]
    if ns.get("type") not in SOURCE_TYPES:
        errors.append(f"{rid}: nutrition_source.type must be one of {sorted(SOURCE_TYPES)}")
    if not ns.get("url"):
        errors.append(f"{rid}: nutrition_source.url (exact endpoint/file) is required")
    if not ns.get("retrieved"):
        errors.append(f"{rid}: nutrition_source.retrieved date is required")
    if not doc["locations"]:
        errors.append(f"{rid}: at least one SF location with lat/lng is required")
    for i, loc in enumerate(doc["locations"]):
        if not loc.get("address"):
            errors.append(f"{rid}: location[{i}] missing address")
        lat, lng = loc.get("lat"), loc.get("lng")
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            errors.append(f"{rid}: location[{i}] missing numeric lat/lng")
        elif not (SF_LAT_RANGE[0] <= lat <= SF_LAT_RANGE[1] and SF_LNG_RANGE[0] <= lng <= SF_LNG_RANGE[1]):
            errors.append(f"{rid}: location[{i}] ({lat},{lng}) outside San Francisco bounds")
    seen = set()
    rejected = []
    for item in doc["items"]:
        item_errors = validate_item(item, rid)
        iid = item.get("id")
        if iid in seen:
            item_errors.append(f"{rid}/{iid}: duplicate item id")
        seen.add(iid)
        if item_errors:
            rejected.append({"item": item, "reasons": item_errors})
    # crowd/derived data must be flagged as estimates
    for item in doc["items"]:
        src_type = (item.get("source") or ns).get("type")
        if src_type in ("crowd", "derived") and not item.get("is_estimate"):
            rejected.append({
                "item": item,
                "reasons": [f"{rid}/{item.get('id')}: {src_type} source must set is_estimate=true"],
            })
    return errors, rejected
