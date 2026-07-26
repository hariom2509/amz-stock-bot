"""
Pytest configuration and environment setup fixture.
"""
import os
import asyncio
import pytest
from app.database.db import init_db

TEST_DB_PATH = "data/test_app.db"

os.environ["TELEGRAM_BOT_TOKEN"] = "123456789:TEST_BOT_TOKEN_FOR_PYTEST"
os.environ["DATABASE_PATH"] = TEST_DB_PATH
os.environ["BOT_USERNAME"] = "TestStockWatcherBot"


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Initialize DB schema for tests once per session."""
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except OSError:
            pass

    asyncio.run(init_db(TEST_DB_PATH))
    yield

    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except OSError:
            pass
