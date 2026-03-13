"""Food.com scraper."""

from __future__ import annotations

import re
from bs4 import BeautifulSoup

from app.utils import clean
from app.parsers.jsonld import extract_jsonld_recipe
from app.parsers.base import fallback_title, fallback_image, finalise_recipe


def _fallback_description(soup: BeautifulSoup) -> str:
    """Food.com often wraps the submitter description in quotes."""
    for p in soup.find_all("p"):
        text = clean(p.get_text())
        if text and text.startswith('"') and text.endswith('"') and len(text) > 20:
            return text.strip('"')
    return ""


def _fallback_ingredients(soup: BeautifulSoup) -> list[str]:
    found = []
    for li in soup.select("li"):
        text = clean(li.get_text())
        if not text or len(text) < 3:
            continue
        if any(w in text.lower() for w in (
            "recipe", "photo", "view", "more", "sign", "follow", "advertisement",
        )):
            continue
        has_measure = any(w in text.lower() for w in (
            "cup", "cups", "teaspoon", "tablespoon", "pound", "ounce",
            "gram", "ml", "tsp", "tbsp", "lb", "oz", "clove", "slice",
            "piece", "inch", "½", "¼", "¾", "1/2", "1/4", "3/4",
            "can", "package", "frozen", "fresh",
        ))
        has_number = bool(re.search(r"\d", text))
        has_food_link = li.find("a", href=lambda x: x and "/about/" in x)
        if has_measure or has_number or has_food_link:
            found.append(text)
    return found if len(found) >= 3 else []


def _fallback_instructions(soup: BeautifulSoup) -> list[str]:
    action_words = (
        "heat", "cook", "bake", "mix", "stir", "add", "combine", "place",
        "pour", "cover", "simmer", "boil", "fry", "saute", "preheat", "spray", "season",
    )
    found = []
    for li in soup.select("li"):
        text = clean(li.get_text())
        if not text or len(text) < 10:
            continue
        if any(w in text.lower() for w in (
            "cup", "teaspoon", "tablespoon", "ounce", "pound", "recipe", "photo", "view",
        )):
            continue
        if any(a in text.lower() for a in action_words):
            found.append(text)
    return found


def _fallback_time_servings(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    cooking_time = None
    servings = None
    for text_elem in soup.find_all(string=True):
        text = clean(str(text_elem))
        if not text:
            continue
        if "ready in:" in text.lower() and not cooking_time:
            m = re.search(r"ready in:\s*(\d+\s*mins?)", text, re.IGNORECASE)
            if m:
                cooking_time = m.group(1)
        if "serves:" in text.lower() and not servings:
            m = re.search(r"serves:\s*([0-9\-]+)", text, re.IGNORECASE)
            if m:
                servings = m.group(1)
    return cooking_time, servings


def _fallback_food_com_image(soup: BeautifulSoup) -> str | None:
    """Food.com-specific image search."""
    # Main recipe photo
    main_img = soup.find("img", attrs={"alt": lambda x: x and "photo by" in x.lower()})
    if main_img:
        src = main_img.get("src")
        if src and "sndimg.com" in src:
            if "w_960" in src:
                return src.replace("w_960", "w_1200")
            if "w_744" in src:
                return src.replace("w_744", "w_1200")
            return src

    for sel in (
        "img[src*='sndimg.com']",
        "img[src*='recipe']",
        "img[src*='food']",
        ".recipe-image img",
        "img[alt*='photo']",
    ):
        elem = soup.select_one(sel)
        if elem:
            src = elem.get("src") or elem.get("data-src")
            if src and ("sndimg.com" in src or "food.com" in src):
                return src
    return None


def scrape_food_com(soup: BeautifulSoup) -> dict:
    ld = extract_jsonld_recipe(soup)

    if not ld["title"]:
        ld["title"] = fallback_title(soup)
    if not ld["notes"]:
        ld["notes"] = _fallback_description(soup)
    if not ld["ingredients"]:
        ld["ingredients"] = _fallback_ingredients(soup)
    if not ld["instructions"]:
        ld["instructions"] = _fallback_instructions(soup)

    ct, sv = _fallback_time_servings(soup)
    if not ld["cooking_time"]:
        ld["cooking_time"] = ct
    if not ld["servings"]:
        ld["servings"] = sv

    if not ld["image_url"]:
        ld["image_url"] = fallback_image(soup) or _fallback_food_com_image(soup)

    return finalise_recipe(ld)
