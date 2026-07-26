"""
Amazon HTTP client using httpx.

Responsible for:
- Maintaining a reusable async HTTP session
- Rotating modern browser headers & User-Agents to prevent cloud IP throttling
- Detecting HTTP-level blocks (429, 503, CAPTCHA)
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Optional, List

import httpx

from app.amazon.models import ProductState, StockStatus

logger = logging.getLogger(__name__)

# List of real, modern desktop browser User-Agents
_USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
]


def _get_dynamic_headers() -> dict[str, str]:
    ua = random.choice(_USER_AGENTS)
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.amazon.in/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }


class AmazonClient:
    """
    Reusable async HTTP client for fetching Amazon product pages.
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
        Fetch an Amazon product page with header rotation and micro-jitter.
        """
        client = await self._get_client()

        # Add small micro-jitter (100ms - 400ms) to avoid simultaneous burst bursts
        await asyncio.sleep(random.uniform(0.1, 0.4))

        try:
            logger.debug(f"Fetching URL for ASIN={asin}: {url}")
            # Rotate headers per request
            headers = _get_dynamic_headers()
            response = await client.get(url, headers=headers)
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
