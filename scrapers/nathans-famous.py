"""Nathan's Famous scraper intentionally skipped.

The official ``nathansfamous.com/nutrition/`` page redirects to SFD Brands
and is blocked by Cloudflare in the supplied Chrome session. The official
``restaurants.nathansfamous.com`` site exposes menu descriptions and
third-party ordering links, but no nutrition payload, nutrition endpoint,
per-item calories, or contracted Nutritionix brand grid. Its menu page only
loads a JPEG menu image. Therefore no reproducible, restaurant-published
per-item nutrition source was found and no Nathan's data file is published.
"""


def main():
    raise SystemExit("Nathan's Famous: no reproducible official restaurant nutrition source")


if __name__ == "__main__":
    main()
