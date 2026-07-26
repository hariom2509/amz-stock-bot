"""
Async monitoring scheduler for Telegram-First Amazon Stock Watcher.

Continuously loops, finds products due for checking, and runs checks concurrently.
Uses high-resolution scheduling loop (500ms wakeup) to minimize dispatch drift.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Union, TYPE_CHECKING

from app.config import Settings
from app.database import repository as repo
from app.database.models import WatchedProduct, Product, MonitoringMode
from app.monitoring.watcher import ProductWatcher

if TYPE_CHECKING:
    from app.amazon.client import AmazonClient
    from app.alerts.telegram import AlertManager

logger = logging.getLogger(__name__)

# High-resolution wakeup interval (500ms)
_SCHEDULER_POLL_INTERVAL_SECONDS = 0.5


class MonitoringScheduler:
    """
    Central low-latency scheduler for product monitoring.
    """

    def __init__(
        self,
        settings: Settings,
        http_client: "AmazonClient",
        alert_manager: "AlertManager",
    ) -> None:
        self.settings = settings
        self.http_client = http_client
        self.alert_manager = alert_manager

        self._semaphore = asyncio.Semaphore(settings.max_concurrent_checks)
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._active_checks: set[int] = set()

    async def start(self) -> None:
        if self._running:
            logger.warning("Scheduler already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop(), name="monitoring_scheduler")
        logger.info("Monitoring scheduler started (high resolution 500ms poll)")

        products = await repo.list_active_shared_products(self.settings.database_path)
        if products:
            logger.info(
                f"Resuming monitoring for {len(products)} shared product(s): "
                f"{[p.asin for p in products]}"
            )
        else:
            legacy = await repo.list_active_products(self.settings.database_path)
            if legacy:
                logger.info(f"Resuming monitoring for {len(legacy)} legacy product(s)")
            else:
                logger.info("No active products to monitor at startup")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Monitoring scheduler stopped")

    async def _scheduler_loop(self) -> None:
        while self._running:
            try:
                await self._run_due_checks()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}", exc_info=True)

            await asyncio.sleep(_SCHEDULER_POLL_INTERVAL_SECONDS)

    async def _run_due_checks(self) -> None:
        now = datetime.now(timezone.utc)

        products = await repo.list_active_shared_products(self.settings.database_path)
        if not products:
            legacy = await repo.list_active_products(self.settings.database_path)
            if not legacy:
                return
            due_legacy = [
                p for p in legacy
                if self._is_due(p, now) and p.id not in self._active_checks
            ]
            for p in due_legacy:
                asyncio.create_task(self._run_single_check(p), name=f"check_leg_{p.asin}")
            return

        due = [
            p for p in products
            if self._is_due(p, now) and p.id not in self._active_checks
        ]

        if not due:
            return

        logger.debug(f"Scheduler: {len(due)} shared product(s) due for check")

        for p in due:
            # Measure drift if next_check_at was set
            if p.next_check_at:
                check_at = p.next_check_at if p.next_check_at.tzinfo else p.next_check_at.replace(tzinfo=timezone.utc)
                drift_ms = (now - check_at).total_seconds() * 1000.0
                if drift_ms > 1000:
                    logger.debug(f"Scheduler drift for ASIN={p.asin}: {drift_ms:.1f}ms")

            asyncio.create_task(self._run_single_check(p), name=f"check_{p.asin}")

    async def _run_single_check(self, product: Union[Product, WatchedProduct]) -> None:
        async with self._semaphore:
            self._active_checks.add(product.id)
            try:
                watcher = ProductWatcher(
                    settings=self.settings,
                    http_client=self.http_client,
                    alert_manager=self.alert_manager,
                )
                await watcher.check_product(product)
            except Exception as e:
                logger.error(
                    f"Unhandled error in check for ASIN={product.asin}: {e}",
                    exc_info=True,
                )
            finally:
                self._active_checks.discard(product.id)

    def _is_due(self, product: Union[Product, WatchedProduct], now: datetime) -> bool:
        if product.next_check_at is None:
            return True

        check_at = product.next_check_at
        if check_at.tzinfo is None:
            check_at = check_at.replace(tzinfo=timezone.utc)

        return check_at <= now

    async def trigger_immediate_check(self, product: Union[Product, WatchedProduct]) -> None:
        if product.id in self._active_checks:
            logger.info(f"ASIN={product.asin} already being checked, skipping immediate check")
            return

        asyncio.create_task(
            self._run_single_check(product),
            name=f"immediate_check_{product.asin}",
        )
        logger.info(f"Immediate check triggered for ASIN={product.asin}")
