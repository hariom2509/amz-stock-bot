"""
Internal Mocked Latency Benchmark Test.

Measures the internal pipeline execution time:
  Scheduler due time -> Checker invocation -> IN_STOCK parse -> Alert dispatch

Note: This benchmark measures internal Python/asyncio execution overhead only.
It does NOT measure real-world network transmission to Amazon or Telegram API delivery.
"""
import asyncio
import time
from datetime import datetime, timezone
import pytest

from app.amazon.models import ProductState, StockStatus as AmazonStatus
from app.config import Settings
from app.database import repository as repo
from app.database.models import StockStatus, Product
from app.monitoring.watcher import ProductWatcher


class MockAmazonClient:
    """Mock HTTP client returning instantaneous in-stock HTML."""
    def __init__(self, html_content: str):
        self.html_content = html_content

    async def fetch_product_page(self, url: str, asin: str):
        return self.html_content, None


class MockAlertManager:
    """Mock AlertManager capturing dispatch timestamps."""
    def __init__(self):
        self.alerts_sent = []

    async def send_in_stock_alert_to(self, chat_id: int, product, detected_at: datetime):
        self.alerts_sent.append({
            "chat_id": chat_id,
            "asin": product.asin,
            "dispatch_time": time.perf_counter(),
            "detected_at": detected_at,
        })

    async def send_in_stock_alert(self, product, detected_at: datetime):
        await self.send_in_stock_alert_to(product.telegram_chat_id, product, detected_at)


@pytest.mark.asyncio
async def test_internal_pipeline_latency_benchmark():
    import uuid
    db = f"data/test_benchmark_{uuid.uuid4().hex[:8]}.db"
    chat_id = 12345678
    asin = "B0BENCHMARK1"
    url = f"https://www.amazon.in/dp/{asin}"

    # Setup database record
    await repo.add_product(db, chat_id, asin, url)
    shared_product = await repo.get_product_by_asin(db, asin)
    assert shared_product is not None


    # In-stock Amazon HTML fixture
    in_stock_html = """
    <html>
        <head><title>Benchmark Product</title></head>
        <body>
            <span id="productTitle">Benchmark In-Stock Wireless Headphones</span>
            <span class="a-price-whole">14,999</span>
            <input type="submit" id="add-to-cart-button" value="Add to Cart" />
            <input type="submit" id="buy-now-button" value="Buy Now" />
            <div id="availability"><span>In Stock.</span></div>
        </body>
    </html>
    """

    mock_client = MockAmazonClient(in_stock_html)
    mock_alerts = MockAlertManager()
    settings = Settings(telegram_bot_token="123456789:TEST_BOT_TOKEN", database_path=db)

    watcher = ProductWatcher(
        settings=settings,
        http_client=mock_client,
        alert_manager=mock_alerts,
    )

    # Measure internal execution pipeline
    t_start = time.perf_counter()
    await watcher.check_shared_product(shared_product)
    t_end = time.perf_counter()

    total_internal_ms = (t_end - t_start) * 1000.0

    print(f"\n[LATENCY BENCHMARK RESULT]")
    print(f"   Internal Pipeline Latency: {total_internal_ms:.2f} ms")
    assert len(mock_alerts.alerts_sent) == 1
    assert mock_alerts.alerts_sent[0]["asin"] == asin
    assert total_internal_ms < 50.0  # Internal code execution should take < 50ms
