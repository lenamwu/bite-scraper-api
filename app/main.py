from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from bs4 import BeautifulSoup
import requests, json, re
from urllib.parse import urlparse

app = FastAPI()

class RecipeRequest(BaseModel):
    url: str

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()

def _best_from_srcset(srcset):
    if not srcset:
        return None
    items = []
    for part in srcset.split(","):
        seg = part.strip().split()
        if not seg:
            continue
        url = seg[0]
        w = 0
        if len(seg) > 1 and seg[1].endswith("w"):
            try:
                w = int(seg[1][:-1])
            except:
                w = 0
        items.append((w, url))
    if not items:
        return None
    items.sort(key=lambda x: x[0], reverse=True)
    return items[0][1]

def _to_float(txt) -> float | None:
    if txt is None:
        return None
    try:
        # keep only first number like 4.7, 4, 4,200 etc.
        m = re.search(r"(\d+(?:[.,]\d+)?)", str(txt))
        if not m:
            return None
        return float(m.group(1).replace(",", "."))
    except:
        return None

# ---------------- AllRecipes (rewritten from scratch) ----------------
def scrape_allrecipes(soup: BeautifulSoup) -> dict:
    # Initialize return values
    title = "Untitled"
    notes = ""
    ingredients = []
    instructions = []
    cooking_time = None
    servings = None
    image_url = None
    rating = None

    # Extract title - look for h1 tag
    title_tag = soup.find("h1")
    if title_tag:
        title = clean(title_tag.get_text())

    # Extract description/notes - look for recipe description
    desc_selectors = [
        "p.article-subheading",
        ".recipe-summary p",
        ".entry-content p:first-of-type",
        "div[data-module='RecipeSummary'] p"
    ]
    for selector in desc_selectors:
        desc_tag = soup.select_one(selector)
        if desc_tag:
            notes = clean(desc_tag.get_text())
            break

    # Try JSON-LD first for ingredients (most reliable)
    try:
        for script in soup.find_all("script", type="application/ld+json"):
            script_text = script.string or script.get_text()
            if not script_text:
                continue
            
            try:
                data = json.loads(script_text)
                candidates = []
                
                if isinstance(data, dict):
                    candidates.append(data)
                    if "@graph" in data and isinstance(data["@graph"], list):
                        candidates.extend(data["@graph"])
                elif isinstance(data, list):
                    candidates.extend(data)
                
                for item in candidates:
                    if not isinstance(item, dict):
                        continue
                    
                    item_type = item.get("@type")
                    types = [item_type] if isinstance(item_type, str) else (item_type or [])
                    
                    if any(str(t).lower() == "recipe" for t in types):
                        recipe_ingredients = item.get("recipeIngredient", [])
                        if recipe_ingredients:
                            ingredients = [clean(ing) for ing in recipe_ingredients if clean(ing)]
                            break
                
                if ingredients:
                    break
            except json.JSONDecodeError:
                continue
    except Exception:
        pass

    # If JSON-LD didn't work, try HTML extraction with very specific targeting
    if not ingredients:
        # Look for lists that contain ingredient-like items (with measurements)
        all_lists = soup.find_all("ul")
        for ul in all_lists:
            # Skip navigation and menu lists by checking classes and parent context
            ul_classes = " ".join(ul.get("class", [])).lower()
            ul_parent_classes = " ".join(ul.parent.get("class", [])).lower() if ul.parent else ""
            ul_context = (ul_classes + " " + ul_parent_classes)
            
            # Skip obvious navigation/menu elements
            if any(skip_word in ul_context for skip_word in 
                   ["nav", "menu", "header", "footer", "sidebar", "breadcrumb", "dropdown", "global", "primary"]):
                continue
            
            list_items = ul.find_all("li")
            if len(list_items) < 2:  # Need at least 2 items
                continue
                
            # Check if this list contains ingredient-like items
            ingredient_like_count = 0
            potential_ingredients = []
            navigation_words = {"chicken", "beef", "pork", "seafood", "pasta", "fruits", "vegetables", "view all", "recipes", "browse", "categories", "appetizers", "desserts", "main dishes"}
            
            for item in list_items:
                text = clean(item.get_text())
                if not text or len(text) < 3:
                    continue
                
                # Skip obvious navigation items
                if text.lower() in navigation_words:
                    continue
                
                # Check if it looks like an ingredient
                has_measurement = any(word in text.lower() for word in 
                    ["cup", "cups", "teaspoon", "teaspoons", "tablespoon", "tablespoons", 
                     "pound", "pounds", "ounce", "ounces", "gram", "grams", "ml", "liter", 
                     "tsp", "tbsp", "lb", "lbs", "oz", "clove", "cloves", "slice", "slices", 
                     "piece", "pieces", "inch", "inches", "½", "¼", "¾", "1/2", "1/4", "3/4"])
                
                has_number = bool(re.search(r'\d', text))
                
                if has_measurement or has_number:
                    ingredient_like_count += 1
                    potential_ingredients.append(text)
                elif len(potential_ingredients) == 0:  # First item might not have measurement
                    potential_ingredients.append(text)
            
            # If most items look like ingredients, use this list
            if ingredient_like_count >= 2 and ingredient_like_count >= len(list_items) * 0.5:
                ingredients = potential_ingredients
                break

    # Extract instructions - look for instruction steps
    instruction_selectors = [
        "li[data-instruction] p",
        "ol.comp.mntl-sc-block-group--OL li p",
        ".recipe-instructions li p",
        ".instructions-section li p"
    ]
    
    for selector in instruction_selectors:
        instruction_items = soup.select(selector)
        if instruction_items:
            for item in instruction_items:
                step_text = clean(item.get_text())
                
                # Filter out photo credits and attribution text
                if step_text and not any(credit in step_text.lower() for credit in [
                    "allrecipes /", "dotdash meredith", "food studios", 
                    "photo by", "credit:", "image by", "© "
                ]):
                    instructions.append(step_text)
            break

    # Extract timing and servings information
    # Look for recipe details section
    detail_selectors = [
        ".mm-recipes-details__item",
        ".recipe-details-item",
        ".mntl-recipe-details__item"
    ]
    
    for selector in detail_selectors:
        detail_items = soup.select(selector)
        for item in detail_items:
            label_elem = item.find(class_=lambda c: c and "label" in c)
            value_elem = item.find(class_=lambda c: c and "value" in c)
            
            if label_elem and value_elem:
                label_text = clean(label_elem.get_text()).lower()
                value_text = clean(value_elem.get_text())
                
                if "servings" in label_text or "yield" in label_text:
                    servings = value_text
                elif "total time" in label_text or "cook time" in label_text:
                    cooking_time = value_text

    # Alternative timing extraction from structured data
    if not cooking_time or not servings:
        time_elements = soup.select("[class*='time'], [class*='serving'], [class*='yield']")
        for elem in time_elements:
            text = clean(elem.get_text())
            if text:
                if any(word in text.lower() for word in ["min", "hour", "hr"]) and not cooking_time:
                    cooking_time = text
                elif any(word in text.lower() for word in ["serving", "yield"]) and not servings:
                    servings = text

    # Extract image URL
    # Try og:image first
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        image_url = og_image["content"]
    else:
        # Look for recipe image
        img_selectors = [
            "img.primary-image",
            "img[data-src*='recipe']",
            ".recipe-image img",
            ".hero-image img"
        ]
        for selector in img_selectors:
            img_elem = soup.select_one(selector)
            if img_elem:
                image_url = img_elem.get("src") or img_elem.get("data-src")
                break

    # Extract rating - try JSON-LD first, then HTML fallback
    try:
        for script in soup.find_all("script", type="application/ld+json"):
            script_text = script.string or script.get_text()
            if not script_text:
                continue
            
            try:
                data = json.loads(script_text)
                candidates = []
                
                if isinstance(data, dict):
                    candidates.append(data)
                    if "@graph" in data and isinstance(data["@graph"], list):
                        candidates.extend(data["@graph"])
                elif isinstance(data, list):
                    candidates.extend(data)
                
                for item in candidates:
                    if not isinstance(item, dict):
                        continue
                    
                    item_type = item.get("@type")
                    types = [item_type] if isinstance(item_type, str) else (item_type or [])
                    
                    if any(str(t).lower() == "recipe" for t in types):
                        agg_rating = item.get("aggregateRating")
                        if isinstance(agg_rating, dict):
                            rating_value = agg_rating.get("ratingValue")
                            if rating_value:
                                rating = _to_float(rating_value)
                                break
                
                if rating:
                    break
            except json.JSONDecodeError:
                continue
    except Exception:
        pass

    # HTML rating fallback
    if rating is None:
        rating_selectors = [
            ".mm-recipes-review-bar__rating",
            ".recipe-rating .rating-value",
            "[class*='rating'] [class*='value']"
        ]
        for selector in rating_selectors:
            rating_elem = soup.select_one(selector)
            if rating_elem:
                rating = _to_float(rating_elem.get_text())
                if rating:
                    break

    return {
        "title": title,
        "notes": notes,
        "ingredients": ingredients,
        "instructions": instructions,
        "cooking_time": cooking_time,
        "servings": servings or "servings not specified",
        "image_url": image_url,
        "rating": rating,
    }

# ---------------- FoodNetwork UK ----------------
def _html_str_to_steps(html_str: str):
    soup = BeautifulSoup(html_str, "html.parser")
    steps = [clean(li.get_text()) for li in soup.find_all("li") if clean(li.get_text())]
    if steps:
        return steps
    steps = [clean(p.get_text()) for p in soup.find_all("p") if clean(p.get_text())]
    if steps:
        return steps
    whole = clean(soup.get_text())
    return [whole] if whole else []

def _parse_fnuk_jsonld(soup: BeautifulSoup) -> dict:
    out = {
        "title": None, "notes": None, "ingredients": [], "instructions": [],
        "cooking_time": None, "servings": None, "image_url": None, "rating": None
    }
    scripts = soup.find_all("script", type="application/ld+json")
    for sc in scripts:
        txt = sc.string or sc.get_text()
        if not txt:
            continue
        try:
            data = json.loads(txt)
        except Exception:
            continue
        candidates = []
        if isinstance(data, dict):
            candidates.append(data)
            if "@graph" in data and isinstance(data["@graph"], list):
                candidates += data["@graph"]
        elif isinstance(data, list):
            candidates += data
        for node in candidates:
            if not isinstance(node, dict):
                continue
            t = node.get("@type")
            types = [t] if isinstance(t, str) else (t or [])
            if not any(str(x).lower() == "recipe" for x in types):
                continue

            out["title"] = out["title"] or clean(node.get("name"))
            out["notes"] = out["notes"] or clean(node.get("description"))

            img = node.get("image")
            if isinstance(img, str):
                out["image_url"] = out["image_url"] or img
            elif isinstance(img, list) and img:
                out["image_url"] = out["image_url"] or img[0]
            elif isinstance(img, dict):
                out["image_url"] = out["image_url"] or img.get("url")

            ings = node.get("recipeIngredient") or node.get("ingredients")
            if ings:
                out["ingredients"] = [clean(i) for i in (ings if isinstance(ings, list) else [ings]) if clean(i)]

            inst = node.get("recipeInstructions")
            steps = []
            if isinstance(inst, str):
                steps += _html_str_to_steps(inst)
            elif isinstance(inst, list):
                for it in inst:
                    if isinstance(it, str):
                        steps += _html_str_to_steps(it)
                    elif isinstance(it, dict):
                        txt2 = it.get("text") or it.get("name") or ""
                        steps += _html_str_to_steps(txt2)
                        if it.get("@type") == "HowToSection" and it.get("itemListElement"):
                            for sub in it["itemListElement"]:
                                if isinstance(sub, dict):
                                    txt3 = sub.get("text") or sub.get("name") or ""
                                    steps += _html_str_to_steps(txt3)
            elif isinstance(inst, dict):
                steps += _html_str_to_steps(inst.get("text") or inst.get("name") or "")
            
            # Filter out copyright and attribution text from Food Network
            filtered_steps = []
            for step in steps:
                if step and not any(copyright_text in step.lower() for copyright_text in [
                    "copyright", "television food network", "all rights reserved", 
                    "from food network kitchen", "food network, g.p."
                ]):
                    filtered_steps.append(step)
            
            out["instructions"] = out["instructions"] or filtered_steps

            total = node.get("totalTime") or node.get("cookTime") or node.get("prepTime")
            if total:
                out["cooking_time"] = out["cooking_time"] or clean(total)

            ry = node.get("recipeYield")
            if isinstance(ry, list):
                ry = " ".join([clean(x) for x in ry if clean(x)])
            if ry:
                out["servings"] = out["servings"] or clean(str(ry))

            # ⭐ rating from JSON-LD
            agg = node.get("aggregateRating")
            if isinstance(agg, dict):
                out["rating"] = _to_float(agg.get("ratingValue"))

            return out  # first Recipe is enough
    return out

def iso_duration_to_short(s: str | None) -> str | None:
    if not s:
        return None
    m = re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', s.strip(), re.I)
    if not m:
        m = re.fullmatch(r'P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', s.strip(), re.I)
    if not m:
        return s  # return as-is if unknown format
    d, h, mnt, sec = m.groups() if m.lastindex == 4 else (None, m.group(1), m.group(2), m.group(3))
    total_min = 0
    if d: total_min += int(d) * 24 * 60
    if h: total_min += int(h) * 60
    if mnt: total_min += int(mnt)
    if sec and not total_min:
        total_min = 1
    if total_min >= 60:
        hrs = total_min // 60
        mins = total_min % 60
        return f"{hrs} HR {mins} MINS" if mins else f"{hrs} HRS"
    return f"{total_min} MINS"

def _fnuk_html_fallbacks(soup: BeautifulSoup, raw_html: str) -> dict:
    # Title / notes / image from HTML
    title = None
    h1 = soup.find("h1", class_=lambda c: c and "p-name" in c)
    if h1:
        title = clean(h1.get_text())
    notes = None
    notes_tag = soup.find("p", class_=lambda c: c and "p-summary" in c)
    if notes_tag:
        notes = clean(notes_tag.get_text())

    image_url = None
    img = soup.find("img", class_=lambda c: c and "u-photo" in c)
    if img:
        image_url = _best_from_srcset(img.get("srcset")) or img.get("src")
    if not image_url:
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            image_url = og["content"]

    # Time/servings from visible HTML
    cooking_time = None
    time_tag = soup.find("span", class_=lambda c: c and "dt-duration" in c)
    if time_tag:
        cooking_time = clean(time_tag.get_text())  # e.g., "15 MINS"

    servings = None
    yield_tag = soup.find("span", class_=lambda c: c and "p-yield" in c)
    if yield_tag:
        servings = clean(yield_tag.get_text())

    # If not found, look inside raw HTML (script JSON)
    if not cooking_time:
        m = re.search(r'"total_time_formatted_short"\s*:\s*"([^"]+)"', raw_html)
        if m:
            cooking_time = clean(m.group(1))
    if not servings:
        m2 = re.search(r'"servings"\s*:\s*([0-9]+)', raw_html)
        if m2:
            servings = m2.group(1)

    rating = None

    # 1) Try schema-ish
    rv = soup.select_one('[itemprop="ratingValue"]')
    if rv:
        rating = _to_float(rv.get_text() or rv.get("content"))

    # 2) Try exact Tailwind class combo (need to escape brackets)
    if rating is None:
        cand = soup.select_one('div.font-\\[700\\].text-\\[14px\\].text-white')
        if cand:
            val = _to_float(cand.get_text())
            if val is not None and 0 < val <= 5:
                rating = val

    # 3) Broader fallback: any div with class "font-[700]" (regex),
    #    keep the first number that looks like a 0–5 rating.
    if rating is None:
        for div in soup.find_all('div', class_=re.compile(r'(^|\s)font-\[700\](\s|$)')):
            val = _to_float(div.get_text())
            if val is not None and 0 < val <= 5:
                rating = val
                break

    return {
        "title": title or None,
        "notes": notes or None,
        "ingredients": [],      # JSON-LD will fill these
        "instructions": [],     # JSON-LD will fill these
        "cooking_time": cooking_time or None,
        "servings": servings or "servings not specified",
        "image_url": image_url or None,
        "rating": rating,
    }

def scrape_foodnetwork_uk(soup: BeautifulSoup, raw_html: str) -> dict:
    ld   = _parse_fnuk_jsonld(soup)               # ingredients/instructions/time (ISO) and rating if present
    html = _fnuk_html_fallbacks(soup, raw_html)   # title/notes/image/time(short)/servings and rating fallback

    cooking_time = html["cooking_time"] or iso_duration_to_short(ld["cooking_time"])
    rating = ld["rating"] if ld["rating"] is not None else html["rating"]

    return {
        "title": html["title"] or ld["title"] or "Untitled",
        "notes": html["notes"] or ld["notes"] or "",
        "ingredients": ld["ingredients"] or [],
        "instructions": ld["instructions"] or [],
        "cooking_time": cooking_time,
        "servings": html["servings"] or ld["servings"] or "servings not specified",
        "image_url": html["image_url"] or ld["image_url"],
        "rating": rating,
    }

# ---------------- The Table of Spice ----------------
def scrape_tableofspice(soup: BeautifulSoup) -> dict:
    title = None
    notes = None
    ingredients = []
    instructions = []
    cooking_time = None
    servings = None
    image_url = None
    rating = None

    # Try JSON-LD first for structured data
    try:
        for script in soup.find_all("script", type="application/ld+json"):
            txt = script.string or script.get_text()
            if not txt:
                continue
            data = json.loads(txt)
            
            # Handle both single objects and arrays
            candidates = []
            if isinstance(data, dict):
                candidates.append(data)
                if "@graph" in data and isinstance(data["@graph"], list):
                    candidates += data["@graph"]
            elif isinstance(data, list):
                candidates += data
            
            for node in candidates:
                if not isinstance(node, dict):
                    continue
                
                node_type = node.get("@type")
                types = [node_type] if isinstance(node_type, str) else (node_type or [])
                
                if not any(str(t).lower() == "recipe" for t in types):
                    continue
                
                # Extract data from JSON-LD
                title = title or clean(node.get("name"))
                notes = notes or clean(node.get("description"))
                
                # Image
                img = node.get("image")
                if isinstance(img, str):
                    image_url = image_url or img
                elif isinstance(img, list) and img:
                    image_url = image_url or img[0]
                elif isinstance(img, dict):
                    image_url = image_url or img.get("url")
                
                # Ingredients
                recipe_ingredients = node.get("recipeIngredient", [])
                if recipe_ingredients and not ingredients:
                    ingredients = [clean(ing) for ing in recipe_ingredients if clean(ing)]
                
                # Instructions
                recipe_instructions = node.get("recipeInstructions", [])
                if recipe_instructions and not instructions:
                    for inst in recipe_instructions:
                        if isinstance(inst, str):
                            instructions.append(clean(inst))
                        elif isinstance(inst, dict):
                            text = inst.get("text") or inst.get("name") or ""
                            if text:
                                instructions.append(clean(text))
                
                # Times
                total_time = node.get("totalTime")
                prep_time = node.get("prepTime") 
                cook_time = node.get("cookTime")
                
                if total_time:
                    cooking_time = cooking_time or iso_duration_to_short(total_time)
                elif cook_time:
                    cooking_time = cooking_time or iso_duration_to_short(cook_time)
                elif prep_time:
                    cooking_time = cooking_time or iso_duration_to_short(prep_time)
                
                # Servings/Yield
                recipe_yield = node.get("recipeYield")
                if recipe_yield:
                    if isinstance(recipe_yield, list):
                        servings = servings or " ".join([clean(str(y)) for y in recipe_yield if clean(str(y))])
                    else:
                        servings = servings or clean(str(recipe_yield))
                
                # Rating
                agg_rating = node.get("aggregateRating")
                if isinstance(agg_rating, dict) and not rating:
                    rating = _to_float(agg_rating.get("ratingValue"))
                
                break  # Use first recipe found
    except Exception:
        pass
    
    # HTML fallbacks if JSON-LD didn't provide everything
    if not title:
        title_tag = soup.find("h1")
        if title_tag:
            title = clean(title_tag.get_text())
    
    if not notes:
        # Look for recipe description/summary
        desc_selectors = [
            "p.recipe-summary",
            ".recipe-description p",
            "div.entry-content p:first-of-type"
        ]
        for selector in desc_selectors:
            desc_tag = soup.select_one(selector)
            if desc_tag:
                notes = clean(desc_tag.get_text())
                break
    
    if not image_url:
        # Try og:image
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            image_url = og_img["content"]
        else:
            # Try to find recipe image
            img_tag = soup.find("img", class_=lambda c: c and ("recipe" in c.lower() or "featured" in c.lower()))
            if img_tag:
                image_url = img_tag.get("src") or img_tag.get("data-src")
    
    # Look for time information in HTML if not found in JSON-LD
    if not cooking_time:
        time_selectors = [
            ".recipe-time",
            ".total-time",
            ".cook-time",
            "[class*='time']"
        ]
        for selector in time_selectors:
            time_elem = soup.select_one(selector)
            if time_elem:
                time_text = clean(time_elem.get_text())
                if time_text and any(word in time_text.lower() for word in ["min", "hour", "hr"]):
                    cooking_time = time_text
                    break
    
    # Look for servings in HTML if not found in JSON-LD
    if not servings:
        serving_selectors = [
            ".recipe-yield",
            ".servings",
            "[class*='yield']",
            "[class*='serving']"
        ]
        for selector in serving_selectors:
            serving_elem = soup.select_one(selector)
            if serving_elem:
                serving_text = clean(serving_elem.get_text())
                if serving_text:
                    servings = serving_text
                    break

    return {
        "title": title or "Untitled",
        "notes": notes or "",
        "ingredients": ingredients,
        "instructions": instructions,
        "cooking_time": cooking_time,
        "servings": servings or "servings not specified",
        "image_url": image_url,
        "rating": rating,
    }

# ---------------- Food.com ----------------
def scrape_food_com(soup: BeautifulSoup) -> dict:
    title = "Untitled"
    notes = ""
    ingredients = []
    instructions = []
    cooking_time = None
    servings = None
    image_url = None
    rating = None

    # Extract title
    title_tag = soup.find("h1")
    if title_tag:
        title = clean(title_tag.get_text())

    # Extract description/notes - look for the recipe description
    # Food.com typically has the description in quotes after the submitter info
    desc_selectors = [
        'p:contains(")")',  # Look for description in quotes
        '.recipe-description',
        '.recipe-summary'
    ]
    
    # Try to find description text in quotes
    for p_tag in soup.find_all("p"):
        text = clean(p_tag.get_text())
        if text and text.startswith('"') and text.endswith('"') and len(text) > 20:
            notes = text.strip('"')
            break
    
    if not notes:
        # Fallback to other selectors
        for selector in desc_selectors:
            desc_tag = soup.select_one(selector)
            if desc_tag:
                notes = clean(desc_tag.get_text())
                break

    # Try JSON-LD first for structured data
    try:
        for script in soup.find_all("script", type="application/ld+json"):
            script_text = script.string or script.get_text()
            if not script_text:
                continue
            
            try:
                data = json.loads(script_text)
                candidates = []
                
                if isinstance(data, dict):
                    candidates.append(data)
                    if "@graph" in data and isinstance(data["@graph"], list):
                        candidates.extend(data["@graph"])
                elif isinstance(data, list):
                    candidates.extend(data)
                
                for item in candidates:
                    if not isinstance(item, dict):
                        continue
                    
                    item_type = item.get("@type")
                    types = [item_type] if isinstance(item_type, str) else (item_type or [])
                    
                    if any(str(t).lower() == "recipe" for t in types):
                        # Extract from JSON-LD
                        if not title or title == "Untitled":
                            title = clean(item.get("name")) or title
                        
                        if not notes:
                            notes = clean(item.get("description")) or notes
                        
                        # Ingredients
                        recipe_ingredients = item.get("recipeIngredient", [])
                        if recipe_ingredients and not ingredients:
                            ingredients = [clean(ing) for ing in recipe_ingredients if clean(ing)]
                        
                        # Instructions
                        recipe_instructions = item.get("recipeInstructions", [])
                        if recipe_instructions and not instructions:
                            for inst in recipe_instructions:
                                if isinstance(inst, str):
                                    instructions.append(clean(inst))
                                elif isinstance(inst, dict):
                                    text = inst.get("text") or inst.get("name") or ""
                                    if text:
                                        instructions.append(clean(text))
                        
                        # Image
                        img = item.get("image")
                        if isinstance(img, str):
                            image_url = image_url or img
                        elif isinstance(img, list) and img:
                            image_url = image_url or img[0]
                        elif isinstance(img, dict):
                            image_url = image_url or img.get("url")
                        
                        # Times
                        total_time = item.get("totalTime")
                        if total_time:
                            cooking_time = cooking_time or iso_duration_to_short(total_time)
                        
                        # Servings
                        recipe_yield = item.get("recipeYield")
                        if recipe_yield:
                            if isinstance(recipe_yield, list):
                                servings = servings or " ".join([clean(str(y)) for y in recipe_yield if clean(str(y))])
                            else:
                                servings = servings or clean(str(recipe_yield))
                        
                        # Rating
                        agg_rating = item.get("aggregateRating")
                        if isinstance(agg_rating, dict) and not rating:
                            rating = _to_float(agg_rating.get("ratingValue"))
                        
                        break  # Use first recipe found
            except json.JSONDecodeError:
                continue
    except Exception:
        pass

    # HTML fallbacks if JSON-LD didn't provide everything
    if not ingredients:
        # Look for ingredients list - Food.com uses a specific structure
        ingredient_items = soup.select("li")
        potential_ingredients = []
        
        for li in ingredient_items:
            text = clean(li.get_text())
            if not text or len(text) < 3:
                continue
            
            # Skip navigation and non-ingredient items
            if any(skip_word in text.lower() for skip_word in 
                   ["recipe", "photo", "view", "more", "sign", "follow", "advertisement"]):
                continue
            
            # Look for measurement indicators or food items
            has_measurement = any(word in text.lower() for word in 
                ["cup", "cups", "teaspoon", "teaspoons", "tablespoon", "tablespoons", 
                 "pound", "pounds", "ounce", "ounces", "gram", "grams", "ml", "liter", 
                 "tsp", "tbsp", "lb", "lbs", "oz", "clove", "cloves", "slice", "slices", 
                 "piece", "pieces", "inch", "inches", "½", "¼", "¾", "1/2", "1/4", "3/4",
                 "can", "package", "frozen", "fresh"])
            
            has_number = bool(re.search(r'\d', text))
            
            # Food.com specific patterns
            has_food_link = li.find("a", href=lambda x: x and "/about/" in x)
            
            if has_measurement or has_number or has_food_link:
                potential_ingredients.append(text)
        
        # If we found a reasonable number of ingredients, use them
        if len(potential_ingredients) >= 3:
            ingredients = potential_ingredients

    # Extract instructions if not found in JSON-LD
    if not instructions:
        # Look for directions/instructions
        instruction_items = soup.select("li")
        potential_instructions = []
        
        for li in instruction_items:
            text = clean(li.get_text())
            if not text or len(text) < 10:  # Instructions should be longer
                continue
            
            # Skip ingredient-like items and navigation
            if any(skip_word in text.lower() for skip_word in 
                   ["cup", "teaspoon", "tablespoon", "ounce", "pound", "recipe", "photo", "view"]):
                continue
            
            # Look for instruction-like content
            if any(action in text.lower() for action in 
                   ["heat", "cook", "bake", "mix", "stir", "add", "combine", "place", "pour", 
                    "cover", "simmer", "boil", "fry", "saute", "preheat", "spray", "season"]):
                potential_instructions.append(text)
        
        if potential_instructions:
            instructions = potential_instructions

    # Extract timing and servings from visible text
    if not cooking_time or not servings:
        # Look for "Ready In:" and "Serves:" information
        for text_elem in soup.find_all(text=True):
            text = clean(str(text_elem))
            if not text:
                continue
            
            if "ready in:" in text.lower() and not cooking_time:
                # Extract time after "Ready In:"
                time_match = re.search(r'ready in:\s*(\d+\s*mins?)', text, re.IGNORECASE)
                if time_match:
                    cooking_time = time_match.group(1)
            
            if "serves:" in text.lower() and not servings:
                # Extract servings after "Serves:"
                serves_match = re.search(r'serves:\s*([0-9\-]+)', text, re.IGNORECASE)
                if serves_match:
                    servings = serves_match.group(1)

    # Extract image URL if not found
    if not image_url:
        # Try og:image first (usually the most accessible)
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            image_url = og_image["content"]
        
        # If no og:image, try twitter:image
        if not image_url:
            twitter_image = soup.find("meta", attrs={"name": "twitter:image"})
            if twitter_image and twitter_image.get("content"):
                image_url = twitter_image["content"]
        
        # Look for the main recipe photo - Food.com has specific patterns
        if not image_url:
            # Try to find the main recipe image with higher resolution
            main_img = soup.find("img", attrs={"alt": lambda x: x and "photo by" in x.lower()})
            if main_img:
                src = main_img.get("src")
                if src and "sndimg.com" in src:
                    # Try to get a higher resolution version by modifying the URL
                    if "w_960" in src:
                        image_url = src.replace("w_960", "w_1200")
                    elif "w_744" in src:
                        image_url = src.replace("w_744", "w_1200")
                    else:
                        image_url = src
        
        # Fallback to any food.com image
        if not image_url:
            img_selectors = [
                "img[src*='sndimg.com']",  # Food.com's CDN
                "img[src*='recipe']",
                "img[src*='food']",
                ".recipe-image img",
                "img[alt*='photo']"
            ]
            for selector in img_selectors:
                img_elem = soup.select_one(selector)
                if img_elem:
                    src = img_elem.get("src") or img_elem.get("data-src")
                    if src and ("sndimg.com" in src or "food.com" in src):
                        image_url = src
                        break

    return {
        "title": title,
        "notes": notes,
        "ingredients": ingredients,
        "instructions": instructions,
        "cooking_time": cooking_time,
        "servings": servings or "servings not specified",
        "image_url": image_url,
        "rating": rating,
    }

# ---------------- Router ----------------
@app.post("/api/parseRecipe")
def parse_recipe(data: RecipeRequest):
    try:
        url = data.url if data.url.startswith("http") else f"https://{data.url}"
        domain = urlparse(url).netloc.lower()

        resp = requests.get(url, headers=HEADERS, timeout=25)
        if resp.status_code != 200:
            raise HTTPException(status_code=404, detail="Recipe page not found")

        soup = BeautifulSoup(resp.content, "html.parser")

        if "food.com" in domain:
            return scrape_food_com(soup)
        elif "thetableofspice.com" in domain:
            return scrape_tableofspice(soup)
        elif "foodnetwork.co.uk" in domain:
            return scrape_foodnetwork_uk(soup, resp.text)  # pass RAW HTML here
        elif "allrecipes.com" in domain:
            return scrape_allrecipes(soup)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported domain: {domain}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
