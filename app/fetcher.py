"""HTTP fetching with User-Agent rotation and Cloudflare bypass."""

from __future__ import annotations

import os
import random
from urllib.parse import quote

import cloudscraper
import requests

ALLRECIPES_PROXY = os.getenv("ALLRECIPES_PROXY")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 11_2_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:116.0) Gecko/20100101 Firefox/116.0",
]

# Shared cloudscraper instance — handles Cloudflare JS challenges automatically
_scraper = cloudscraper.create_scraper()


def _random_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


def fetch_page(url: str) -> requests.Response:
    """Fetch *url*, bypassing Cloudflare challenges when needed.

    Strategy:
    1. Try cloudscraper (handles Cloudflare JS challenges).
    2. If that fails and ALLRECIPES_PROXY is set, retry through the proxy.
    3. As a last resort, try a public CORS proxy (allorigins.win).
    """
    headers = _random_headers()

    # cloudscraper handles Cloudflare automatically
    try:
        resp = _scraper.get(url, headers=headers, timeout=25)
        if resp.status_code == 200:
            return resp
    except Exception:
        resp = None

    # If cloudscraper didn't get a 200, try with private proxy
    if ALLRECIPES_PROXY:
        try:
            resp = requests.get(
                url,
                headers=_random_headers(),
                proxies={"http": ALLRECIPES_PROXY, "https": ALLRECIPES_PROXY},
                timeout=25,
            )
            if resp.status_code == 200:
                return resp
        except Exception:
            pass

    # Last resort: public CORS proxy
    if resp is None or resp.status_code != 200:
        try:
            proxy_url = f"https://api.allorigins.win/raw?url={quote(url)}"
            fallback = requests.get(proxy_url, headers=_random_headers(), timeout=25)
            if fallback.status_code == 200:
                return fallback
        except Exception:
            pass

    # Return whatever we got (may be an error response)
    if resp is not None:
        return resp
    # If everything failed with exceptions, create a minimal error response
    raise ConnectionError(f"All fetch methods failed for {url}")
