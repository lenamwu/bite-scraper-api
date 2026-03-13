"""FoodNetwork.co.uk scraper."""

from __future__ import annotations

import re
from bs4 import BeautifulSoup

from app.utils import clean, best_from_srcset, to_float
from app.parsers.jsonld import extract_jsonld_recipe
from app.parsers.base import fallback_image, finalise_recipe

# Copyright / attribution lines that Food Network injects into instructions
_COPYRIGHT_PHRASES = (
    "copyright", "television food network", "all rights reserved",
    "from food network kitchen", "food network, g.p.",
    "recipe courtesy of", "follow ", "for more news, recipes",
    "facebook", "instagram", "twitter",
)


def _html_fallbacks(soup: BeautifulSoup, raw_html: str) -> dict:
    """Extract fields from visible HTML that JSON-LD may not cover."""
    title = None
    h1 = soup.find("h1", class_=lambda c: c and "p-name" in c)
    if h1:
        title = clean(h1.get_text())

    notes = None
    notes_tag = soup.find("p", class_=lambda c: c and "p-summary" in c)
    if notes_tag:
        notes = clean(notes_tag.get_text())

    # Image
    image_url = None
    img = soup.find("img", class_=lambda c: c and "u-photo" in c)
    if img:
        image_url = best_from_srcset(img.get("srcset")) or img.get("src")
    if not image_url:
        image_url = fallback_image(soup)

    # Time / servings from visible HTML
    cooking_time = None
    time_tag = soup.find("span", class_=lambda c: c and "dt-duration" in c)
    if time_tag:
        cooking_time = clean(time_tag.get_text())

    servings = None
    yield_tag = soup.find("span", class_=lambda c: c and "p-yield" in c)
    if yield_tag:
        servings = clean(yield_tag.get_text())

    # Fallback: regex on raw HTML
    if not cooking_time:
        m = re.search(r'"total_time_formatted_short"\s*:\s*"([^"]+)"', raw_html)
        if m:
            cooking_time = clean(m.group(1))
    if not servings:
        m = re.search(r'"servings"\s*:\s*([0-9]+)', raw_html)
        if m:
            servings = m.group(1)

    # Rating via Tailwind-style classes
    rating = None
    rv = soup.select_one('[itemprop="ratingValue"]')
    if rv:
        rating = to_float(rv.get_text() or rv.get("content"))

    if rating is None:
        cand = soup.select_one(r"div.font-\[700\].text-\[14px\].text-white")
        if cand:
            val = to_float(cand.get_text())
            if val is not None and 0 < val <= 5:
                rating = val

    if rating is None:
        for div in soup.find_all("div", class_=re.compile(r"(^|\s)font-\[700\](\s|$)")):
            val = to_float(div.get_text())
            if val is not None and 0 < val <= 5:
                rating = val
                break

    return {
        "title": title,
        "notes": notes,
        "image_url": image_url,
        "cooking_time": cooking_time,
        "servings": servings,
        "rating": rating,
    }


def scrape_foodnetwork_uk(soup: BeautifulSoup, raw_html: str) -> dict:
    ld = extract_jsonld_recipe(soup)
    html = _html_fallbacks(soup, raw_html)

    # Filter copyright lines from instructions
    if ld["instructions"]:
        ld["instructions"] = [
            s for s in ld["instructions"]
            if not any(p in s.lower() for p in _COPYRIGHT_PHRASES)
        ]

    recipe = {
        "title": html["title"] or ld["title"],
        "notes": html["notes"] or ld["notes"],
        "ingredients": ld["ingredients"],
        "instructions": ld["instructions"],
        "cooking_time": html["cooking_time"] or ld["cooking_time"],
        "servings": html["servings"] or ld["servings"],
        "image_url": html["image_url"] or ld["image_url"],
        "rating": ld["rating"] if ld["rating"] is not None else html["rating"],
    }
    return finalise_recipe(recipe)
