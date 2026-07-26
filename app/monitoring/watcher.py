"""
Per-product watcher logic with structured latency metrics and smart restock alert rules.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Union, TYPE_CHECKING

from app.amazon.client import AmazonClient
from app.amazon.models import ProductState, StockStatus as AmazonStatus
from app.amazon.parser import parse_product_page
from app.database import repository as repo
from app.database.models import Product, WatchedProduct, UserWatch, StockStatus, MonitoringMode
from app.config import Settings

if TYPE_CHECKING:
    from app.alerts.telegram import AlertManager

logger = logging.getLogger(__name__)


class ProductWatcher:
    """
    Performs a single product check and handles all side effects + structured latency metrics.
    """

    def __init__(
        self,
        settings: Settings,
        http_client: AmazonClient,
        alert_manager: "AlertManager",
    ) -> None:
        self.settings = settings
        self.http_client = http_client
        self.alert_manager = alert_manager

    async def check_product(self, product: Union[WatchedProduct, Product]) -> None:
        if isinstance(product, Product):
            await self.check_shared_product(product)
            return

        asin = product.asin
        now = datetime.now(timezone.utc)

        logger.info(
            f"CHECK_START | ASIN={asin} | mode={product.monitoring_mode.value} "
            f"| prev_status={product.status.value}"
        )

        html, error = await self.http_client.fetch_product_page(product.url, asin)

        if error:
            await self._handle_fetch_error(product, error, now)
            return

        state = parse_product_page(html, asin)

        new_status = _map_status(state.status)

        logger.info(
            f"CHECK_RESULT | ASIN={asin} "
            f"| previous={product.status.value} current={new_status.value} "
            f"| confidence={state.confidence:.2f} price={state.price}"
        )

        status_changed = new_status != product.status

        next_check = _compute_next_check(
            product.monitoring_mode,
            self.settings,
            failures=0,
            status=new_status,
        )

        should_alert = False
        alert_sent_flag = product.alert_sent_for_current_stock_state
        last_status_changed_at = product.last_status_changed_at

        if status_changed:
            last_status_changed_at = now
            logger.info(f"STOCK_TRANSITION | ASIN={asin} | {product.status.value} → {new_status.value}")

        if new_status == StockStatus.IN_STOCK:
            # Alert only ONCE when transitioning to IN_STOCK
            if state.is_confident_in_stock and not product.alert_sent_for_current_stock_state:
                should_alert = True
                alert_sent_flag = True
        elif new_status in (StockStatus.OUT_OF_STOCK, StockStatus.UNKNOWN):
            # Reset alert flag when item goes out of stock so restock alerts trigger again
            alert_sent_flag = False

        await repo.update_product_state(
            self.settings.database_path,
            product.id,
            status=new_status,
            title=state.title or product.title,
            price=state.price or product.price,
            alert_sent_for_current_stock_state=alert_sent_flag,
            consecutive_failures=0,
            next_check_at=next_check,
            last_checked_at=now,
            last_status_changed_at=last_status_changed_at if status_changed else None,
        )

        if should_alert:
            logger.info(f"TELEGRAM_ALERT_SEND | ASIN={asin}")
            updated = await repo.get_product_by_id(self.settings.database_path, product.id)
            target = updated or product
            if state.title:
                target.title = state.title
            if state.price:
                target.price = state.price

            await self._send_alert_safe(target, now)

    async def check_shared_product(self, product: Product) -> None:
        """
        Check a shared Product instance and fan-out alerts to all subscribed user watches.
        """
        asin = product.asin
        now = datetime.now(timezone.utc)

        amazon_request_started_at = datetime.now(timezone.utc)

        watches_and_users = await repo.list_watches_for_product(self.settings.database_path, product.id)
        effective_mode = MonitoringMode.NORMAL
        for watch, _ in watches_and_users:
            if watch.monitoring_mode == MonitoringMode.TURBO:
                effective_mode = MonitoringMode.TURBO
                break

        logger.info(f"CHECK_START | Shared ASIN={asin} | mode={effective_mode.value} | prev_status={product.status.value}")

        html, error = await self.http_client.fetch_product_page(product.canonical_url, asin)
        amazon_response_received_at = datetime.now(timezone.utc)

        if error:
            await self._handle_shared_fetch_error(product, error, now, effective_mode)
            return

        state = parse_product_page(html, asin)
        stock_detected_at = datetime.now(timezone.utc)

        new_status = _map_status(state.status)

        fetch_ms = (amazon_response_received_at - amazon_request_started_at).total_seconds() * 1000.0
        parse_ms = (stock_detected_at - amazon_response_received_at).total_seconds() * 1000.0

        logger.info(
            f"CHECK_RESULT | Shared ASIN={asin} "
            f"| previous={product.status.value} current={new_status.value} "
            f"| confidence={state.confidence:.2f} price={state.price} "
            f"| fetch_ms={fetch_ms:.1f} parse_ms={parse_ms:.1f}"
        )

        status_changed = new_status != product.status
        next_check = _compute_next_check(effective_mode, self.settings, failures=0, status=new_status)

        await repo.update_shared_product_state(
            self.settings.database_path,
            product.id,
            status=new_status,
            title=state.title or product.title,
            price=state.price or product.price,
            consecutive_failures=0,
            next_check_at=next_check,
            last_checked_at=now,
        )

        # Fan-out alerts to subscribers
        for watch, user in watches_and_users:
            try:
                alert_sent_flag = watch.alert_sent_for_current_stock_state
                should_alert = False
                watch_status_changed_at = watch.last_status_changed_at

                if status_changed:
                    watch_status_changed_at = now

                if new_status == StockStatus.IN_STOCK:
                    if state.is_confident_in_stock and not watch.alert_sent_for_current_stock_state:
                        should_alert = True
                        alert_sent_flag = True
                elif new_status in (StockStatus.OUT_OF_STOCK, StockStatus.UNKNOWN):
                    # Reset alert flag so future restocks alert again
                    alert_sent_flag = False

                await repo.update_user_watch_state(
                    self.settings.database_path,
                    watch.id,
                    alert_sent_for_current_stock_state=alert_sent_flag,
                    last_status_changed_at=watch_status_changed_at if status_changed else None,
                )

                if should_alert and user.telegram_chat_id:
                    logger.info(f"FANOUT_ALERT | ASIN={asin} -> user_id={user.id} chat_id={user.telegram_chat_id}")
                    target_prod = Product(
                        id=product.id,
                        asin=product.asin,
                        canonical_url=product.canonical_url,
                        title=state.title or product.title,
                        status=new_status,
                        price=state.price or product.price,
                    )
                    await self._send_fanout_alert_safe(user.telegram_chat_id, target_prod, watch.id, now)
            except Exception as e:
                logger.error(f"Error evaluating fan-out for watch_id={watch.id}: {e}", exc_info=True)

    async def _handle_fetch_error(
        self,
        product: WatchedProduct,
        error: str,
        now: datetime,
    ) -> None:
        asin = product.asin
        new_failures = product.consecutive_failures + 1

        is_blocked = error.startswith("BLOCKED:")
        new_status = StockStatus.BLOCKED if is_blocked else StockStatus.ERROR

        logger.warning(
            f"CHECK_FAILURE | ASIN={asin} | error={error} | failures={new_failures}"
        )

        next_check = _compute_next_check(
            product.monitoring_mode,
            self.settings,
            failures=new_failures,
            status=new_status,
        )

        status_to_save = new_status
        if product.status == StockStatus.IN_STOCK:
            status_to_save = StockStatus.IN_STOCK

        await repo.update_product_state(
            self.settings.database_path,
            product.id,
            status=status_to_save,
            consecutive_failures=new_failures,
            next_check_at=next_check,
            last_checked_at=now,
        )

    async def _handle_shared_fetch_error(
        self,
        product: Product,
        error: str,
        now: datetime,
        mode: MonitoringMode,
    ) -> None:
        asin = product.asin
        new_failures = product.consecutive_failures + 1

        is_blocked = error.startswith("BLOCKED:")
        new_status = StockStatus.BLOCKED if is_blocked else StockStatus.ERROR

        logger.warning(f"SHARED_CHECK_FAILURE | ASIN={asin} | error={error} | failures={new_failures}")

        next_check = _compute_next_check(mode, self.settings, failures=new_failures, status=new_status)

        status_to_save = new_status
        if product.status == StockStatus.IN_STOCK:
            status_to_save = StockStatus.IN_STOCK

        await repo.update_shared_product_state(
            self.settings.database_path,
            product.id,
            status=status_to_save,
            consecutive_failures=new_failures,
            next_check_at=next_check,
            last_checked_at=now,
        )

    async def _send_alert_safe(
        self, product: WatchedProduct, detected_at: datetime
    ) -> None:
        try:
            await self.alert_manager.send_in_stock_alert(product, detected_at)
            logger.info(f"TELEGRAM_ALERT_SUCCESS | ASIN={product.asin}")
            await repo.update_product_state(
                self.settings.database_path,
                product.id,
                last_alerted_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            logger.error(
                f"TELEGRAM_ALERT_FAILED | ASIN={product.asin} | error={e}",
                exc_info=True,
            )

    async def _send_fanout_alert_safe(
        self, chat_id: int, product: Product, watch_id: int, detected_at: datetime
    ) -> None:
        telegram_send_started_at = datetime.now(timezone.utc)
        try:
            await self.alert_manager.send_in_stock_alert_to(chat_id, product, detected_at)
            telegram_send_completed_at = datetime.now(timezone.utc)

            tg_ms = (telegram_send_completed_at - telegram_send_started_at).total_seconds() * 1000.0
            logger.info(f"FANOUT_ALERT_SUCCESS | chat_id={chat_id} ASIN={product.asin} tg_ms={tg_ms:.1f}")

            await repo.update_user_watch_state(
                self.settings.database_path,
                watch_id,
                last_alerted_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            logger.error(
                f"FANOUT_ALERT_FAILED | chat_id={chat_id} ASIN={product.asin} | error={e}",
                exc_info=True,
            )


def _map_status(amazon_status: AmazonStatus) -> StockStatus:
    mapping = {
        AmazonStatus.IN_STOCK: StockStatus.IN_STOCK,
        AmazonStatus.OUT_OF_STOCK: StockStatus.OUT_OF_STOCK,
        AmazonStatus.UNKNOWN: StockStatus.UNKNOWN,
        AmazonStatus.BLOCKED: StockStatus.BLOCKED,
        AmazonStatus.ERROR: StockStatus.ERROR,
    }
    return mapping.get(amazon_status, StockStatus.UNKNOWN)


def _compute_next_check(
    mode: MonitoringMode,
    settings: Settings,
    failures: int,
    status: StockStatus = StockStatus.UNKNOWN,
) -> datetime:
    now = datetime.now(timezone.utc)

    # While IN_STOCK, take a clean 30-second break interval to avoid spamming requests
    if status == StockStatus.IN_STOCK and failures == 0:
        delay = 30.0
        jitter_max = 5.0
    elif mode == MonitoringMode.TURBO:
        delay = float(settings.turbo_check_interval_seconds)
        jitter_max = float(settings.turbo_jitter_seconds)
    else:
        delay = float(settings.fast_check_interval_seconds)
        jitter_max = float(settings.fast_jitter_seconds)

    if failures > 0:
        backoff = min(
            delay * (2 ** (failures - 1)),
            float(settings.max_failure_backoff_seconds),
        )
        delay = backoff

    jitter = random.uniform(0, jitter_max)
    total_delay = delay + jitter

    return now + timedelta(seconds=total_delay)
