"""Recipe quality validation and article detection."""

from __future__ import annotations

from bs4 import BeautifulSoup


def is_article_not_recipe(soup: BeautifulSoup, recipe_data: dict) -> bool:
    """Return True if the page looks like an article/review rather than a recipe."""
    title = recipe_data.get("title", "").lower()

    article_indicators = (
        "i tried", "we tried", "tested", "review", "compared", "ranking",
        "best of", "top ", "most popular", "taste test", "which is better",
        "vs", "versus", "battle", "showdown", "ultimate guide",
    )
    if any(ind in title for ind in article_indicators):
        return True

    ingredients = recipe_data.get("ingredients", [])
    article_ingredient_markers = (
        "average rating:", "stars", "by ", "recipe by", "sandwich by",
        "classic", "legendary", "make lunch", "dinners", "meals",
    )
    article_like = 0
    for ing in ingredients:
        low = ing.lower()
        if any(m in low for m in article_ingredient_markers):
            article_like += 1
        if len(ing) > 100:
            article_like += 1
    if ingredients and article_like / len(ingredients) > 0.5:
        return True

    if not recipe_data.get("instructions"):
        return True

    return False
