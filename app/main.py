from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from app.fetcher import fetch_page, ALLRECIPES_PROXY
from app.validation import is_article_not_recipe
from app.parsers.allrecipes import scrape_allrecipes
from app.parsers.foodnetwork import scrape_foodnetwork_uk
from app.parsers.tableofspice import scrape_tableofspice
from app.parsers.food_com import scrape_food_com
from app.parsers.recipetineats import scrape_recipetineats
from app.parsers.gimmesomeoven import scrape_gimmesomeoven

app = FastAPI()


class RecipeRequest(BaseModel):
    url: str


# Map domain substrings to their scraper functions.
# Food Network needs the raw HTML too, so it's handled separately below.
_SCRAPERS = {
    "food.com": scrape_food_com,
    "thetableofspice.com": scrape_tableofspice,
    "allrecipes.com": scrape_allrecipes,
    "recipetineats.com": scrape_recipetineats,
    "gimmesomeoven.com": scrape_gimmesomeoven,
}


@app.post("/api/parseRecipe")
async def parse_recipe(data: RecipeRequest):
    try:
        url = data.url if data.url.startswith("http") else f"https://{data.url}"
        domain = urlparse(url).netloc.lower()

        resp = fetch_page(url)

        # If the proxy itself failed, retry without it
        if resp.status_code != 200 and ALLRECIPES_PROXY:
            resp = fetch_page(url)

        if resp.status_code != 200:
            detail = f"Recipe page not found (status {resp.status_code})"
            try:
                snippet = resp.text[:200].strip().replace("\n", " ")
                if snippet:
                    detail += f" -- {snippet}"
            except Exception:
                pass
            raise HTTPException(status_code=404, detail=detail)

        soup = BeautifulSoup(resp.content, "html.parser")

        # Route to the right scraper
        if "foodnetwork.co.uk" in domain:
            recipe_data = scrape_foodnetwork_uk(soup, resp.text)
        else:
            scraper = None
            for key, fn in _SCRAPERS.items():
                if key in domain:
                    scraper = fn
                    break
            if scraper is None:
                raise HTTPException(status_code=400, detail=f"Unsupported domain: {domain}")
            recipe_data = scraper(soup)

        # Article / review detection
        if is_article_not_recipe(soup, recipe_data):
            snippet = None
            try:
                snippet = resp.text[:500].replace("\n", " ")
            except Exception:
                pass
            result = {
                "title": "error",
                "notes": "This appears to be an article or review, not a recipe. Please provide a direct link to a recipe page.",
                "ingredients": [],
                "instructions": [],
                "cooking_time": None,
                "servings": "servings not specified",
                "image_url": None,
                "rating": None,
            }
            if snippet:
                result["debug_html"] = snippet
            return result

        return recipe_data

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
