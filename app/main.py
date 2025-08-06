from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from bs4 import BeautifulSoup
import requests
import json

app = FastAPI()

class RecipeRequest(BaseModel):
    url: str

@app.post("/api/parseRecipe")
def parse_recipe(data: RecipeRequest):
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/138.0.0.0 Safari/537.36"
            )
        }

        response = requests.get(data.url, headers=headers)
        if response.status_code != 200:
            raise HTTPException(status_code=404, detail="Recipe page not found")

        soup = BeautifulSoup(response.content, "html.parser")

        # Title
        title_tag = soup.find("h1")
        title = title_tag.get_text(strip=True) if title_tag else "Untitled"

        # Notes (from <p class="article-subheading text-utility-300">)
        notes_tag = soup.find("p", class_="article-subheading text-utility-300")
        notes = notes_tag.get_text(strip=True) if notes_tag else ""

        # Ingredients
        ingredients = []
        for p in soup.find_all("p"):
            quantity = p.find("span", {"data-ingredient-quantity": "true"})
            unit = p.find("span", {"data-ingredient-unit": "true"})
            name = p.find("span", {"data-ingredient-name": "true"})
            if name:
                ingredients.append(" ".join([
                    quantity.get_text(strip=True) if quantity else "",
                    unit.get_text(strip=True) if unit else "",
                    name.get_text(strip=True)
                ]).strip())

        # ✅ Instructions (HTML-based)
        instructions = []
        instruction_blocks = soup.select("li > p.mntl-sc-block-html")
        for p in instruction_blocks:
            step = p.get_text(strip=True)
            if step:
                instructions.append(step)

        # Cooking time & servings
        cooking_time = None
        servings = None
        labels = soup.find_all("div", class_="mm-recipes-details__label")
        values = soup.find_all("div", class_="mm-recipes-details__value")
        for i in range(len(labels)):
            label_text = labels[i].get_text(strip=True).lower()
            value_text = values[i].get_text(strip=True)
            if "servings" in label_text:
                servings = value_text
            elif "total time" in label_text:
                cooking_time = value_text

        return {
            "title": title,
            "notes": notes,
            "ingredients": ingredients,
            "instructions": instructions,
            "cooking_time": cooking_time,
            "servings": servings
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
