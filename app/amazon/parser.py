"""
Multi-signal Amazon & Flipkart product page parser.

Determines stock availability using multiple independent signals
rather than relying on a single CSS selector.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple

from bs4 import BeautifulSoup, Tag

from app.amazon.models import ProductState, StockStatus

logger = logging.getLogger(__name__)

# ── Positive stock signals (Amazon) ──────────────────────────────────────────
_POSITIVE_SIGNALS = [
    ("add_to_cart_button", 0.45),
    ("buy_now_button", 0.35),
    ("availability_in_stock", 0.30),
    ("in_stock_text_body", 0.20),
    ("offer_listing_present", 0.25),
    ("delivery_promise", 0.15),
]

# ── Negative stock signals (Amazon) ──────────────────────────────────────────
_NEGATIVE_SIGNALS = [
    ("currently_unavailable", 0.60),
    ("temporarily_out_of_stock", 0.55),
    ("no_featured_offers", 0.40),
    ("out_of_stock_text", 0.50),
    ("unavailable_text", 0.40),
    ("notify_me_button", 0.35),
]

_IN_STOCK_THRESHOLD = 0.45
_OUT_OF_STOCK_THRESHOLD = 0.45


def parse_product_page(html: str, asin: str) -> ProductState:
    """
    Parse Amazon or Flipkart product page HTML and return a ProductState.
    """
    if not html or len(html) < 50:
        logger.warning(f"ASIN/ID={asin}: HTML too short ({len(html)} bytes) — UNKNOWN")
        return ProductState(
            status=StockStatus.UNKNOWN,
            confidence=0.0,
            evidence=["html_too_short"],
            error_message="Page content too short to parse",
        )

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as e:
        logger.error(f"ASIN/ID={asin}: Parse error: {e}")
        return ProductState(
            status=StockStatus.ERROR,
            confidence=0.0,
            evidence=["parse_error"],
            error_message=str(e),
        )

    # Check if page is Flipkart
    if _is_flipkart_page(soup, html, asin):
        return _parse_flipkart_page(soup, html, asin)

    # ── Amazon Parsing ────────────────────────────────────────────────────
    title = _extract_title(soup)
    price, currency = _extract_price(soup)

    positive_evidence: List[str] = []
    negative_evidence: List[str] = []
    positive_score = 0.0
    negative_score = 0.0

    availability_text = _extract_availability_text(soup)

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

    all_evidence = positive_evidence + [f"~{e}" for e in negative_evidence]

    if positive_score >= _IN_STOCK_THRESHOLD and positive_score > negative_score:
        return ProductState(
            status=StockStatus.IN_STOCK,
            confidence=min(1.0, positive_score),
            title=title,
            price=price,
            currency=currency,
            evidence=all_evidence,
            raw_availability_text=availability_text,
        )

    elif negative_score >= _OUT_OF_STOCK_THRESHOLD and negative_score >= positive_score:
        return ProductState(
            status=StockStatus.OUT_OF_STOCK,
            confidence=min(1.0, negative_score),
            title=title,
            price=price,
            currency=currency,
            evidence=all_evidence,
            raw_availability_text=availability_text,
        )

    else:
        return ProductState(
            status=StockStatus.UNKNOWN,
            confidence=max(positive_score, negative_score),
            title=title,
            price=price,
            currency=currency,
            evidence=all_evidence,
            raw_availability_text=availability_text,
        )


# ── Flipkart Specific Parser ──────────────────────────────────────────────────

def _is_flipkart_page(soup: BeautifulSoup, html: str, item_id: str) -> bool:
    if item_id.startswith("FK_") or "ITM" in item_id.upper():
        return True
    html_lower = html.lower()
    return "flipkart" in html_lower or "fkrt" in html_lower


def _parse_flipkart_page(soup: BeautifulSoup, html: str, pid: str) -> ProductState:
    html_lower = html.lower()

    # Extract Flipkart Title
    title = _extract_flipkart_title(soup)
    price = _extract_flipkart_price(soup)

    oos_indicators = [
        "currently unavailable",
        "sold out",
        "out of stock",
        "this item is currently out of stock",
        "this product is out of stock",
    ]

    is_oos = any(ind in html_lower for ind in oos_indicators) or soup.find(class_=re.compile(r"_16FRp0", re.I))

    in_stock_indicators = [
        "buy now",
        "add to cart",
        "notify me",
    ]
    has_buy_button = any(ind in html_lower for ind in ("buy now", "add to cart"))

    if is_oos:
        return ProductState(
            status=StockStatus.OUT_OF_STOCK,
            confidence=0.9,
            title=title,
            price=price,
            currency="INR",
            evidence=["flipkart_out_of_stock"],
        )
    elif has_buy_button or price:
        return ProductState(
            status=StockStatus.IN_STOCK,
            confidence=0.85,
            title=title,
            price=price,
            currency="INR",
            evidence=["flipkart_buy_button_present"],
        )
    else:
        return ProductState(
            status=StockStatus.UNKNOWN,
            confidence=0.5,
            title=title,
            price=price,
            currency="INR",
            evidence=["flipkart_unknown"],
        )


def _extract_flipkart_title(soup: BeautifulSoup) -> Optional[str]:
    for cls in ("B_NuOD", "_35Kyg6", "vuuWh", "_2Ndhp4"):
        el = soup.find(class_=cls)
        if el:
            t = el.get_text(strip=True)
            if t:
                return _clean_title(t)
    el = soup.find("h1")
    if el:
        return _clean_title(el.get_text(strip=True))
    title_tag = soup.find("title")
    if title_tag:
        raw = title_tag.get_text(strip=True)
        return _clean_title(raw.split(" Online")[0].split(" Price")[0])
    return None


def _extract_flipkart_price(soup: BeautifulSoup) -> Optional[str]:
    for cls in ("_30jeq3", "_16JBLd", "_25bW7y", "_30jeq3 _16JBLd"):
        el = soup.find(class_=cls)
        if el:
            cleaned = _clean_price(el.get_text(strip=True))
            if cleaned:
                return cleaned
    match = re.search(r"₹\s*([\d,]+)", soup.get_text())
    if match:
        return _clean_price(match.group(1))
    return None


# ── Amazon Helper Signal detectors ──────────────────────────────────────────

def _has_add_to_cart(soup: BeautifulSoup) -> bool:
    btn = soup.find("input", {"id": "add-to-cart-button"})
    if btn and not btn.get("disabled"):
        return True
    btn = soup.find("input", {"id": "submit.add-to-cart"})
    if btn and not btn.get("disabled"):
        return True
    btn = soup.find("input", {"name": "submit.add-to-cart"})
    if btn and not btn.get("disabled"):
        return True
    for el in soup.find_all(["button", "span"], class_=re.compile(r"add-to-cart", re.I)):
        text = el.get_text(strip=True).lower()
        if "add to cart" in text or "add to basket" in text:
            return True
    return False


def _has_buy_now(soup: BeautifulSoup) -> bool:
    btn = soup.find("input", {"id": "buy-now-button"})
    if btn and not btn.get("disabled"):
        return True
    btn = soup.find("input", {"id": "one-click-button"})
    if btn and not btn.get("disabled"):
        return True
    return False


def _extract_availability_text(soup: BeautifulSoup) -> Optional[str]:
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
    out_el = soup.find(id="outOfStock")
    if out_el:
        text = out_el.get_text(strip=True)
        if text:
            return text
    for el in soup.find_all(class_=re.compile(r"availability", re.I)):
        text = el.get_text(separator=" ", strip=True)
        if text and len(text) < 200:
            return text
    return None


def _matches_positive_availability(text_lower: str) -> bool:
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
    detail_area = soup.find("div", {"id": "centerCol"}) or soup.find(
        "div", {"id": "ppd"}
    )
    if not detail_area:
        return False
    text = detail_area.get_text(separator=" ").lower()
    matches = re.findall(r'\bin stock\b', text)
    anti_matches = re.findall(r'out of stock|not in stock', text)
    return len(matches) > len(anti_matches)


def _has_offer_listing(soup: BeautifulSoup) -> bool:
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
    delivery_ids = [
        "mir-layout-DELIVERY_BLOCK",
        "deliveryMessageMirId",
        "ddmDeliveryMessage",
        "desktop_unifiedPrice",
    ]
    for el_id in delivery_ids:
        if soup.find(id=el_id):
            return True
    for el in soup.find_all(class_=re.compile(r"delivery|shipping", re.I)):
        text = el.get_text().lower()
        if "delivery by" in text or "get it by" in text or "arrives" in text:
            return True
    return False


def _has_notify_me_button(soup: BeautifulSoup) -> bool:
    if soup.find("input", {"id": "notify-me-button"}):
        return True
    for el in soup.find_all(["button", "input", "span"]):
        text = el.get_text(strip=True).lower()
        if text in ("notify me", "notify me when available"):
            return True
    return False


def _extract_title(soup: BeautifulSoup) -> Optional[str]:
    el = soup.find(id="productTitle")
    if el:
        title = el.get_text(strip=True)
        if title:
            return _clean_title(title)
    meta = soup.find("meta", {"name": "title"})
    if meta and meta.get("content"):
        return _clean_title(meta["content"])
    og = soup.find("meta", {"property": "og:title"})
    if og and og.get("content"):
        return _clean_title(og["content"])
    title_el = soup.find("title")
    if title_el:
        raw = title_el.get_text(strip=True)
        parts = re.split(r"\s*[:|]\s*Amazon", raw, maxsplit=1)
        if parts[0]:
            return _clean_title(parts[0])
    return None


def _clean_title(title: str) -> str:
    title = re.sub(r'\s+', ' ', title).strip()
    if len(title) > 150:
        title = title[:147] + "..."
    return title


def _extract_price(soup: BeautifulSoup) -> Tuple[Optional[str], str]:
    currency = "INR"
    price_containers = soup.find_all("span", class_="a-price")
    for container in price_containers:
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
    for el_id in ("priceblock_ourprice", "priceblock_dealprice", "price_inside_buybox"):
        el = soup.find(id=el_id)
        if el:
            raw = el.get_text(strip=True)
            cleaned = _clean_price(raw)
            if cleaned:
                return cleaned, currency
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
    if not raw:
        return None
    cleaned = re.sub(r'[₹$€£¥INR\s,]', '', raw)
    match = re.search(r'(\d+(?:\.\d{2})?)', cleaned)
    if match:
        price = match.group(1)
        if price.endswith(".00"):
            price = price[:-3]
        return price
    return None
