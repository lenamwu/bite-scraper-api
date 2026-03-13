"""HTTP fetching with TLS fingerprint impersonation for Cloudflare bypass."""

from __future__ import annotations

import os
import random
from urllib.parse import quote

from curl_cffi import requests as cf_requests
import requests

ALLRECIPES_PROXY = os.getenv("ALLRECIPES_PROXY")

# Browser identities for curl_cffi to impersonate (TLS fingerprint + headers)
_IMPERSONATE_TARGETS = ["chrome", "chrome110", "edge99"]


def _has_recipe_data(text: str) -> bool:
    """Quick check that a response actually contains recipe structured data,
    not a Cloudflare challenge page masquerading as a 200."""
    return "recipeIngredient" in text or "recipeInstructions" in text or "<h1" in text


def fetch_page(url: str) -> requests.Response:
    """Fetch *url*, bypassing Cloudflare with TLS fingerprint impersonation.

    Strategy:
    1. curl_cffi with Chrome impersonation (best Cloudflare bypass).
    2. If that returns a challenge page, try a different impersonation target.
    3. If ALLRECIPES_PROXY is set, try through the proxy.
    4. Last resort: public CORS proxy.
    """
    # --- Primary: curl_cffi with browser impersonation ---
    last_resp = None
    for target in _IMPERSONATE_TARGETS:
        try:
            resp = cf_requests.get(url, impersonate=target, timeout=25)
            # curl_cffi returns its own Response; convert key fields so callers
            # can treat it like a requests.Response
            if resp.status_code == 200 and _has_recipe_data(resp.text):
                return resp
            last_resp = resp
        except Exception:
            continue

    # --- Fallback: private proxy ---
    if ALLRECIPES_PROXY:
        try:
            resp = requests.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                proxies={"http": ALLRECIPES_PROXY, "https": ALLRECIPES_PROXY},
                timeout=25,
            )
            if resp.status_code == 200:
                return resp
            last_resp = last_resp or resp
        except Exception:
            pass

    # --- Last resort: public CORS proxy ---
    try:
        proxy_url = f"https://api.allorigins.win/raw?url={quote(url)}"
        resp = requests.get(proxy_url, timeout=25)
        if resp.status_code == 200:
            return resp
        last_resp = last_resp or resp
    except Exception:
        pass

    if last_resp is not None:
        return last_resp
    raise ConnectionError(f"All fetch methods failed for {url}")
