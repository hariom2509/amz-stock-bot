"""
Amazon HTTP client using httpx.

Responsible for:
- Maintaining a reusable async HTTP session
- Sending browser-like headers to avoid trivial bot detection
- Detecting HTTP-level blocks (429, 503)
- Returning raw HTML or raising appropriate exceptions

Does NOT implement any anti-bot bypass techniques.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Optional

import httpx

from app.amazon.models import ProductState, StockStatus

logger = logging.getLogger(__name__)

# ── Browser-like headers ─────────────────────────────────────────────────────
# These mimic a regular Chrome browser to avoid trivial blocking.
# We do NOT spoof fingerprints or rotate proxies.
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;"
        "q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "DNT": "1",
}


class AmazonClient:
    """
    Reusable async HTTP client for fetching Amazon product pages.

    Create once and share across the application lifecycle.
    Call close() on shutdown.
    """

    def __init__(self, timeout_seconds: int = 15) -> None:
        self._timeout = httpx.Timeout(
            connect=10.0,
            read=float(timeout_seconds),
            write=5.0,
            pool=5.0,
        )
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=_DEFAULT_HEADERS,
                timeout=self._timeout,
                follow_redirects=True,
                http2=False,  # Some proxies don't support H2, keep reliable
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5,
                    keepalive_expiry=30,
                ),
            )
        return self._client

    async def fetch_product_page(
        self, url: str, asin: str
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Fetch an Amazon product page.

        Returns:
            (html_content, error_message) — one of these will be None.

        Handles:
            - HTTP 429 / 503 → returns (None, "BLOCKED:...")
            - Redirect to captcha → returns (None, "BLOCKED:CAPTCHA")
            - Network errors → returns (None, "ERROR:...")
        """
        client = await self._get_client()

        try:
            logger.debug(f"Fetching URL for ASIN={asin}: {url}")
            response = await client.get(url)
            html = response.text

            # ── HTTP-level blocks ─────────────────────────────────────────
            if response.status_code == 429:
                logger.warning(f"HTTP 429 (rate limited) for ASIN={asin}")
                return None, "BLOCKED:HTTP_429"

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

    Checks both URL redirect (to /errors/validateCaptcha) and
    page content indicators.
    """
    url_str = str(url).lower()

    # URL-based detection
    if "validatecaptcha" in url_str or "/errors/" in url_str:
        return True

    # Content-based detection (case-insensitive)
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
