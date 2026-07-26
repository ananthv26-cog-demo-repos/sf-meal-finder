"""Small FatSecret Platform REST client used for permitted crowd fallbacks."""
import base64
import datetime
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request

URL = "https://platform.fatsecret.com/rest/server.api"


def call(method, params):
    oauth = {
        "oauth_consumer_key": os.environ["FATSECRET_CONSUMER_KEY"],
        "oauth_nonce": str(int(time.time() * 1000000)),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_version": "1.0",
    }
    all_params = {**oauth, "method": method, "format": "json", **params}
    enc = lambda value: urllib.parse.quote(str(value), safe="~-._")
    query = "&".join(f"{enc(k)}={enc(v)}" for k, v in sorted(all_params.items()))
    base = "&".join((enc("POST"), enc(URL), enc(query)))
    key = enc(os.environ["FAT_SECRET_CONSUMER_SECRET"]) + "&"
    oauth["oauth_signature"] = base64.b64encode(
        hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()
    ).decode()
    auth = "OAuth " + ", ".join(f'{enc(k)}="{enc(v)}"' for k, v in oauth.items())
    body = urllib.parse.urlencode({"method": method, "format": "json", **params}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Authorization": auth})
    response = json.load(urllib.request.urlopen(req, timeout=30))
    if "error" in response:
        raise RuntimeError(f"FatSecret API error {response['error']}")
    return response


def food(query=None, brand=None, food_id=None):
    if food_id:
        row = {"food_id": str(food_id), "food_url": f"https://foods.fatsecret.com/calories-nutrition/{food_id}"}
    else:
        rows = call("foods.search", {"search_expression": query, "max_results": "20"}).get(
            "foods", {}
        ).get("food", [])
        if isinstance(rows, dict):
            rows = [rows]
        if brand:
            branded = [r for r in rows if isinstance(r, dict) and brand.lower() in (r.get("brand_name") or "").lower()]
            rows = branded or rows
        if not rows:
            raise RuntimeError(f"FatSecret returned no result for {query!r}")
        row = rows[0]
    detail = call("food.get", {"food_id": row["food_id"]}).get("food", {})
    servings = detail.get(" servings", {}) or detail.get("servings", {})
    serving_rows = servings.get("serving", [{}])
    if isinstance(serving_rows, dict):
        serving = serving_rows
    else:
        serving = serving_rows[0]
    def number(key):
        try:
            return float(serving.get(key, 0))
        except (TypeError, ValueError):
            return 0.0
    return {
        "calories": number("calories"),
        "protein_g": number("protein"),
        "carbs_g": number("carbohydrate"),
        "fat_g": number("fat"),
        "fiber_g": number("fiber"),
        "sodium_mg": number("sodium"),
        "serving_note": f"per {serving.get('serving_description', 'listed serving')}",
        "source": {"type": "crowd", "url": row.get("food_url", "https://platform.fatsecret.com/")},
    }


TODAY = datetime.date.today().isoformat()
