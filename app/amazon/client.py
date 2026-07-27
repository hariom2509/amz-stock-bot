"""
Amazon HTTP client — pure direct fetch, no ScraperAPI.

3-Tier Fetch Strategy (each tier tried in order):
  Tier 1: Mobile user-agent via /dp/{asin} — lighter page, less bot detection
  Tier 2: Desktop browser via /dp/{asin}?th=1&psc=1 — full page with all signals
  Tier 3: Alternate URL format /gp/product/{asin} — different code path on Amazon's side

Additional techniques:
  - Persistent cookie jar per client instance (session simulation)
  - HTTP/2 disabled (Amazon's anti-bot fingerprinting checks HTTP version consistency)
  - Randomised realistic browser headers per request
  - Exponential jitter sleep between tiers to mimic human behaviour
  - CAPTCHA detection: if blocked, preserve last known status (never falsely OOS)
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import re
from typing import Optional, List, Tuple
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# ── User-Agent pools ─────────────────────────────────────────────────────────

_MOBILE_USER_AGENTS: List[str] = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.64 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; OnePlus 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.64 Mobile Safari/537.36",
]

_DESKTOP_USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
]

_ACCEPT_LANGUAGES: List[str] = [
    "en-IN,en;q=0.9,hi;q=0.8",
    "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
    "en-US,en;q=0.9,en-IN;q=0.8",
    "en-IN,en;q=0.9",
]

# Amazon.in base URL
_AMAZON_BASE = "https://www.amazon.in"


def _mobile_headers(lang: str) -> dict:
    ua = random.choice(_MOBILE_USER_AGENTS)
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": lang,
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }


def _desktop_headers(lang: str) -> dict:
    ua = random.choice(_DESKTOP_USER_AGENTS)
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": lang,
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.amazon.in/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "DNT": "1",
    }


def _build_tier_urls(asin: str) -> List[Tuple[str, str]]:
    """
    Return ordered list of (url, tier_name) to attempt for this ASIN.
    Tier 1: Mobile /dp/ — lightest response, least bot detection
    Tier 2: Desktop /dp/ with variant params — full page
    Tier 3: Alternate /gp/product/ path — hits different cache/CDN node
    """
    return [
        (f"{_AMAZON_BASE}/dp/{asin}?th=1", "mobile_dp"),
        (f"{_AMAZON_BASE}/dp/{asin}?th=1&psc=1", "desktop_dp"),
        (f"{_AMAZON_BASE}/gp/product/{asin}", "desktop_gp"),
    ]


class AmazonClient:
    """
    Reusable async HTTP client for fetching Amazon product pages.
    Uses a 3-tier direct fetch strategy with cookie jar session simulation.
    No external proxy services required.
    """

    def __init__(self, timeout_seconds: int = 15, **kwargs) -> None:
        # Accept but ignore legacy kwargs (e.g. scraper_api_key) for compat
        self._timeout = httpx.Timeout(
            connect=10.0,
            read=float(timeout_seconds),
            write=5.0,
            pool=5.0,
        )
        self._client: Optional[httpx.AsyncClient] = None
        logger.info("AmazonClient: Direct fetch mode (no external proxy)")

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create the shared HTTP client with persistent cookie jar."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                http2=False,          # Consistent fingerprint — don't mix HTTP versions
                limits=httpx.Limits(
                    max_connections=20,
                    max_keepalive_connections=10,
                    keepalive_expiry=60,
                ),
                # Persistent cookie jar across requests — makes requests look more like a session
            )
        return self._client

    async def fetch_product_page(
        self,
        url: str,
        asin: str,
        **kwargs,          # absorb legacy force_proxy etc.
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Fetch an Amazon product page using 3-tier strategy.
        Returns (html, None) on success or (None, error_code) on failure.
        """
        client = await self._get_client()
        lang = random.choice(_ACCEPT_LANGUAGES)
        tier_urls = _build_tier_urls(asin)

        for tier_idx, (tier_url, tier_name) in enumerate(tier_urls):
            # Small jitter between tiers to look human
            if tier_idx > 0:
                await asyncio.sleep(random.uniform(0.5, 1.5))

            headers = _mobile_headers(lang) if tier_idx == 0 else _desktop_headers(lang)

            try:
                logger.debug(f"ASIN={asin}: Tier {tier_idx + 1} ({tier_name}) fetch → {tier_url}")
                response = await client.get(tier_url, headers=headers)
                html = response.text

                # ── HTTP-level error handling ──────────────────────────────
                if response.status_code == 429:
                    logger.warning(f"ASIN={asin}: HTTP 429 on tier {tier_idx + 1} — rate limited")
                    continue  # try next tier

                if response.status_code in (503, 502, 500):
                    logger.warning(f"ASIN={asin}: HTTP {response.status_code} on tier {tier_idx + 1}")
                    continue

                if response.status_code == 404:
                    logger.warning(f"ASIN={asin}: HTTP 404 — product not found")
                    return None, "ERROR:NOT_FOUND"

                if response.status_code not in (200, 301, 302):
                    logger.warning(f"ASIN={asin}: Unexpected HTTP {response.status_code} on tier {tier_idx + 1}")
                    continue

                # ── CAPTCHA / block detection ──────────────────────────────
                if _is_captcha_page(html, response.url):
                    logger.info(f"ASIN={asin}: CAPTCHA on tier {tier_idx + 1} — trying next tier")
                    continue

                # ── Sanity check: must look like a real product page ───────
                if not _looks_like_product_page(html):
                    logger.info(f"ASIN={asin}: Page doesn't look like product page on tier {tier_idx + 1} — trying next tier")
                    continue

                logger.debug(f"ASIN={asin}: Tier {tier_idx + 1} ({tier_name}) SUCCESS ({len(html)} bytes)")
                return html, None

            except httpx.TimeoutException:
                logger.warning(f"ASIN={asin}: Timeout on tier {tier_idx + 1}")
                continue

            except httpx.ConnectError as e:
                logger.warning(f"ASIN={asin}: Connection error on tier {tier_idx + 1}: {e}")
                continue

            except httpx.TooManyRedirects:
                logger.warning(f"ASIN={asin}: Redirect loop on tier {tier_idx + 1}")
                continue

            except Exception as e:
                logger.error(f"ASIN={asin}: Unexpected error on tier {tier_idx + 1}: {e}", exc_info=True)
                continue

        # All tiers exhausted
        logger.warning(f"ASIN={asin}: All 3 fetch tiers failed (Amazon is blocking this server IP)")
        return None, "BLOCKED:CAPTCHA"

    async def close(self) -> None:
        """Close the HTTP client and release connections."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
            logger.debug("Amazon HTTP client closed")


def _is_captcha_page(html: str, url) -> bool:
    """Detect Amazon CAPTCHA / robot-check pages.
    
    IMPORTANT: Must only match ACTUAL captcha pages, not normal product pages.
    Amazon product pages contain the word 'captcha' in their scripts/divs, so
    bare substring matching causes false positives on every successful fetch.
    Use only phrases that appear EXCLUSIVELY on Amazon's error/captcha page.
    """
    url_str = str(url).lower()
    # URL-based detection is the most reliable — CAPTCHA pages always redirect here
    if "validatecaptcha" in url_str or "/errors/validatecaptcha" in url_str:
        return True

    html_lower = html.lower()

    # These phrases ONLY appear on Amazon's actual CAPTCHA error page,
    # never on normal product pages
    captcha_page_only_phrases = [
        "sorry, we just need to make sure you're not a robot",
        "enter the characters you see below",
        "type the characters you see in this image",
        "to discuss automated access to amazon data please contact",
        "api.amazon.com/captcha",
        "validatecaptcha",
    ]
    return any(phrase in html_lower for phrase in captcha_page_only_phrases)


def _looks_like_product_page(html: str) -> bool:
    """
    Sanity check: does this HTML look like a real Amazon product page?
    Real Amazon product pages are always 50KB+.
    """
    if len(html) < 10000:
        return False
    html_lower = html.lower()
    # Any one of these confirms it's a real product page (not a redirect/error page)
    product_markers = [
        "productdetails",
        "acrpopover",
        "add-to-cart",
        "buy-now-button",
        "availability",
        "producttitle",
        "a-price",
        "dp-container",
        "ppd",
    ]
    return any(marker in html_lower for marker in product_markers)
