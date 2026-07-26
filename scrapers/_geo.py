"""Small geocoding helper with an address-keyed Nominatim fallback."""

import json
import time
import urllib.parse
import urllib.request

KNOWN_COORDS = {
    "152 kearny street, san francisco, ca 94108": (37.789638409754204, -122.40365563438391),
    "170 o'farrell st food court, san francisco, ca 94102": (37.787006, -122.4072604),
    "2300 16th st #245, san francisco, ca 94103": (37.76650010169665, -122.40897547347302),
    "500 parnassus ave, millberry union, san francisco, ca 94619": (37.7634488, -122.4585716),
    "251 geary street, 8th floor, san francisco, ca 94102": (37.7872963, -122.4074595),
    "251 geary street 8th floor, san francisco, ca 94102": (37.7872963, -122.4074595),
    "399 4th st, san francisco, ca 94107": (37.7811499, -122.3997789),
    "1150 ocean ave, san francisco, ca 94112": (37.7237981, -122.4546813),
    "450 rhode island st, san francisco, ca 94107": (37.7643298, -122.4027236),
    "2001 market st, san francisco, ca 94114": (37.768896, -122.426891),
    "1765 california st, san francisco, ca 94109": (37.7900899, -122.4234142),
    "3251 20th ave, suite 340, san francisco, ca 94132": (37.7289115, -122.475687),
    "1185 market st, san francisco, ca 94103": (37.7788891, -122.414112),
    "2300 16th street unit 203, san francisco, ca 94103": (37.7669716, -122.409327),
    "4201 18th st, san francisco, ca 94114": (37.760582, -122.4364315),
    "2435 california st, san francisco, ca 94115": (37.7885533, -122.4345222),
    "203 folsom st, san francisco, ca 94105": (37.7890338, -122.3919796),
    "1200 irving st, san francisco, ca 94122": (37.7640893, -122.4711666),
    "375 32nd ave, san francisco, ca 94121": (37.782188, -122.4930572),
    "300 california st ste 100, san francisco, ca 94104": (37.7933044, -122.4003067),
    "300 california st. ste 100, san francisco, ca 94104": (37.7933044, -122.4003067),
    "98 post st, san francisco, ca 94104": (37.7889739, -122.4030976),
    "575 market st ste 150, san francisco, ca 94105": (37.7895414, -122.4003752),
    "575 market st. ste 150, san francisco, ca 94105": (37.7895414, -122.4003752),
    "3 embarcadero center, san francisco, ca 94111": (37.7946662, -122.3996548),
    "3639 18th st, san francisco, ca 94110": (37.7614011, -122.4247039),
    "550 divisadero st, san francisco, ca 94117": (37.774509, -122.4378445),
    "1745 folsom st, san francisco, ca 94103": (37.7691367, -122.4150751),
    "680 mission street, san francisco, ca 94105": (37.7865699, -122.4020333),
    "1957 union st, san francisco, ca 94123": (37.7974129, -122.4314868),
    "181 fremont st, san francisco, ca 94105": (37.7896303, -122.3955461),
    "450 hayes st, san francisco, ca 94117": (37.7770310, -122.4238821),
    "3870 24th st, san francisco, ca 94114": (37.7517632, -122.4290685),
    "1 ferry bldg. (across from sur la table), san francisco, ca 94111": (37.7955487, -122.3934746),
    "pier 39 bldg b-06, san francisco, ca 94133": (37.808673, -122.409821),
}


def geocode(address):
    key = " ".join(address.casefold().split())
    if key in KNOWN_COORDS:
        return KNOWN_COORDS[key]
    query = urllib.parse.urlencode({
        "q": address,
        "format": "jsonv2",
        "limit": 1,
    })
    request = urllib.request.Request(
        f"https://nominatim.openstreetmap.org/search?{query}",
        headers={"User-Agent": "sf-meal-finder/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        rows = json.load(response)
    time.sleep(1)
    if not rows:
        raise RuntimeError(f"Nominatim returned no result for {address!r}")
    return float(rows[0]["lat"]), float(rows[0]["lon"])
