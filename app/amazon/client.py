"""
Amazon HTTP client using httpx.

Responsible for:
- Maintaining a reusable async HTTP session
- Routing through ScraperAPI when SCRAPER_API_KEY is set (bypasses CAPTCHA)
- Rotating modern browser headers & User-Agents as fallback
- Detecting HTTP-level blocks (429, 503, CAPTCHA)
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import Optional, List
from urllib.parse import quote_plus

import httpx

from app.amazon.models import ProductState, StockStatus

logger = logging.getLogger(__name__)

# ── ScraperAPI endpoint ───────────────────────────────────────────────────────
_SCRAPER_API_BASE = "http://api.scraperapi.com"

# List of real, modern desktop browser User-Agents (rotate to reduce bot detection)
_USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.64 Mobile Safari/537.36",
]

_ACCEPT_LANGUAGES = [
    "en-IN,en;q=0.9,hi;q=0.8",
    "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
    "en-US,en;q=0.9,en-IN;q=0.8",
    "en-IN,en;q=0.9",
]


def _get_dynamic_headers() -> dict[str, str]:
    ua = random.choice(_USER_AGENTS)
    lang = random.choice(_ACCEPT_LANGUAGES)
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
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "DNT": "1",
    }


class AmazonClient:
    """
    Reusable async HTTP client for fetching Amazon product pages.
    Routes through ScraperAPI when SCRAPER_API_KEY is available to bypass CAPTCHAs.
    Falls back to direct requests with header rotation.
    """

    def __init__(self, timeout_seconds: int = 15, scraper_api_key: Optional[str] = None) -> None:
        self._scraper_api_key = scraper_api_key or os.getenv("SCRAPER_API_KEY", "").strip() or None

        if self._scraper_api_key:
            logger.info("AmazonClient: ScraperAPI mode ENABLED (Fast Proxy active)")
        else:
            logger.info("AmazonClient: Direct request mode (no ScraperAPI key)")

        read_timeout = 25.0 if self._scraper_api_key else float(timeout_seconds)

        self._timeout = httpx.Timeout(
            connect=10.0,
            read=read_timeout,
            write=5.0,
            pool=5.0,
        )
        self._client: Optional[httpx.AsyncClient] = None

    def _build_url(self, url: str) -> str:
        """Build the fetch URL — routes through fast ScraperAPI if key is configured."""
        if self._scraper_api_key:
            encoded = quote_plus(url)
            return f"{_SCRAPER_API_BASE}?api_key={self._scraper_api_key}&url={encoded}"
        return url

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=_get_dynamic_headers(),
                timeout=self._timeout,
                follow_redirects=True,
                http2=False,
                limits=httpx.Limits(
                    max_connections=15,
                    max_keepalive_connections=8,
                    keepalive_expiry=30,
                ),
            )
        return self._client

    async def fetch_product_page(
        self, url: str, asin: str
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Fetch an Amazon product page.
        Routes through fast ScraperAPI if key is set, otherwise direct with header rotation.
        """
        client = await self._get_client()

        fetch_url = self._build_url(url)
        using_proxy = fetch_url != url

        if not using_proxy:
            await asyncio.sleep(random.uniform(0.1, 0.4))

        try:
            logger.debug(f"Fetching ASIN={asin} via {'ScraperAPI' if using_proxy else 'direct'}: {url}")
            headers = _get_dynamic_headers()
            response = await client.get(fetch_url, headers=headers)
            html = response.text

            # ── HTTP-level blocks ─────────────────────────────────────────
            if response.status_code == 429:
                logger.warning(f"HTTP 429 (rate limited) for ASIN={asin}")
                return None, "BLOCKED:HTTP_429"

            if response.status_code == 403 and using_proxy:
                logger.warning(f"ScraperAPI 403 — invalid key or quota exceeded for ASIN={asin}")
                return None, "BLOCKED:SCRAPER_403"

            if response.status_code == 503:
                logger.warning(f"HTTP 503 (service unavailable) for ASIN={asin}")
                return None, "BLOCKED:HTTP_503"

            if response.status_code not in (200, 301, 302):
                logger.warning(
                    f"Unexpected HTTP {response.status_code} for ASIN={asin}"
                )
                return None, f"ERROR:HTTP_{response.status_code}"

            # ── CAPTCHA / robot check detection ──────────────────────────
            if _is_captcha_page(html, response.url):
                if using_proxy:
                    logger.warning(f"CAPTCHA page returned via ScraperAPI for ASIN={asin}")
                    return None, "BLOCKED:SCRAPER_CAPTCHA"
                else:
                    logger.warning(f"CAPTCHA page detected for ASIN={asin}")
                    return None, "BLOCKED:CAPTCHA"

            return html, None

        except httpx.TimeoutException as e:
            logger.warning(f"Timeout fetching ASIN={asin}: {e}")
            return None, f"ERROR:TIMEOUT"

        except httpx.ConnectError as e:
            logger.warning(f"Connection error for ASIN={asin}: {e}")
            return None, "ERROR:CONNECTION"

        except httpx.TooManyRedirects as e:
            logger.warning(f"Too many redirects for ASIN={asin}: {e}")
            return None, "BLOCKED:REDIRECT_LOOP"

        except httpx.HTTPError as e:
            logger.warning(f"HTTP error for ASIN={asin}: {e}")
            return None, f"ERROR:HTTP"

        except Exception as e:
            logger.error(f"Unexpected error fetching ASIN={asin}: {e}", exc_info=True)
            return None, f"ERROR:UNEXPECTED"

    async def close(self) -> None:
        """Close the HTTP client and release connections."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
            logger.debug("Amazon HTTP client closed")


def _is_captcha_page(html: str, url) -> bool:
    """
    Detect Amazon CAPTCHA / robot check pages.
    """
    url_str = str(url).lower()

    if "validatecaptcha" in url_str or "/errors/" in url_str:
        return True

    html_lower = html.lower()
    captcha_indicators = [
        "sorry, we just need to make sure you're not a robot",
        "enter the characters you see below",
        "type the characters you see in this image",
        "robot check",
        "captcha",
        "validatecaptcha",
        "automated access",
        "to discuss automated access to amazon data",
    ]

    return any(indicator in html_lower for indicator in captcha_indicators)
