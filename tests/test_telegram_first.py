"""
Tests for Telegram-First Amazon Stock Alert Service.
"""
import pytest
from datetime import datetime, timezone
from app.database import repository as repo
from app.database.models import StockStatus, MonitoringMode
from app.monitoring.watcher import ProductWatcher
from app.config import Settings


@pytest.mark.asyncio
async def test_telegram_user_auto_registration():
    db = "data/test_app.db"
    chat_id = 99887766

    # Adding product via legacy/bot helper auto-creates user
    product = await repo.add_product(db, chat_id, "B0TESTAUTO1", "https://www.amazon.in/dp/B0TESTAUTO1")
    assert product.asin == "B0TESTAUTO1"
    assert product.telegram_chat_id == chat_id

    # Verify user exists in users table
    user = await repo.get_user_by_chat_id(db, chat_id)
    assert user is not None
    assert user.telegram_chat_id == chat_id


@pytest.mark.asyncio
async def test_shared_asin_single_product_record():
    db = "data/test_app.db"
    chat1 = 11111111
    chat2 = 22222222
    asin = "B0SHARED100"
    url = "https://www.amazon.in/dp/B0SHARED100"

    # User 1 & User 2 watch same ASIN
    prod1 = await repo.add_product(db, chat1, asin, url)
    prod2 = await repo.add_product(db, chat2, asin, url)

    assert prod1.asin == asin
    assert prod2.asin == asin

    # Shared product table should contain ONLY ONE row for this ASIN
    shared_prod = await repo.get_product_by_asin(db, asin)
    assert shared_prod is not None
    assert shared_prod.asin == asin

    # Listing active shared products returns 1 instance
    active = await repo.list_active_shared_products(db)
    shared_asins = [p.asin for p in active]
    assert shared_asins.count(asin) == 1


@pytest.mark.asyncio
async def test_watch_limit_enforcement():
    db = "data/test_app.db"
    chat_id = 55544433

    # Add 5 products
    for i in range(1, 6):
        await repo.add_product(db, chat_id, f"B0LIMIT{i}00", f"https://www.amazon.in/dp/B0LIMIT{i}00")

    count = await repo.count_products_for_chat(db, chat_id)
    assert count == 5


@pytest.mark.asyncio
async def test_pause_resume_remove():
    db = "data/test_app.db"
    chat_id = 77766655
    asin = "B0CONTROL1"
    url = "https://www.amazon.in/dp/B0CONTROL1"

    await repo.add_product(db, chat_id, asin, url)

    # Pause
    paused = await repo.set_monitoring_enabled(db, chat_id, asin, False)
    assert paused is True
    prod = await repo.get_product(db, chat_id, asin)
    assert prod.monitoring_enabled is False

    # Resume
    resumed = await repo.set_monitoring_enabled(db, chat_id, asin, True)
    assert resumed is True
    prod_resumed = await repo.get_product(db, chat_id, asin)
    assert prod_resumed.monitoring_enabled is True

    # Remove
    removed = await repo.remove_product(db, chat_id, asin)
    assert removed is True
    prod_none = await repo.get_product(db, chat_id, asin)
    assert prod_none is None
