"""TheTableOfSpice.com scraper."""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.utils import clean
from app.parsers.jsonld import extract_jsonld_recipe
from app.parsers.base import fallback_title, fallback_image, fallback_description, finalise_recipe


def scrape_tableofspice(soup: BeautifulSoup) -> dict:
    ld = extract_jsonld_recipe(soup)

    if not ld["title"]:
        ld["title"] = fallback_title(soup)

    if not ld["notes"]:
        ld["notes"] = fallback_description(soup, [
            "p.recipe-summary",
            ".recipe-description p",
            "div.entry-content p:first-of-type",
        ])

    if not ld["image_url"]:
        ld["image_url"] = fallback_image(soup)
        if not ld["image_url"]:
            img_tag = soup.find(
                "img",
                class_=lambda c: c and ("recipe" in c.lower() or "featured" in c.lower()),
            )
            if img_tag:
                ld["image_url"] = img_tag.get("src") or img_tag.get("data-src")

    if not ld["cooking_time"]:
        for sel in (".recipe-time", ".total-time", ".cook-time", "[class*='time']"):
            elem = soup.select_one(sel)
            if elem:
                text = clean(elem.get_text())
                if text and any(w in text.lower() for w in ("min", "hour", "hr")):
                    ld["cooking_time"] = text
                    break

    if not ld["servings"]:
        for sel in (".recipe-yield", ".servings", "[class*='yield']", "[class*='serving']"):
            elem = soup.select_one(sel)
            if elem:
                text = clean(elem.get_text())
                if text:
                    ld["servings"] = text
                    break

    return finalise_recipe(ld)
