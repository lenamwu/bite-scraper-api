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

# ---------------- AllRecipes (unchanged) ----------------
def scrape_allrecipes(soup: BeautifulSoup) -> dict:
    title_tag = soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else "Untitled"

    notes_tag = soup.find("p", class_="article-subheading text-utility-300")
    notes = notes_tag.get_text(strip=True) if notes_tag else ""

    ingredients = []
    for p in soup.find_all("p"):
        q = p.find("span", {"data-ingredient-quantity": "true"})
        u = p.find("span", {"data-ingredient-unit": "true"})
        n = p.find("span", {"data-ingredient-name": "true"})
        if n:
            ingredients.append(" ".join([
                q.get_text(strip=True) if q else "",
                u.get_text(strip=True) if u else "",
                n.get_text(strip=True)
            ]).strip())

    instructions = []
    for p in soup.select("li > p.mntl-sc-block-html"):
        step = p.get_text(strip=True)
        if step:
            instructions.append(step)

    cooking_time = None
    servings = None
    labels = soup.find_all("div", class_="mm-recipes-details__label")
    values = soup.find_all("div", class_="mm-recipes-details__value")
    for i in range(min(len(labels), len(values))):
        label_text = labels[i].get_text(strip=True).lower()
        value_text = values[i].get_text(strip=True)
        if "servings" in label_text:
            servings = value_text
        elif "total time" in label_text:
            cooking_time = value_text

    image_url = None
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        image_url = og["content"]

    return {
        "title": title,
        "notes": notes,
        "ingredients": ingredients,
        "instructions": instructions,
        "cooking_time": cooking_time,
        "servings": servings,
        "image_url": image_url
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
        "cooking_time": None, "servings": None, "image_url": None
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
            out["instructions"] = out["instructions"] or [s for s in steps if s]

            total = node.get("totalTime") or node.get("cookTime") or node.get("prepTime")
            if total:
                out["cooking_time"] = out["cooking_time"] or clean(total)

            ry = node.get("recipeYield")
            if isinstance(ry, list):
                ry = " ".join([clean(x) for x in ry if clean(x)])
            if ry:
                out["servings"] = out["servings"] or clean(str(ry))

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

    return {
        "title": title or None,
        "notes": notes or None,
        "ingredients": [],      # JSON-LD will fill these
        "instructions": [],     # JSON-LD will fill these
        "cooking_time": cooking_time or None,
        "servings": servings or None,
        "image_url": image_url or None,
    }

def scrape_foodnetwork_uk(soup: BeautifulSoup, raw_html: str) -> dict:
    ld   = _parse_fnuk_jsonld(soup)               # ingredients/instructions/time (ISO) if present
    html = _fnuk_html_fallbacks(soup, raw_html)   # title/notes/image/time(short)/servings

    cooking_time = html["cooking_time"] or iso_duration_to_short(ld["cooking_time"])

    return {
        "title": html["title"] or ld["title"] or "Untitled",
        "notes": html["notes"] or ld["notes"] or "",
        "ingredients": ld["ingredients"] or [],
        "instructions": ld["instructions"] or [],
        "cooking_time": cooking_time,
        "servings": html["servings"] or ld["servings"],
        "image_url": html["image_url"] or ld["image_url"],
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

        if "allrecipes.com" in domain:
            return scrape_allrecipes(soup)
        elif "foodnetwork.co.uk" in domain:
            return scrape_foodnetwork_uk(soup, resp.text)  # pass RAW HTML here
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported domain: {domain}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
