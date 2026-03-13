"""Food52.com scraper."""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.parsers.jsonld import extract_jsonld_recipe
from app.parsers.base import fallback_title, fallback_image, fallback_description, finalise_recipe


def scrape_food52(soup: BeautifulSoup) -> dict:
    ld = extract_jsonld_recipe(soup)

    if not ld["image_url"]:
        ld["image_url"] = fallback_image(soup)

    if not ld["title"]:
        ld["title"] = fallback_title(soup)

    if not ld["notes"]:
        ld["notes"] = fallback_description(soup, [
            ".recipe__description p",
            ".recipe__description",
            'meta[property="og:description"]',
        ])

    return finalise_recipe(ld)
