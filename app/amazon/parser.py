"""
Multi-signal Amazon product page parser.

Determines stock availability using multiple independent signals
rather than relying on a single CSS selector.

Approach:
  1. Collect positive signals (evidence for IN_STOCK)
  2. Collect negative signals (evidence for OUT_OF_STOCK)
  3. Compute a weighted confidence score
  4. Classify result

Returns ProductState with status, confidence, title, price, and evidence list.

IMPORTANT: UNKNOWN is returned whenever confidence is insufficient.
We never falsely classify a page as IN_STOCK from ambiguous signals.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple

from bs4 import BeautifulSoup, Tag

from app.amazon.models import ProductState, StockStatus

logger = logging.getLogger(__name__)

# ── Positive stock signals ────────────────────────────────────────────────────
# Each entry: (signal_name, weight)
# Total positive weight ≥ threshold → IN_STOCK

_POSITIVE_SIGNALS = [
    ("add_to_cart_button", 0.45),   # #add-to-cart-button present and not disabled
    ("buy_now_button", 0.35),       # #buy-now-button present
    ("availability_in_stock", 0.30), # explicit "In Stock" in availability section
    ("in_stock_text_body", 0.20),   # "in stock" anywhere in product details
    ("offer_listing_present", 0.25), # offer listing / sold by present
    ("delivery_promise", 0.15),     # delivery date mentioned
]

# ── Negative stock signals ────────────────────────────────────────────────────
_NEGATIVE_SIGNALS = [
    ("currently_unavailable", 0.60),      # "Currently unavailable" text
    ("temporarily_out_of_stock", 0.55),   # "Temporarily out of stock"
    ("no_featured_offers", 0.40),         # "No featured offers available"
    ("out_of_stock_text", 0.50),          # Explicit "Out of Stock" in avail section
    ("unavailable_text", 0.40),           # Generic "unavailable" in avail section
    ("notify_me_button", 0.35),           # "Notify Me" button instead of Add to Cart
]

_IN_STOCK_THRESHOLD = 0.45     # Minimum positive score to call IN_STOCK
_OUT_OF_STOCK_THRESHOLD = 0.45  # Minimum negative score to call OUT_OF_STOCK


def parse_product_page(html: str, asin: str) -> ProductState:
    """
    Parse an Amazon product page HTML and return a ProductState.

    Args:
        html: Raw HTML string from Amazon product page
        asin: ASIN being checked (for logging)

    Returns:
        ProductState with status, confidence, title, price, evidence
    """
    if not html or len(html) < 50:
        logger.warning(f"ASIN={asin}: HTML too short ({len(html)} bytes) — UNKNOWN")
        return ProductState(
            status=StockStatus.UNKNOWN,
            confidence=0.0,
            evidence=["html_too_short"],
            error_message="Page content too short to parse",
        )

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as e:
        logger.error(f"ASIN={asin}: Parse error: {e}")
        return ProductState(
            status=StockStatus.ERROR,
            confidence=0.0,
            evidence=["parse_error"],
            error_message=str(e),
        )

    # ── Extract basic product info ────────────────────────────────────────
    title = _extract_title(soup)
    price, currency = _extract_price(soup)

    # ── Collect evidence ─────────────────────────────────────────────────
    positive_evidence: List[str] = []
    negative_evidence: List[str] = []
    positive_score = 0.0
    negative_score = 0.0

    availability_text = _extract_availability_text(soup)

    # ── Check each positive signal ────────────────────────────────────────
    if _has_add_to_cart(soup):
        positive_evidence.append("add_to_cart_button")
        positive_score += 0.45

    if _has_buy_now(soup):
        positive_evidence.append("buy_now_button")
        positive_score += 0.35

    if availability_text:
        avail_lower = availability_text.lower().strip()

        if _matches_positive_availability(avail_lower):
            positive_evidence.append("availability_in_stock")
            positive_score += 0.30
        elif _matches_negative_availability(avail_lower):
            if "currently unavailable" in avail_lower:
                negative_evidence.append("currently_unavailable")
                negative_score += 0.60
            elif "temporarily out of stock" in avail_lower:
                negative_evidence.append("temporarily_out_of_stock")
                negative_score += 0.55
            elif "no featured offers" in avail_lower:
                negative_evidence.append("no_featured_offers")
                negative_score += 0.40
            elif "out of stock" in avail_lower:
                negative_evidence.append("out_of_stock_text")
                negative_score += 0.50
            else:
                negative_evidence.append("unavailable_text")
                negative_score += 0.40

    if _has_in_stock_text_body(soup):
        positive_evidence.append("in_stock_text_body")
        positive_score += 0.20

    if _has_offer_listing(soup):
        positive_evidence.append("offer_listing_present")
        positive_score += 0.25

    if _has_delivery_promise(soup):
        positive_evidence.append("delivery_promise")
        positive_score += 0.15

    if _has_notify_me_button(soup):
        negative_evidence.append("notify_me_button")
        negative_score += 0.35

    # ── Determine status ──────────────────────────────────────────────────
    all_evidence = positive_evidence + [f"~{e}" for e in negative_evidence]

    logger.debug(
        f"ASIN={asin} | pos_score={positive_score:.2f} neg_score={negative_score:.2f} "
        f"| avail_text={availability_text!r} | evidence={all_evidence}"
    )

    if positive_score >= _IN_STOCK_THRESHOLD and positive_score > negative_score:
        confidence = min(1.0, positive_score)
        return ProductState(
            status=StockStatus.IN_STOCK,
            confidence=confidence,
            title=title,
            price=price,
            currency=currency,
            evidence=all_evidence,
            raw_availability_text=availability_text,
        )

    elif negative_score >= _OUT_OF_STOCK_THRESHOLD and negative_score >= positive_score:
        confidence = min(1.0, negative_score)
        return ProductState(
            status=StockStatus.OUT_OF_STOCK,
            confidence=confidence,
            title=title,
            price=price,
            currency=currency,
            evidence=all_evidence,
            raw_availability_text=availability_text,
        )

    else:
        # Cannot confidently determine — return UNKNOWN
        logger.info(
            f"ASIN={asin}: Insufficient evidence for clear classification "
            f"(pos={positive_score:.2f}, neg={negative_score:.2f}) → UNKNOWN"
        )
        return ProductState(
            status=StockStatus.UNKNOWN,
            confidence=max(positive_score, negative_score),
            title=title,
            price=price,
            currency=currency,
            evidence=all_evidence,
            raw_availability_text=availability_text,
        )


# ── Signal detectors ─────────────────────────────────────────────────────────

def _has_add_to_cart(soup: BeautifulSoup) -> bool:
    """Detect Add to Cart button — primary positive signal."""
    # Primary ID
    btn = soup.find("input", {"id": "add-to-cart-button"})
    if btn and not btn.get("disabled"):
        return True

    # Alternate form ID
    btn = soup.find("input", {"id": "submit.add-to-cart"})
    if btn and not btn.get("disabled"):
        return True

    # By name attribute
    btn = soup.find("input", {"name": "submit.add-to-cart"})
    if btn and not btn.get("disabled"):
        return True

    # By text content (button element)
    for el in soup.find_all(["button", "span"], class_=re.compile(r"add-to-cart", re.I)):
        text = el.get_text(strip=True).lower()
        if "add to cart" in text or "add to basket" in text:
            return True

    return False


def _has_buy_now(soup: BeautifulSoup) -> bool:
    """Detect Buy Now button — strong positive signal."""
    btn = soup.find("input", {"id": "buy-now-button"})
    if btn and not btn.get("disabled"):
        return True

    btn = soup.find("input", {"id": "one-click-button"})
    if btn and not btn.get("disabled"):
        return True

    return False


def _extract_availability_text(soup: BeautifulSoup) -> Optional[str]:
    """
    Extract text from Amazon's availability section.

    Checks multiple possible locations Amazon uses.
    """
    # Primary: #availability span
    avail_div = soup.find("div", {"id": "availability"})
    if avail_div:
        span = avail_div.find("span")
        if span:
            text = span.get_text(separator=" ", strip=True)
            if text:
                return text
        text = avail_div.get_text(separator=" ", strip=True)
        if text:
            return text

    # Alternate: #outOfStock
    out_el = soup.find(id="outOfStock")
    if out_el:
        text = out_el.get_text(strip=True)
        if text:
            return text

    # Alternate: class containing "availability"
    for el in soup.find_all(class_=re.compile(r"availability", re.I)):
        text = el.get_text(separator=" ", strip=True)
        if text and len(text) < 200:
            return text

    return None


def _matches_positive_availability(text_lower: str) -> bool:
    """Check if availability text indicates in-stock."""
    # First, explicitly block all negative phrases — these take priority
    negative_blockers = [
        "currently unavailable",
        "temporarily out of stock",
        "out of stock",
        "no longer available",
        "not available",
        "no featured offers",
        "unavailable",
        "notify me",
    ]
    if any(p in text_lower for p in negative_blockers):
        return False

    positive_phrases = [
        "in stock",
        "in-stock",
        "ships from",
        "usually ships",
        "add to cart",
        "buy now",
        "in stock.",
    ]
    return any(p in text_lower for p in positive_phrases)


def _matches_negative_availability(text_lower: str) -> bool:
    """Check if availability text indicates out-of-stock."""
    negative_phrases = [
        "currently unavailable",
        "out of stock",
        "temporarily out of stock",
        "no featured offers available",
        "unavailable",
        "not available",
        "notify me",
        "back in stock",
        "sign up to be notified",
    ]
    return any(p in text_lower for p in negative_phrases)


def _has_in_stock_text_body(soup: BeautifulSoup) -> bool:
    """Check for 'in stock' text in the product detail area."""
    detail_area = soup.find("div", {"id": "centerCol"}) or soup.find(
        "div", {"id": "ppd"}
    )
    if not detail_area:
        return False

    text = detail_area.get_text(separator=" ").lower()
    # Look for "in stock" NOT preceded by "out of"
    matches = re.findall(r'\bin stock\b', text)
    anti_matches = re.findall(r'out of stock|not in stock', text)
    return len(matches) > len(anti_matches)


def _has_offer_listing(soup: BeautifulSoup) -> bool:
    """Check for offer listing / seller information (suggests purchasable)."""
    # Sold by / ships from section
    if soup.find("div", {"id": "merchant-info"}):
        return True
    if soup.find("div", {"id": "tabular-buybox"}):
        return True
    if soup.find("div", {"id": "buybox"}):
        buybox = soup.find("div", {"id": "buybox"})
        text = buybox.get_text().lower()
        if "sold by" in text or "ships from" in text:
            return True
    return False


def _has_delivery_promise(soup: BeautifulSoup) -> bool:
    """Check for delivery date promise (suggests purchasable)."""
    delivery_ids = [
        "mir-layout-DELIVERY_BLOCK",
        "deliveryMessageMirId",
        "ddmDeliveryMessage",
        "desktop_unifiedPrice",
    ]
    for el_id in delivery_ids:
        if soup.find(id=el_id):
            return True

    # Also check for "Delivery by" or "Get it by" text
    for el in soup.find_all(class_=re.compile(r"delivery|shipping", re.I)):
        text = el.get_text().lower()
        if "delivery by" in text or "get it by" in text or "arrives" in text:
            return True

    return False


def _has_notify_me_button(soup: BeautifulSoup) -> bool:
    """Check for 'Notify Me' button — strong negative signal."""
    # By ID
    if soup.find("input", {"id": "notify-me-button"}):
        return True

    # By text
    for el in soup.find_all(["button", "input", "span"]):
        text = el.get_text(strip=True).lower()
        if text in ("notify me", "notify me when available"):
            return True

    return False


def _extract_title(soup: BeautifulSoup) -> Optional[str]:
    """
    Extract product title from Amazon page.

    Tries multiple selectors in priority order.
    """
    # Primary: #productTitle
    el = soup.find(id="productTitle")
    if el:
        title = el.get_text(strip=True)
        if title:
            return _clean_title(title)

    # Alternate: meta tag
    meta = soup.find("meta", {"name": "title"})
    if meta and meta.get("content"):
        return _clean_title(meta["content"])

    # Alternate: og:title
    og = soup.find("meta", {"property": "og:title"})
    if og and og.get("content"):
        return _clean_title(og["content"])

    # Alternate: page title
    title_el = soup.find("title")
    if title_el:
        raw = title_el.get_text(strip=True)
        # Amazon page titles are like "Product Name : Amazon.in: ..."
        parts = re.split(r"\s*[:|]\s*Amazon", raw, maxsplit=1)
        if parts[0]:
            return _clean_title(parts[0])

    return None


def _clean_title(title: str) -> str:
    """Clean and truncate a product title."""
    title = re.sub(r'\s+', ' ', title).strip()
    if len(title) > 150:
        title = title[:147] + "..."
    return title


def _extract_price(soup: BeautifulSoup) -> Tuple[Optional[str], str]:
    """
    Extract the primary purchase price from an Amazon page.

    Returns:
        (price_string_without_symbol, currency)

    We target the "a-price" element which Amazon uses for the current price.
    Avoids MRP / strikethrough prices.
    """
    currency = "INR"

    # Primary: .a-price .a-offscreen (screen-reader price, most reliable)
    # But skip if it's inside a strikethrough/was-price element
    price_containers = soup.find_all("span", class_="a-price")
    for container in price_containers:
        # Skip if inside a "basisPrice" or "was-price" parent
        parent_classes = " ".join(
            str(c) for c in [p.get("class", []) for p in container.parents]
        ).lower()
        if any(
            x in parent_classes
            for x in ["basis", "was-price", "a-text-price", "strike", "list-price"]
        ):
            continue

        offscreen = container.find("span", class_="a-offscreen")
        if offscreen:
            raw = offscreen.get_text(strip=True)
            cleaned = _clean_price(raw)
            if cleaned:
                return cleaned, currency

    # Fallback: #priceblock_ourprice
    for el_id in ("priceblock_ourprice", "priceblock_dealprice", "price_inside_buybox"):
        el = soup.find(id=el_id)
        if el:
            raw = el.get_text(strip=True)
            cleaned = _clean_price(raw)
            if cleaned:
                return cleaned, currency

    # Fallback: #corePrice_feature_div
    price_div = soup.find("div", {"id": "corePrice_feature_div"})
    if price_div:
        offscreen = price_div.find("span", class_="a-offscreen")
        if offscreen:
            raw = offscreen.get_text(strip=True)
            cleaned = _clean_price(raw)
            if cleaned:
                return cleaned, currency

    return None, currency


def _clean_price(raw: str) -> Optional[str]:
    """
    Extract numeric price from a string like '₹24,990' or 'INR 24,990.00'.

    Returns digits-only price string like '24990' or '24990.00'.
    """
    if not raw:
        return None

    # Remove currency symbols and codes
    cleaned = re.sub(r'[₹$€£¥INR\s,]', '', raw)

    # Extract the numeric part
    match = re.search(r'(\d+(?:\.\d{2})?)', cleaned)
    if match:
        price = match.group(1)
        # Remove trailing .00
        if price.endswith(".00"):
            price = price[:-3]
        return price

    return None
