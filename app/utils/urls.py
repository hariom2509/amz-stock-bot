"""
Amazon and Flipkart URL normalization, ID extraction, and Affiliate URL building.

Supports:
  - Amazon.in: /dp/ASIN, /gp/product/ASIN, amzn.in/d/ASIN
  - Flipkart: flipkart.com/product/p/itm..., dl.flipkart.com, fkrt.co
"""
from __future__ import annotations

import re
import urllib.parse
from urllib.parse import urlparse, parse_qs
from typing import Optional, Tuple

# ASIN / FSN patterns
ASIN_PATTERN = re.compile(r"\b([A-Z0-9]{10})\b")
FLIPKART_PID_PATTERN = re.compile(r"\b(ITM[A-Z0-9]{12,16}|[A-Z0-9]{16})\b", re.IGNORECASE)

# Supported Domains
SUPPORTED_AMAZON_DOMAINS = {"amazon.in", "www.amazon.in", "amzn.in"}
SUPPORTED_FLIPKART_DOMAINS = {"flipkart.com", "www.flipkart.com", "dl.flipkart.com", "fkrt.co", "fkrt.it"}
ALL_SUPPORTED_DOMAINS = SUPPORTED_AMAZON_DOMAINS | SUPPORTED_FLIPKART_DOMAINS

CANONICAL_AMAZON_BASE = "https://www.amazon.in/dp/{asin}"

# Default Affiliate Parameters
DEFAULT_AMAZON_TAG = "cashkacom-21"
DEFAULT_AMAZON_ASCSUBTAG = "CHKR20260726A442944725"
DEFAULT_FLIPKART_AFFILIATE_URL = "https://fkrt.co/t1d3OJ"


def extract_asin(url: str) -> Optional[str]:
    """Extract ASIN from an Amazon URL."""
    parsed = urlparse(url.strip())

    if parsed.netloc in ("amzn.in",):
        parts = [p for p in parsed.path.split("/") if p]
        for part in parts:
            if ASIN_PATTERN.fullmatch(part.upper()):
                return part.upper()

    dp_match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", parsed.path.upper())
    if dp_match:
        return dp_match.group(1)

    path_parts = [p for p in parsed.path.split("/") if p]
    for part in path_parts:
        if ASIN_PATTERN.fullmatch(part.upper()):
            return part.upper()

    qs = parse_qs(parsed.query)
    for key in ("asin", "ASIN"):
        if key in qs:
            candidate = qs[key][0].upper()
            if ASIN_PATTERN.fullmatch(candidate):
                return candidate

    return None


def extract_flipkart_pid(url: str) -> Optional[str]:
    """Extract Product ID / FSN from a Flipkart URL."""
    url_clean = url.strip()
    parsed = urlparse(url_clean)

    qs = parse_qs(parsed.query)
    for key in ("pid", "PID", "fsn", "FSN"):
        if key in qs:
            candidate = qs[key][0].strip()
            if candidate:
                return candidate.upper()

    itm_match = re.search(r"/(itm[a-z0-9]{12,16})", parsed.path.lower())
    if itm_match:
        return itm_match.group(1).upper()

    parts = [p for p in parsed.path.split("/") if p]
    for part in parts:
        if FLIPKART_PID_PATTERN.fullmatch(part):
            return part.upper()

    if parsed.netloc in ("fkrt.co", "fkrt.it"):
        part = parsed.path.strip("/")
        if part:
            return f"FK_{part.upper()}"

    return None


def is_amazon_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
        return parsed.scheme in ("http", "https") and parsed.netloc.lower() in SUPPORTED_AMAZON_DOMAINS
    except Exception:
        return False


def is_flipkart_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
        return parsed.scheme in ("http", "https") and parsed.netloc.lower() in SUPPORTED_FLIPKART_DOMAINS
    except Exception:
        return False


def normalize_url(url: str) -> Optional[Tuple[str, str]]:
    """
    Normalize Amazon or Flipkart URL to canonical form.
    Returns (canonical_url, item_id).
    """
    url = url.strip()

    if is_amazon_url(url):
        asin = extract_asin(url)
        if asin:
            return CANONICAL_AMAZON_BASE.format(asin=asin), asin

    if is_flipkart_url(url):
        pid = extract_flipkart_pid(url)
        if pid:
            clean_base = url.split("?")[0].strip()
            if clean_base.endswith("/"):
                clean_base = clean_base[:-1]
            if "pid=" in url.lower():
                canonical = f"{clean_base}"
            else:
                canonical = f"{clean_base}?pid={pid}"
            return canonical, pid

    return None


def build_affiliate_url(
    url: str,
    amazon_tag: str = DEFAULT_AMAZON_TAG,
    amazon_ascsubtag: str = DEFAULT_AMAZON_ASCSUBTAG,
    flipkart_affiliate_base: str = DEFAULT_FLIPKART_AFFILIATE_URL,
) -> str:
    """
    Build affiliate URL for Amazon or Flipkart.
    Preserves exact product target URL for Flipkart redirection.
    """
    if "flipkart" in url.lower() or "fkrt" in url.lower():
        if url.strip() == flipkart_affiliate_base:
            return url
        quoted_url = urllib.parse.quote(url, safe="")
        return f"{flipkart_affiliate_base}?url={quoted_url}"
    else:
        clean_url = url.split("?")[0].strip()
        return f"{clean_url}?tag={amazon_tag}&ascsubtag={amazon_ascsubtag}"


def looks_like_amazon_url(text: str) -> bool:
    """Quick check: does this text look like an Amazon or Flipkart product URL?"""
    text = text.strip().lower()
    has_domain = any(domain in text for domain in ("amazon.in", "amzn.in", "flipkart.com", "fkrt.co", "fkrt.it"))
    has_scheme = "http" in text or text.startswith("www.")
    return has_domain and has_scheme
