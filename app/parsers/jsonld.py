"""Generic JSON-LD Recipe extractor.

Most recipe sites embed structured data in <script type="application/ld+json">
blocks.  This module provides a single function that extracts a normalised
recipe dict from any page that follows the schema.org/Recipe spec.
"""

from __future__ import annotations

import json
from bs4 import BeautifulSoup

from app.utils import clean, clean_ingredient_decimals, iso_duration_to_short, to_float


def _html_str_to_steps(html_str: str) -> list[str]:
    """Extract step texts from an HTML string (used by recipeInstructions)."""
    soup = BeautifulSoup(html_str, "html.parser")
    steps = [clean(li.get_text()) for li in soup.find_all("li") if clean(li.get_text())]
    if steps:
        return steps
    steps = [clean(p.get_text()) for p in soup.find_all("p") if clean(p.get_text())]
    if steps:
        return steps
    whole = clean(soup.get_text())
    return [whole] if whole else []


def _extract_instructions(inst) -> list[str]:
    """Normalise the many shapes recipeInstructions can take."""
    steps: list[str] = []
    if isinstance(inst, str):
        steps += _html_str_to_steps(inst)
    elif isinstance(inst, list):
        for it in inst:
            if isinstance(it, str):
                steps += _html_str_to_steps(it)
            elif isinstance(it, dict):
                txt = it.get("text") or it.get("name") or ""
                if txt:
                    steps += _html_str_to_steps(txt)
                # Handle HowToSection with nested steps
                if it.get("@type") == "HowToSection" and it.get("itemListElement"):
                    for sub in it["itemListElement"]:
                        if isinstance(sub, dict):
                            sub_txt = sub.get("text") or sub.get("name") or ""
                            if sub_txt:
                                steps += _html_str_to_steps(sub_txt)
    elif isinstance(inst, dict):
        steps += _html_str_to_steps(inst.get("text") or inst.get("name") or "")
    return steps


def _extract_image(img) -> str | None:
    """Normalise the image field (string, list, or ImageObject).

    When given a list of URLs, pick the last one — sites typically list
    thumbnails first and the full-size image last.
    """
    if isinstance(img, str):
        return img
    if isinstance(img, list) and img:
        # Pick the last (usually largest) image URL
        last = img[-1]
        if isinstance(last, str):
            return last
        if isinstance(last, dict):
            return last.get("url")
    if isinstance(img, dict):
        return img.get("url")
    return None


def empty_recipe() -> dict:
    """Return a recipe dict with all fields set to their empty defaults."""
    return {
        "title": None,
        "notes": None,
        "ingredients": [],
        "instructions": [],
        "cooking_time": None,
        "servings": None,
        "image_url": None,
        "rating": None,
    }


def extract_jsonld_recipe(soup: BeautifulSoup) -> dict:
    """Parse every JSON-LD block in *soup* and return the first Recipe found.

    Returns a recipe dict (see `empty_recipe`) with whatever fields were
    present in the structured data.  Fields that were absent remain ``None``
    (or empty list).
    """
    out = empty_recipe()

    for script in soup.find_all("script", type="application/ld+json"):
        txt = script.string or script.get_text()
        if not txt:
            continue
        try:
            data = json.loads(txt, strict=False)
        except (json.JSONDecodeError, ValueError):
            continue

        candidates: list[dict] = []
        if isinstance(data, dict):
            candidates.append(data)
            if "@graph" in data and isinstance(data["@graph"], list):
                candidates.extend(data["@graph"])
        elif isinstance(data, list):
            candidates.extend(data)

        for node in candidates:
            if not isinstance(node, dict):
                continue
            t = node.get("@type")
            types = [t] if isinstance(t, str) else (t or [])
            if not any(str(x).lower() == "recipe" for x in types):
                continue

            # --- populate fields from the first Recipe node ---
            out["title"] = out["title"] or clean(node.get("name"))
            out["notes"] = out["notes"] or clean(node.get("description"))

            out["image_url"] = out["image_url"] or _extract_image(node.get("image"))

            ings = node.get("recipeIngredient") or node.get("ingredients")
            if ings and not out["ingredients"]:
                if isinstance(ings, list):
                    out["ingredients"] = [
                        clean_ingredient_decimals(clean(i))
                        for i in ings
                        if clean(i)
                    ]
                else:
                    val = clean_ingredient_decimals(clean(str(ings)))
                    if val:
                        out["ingredients"] = [val]

            inst = node.get("recipeInstructions")
            if inst and not out["instructions"]:
                out["instructions"] = _extract_instructions(inst)

            total = node.get("totalTime") or node.get("cookTime") or node.get("prepTime")
            if total and not out["cooking_time"]:
                out["cooking_time"] = iso_duration_to_short(clean(total))

            ry = node.get("recipeYield")
            if ry and not out["servings"]:
                if isinstance(ry, list):
                    # Pick the most descriptive entry (e.g. "4 servings" over "4")
                    candidates = [clean(str(x)) for x in ry if clean(str(x))]
                    out["servings"] = max(candidates, key=len) if candidates else None
                else:
                    out["servings"] = clean(str(ry))

            agg = node.get("aggregateRating")
            if isinstance(agg, dict) and out["rating"] is None:
                out["rating"] = to_float(agg.get("ratingValue"))

            return out  # first Recipe node is enough

    return out
