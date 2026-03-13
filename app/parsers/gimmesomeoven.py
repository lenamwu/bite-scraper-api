"""GimmeSomeOven.com scraper."""

from __future__ import annotations

import re
from bs4 import BeautifulSoup

from app.parsers.jsonld import extract_jsonld_recipe
from app.parsers.base import fallback_title, fallback_image, fallback_description, finalise_recipe


def _clean_wp_image_url(url: str | None) -> str | None:
    """Strip WordPress thumbnail dimensions (e.g. -225x225) from image URLs."""
    if not url:
        return None
    # Remove ?resize= query params
    url = re.sub(r"\?resize=\d+%2C\d+$", "", url)
    # Remove WordPress-style dimension suffixes like -225x225 before the extension
    url = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", url)
    return url


def scrape_gimmesomeoven(soup: BeautifulSoup) -> dict:
    ld = extract_jsonld_recipe(soup)

    # Fix image: get full-size by stripping resize/dimension suffixes
    ld["image_url"] = _clean_wp_image_url(ld["image_url"])

    if not ld["image_url"]:
        ld["image_url"] = _clean_wp_image_url(fallback_image(soup))

    if not ld["title"]:
        ld["title"] = fallback_title(soup)

    if not ld["notes"]:
        ld["notes"] = fallback_description(soup, [
            ".tasty-recipes-description",
            ".recipe-summary p",
            ".entry-content > p:first-of-type",
        ])

    return finalise_recipe(ld)
