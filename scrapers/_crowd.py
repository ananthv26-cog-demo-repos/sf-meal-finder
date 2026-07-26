"""Small HTML readers shared by the crowd-data scrapers."""
import html
import re
import urllib.parse
import urllib.request


HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/126"}


def fetch(url):
    request = urllib.request.Request(url, headers=HEADERS)
    return urllib.request.urlopen(request, timeout=30).read().decode("utf-8", "replace")


def fatsecret_items(brand_url):
    listing = fetch(brand_url)
    paths = list(dict.fromkeys(re.findall(r'href="([^"]+)"', listing)))
    paths = [p for p in paths if p.startswith(urllib.parse.urlsplit(brand_url).path + "/")]
    items = []
    for path in paths:
        url = urllib.parse.urljoin(brand_url, path)
        body = fetch(url)
        title = re.search(r"<title>Calories in (.*?) and Nutrition Facts</title>", body)
        values = dict(
            (k.lower(), float(v))
            for k, v in re.findall(
                r'<div class="factTitle">(Calories|Fat|Carbs|Protein)</div>\s*'
                r'<div class="factValue">([\d.]+)', body
            )
        )
        if not {"calories", "fat", "carbs", "protein"} <= values.keys():
            continue
        name = html.unescape(title.group(1)).strip() if title else path.rsplit("/", 1)[-1].replace("-", " ").title()
        name = re.sub(
            r"^(?:Joe\s*&\s*The\s*Juice|Erik['’]s\s+Delicafe|La\s+Boulangerie)\s+",
            "",
            name,
            flags=re.I,
        ).strip()
        lower = name.lower()
        category = "condiment" if (
            any(x in lower for x in ("dressing", "sauce", "dip", "hummus", "babaganoush"))
            and "without dressing" not in lower
        ) else "meal" if lower == "tunacado" or any(
            x in lower for x in ("sandwich", "burrito", "bowl", "salad", "club", "soup")
        ) else "drink" if any(x in lower for x in ("juice", "coffee", "shake", "smoothie", "tea")) else (
            "side" if any(x in lower for x in ("dessert", "bread", "chips")) else "component"
        )
        items.append({
            "id": re.sub(r"[^a-z0-9]+", "-", lower).strip("-"),
            "name": name,
            "description": None,
            "category": category,
            "calories": values["calories"],
            "protein_g": values["protein"],
            "carbs_g": values["carbs"],
            "fat_g": values["fat"],
            "fiber_g": None,
            "sodium_mg": None,
            "serving_note": "per serving (as listed by FatSecret)",
            "is_estimate": True,
            "source": {"type": "crowd", "url": url},
        })
    return items


def mynetdiary_item(url, category="meal"):
    body = fetch(url)
    meta = re.search(r'<meta name="description" content="([^"]+)"', body)
    text = html.unescape(meta.group(1)) if meta else ""
    m = re.search(r"There are ([\d.]+) calories in ([^ ]+) of (.*) from: Carbs ([\d.]+)g, Fat ([\d.]+)g, Protein ([\d.]+)g", text)
    if not m:
        # Current pages also expose a JSON-LD-like object.
        m = re.search(r'"cleanFoodName":"([^"]+)".*?"rawCalories":([\d.]+).*?"totalFat".*?"rawValue":([\d.]+).*?"totalCarbs".*?"rawValue":([\d.]+).*?"protein".*?"rawValue":([\d.]+)', body, re.S)
        if not m:
            raise ValueError(f"nutrition fields not found: {url}")
        name, calories, fat, carbs, protein = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
    else:
        calories, _, name, carbs, fat, protein = m.groups()
    name = html.unescape(name).strip()
    return {
        "id": re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"),
        "name": name,
        "description": None,
        "category": category,
        "calories": float(calories),
        "protein_g": float(protein),
        "carbs_g": float(carbs),
        "fat_g": float(fat),
        "fiber_g": None,
        "sodium_mg": None,
        "serving_note": "per serving (as listed by MyNetDiary)",
        "is_estimate": True,
        "source": {"type": "crowd", "url": url},
    }
