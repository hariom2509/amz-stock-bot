"""
Database initialization and dual engine support (SQLite & PostgreSQL Connection Pooling).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional, Any

import aiosqlite

try:
    import psycopg
    from psycopg.rows import tuple_row
    from psycopg_pool import AsyncConnectionPool
    HAS_PSYCOPG = True
except ImportError:
    HAS_PSYCOPG = False

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2

# Global Connection Pool for PostgreSQL
_PG_POOL: Optional[Any] = None


def is_postgres(target: str) -> bool:
    target = target.lower()
    return target.startswith("postgres://") or target.startswith("postgresql://")


async def get_pg_pool(db_url: str) -> Any:
    global _PG_POOL
    if _PG_POOL is None:
        if db_url.startswith("postgres://"):
            db_url = "postgresql://" + db_url[11:]
        _PG_POOL = AsyncConnectionPool(
            conninfo=db_url,
            min_size=2,
            max_size=10,
            open=False,
            kwargs={"row_factory": tuple_row},
        )
        await _PG_POOL.open()
        logger.info("PostgreSQL AsyncConnectionPool opened successfully!")
    return _PG_POOL


class DatabaseConnection:
    """Async wrapper unifying SQLite and pooled PostgreSQL operations."""

    def __init__(self, db_target: str):
        env_url = os.getenv("DATABASE_URL", "")
        if env_url and is_postgres(env_url):
            self.db_target = env_url
        else:
            self.db_target = db_target

        self.is_pg = is_postgres(self.db_target)
        if self.is_pg and self.db_target.startswith("postgres://"):
            self.db_target = "postgresql://" + self.db_target[11:]

        self._conn: Any = None
        self._pool_conn_ctx: Any = None

    async def __aenter__(self) -> "DatabaseConnection":
        if self.is_pg:
            if not HAS_PSYCOPG:
                raise RuntimeError("psycopg package required for PostgreSQL support")
            pool = await get_pg_pool(self.db_target)
            self._pool_conn_ctx = pool.connection()
            self._conn = await self._pool_conn_ctx.__aenter__()
        else:
            db_path = Path(self.db_target)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(self.db_target)
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA foreign_keys=ON")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.is_pg:
            if self._pool_conn_ctx:
                await self._pool_conn_ctx.__aexit__(exc_type, exc_val, exc_tb)
        else:
            if self._conn:
                await self._conn.close()

    async def execute(self, query: str, params: tuple = ()) -> Any:
        if self.is_pg:
            pg_query = query.replace("?", "%s")
            cursor = await self._conn.execute(pg_query, params)
            return cursor
        else:
            return await self._conn.execute(query, params)

    async def executescript(self, sql_script: str) -> None:
        if self.is_pg:
            statements = [s.strip() for s in sql_script.split(";") if s.strip()]
            for stmt in statements:
                stmt_pg = stmt.replace("AUTOINCREMENT", "").replace("?", "%s")
                await self._conn.execute(stmt_pg)
        else:
            await self._conn.executescript(sql_script)

    async def fetchone(self, query: str, params: tuple = ()) -> Optional[tuple]:
        if self.is_pg:
            pg_query = query.replace("?", "%s")
            cursor = await self._conn.execute(pg_query, params)
            return await cursor.fetchone()
        else:
            cursor = await self._conn.execute(query, params)
            row = await cursor.fetchone()
            return tuple(row) if row else None

    async def fetchall(self, query: str, params: tuple = ()) -> list[tuple]:
        if self.is_pg:
            pg_query = query.replace("?", "%s")
            cursor = await self._conn.execute(pg_query, params)
            return await cursor.fetchall()
        else:
            cursor = await self._conn.execute(query, params)
            rows = await cursor.fetchall()
            return [tuple(r) for r in rows]

    async def commit(self) -> None:
        await self._conn.commit()


async def init_db(database_path: str) -> None:
    env_url = os.getenv("DATABASE_URL", "")
    target = env_url if (env_url and is_postgres(env_url)) else database_path

    logger.info(f"Initializing database target: {target}")

    async with DatabaseConnection(target) as db:
        if db.is_pg:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id                      SERIAL PRIMARY KEY,
                    public_id               TEXT NOT NULL UNIQUE,
                    auth_token_hash         TEXT NOT NULL UNIQUE,
                    telegram_chat_id        BIGINT UNIQUE,
                    telegram_connected_at    TEXT,
                    created_at              TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
                    updated_at              TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS telegram_link_tokens (
                    id          SERIAL PRIMARY KEY,
                    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_hash  TEXT NOT NULL UNIQUE,
                    expires_at  TEXT NOT NULL,
                    used_at     TEXT,
                    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id                      SERIAL PRIMARY KEY,
                    asin                    TEXT NOT NULL UNIQUE,
                    canonical_url           TEXT NOT NULL,
                    title                   TEXT,
                    status                  TEXT NOT NULL DEFAULT 'UNKNOWN',
                    price                   TEXT,
                    currency                TEXT NOT NULL DEFAULT 'INR',
                    consecutive_failures    INTEGER NOT NULL DEFAULT 0,
                    last_checked_at         TEXT,
                    next_check_at           TEXT,
                    created_at              TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
                    updated_at              TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_watches (
                    id                                  SERIAL PRIMARY KEY,
                    user_id                             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    product_id                          INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    monitoring_enabled                  INTEGER NOT NULL DEFAULT 1,
                    monitoring_mode                     TEXT NOT NULL DEFAULT 'NORMAL',
                    alert_sent_for_current_stock_state  INTEGER NOT NULL DEFAULT 0,
                    last_alerted_at                     TEXT,
                    last_status_changed_at              TEXT,
                    created_at                          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
                    updated_at                          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
                    UNIQUE(user_id, product_id)
                );
            """)
            await db.commit()
            logger.info("PostgreSQL schema initialized successfully!")
            return

        # SQLite Schema Initialization
        await db.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER NOT NULL
            )
        """)

        row = await db.fetchone("SELECT version FROM schema_version")
        current_version = row[0] if row else 0

        if current_version < 1:
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

        if current_version < 2:
            migrations_dir = Path(__file__).parent.parent.parent / "migrations"
            mig1 = migrations_dir / "001_initial_multiuser_schema.sql"
            if mig1.exists():
                sql1 = mig1.read_text(encoding="utf-8")
                await db.executescript(sql1)

            await db.execute("DELETE FROM schema_version")
            await db.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
            )

        await db.commit()
        logger.info(f"SQLite database initialized at schema version {SCHEMA_VERSION}")


def get_db_path(database_path: str) -> str:
    env_url = os.getenv("DATABASE_URL", "")
    if env_url and is_postgres(env_url):
        return env_url
    return database_path
