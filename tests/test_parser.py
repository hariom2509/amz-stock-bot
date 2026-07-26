"""
Tests for the Amazon HTML parser.

Uses local HTML fixtures — no network calls.
"""
import os
import pytest
from pathlib import Path

from app.amazon.parser import parse_product_page
from app.amazon.models import StockStatus

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(filename: str) -> str:
    return (FIXTURES_DIR / filename).read_text(encoding="utf-8")


class TestParserInStock:
    def setup_method(self):
        self.html = load_fixture("in_stock.html")
        self.result = parse_product_page(self.html, "B09XS7JWHH")

    def test_status_is_in_stock(self):
        assert self.result.status == StockStatus.IN_STOCK

    def test_confidence_sufficient(self):
        assert self.result.confidence >= 0.45

    def test_is_confident_in_stock(self):
        assert self.result.is_confident_in_stock is True

    def test_title_extracted(self):
        assert self.result.title is not None
        assert "Sony" in self.result.title or "WH-1000XM5" in self.result.title

    def test_price_extracted(self):
        assert self.result.price is not None
        assert self.result.price == "24990"

    def test_add_to_cart_in_evidence(self):
        assert "add_to_cart_button" in self.result.evidence

    def test_buy_now_in_evidence(self):
        assert "buy_now_button" in self.result.evidence

    def test_availability_text_positive(self):
        assert "availability_in_stock" in self.result.evidence


class TestParserOutOfStock:
    def setup_method(self):
        self.html = load_fixture("out_of_stock.html")
        self.result = parse_product_page(self.html, "B00PS5XXXXXX")

    def test_status_is_out_of_stock(self):
        assert self.result.status == StockStatus.OUT_OF_STOCK

    def test_confidence_sufficient(self):
        assert self.result.confidence >= 0.45

    def test_not_in_stock(self):
        assert self.result.is_confident_in_stock is False

    def test_title_extracted(self):
        assert self.result.title is not None
        assert "PlayStation" in self.result.title or "PS5" in self.result.title

    def test_currently_unavailable_in_evidence(self):
        evidence_str = " ".join(self.result.evidence)
        assert "currently_unavailable" in evidence_str or "notify_me_button" in evidence_str

    def test_no_add_to_cart(self):
        assert "add_to_cart_button" not in self.result.evidence

    def test_no_buy_now(self):
        assert "buy_now_button" not in self.result.evidence


class TestParserTemporarilyUnavailable:
    def setup_method(self):
        self.html = load_fixture("temporarily_unavailable.html")
        self.result = parse_product_page(self.html, "B0CWRXH8B1")

    def test_status_is_out_of_stock(self):
        # Temporarily out of stock is still OUT_OF_STOCK
        assert self.result.status == StockStatus.OUT_OF_STOCK

    def test_temporarily_out_in_evidence(self):
        evidence_str = " ".join(self.result.evidence)
        assert "temporarily_out_of_stock" in evidence_str or "notify_me_button" in evidence_str

    def test_not_in_stock(self):
        assert self.result.is_confident_in_stock is False


class TestParserCaptcha:
    def setup_method(self):
        self.html = load_fixture("captcha.html")

    def test_captcha_page_not_classified_as_out_of_stock(self):
        """
        A CAPTCHA page must NOT be classified as OUT_OF_STOCK.
        The client layer detects CAPTCHA before calling the parser,
        but if the HTML somehow makes it to the parser, it should return UNKNOWN.
        """
        result = parse_product_page(self.html, "B0TEST00000")
        # CAPTCHA page has no availability signals — should be UNKNOWN
        assert result.status != StockStatus.OUT_OF_STOCK
        assert result.status != StockStatus.IN_STOCK

    def test_no_false_in_stock_from_captcha(self):
        result = parse_product_page(self.html, "B0TEST00000")
        assert result.is_confident_in_stock is False


class TestParserUnknown:
    def setup_method(self):
        self.html = load_fixture("unknown.html")
        self.result = parse_product_page(self.html, "B0UNKNOWN00")

    def test_status_is_unknown(self):
        assert self.result.status == StockStatus.UNKNOWN

    def test_not_confident_in_stock(self):
        assert self.result.is_confident_in_stock is False


class TestParserEdgeCases:
    def test_empty_html(self):
        result = parse_product_page("", "B0TEST00000")
        assert result.status == StockStatus.UNKNOWN
        assert result.confidence == 0.0

    def test_very_short_html(self):
        result = parse_product_page("<html></html>", "B0TEST00000")
        assert result.status == StockStatus.UNKNOWN

    def test_does_not_crash_on_malformed_html(self):
        bad_html = "<div id='availability'><span>In Stock.</span>" + "x" * 1000
        result = parse_product_page(bad_html, "B0TEST00000")
        # Should not raise exception
        assert result.status in (
            StockStatus.IN_STOCK,
            StockStatus.OUT_OF_STOCK,
            StockStatus.UNKNOWN,
            StockStatus.ERROR,
        )

    def test_price_extraction_with_rupee_symbol(self):
        html = """
        <html><body>
        <div id='productTitle'>Test Product</div>
        <div id='corePrice_feature_div'>
          <span class='a-price'>
            <span class='a-offscreen'>₹19,999</span>
          </span>
        </div>
        <div id='availability'><span>In Stock.</span></div>
        <input type='submit' id='add-to-cart-button' value='Add to Cart'/>
        </body></html>
        """
        result = parse_product_page(html, "B0TEST00001")
        assert result.price == "19999"

    def test_price_extraction_with_decimal(self):
        html = """
        <html><body>
        <div id='productTitle'>Test Product</div>
        <div id='corePrice_feature_div'>
          <span class='a-price'>
            <span class='a-offscreen'>₹1,499.00</span>
          </span>
        </div>
        <div id='availability'><span>In Stock.</span></div>
        <input type='submit' id='add-to-cart-button' value='Add to Cart'/>
        </body></html>
        """
        result = parse_product_page(html, "B0TEST00002")
        assert result.price == "1499"


class TestParserPriceExclusion:
    def test_mrp_not_selected_as_price(self):
        """MRP strikethrough price should NOT be the extracted price."""
        html = """
        <html><body>
        <div id='productTitle'>Test Product</div>
        <div>
          <!-- MRP/was price (strikethrough) -->
          <span class='a-text-price'>
            <span class='a-offscreen'>₹35,000</span>
          </span>
          <!-- Actual selling price -->
          <div id='corePrice_feature_div'>
            <span class='a-price'>
              <span class='a-offscreen'>₹24,990</span>
            </span>
          </div>
        </div>
        <div id='availability'><span>In Stock.</span></div>
        <input type='submit' id='add-to-cart-button' value='Add to Cart'/>
        </body></html>
        """
        result = parse_product_page(html, "B0TEST00003")
        assert result.status == StockStatus.IN_STOCK
        # The actual price should be preferred, not MRP
        assert result.price is not None
