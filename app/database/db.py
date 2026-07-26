"""
SQLite database initialization and migration management.
"""
from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

# Schema version 2 = Multi-User Schema with shared ASIN products
SCHEMA_VERSION = 2


async def init_db(database_path: str) -> None:
    """
    Initialize the SQLite database and apply migrations.
    Called once at application startup.
    """
    db_path = Path(database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Initializing database at: {db_path.resolve()}")

    async with aiosqlite.connect(database_path) as db:
        # Enable WAL mode for better concurrent read performance
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")

        # Create schema version table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER NOT NULL
            )
        """)

        # Get current version
        cursor = await db.execute("SELECT version FROM schema_version")
        row = await cursor.fetchone()
        current_version = row[0] if row else 0

        if current_version < 1:
            # Create original watched_products if starting from scratch
            await db.execute("""
                CREATE TABLE IF NOT EXISTS watched_products (
                    id                              INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_chat_id                INTEGER NOT NULL,
                    asin                            TEXT NOT NULL,
                    url                             TEXT NOT NULL,
                    title                           TEXT,
                    status                          TEXT NOT NULL DEFAULT 'UNKNOWN',
                    price                           TEXT,
                    currency                        TEXT NOT NULL DEFAULT 'INR',
                    monitoring_enabled              INTEGER NOT NULL DEFAULT 1,
                    monitoring_mode                 TEXT NOT NULL DEFAULT 'NORMAL',
                    last_checked_at                 TEXT,
                    last_status_changed_at          TEXT,
                    last_alerted_at                 TEXT,
                    next_check_at                   TEXT,
                    alert_sent_for_current_stock_state  INTEGER NOT NULL DEFAULT 0,
                    consecutive_failures            INTEGER NOT NULL DEFAULT 0,
                    created_at                      TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at                      TEXT NOT NULL DEFAULT (datetime('now')),
                    UNIQUE(telegram_chat_id, asin)
                )
            """)

        # Apply multi-user migration (schema version 2)
        if current_version < 2:
            migrations_dir = Path(__file__).parent.parent.parent / "migrations"
            mig1 = migrations_dir / "001_initial_multiuser_schema.sql"
            if mig1.exists():
                sql1 = mig1.read_text(encoding="utf-8")
                await db.executescript(sql1)

            # Check if watched_products table exists to migrate existing legacy data
            c_wp = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='watched_products'"
            )
            if await c_wp.fetchone():
                mig2 = migrations_dir / "002_migrate_watched_products.sql"
                if mig2.exists():
                    sql2 = mig2.read_text(encoding="utf-8")
                    await db.executescript(sql2)

            # Update version to 2
            await db.execute("DELETE FROM schema_version")
            await db.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
            )

        await db.commit()

    logger.info(f"Database initialized successfully at schema version {SCHEMA_VERSION}")


def get_db_path(database_path: str) -> str:
    """Return the database path string."""
    return database_path
