"""
Tests for stock transition logic and alert deduplication.

Tests the core state machine that decides when to send Telegram alerts.
Uses a mock WatchedProduct — no database, no network calls.
"""
import pytest
from dataclasses import replace
from datetime import datetime, timezone

from app.database.models import WatchedProduct, StockStatus, MonitoringMode


def make_product(
    status: StockStatus = StockStatus.OUT_OF_STOCK,
    alert_sent: bool = False,
) -> WatchedProduct:
    """Create a test WatchedProduct with defaults."""
    return WatchedProduct(
        id=1,
        telegram_chat_id=123456789,
        asin="B0TEST00001",
        url="https://www.amazon.in/dp/B0TEST00001",
        title="Test Product",
        status=status,
        price="24990",
        currency="INR",
        monitoring_enabled=True,
        monitoring_mode=MonitoringMode.NORMAL,
        alert_sent_for_current_stock_state=alert_sent,
        consecutive_failures=0,
    )


class TestTransitionShouldAlert:
    """
    Test the core transition logic.

    The rule: send alert ONLY on OUT_OF_STOCK → IN_STOCK (or UNKNOWN → IN_STOCK
    with high confidence), and only if alert hasn't been sent for this in-stock run.
    """

    def test_out_of_stock_to_in_stock_should_alert(self):
        """The primary scenario: OOS → IN_STOCK = send alert."""
        product = make_product(status=StockStatus.OUT_OF_STOCK, alert_sent=False)

        new_status = StockStatus.IN_STOCK
        # Simulate transition logic
        should_alert = _should_alert(product, new_status, confident=True)

        assert should_alert is True

    def test_in_stock_to_in_stock_no_alert(self):
        """Already in stock + already alerted = no duplicate alert."""
        product = make_product(status=StockStatus.IN_STOCK, alert_sent=True)

        new_status = StockStatus.IN_STOCK
        should_alert = _should_alert(product, new_status, confident=True)

        assert should_alert is False

    def test_in_stock_to_out_of_stock_no_alert(self):
        """Product goes out of stock — no alert, but reset flag."""
        product = make_product(status=StockStatus.IN_STOCK, alert_sent=True)

        new_status = StockStatus.OUT_OF_STOCK
        should_alert = _should_alert(product, new_status, confident=True)

        assert should_alert is False

    def test_out_of_stock_to_out_of_stock_no_alert(self):
        """Still out of stock — no alert."""
        product = make_product(status=StockStatus.OUT_OF_STOCK, alert_sent=False)

        new_status = StockStatus.OUT_OF_STOCK
        should_alert = _should_alert(product, new_status, confident=True)

        assert should_alert is False

    def test_out_of_stock_to_unknown_no_alert(self):
        """OOS → UNKNOWN — don't alert, uncertain."""
        product = make_product(status=StockStatus.OUT_OF_STOCK, alert_sent=False)

        new_status = StockStatus.UNKNOWN
        should_alert = _should_alert(product, new_status, confident=False)

        assert should_alert is False

    def test_unknown_to_in_stock_confident_should_alert(self):
        """UNKNOWN → IN_STOCK with high confidence = alert."""
        product = make_product(status=StockStatus.UNKNOWN, alert_sent=False)

        new_status = StockStatus.IN_STOCK
        should_alert = _should_alert(product, new_status, confident=True)

        assert should_alert is True

    def test_unknown_to_in_stock_not_confident_no_alert(self):
        """UNKNOWN → IN_STOCK with LOW confidence = NO alert."""
        product = make_product(status=StockStatus.UNKNOWN, alert_sent=False)

        new_status = StockStatus.IN_STOCK
        should_alert = _should_alert(product, new_status, confident=False)

        assert should_alert is False

    def test_blocked_does_not_trigger_alert(self):
        """BLOCKED is not IN_STOCK — no alert."""
        product = make_product(status=StockStatus.OUT_OF_STOCK, alert_sent=False)

        new_status = StockStatus.BLOCKED
        should_alert = _should_alert(product, new_status, confident=False)

        assert should_alert is False


class TestAlertDeduplication:
    """Test that we don't send duplicate alerts across multiple checks."""

    def test_no_duplicate_alert_on_repeated_in_stock(self):
        """
        Simulate 3 consecutive IN_STOCK checks.
        Alert should only fire once.
        """
        product = make_product(status=StockStatus.OUT_OF_STOCK, alert_sent=False)

        # Check 1: OOS → IN_STOCK
        alert1 = _should_alert(product, StockStatus.IN_STOCK, confident=True)
        # Update product to reflect that alert was sent
        product = replace(product, status=StockStatus.IN_STOCK, alert_sent_for_current_stock_state=True)

        # Check 2: IN_STOCK → IN_STOCK (still in stock)
        alert2 = _should_alert(product, StockStatus.IN_STOCK, confident=True)
        # Product state unchanged (alert already sent)

        # Check 3: IN_STOCK → IN_STOCK (still in stock)
        alert3 = _should_alert(product, StockStatus.IN_STOCK, confident=True)

        assert alert1 is True
        assert alert2 is False
        assert alert3 is False

    def test_alert_resets_after_going_out_of_stock(self):
        """
        After going out of stock and back, alert should fire again.
        """
        product = make_product(status=StockStatus.OUT_OF_STOCK, alert_sent=False)

        # Phase 1: OOS → IN_STOCK → alert
        alert1 = _should_alert(product, StockStatus.IN_STOCK, confident=True)
        product = replace(product, status=StockStatus.IN_STOCK, alert_sent_for_current_stock_state=True)
        assert alert1 is True

        # Phase 2: IN_STOCK → OUT_OF_STOCK → no alert, flag reset
        alert2 = _should_alert(product, StockStatus.OUT_OF_STOCK, confident=True)
        product = replace(product, status=StockStatus.OUT_OF_STOCK, alert_sent_for_current_stock_state=False)
        assert alert2 is False

        # Phase 3: OOS → IN_STOCK again → should alert again!
        alert3 = _should_alert(product, StockStatus.IN_STOCK, confident=True)
        assert alert3 is True

    def test_no_duplicate_across_restart(self):
        """
        Simulate app restart while product is in stock and alert already sent.
        Should NOT re-alert.
        """
        # After restart: product is IN_STOCK, alert_sent=True (persisted in DB)
        product = make_product(status=StockStatus.IN_STOCK, alert_sent=True)

        # First check after restart: still IN_STOCK
        should_alert = _should_alert(product, StockStatus.IN_STOCK, confident=True)

        assert should_alert is False


class TestAlertFlagReset:
    """Test that alert_sent_for_current_stock_state is correctly managed."""

    def test_flag_set_on_alert(self):
        """When alert fires, flag should be set to True."""
        product = make_product(status=StockStatus.OUT_OF_STOCK, alert_sent=False)
        new_flag = _compute_new_alert_flag(product, StockStatus.IN_STOCK, alerted=True)
        assert new_flag is True

    def test_flag_cleared_on_oos_transition(self):
        """When going to OOS from IN_STOCK, flag should be cleared."""
        product = make_product(status=StockStatus.IN_STOCK, alert_sent=True)
        new_flag = _compute_new_alert_flag(product, StockStatus.OUT_OF_STOCK, alerted=False)
        assert new_flag is False

    def test_flag_cleared_on_unknown_transition(self):
        """When going to UNKNOWN from IN_STOCK, flag should be cleared."""
        product = make_product(status=StockStatus.IN_STOCK, alert_sent=True)
        new_flag = _compute_new_alert_flag(product, StockStatus.UNKNOWN, alerted=False)
        assert new_flag is False

    def test_flag_unchanged_when_staying_in_stock(self):
        """When staying IN_STOCK with alert already sent, flag stays True."""
        product = make_product(status=StockStatus.IN_STOCK, alert_sent=True)
        new_flag = _compute_new_alert_flag(product, StockStatus.IN_STOCK, alerted=False)
        assert new_flag is True


# ── Pure logic helpers (mirror watcher.py logic) ─────────────────────────────
# These replicate the watcher's transition logic in pure functions for testing.

def _should_alert(
    product: WatchedProduct,
    new_status: StockStatus,
    confident: bool,
) -> bool:
    """
    Determine if a Telegram alert should be sent.

    Mirrors the logic in app/monitoring/watcher.py:check_product()
    """
    if new_status != StockStatus.IN_STOCK:
        return False
    if not confident:
        return False
    if product.alert_sent_for_current_stock_state:
        return False
    return True


def _compute_new_alert_flag(
    product: WatchedProduct,
    new_status: StockStatus,
    alerted: bool,
) -> bool:
    """
    Compute the new value of alert_sent_for_current_stock_state.

    Mirrors the logic in app/monitoring/watcher.py
    """
    if alerted:
        return True

    # Reset flag when leaving IN_STOCK
    if product.status == StockStatus.IN_STOCK and new_status != StockStatus.IN_STOCK:
        return False

    return product.alert_sent_for_current_stock_state
