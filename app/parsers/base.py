"""Common HTML fallback helpers shared across site-specific scrapers."""

from __future__ import annotations

import re
from bs4 import BeautifulSoup

from app.utils import clean, to_float


def fallback_title(soup: BeautifulSoup) -> str | None:
    """Return the text of the first <h1> on the page."""
    h1 = soup.find("h1")
    return clean(h1.get_text()) if h1 else None


def fallback_image(soup: BeautifulSoup) -> str | None:
    """Try og:image, then twitter:image meta tags."""
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return og["content"]
    tw = soup.find("meta", attrs={"name": "twitter:image"})
    if tw and tw.get("content"):
        return tw["content"]
    return None


def fallback_rating(soup: BeautifulSoup) -> float | None:
    """Look for a rating value via common HTML patterns."""
    # schema.org itemprop
    rv = soup.select_one('[itemprop="ratingValue"]')
    if rv:
        val = to_float(rv.get_text() or rv.get("content"))
        if val is not None:
            return val

    # Generic class-based selectors
    for selector in (
        "[class*='rating'] [class*='value']",
        ".recipe-rating .rating-value",
    ):
        elem = soup.select_one(selector)
        if elem:
            val = to_float(elem.get_text())
            if val is not None:
                return val
    return None


def fallback_description(soup: BeautifulSoup, selectors: list[str] | None = None) -> str | None:
    """Try a list of CSS selectors, then og:description, to find a recipe description."""
    default_selectors = [
        "p.article-subheading",
        ".recipe-summary p",
        ".recipe-description",
        ".recipe-intro p",
    ]
    for selector in (selectors or default_selectors):
        tag = soup.select_one(selector)
        if tag:
            text = clean(tag.get_text())
            if text:
                return text
    # Fallback: og:description meta tag
    og = soup.find("meta", property="og:description")
    if og and og.get("content"):
        text = clean(og["content"])
        if text:
            return text
    return None


def finalise_recipe(recipe: dict) -> dict:
    """Fill in sensible defaults for missing fields."""
    recipe.setdefault("title", None)
    recipe.setdefault("notes", None)
    recipe.setdefault("ingredients", [])
    recipe.setdefault("instructions", [])
    recipe.setdefault("cooking_time", None)
    recipe.setdefault("image_url", None)
    recipe.setdefault("rating", None)

    if not recipe.get("title"):
        recipe["title"] = "Untitled"
    if not recipe.get("notes"):
        recipe["notes"] = ""
    if not recipe.get("servings"):
        recipe["servings"] = "servings not specified"

    return recipe
