"""AllRecipes.com scraper."""

from __future__ import annotations

import re
from bs4 import BeautifulSoup

from app.utils import clean
from app.parsers.jsonld import extract_jsonld_recipe
from app.parsers.base import fallback_title, fallback_image, fallback_rating, finalise_recipe


def _fallback_ingredients(soup: BeautifulSoup) -> list[str]:
    """HTML fallback: scan list items for ingredient-like text."""
    selectors = [
        ".mntl-structured-ingredients__list-item",
        ".recipe-ingredients li",
        ".ingredients-section li",
        "ul li",
    ]
    for selector in selectors:
        items = soup.select(selector)
        found = []
        for item in items:
            text = clean(item.get_text())
            if not text or len(text) < 3:
                continue
            if any(w in text.lower() for w in (
                "recipe", "photo", "view", "more", "sign", "follow",
                "advertisement", "navigation", "menu", "search", "subscribe", "newsletter",
            )):
                continue
            has_measure = any(w in text.lower() for w in (
                "cup", "cups", "teaspoon", "tablespoon", "pound", "ounce",
                "gram", "ml", "tsp", "tbsp", "lb", "oz", "clove", "slice",
                "piece", "inch", "½", "¼", "¾", "1/2", "1/4", "3/4",
                "large", "medium", "small", "pinch", "dash",
            ))
            has_number = bool(re.search(r"[\d¼½¾⅓⅔⅛⅜⅝⅞]", text))
            has_food = any(w in text.lower() for w in (
                "flour", "sugar", "salt", "pepper", "oil", "butter", "milk",
                "egg", "vanilla", "cinnamon", "bread", "cheese", "onion", "garlic", "water",
            ))
            if has_measure or has_number or has_food:
                found.append(text)
        if len(found) >= 3:
            return found
    return []


def _fallback_instructions(soup: BeautifulSoup) -> list[str]:
    """HTML fallback: scan ordered-list items for instruction-like text."""
    selectors = [
        ".mntl-sc-block-group--OL li",
        ".recipe-instructions li",
        ".instructions-section li",
        ".directions li",
        "ol li",
    ]
    action_words = (
        "heat", "cook", "bake", "mix", "stir", "add", "combine", "place",
        "pour", "cover", "simmer", "boil", "fry", "saute", "preheat", "spray",
        "season", "whisk", "blend", "chop", "slice", "dice", "melt", "serve",
        "remove", "gather", "measure", "soak", "working", "coat",
    )
    for selector in selectors:
        items = soup.select(selector)
        found = []
        for item in items:
            text = clean(item.get_text())
            if not text or len(text) < 10:
                continue
            if any(w in text.lower() for w in (
                "cup", "teaspoon", "tablespoon", "ounce", "pound",
                "recipe", "photo", "view", "navigation", "menu",
                "advertisement", "subscribe",
            )):
                continue
            if any(a in text.lower() for a in action_words):
                found.append(text)
        if len(found) >= 2:
            return found
    return []


def _fallback_description(soup: BeautifulSoup) -> str:
    """AllRecipes-specific description heuristic."""
    selectors = [
        "p.article-subheading",
        ".recipe-summary p",
        ".entry-content p:first-of-type",
        "div[data-module='RecipeSummary'] p",
        ".recipe-description",
        ".recipe-intro p",
    ]
    for sel in selectors:
        tag = soup.select_one(sel)
        if tag:
            return clean(tag.get_text())

    # Heuristic: first paragraph that looks like a description
    for p in soup.find_all("p"):
        text = clean(p.get_text())
        if not text or len(text) <= 50:
            continue
        skip = ("photo", "credit", "advertisement", "subscribe", "newsletter",
                "follow", "save", "print", "share", "rate", "review", "comment")
        if any(s in text.lower() for s in skip):
            continue
        keywords = ("recipe", "dish", "delicious", "flavor", "taste", "cook",
                    "make", "best", "perfect", "easy", "simple", "ingredients",
                    "this", "it's", "you'll")
        if any(k in text.lower() for k in keywords):
            return text
    return ""


def _fallback_time_servings(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Extract timing / servings from AllRecipes detail sections."""
    cooking_time = None
    servings = None

    for selector in (
        ".mm-recipes-details__item",
        ".recipe-details-item",
        ".mntl-recipe-details__item",
    ):
        for item in soup.select(selector):
            label_elem = item.find(class_=lambda c: c and "label" in c)
            value_elem = item.find(class_=lambda c: c and "value" in c)
            if not label_elem or not value_elem:
                continue
            label = clean(label_elem.get_text()).lower()
            value = clean(value_elem.get_text())
            if "servings" in label or "yield" in label:
                servings = servings or value
            elif "total time" in label or "cook time" in label:
                cooking_time = cooking_time or value

    return cooking_time, servings


def _fallback_allrecipes_image(soup: BeautifulSoup) -> str | None:
    """AllRecipes-specific image selectors."""
    selectors = [
        "img.primary-image",
        "img[data-src*='recipe']",
        ".recipe-image img",
        ".hero-image img",
        "img[src*='allrecipes']",
    ]
    for sel in selectors:
        elem = soup.select_one(sel)
        if elem:
            src = elem.get("src") or elem.get("data-src")
            if src:
                if "allrecipes.com" in src and "/filters:" in src:
                    base = src.split("/filters:")[0]
                    return base or src
                return src
    return None


def scrape_allrecipes(soup: BeautifulSoup) -> dict:
    ld = extract_jsonld_recipe(soup)

    # HTML fallbacks for anything JSON-LD missed
    if not ld["title"] or ld["title"] == "Untitled":
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
        ld["image_url"] = fallback_image(soup) or _fallback_allrecipes_image(soup)
    if ld["rating"] is None:
        ld["rating"] = fallback_rating(soup)

    return finalise_recipe(ld)
