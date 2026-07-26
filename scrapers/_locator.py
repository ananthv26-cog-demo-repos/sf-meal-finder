"""Shared parser for RIO SEO store locators (restaurants.<brand>.com).

Applebee's and IHOP both run their official locators on this platform. Every
city page embeds the full store list as JSON in a JS assignment:

    $config.defaultListData = '[{"fid":...,"lat":"37.80","lng":"-122.41",
                                "address_1":"2770 Taylor St","city":"San Francisco",...}]';

The chain publishes lat/lng itself, so no geocoding is needed.

TRAP: filter on the `city` field, never the zip — "South San Francisco" and
"Daly City" stores carry SF-adjacent zips and would otherwise sneak in. The
city page for a slug like `/ca/san-francisco/` is per-city, but this parser
still filters explicitly so a locator that starts returning "nearby" stores
(they do, on single-store city pages) can't pollute the list.
"""

from __future__ import annotations

import json
import re
import urllib.request

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")


def parse_stores(html: str):
    m = re.search(r"\$config\.defaultListData\s*=\s*'(.*?)';", html, re.S)
    if not m:
        raise SystemExit("locator: $config.defaultListData not found — page shape changed")
    return json.loads(m.group(1).encode("utf-8").decode("unicode_escape"))


def sf_locations(url: str, city: str = "San Francisco", state: str = "CA"):
    """Return schema-shaped locations for stores whose city/region match."""
    out = []
    for s in parse_stores(fetch(url)):
        if (s.get("city") or "").strip() != city or (s.get("region") or "").strip() != state:
            continue
        street = " ".join(p for p in (s.get("address_1"), s.get("address_2")) if p).strip()
        out.append({
            "address": f"{street}, {city}, {state} {s.get('post_code', '')}".strip(),
            "lat": float(s["lat"]),
            "lng": float(s["lng"]),
            "neighborhood": None,
        })
    return out
