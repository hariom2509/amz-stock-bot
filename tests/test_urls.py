"""
Tests for URL normalization and ASIN extraction.
"""
import pytest
from app.utils.urls import (
    extract_asin,
    is_amazon_url,
    normalize_url,
    looks_like_amazon_url,
)


class TestIsAmazonUrl:
    def test_valid_amazon_in(self):
        assert is_amazon_url("https://www.amazon.in/dp/B0CHX1W1XY") is True

    def test_valid_amazon_in_no_www(self):
        assert is_amazon_url("https://amazon.in/dp/B0CHX1W1XY") is True

    def test_valid_amzn_in(self):
        assert is_amazon_url("https://amzn.in/d/B0CHX1W1XY") is True

    def test_invalid_amazon_com(self):
        # Only amazon.in is supported initially
        assert is_amazon_url("https://www.amazon.com/dp/B0CHX1W1XY") is False

    def test_invalid_non_amazon(self):
        assert is_amazon_url("https://www.flipkart.com/some-product") is False

    def test_invalid_no_scheme(self):
        assert is_amazon_url("amazon.in/dp/B0CHX1W1XY") is False

    def test_empty_string(self):
        assert is_amazon_url("") is False


class TestExtractAsin:
    def test_dp_format(self):
        assert extract_asin("https://www.amazon.in/dp/B0CHX1W1XY") == "B0CHX1W1XY"

    def test_gp_product_format(self):
        assert extract_asin("https://www.amazon.in/gp/product/B0CHX1W1XY") == "B0CHX1W1XY"

    def test_url_with_product_name(self):
        url = "https://www.amazon.in/Sony-WH-1000XM5-Headphones/dp/B09XS7JWHH"
        assert extract_asin(url) == "B09XS7JWHH"

    def test_url_with_query_params(self):
        url = "https://www.amazon.in/dp/B0CHX1W1XY?ref=foo&tag=bar&pf_rd_r=abc"
        assert extract_asin(url) == "B0CHX1W1XY"

    def test_url_with_ref_and_tracking(self):
        url = (
            "https://www.amazon.in/Apple-AirPods-Pro/dp/B0CHWRXH8B/"
            "ref=sr_1_1?keywords=airpods&qid=1234567890&sr=8-1"
        )
        assert extract_asin(url) == "B0CHWRXH8B"

    def test_short_amzn_link(self):
        # amzn.in short links
        url = "https://amzn.in/d/B0CHX1W1XY"
        result = extract_asin(url)
        assert result == "B0CHX1W1XY"

    def test_lowercase_asin_normalized(self):
        # ASIN should be returned uppercase
        url = "https://www.amazon.in/dp/b0chx1w1xy"
        assert extract_asin(url) == "B0CHX1W1XY"

    def test_no_asin(self):
        url = "https://www.amazon.in/s?k=headphones"
        assert extract_asin(url) is None

    def test_invalid_url(self):
        assert extract_asin("not-a-url") is None

    def test_asin_10_chars(self):
        # ASINs are always exactly 10 alphanumeric characters
        url = "https://www.amazon.in/dp/B00ABCDEFG"
        assert extract_asin(url) == "B00ABCDEFG"

    def test_gp_product_with_slash(self):
        url = "https://www.amazon.in/gp/product/B09XS7JWHH/"
        assert extract_asin(url) == "B09XS7JWHH"


class TestNormalizeUrl:
    def test_normalizes_to_canonical_form(self):
        url = "https://www.amazon.in/Sony-Headphones/dp/B09XS7JWHH?ref=foo"
        result = normalize_url(url)
        assert result is not None
        canonical, asin = result
        assert asin == "B09XS7JWHH"
        assert canonical == "https://www.amazon.in/dp/B09XS7JWHH"

    def test_removes_tracking_params(self):
        url = "https://www.amazon.in/dp/B0CHX1W1XY?tag=myaffiliate&ref=xyz"
        result = normalize_url(url)
        assert result is not None
        canonical, _ = result
        assert "tag=" not in canonical
        assert "ref=" not in canonical

    def test_non_amazon_returns_none(self):
        assert normalize_url("https://www.flipkart.com/product") is None

    def test_amazon_search_returns_none(self):
        assert normalize_url("https://www.amazon.in/s?k=headphones") is None

    def test_empty_returns_none(self):
        assert normalize_url("") is None


class TestLooksLikeAmazonUrl:
    def test_full_amazon_url(self):
        assert looks_like_amazon_url("https://www.amazon.in/dp/B0CHX1W1XY") is True

    def test_short_amazon_url(self):
        assert looks_like_amazon_url("https://amzn.in/d/abc123") is True

    def test_random_text(self):
        assert looks_like_amazon_url("hello world") is False

    def test_flipkart_url(self):
        assert looks_like_amazon_url("https://www.flipkart.com/product/p/itm123") is True

    def test_other_shopping_site(self):
        assert looks_like_amazon_url("https://www.ebay.com/product") is False

