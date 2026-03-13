"""RecipeTinEats.com scraper."""

from __future__ import annotations

import re
from bs4 import BeautifulSoup

from app.utils import clean
from app.parsers.jsonld import extract_jsonld_recipe
from app.parsers.base import fallback_title, fallback_image, fallback_description, finalise_recipe


def _clean_image_url(url: str | None) -> str | None:
    """Strip ?resize= params from RecipeTinEats tachyon CDN URLs to get full-size."""
    if not url:
        return None
    # Remove resize query params but keep the base URL
    return re.sub(r"\?resize=\d+%2C\d+$", "", url)


def scrape_recipetineats(soup: BeautifulSoup) -> dict:
    ld = extract_jsonld_recipe(soup)

    # Fix image: get full-size by stripping resize params
    ld["image_url"] = _clean_image_url(ld["image_url"])

    # If JSON-LD image was a resized variant, try og:image as fallback
    if not ld["image_url"]:
        ld["image_url"] = fallback_image(soup)
    # Clean any fallback image too
    ld["image_url"] = _clean_image_url(ld["image_url"])

    if not ld["title"]:
        ld["title"] = fallback_title(soup)

    if not ld["notes"]:
        ld["notes"] = fallback_description(soup, [
            ".wprm-recipe-summary p",
            ".wprm-recipe-summary",
            ".entry-content > p:first-of-type",
        ])

    # Clean "Recipe video above." prefix from notes
    if ld["notes"] and ld["notes"].startswith("Recipe video above."):
        ld["notes"] = ld["notes"][len("Recipe video above."):].strip()

    return finalise_recipe(ld)
