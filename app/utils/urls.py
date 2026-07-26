"""
Amazon URL normalization, ASIN extraction, and Affiliate URL building.

Supports common Amazon.in URL formats:
  - https://www.amazon.in/dp/ASIN
  - https://www.amazon.in/gp/product/ASIN
  - https://www.amazon.in/some-product-name/dp/ASIN
  - https://www.amazon.in/dp/ASIN?ref=...&tag=...
  - https://amzn.in/d/ASIN  (short links)
"""
from __future__ import annotations

import re
from urllib.parse import urlparse, parse_qs
from typing import Optional, Tuple

# ASIN: exactly 10 alphanumeric characters, uppercase
ASIN_PATTERN = re.compile(r"\b([A-Z0-9]{10})\b")

# Supported Amazon domains
SUPPORTED_DOMAINS = {
    "amazon.in",
    "www.amazon.in",
    "amzn.in",
}

# Canonical base URL
CANONICAL_BASE = "https://www.amazon.in/dp/{asin}"

# Default CashKaro Affiliate Parameters
DEFAULT_AFFILIATE_TAG = "cashkacom-21"
DEFAULT_AFFILIATE_ASCSUBTAG = "CHKR20260726A442944725"


def extract_asin(url: str) -> Optional[str]:
    """
    Extract ASIN from an Amazon URL.

    Returns the 10-character ASIN string or None if not found.
    """
    parsed = urlparse(url.strip())

    # Handle short links: amzn.in/d/ASIN
    if parsed.netloc in ("amzn.in",):
        parts = [p for p in parsed.path.split("/") if p]
        for part in parts:
            if ASIN_PATTERN.fullmatch(part.upper()):
                return part.upper()

    # Standard paths: /dp/ASIN or /gp/product/ASIN
    dp_match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", parsed.path.upper())
    if dp_match:
        return dp_match.group(1)

    # Fallback: look for any 10-char alphanumeric in path segments
    path_parts = [p for p in parsed.path.split("/") if p]
    for part in path_parts:
        if ASIN_PATTERN.fullmatch(part.upper()):
            return part.upper()

    # Try query parameter 'asin'
    qs = parse_qs(parsed.query)
    for key in ("asin", "ASIN"):
        if key in qs:
            candidate = qs[key][0].upper()
            if ASIN_PATTERN.fullmatch(candidate):
                return candidate

    return None


def is_amazon_url(url: str) -> bool:
    """Return True if the URL is from a supported Amazon domain."""
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            return False
        netloc = parsed.netloc.lower()
        return netloc in SUPPORTED_DOMAINS
    except Exception:
        return False


def normalize_url(url: str) -> Optional[Tuple[str, str]]:
    """
    Normalize an Amazon URL to canonical form.

    Returns:
        (canonical_url, asin) tuple if successful
        None if the URL is invalid or ASIN cannot be extracted
    """
    url = url.strip()

    if not is_amazon_url(url):
        return None

    asin = extract_asin(url)
    if not asin:
        return None

    canonical = CANONICAL_BASE.format(asin=asin)
    return canonical, asin


def build_affiliate_url(
    url: str,
    tag: str = DEFAULT_AFFILIATE_TAG,
    ascsubtag: str = DEFAULT_AFFILIATE_ASCSUBTAG,
) -> str:
    """
    Attach affiliate tracking parameters (tag and ascsubtag) to an Amazon product URL.
    Example: https://www.amazon.in/dp/B0CX5N22N3?tag=cashkacom-21&ascsubtag=CHKR20260726A442944725
    """
    clean_url = url.split("?")[0].strip()
    return f"{clean_url}?tag={tag}&ascsubtag={ascsubtag}"


def looks_like_amazon_url(text: str) -> bool:
    """
    Quick check: does this text look like it could be an Amazon URL?
    Used to handle bare URLs sent without /watch command.
    """
    text = text.strip().lower()
    return (
        "amazon.in" in text or "amzn.in" in text
    ) and ("http" in text or text.startswith("www."))
