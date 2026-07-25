"""Canonical schema for sf-meal-finder data.

Every scraper (this session's or a child session's) must produce data through
`save.save_restaurant()`, which validates against this schema. Consistency is
enforced in code, not prose.
"""

from __future__ import annotations

CATEGORIES = {"meal", "side", "drink", "condiment", "component"}
SOURCE_TYPES = {"published", "vendor", "crowd", "derived"}

# Restaurant document (one JSON file per restaurant in data/restaurants/):
# {
#   "id": str,                 # slug, e.g. "chipotle"
#   "name": str,
#   "website": str,
#   "nutrition_source": {
#       "type": one of SOURCE_TYPES,
#       "url": str,            # exact endpoint or file the numbers came from
#       "vendor": str|null,    # e.g. "nutritionix", "everybite", null
#       "retrieved": "YYYY-MM-DD"
#   },
#   "locations": [             # ALL SF locations, not one per chain
#       {"address": str, "lat": float, "lng": float, "neighborhood": str|null}
#   ],
#   "items": [ITEM, ...]
# }
#
# ITEM:
# {
#   "id": str,                 # slug unique within restaurant
#   "name": str,
#   "description": str|null,
#   "category": one of CATEGORIES,   # only "meal" is surfaced in the app
#   "calories": number,
#   "protein_g": number,
#   "carbs_g": number,
#   "fat_g": number,
#   "fiber_g": number|null,
#   "sodium_mg": number|null,
#   "serving_note": str|null,  # what the row is PER: "per bowl", "per slice"...
#   "is_estimate": bool,       # true for crowd/derived numbers -> rendered as estimate
#   "source": {                # per-item override; falls back to restaurant-level
#       "type": one of SOURCE_TYPES, "url": str
#   } | null
# }

REQUIRED_RESTAURANT_FIELDS = {
    "id": str,
    "name": str,
    "website": str,
    "nutrition_source": dict,
    "locations": list,
    "items": list,
}

REQUIRED_ITEM_FIELDS = {
    "id": str,
    "name": str,
    "category": str,
    "calories": (int, float),
    "protein_g": (int, float),
    "carbs_g": (int, float),
    "fat_g": (int, float),
    "is_estimate": bool,
}

OPTIONAL_ITEM_FIELDS = {
    "description": (str, type(None)),
    "fiber_g": (int, float, type(None)),
    "sodium_mg": (int, float, type(None)),
    "serving_note": (str, type(None)),
    "source": (dict, type(None)),
}

SF_LAT_RANGE = (37.60, 37.86)
SF_LNG_RANGE = (-122.55, -122.33)
