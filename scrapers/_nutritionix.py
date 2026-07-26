"""Shared parser for Nutritionix "Interactive Nutrition Menu" brand pages.

Applebee's, IHOP and Pizza Hut all publish their official nutrition through
Nutritionix under contract (the pages carry the brand logo and a
"Last Updated" date, and are the pages the brands' own nutrition links point
at). The grid at https://www.nutritionix.com/<brand>/menu/premium is fully
server-rendered, so no browser is needed.

Cells are read by their column *labels* (`headers="inmGrid_cN"` mapped through
the <thead>), never by position — Nutritionix reorders/adds columns per brand.

Row shapes handled:
  - `<tr class="subCategory">` : menu section header. Pizza Hut folds the
    serving basis into this text ("1 serving = 1 slice = 1/8 of pizza").
  - `<tr class="odd|even">`    : one menu item.
Values may be "< 1" (rendered as `<span class="less-than">`), "-" or blank for
"not published" — the first is treated as 0.5, the others as None.
"""

from __future__ import annotations

import re
import time
import urllib.request

BASE = "https://www.nutritionix.com"

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

# label fragment -> field name in our schema
_FIELDS = {
    "Calories": "calories",
    "Total Fat (g)": "fat_g",
    "Sodium (mg)": "sodium_mg",
    "Total Carbohydrates (g)": "carbs_g",
    "Dietary Fiber (g)": "fiber_g",
    "Protein (g)": "protein_g",
}


def menu_url(brand: str) -> str:
    return f"{BASE}/{brand}/menu/premium"


def fetch(brand: str, attempts: int = 5) -> str:
    """Fetch a brand's grid. The big pages (Pizza Hut's is ~2.3 MB of HTML)
    intermittently 500 on the first hit, so retry with a backoff."""
    req = urllib.request.Request(menu_url(brand), headers={"User-Agent": _UA})
    for attempt in range(1, attempts + 1):
        try:
            return urllib.request.urlopen(req, timeout=120).read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001 - retry any transport/5xx failure
            if attempt == attempts:
                raise
            print(f"nutritionix {brand}: attempt {attempt} failed ({exc}); retrying")
            time.sleep(5 * attempt)
    raise SystemExit("unreachable")


def last_updated(html: str):
    m = re.search(r"Last Updated:</strong>\s*([\d/]{8,10})", html)
    if not m:
        return None
    mm, dd, yyyy = m.group(1).split("/")
    return f"{yyyy}-{mm}-{dd}"


def _num(text):
    """Parse a Nutritionix nutrition cell. '< 1' -> 0.5, '-'/'' -> None."""
    t = (text or "").replace(",", "").replace("\xa0", " ").strip()
    if t in ("", "-", "--", "N/A", "n/a"):
        return None
    if t.startswith("<"):
        inner = t.lstrip("<").strip()
        try:
            return min(0.5, float(inner))
        except ValueError:
            return 0.5
    m = re.match(r"-?\d+(\.\d+)?", t)
    if not m:
        return None
    v = float(m.group(0))
    return int(v) if v == int(v) else v


def parse_rows(html: str):
    """Yield dicts: {section, name, calories, fat_g, carbs_g, protein_g,
    fiber_g, sodium_mg} in menu order, with values parsed from labeled cells."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("#inmGrid table")
    if table is None:
        raise SystemExit("nutritionix: no #inmGrid table — page shape changed")

    col_field = {}
    for th in table.select("thead th"):
        label = th.get_text(" ", strip=True)
        for frag, field in _FIELDS.items():
            if label.startswith(frag):
                col_field[th.get("id")] = field

    missing = set(_FIELDS.values()) - set(col_field.values()) - {"fiber_g", "sodium_mg"}
    if missing:
        raise SystemExit(f"nutritionix: missing columns {sorted(missing)}")

    section = None
    for tr in table.select("tbody tr"):
        classes = tr.get("class") or []
        if "subCategory" in classes:
            section = tr.get_text(" ", strip=True)
            continue
        cells = tr.find_all("td")
        if not cells:
            continue
        name_link = cells[0].select_one("a.nmItem")
        if name_link is None:
            continue
        row = {"section": section, "name": name_link.get_text(" ", strip=True)}
        for td in cells[1:]:
            field = col_field.get((td.get("headers") or [None])[0] if isinstance(td.get("headers"), list) else td.get("headers"))
            if field:
                row[field] = _num(td.get_text(" ", strip=True))
        yield row


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "item"


def dedupe_id(base: str, seen: set) -> str:
    iid, n = base, 2
    while iid in seen:
        iid = f"{base}-{n}"
        n += 1
    seen.add(iid)
    return iid
