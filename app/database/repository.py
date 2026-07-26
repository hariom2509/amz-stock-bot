"""
Database repository — all CRUD operations for Users, Link Tokens, Products, and UserWatches.

Uses aiosqlite for async access with connection-per-operation pattern.
Maintains full backward compatibility for WatchedProduct helpers.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import aiosqlite

from app.database.models import (
    User,
    TelegramLinkToken,
    Product,
    UserWatch,
    WatchedProduct,
    StockStatus,
    MonitoringMode,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(v: Optional[str]) -> Optional[datetime]:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _dt_str(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat()


# ── USER CRUD ─────────────────────────────────────────────────────────────

async def create_user(
    db_path: str,
    public_id: str,
    auth_token_hash: str,
) -> User:
    """Create a new user / device identity."""
    now = _now_iso()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """
            INSERT INTO users (public_id, auth_token_hash, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (public_id, auth_token_hash, now, now),
        )
        await db.commit()

        cursor = await db.execute(
            "SELECT id, public_id, auth_token_hash, telegram_chat_id, "
            "telegram_connected_at, created_at, updated_at FROM users WHERE public_id = ?",
            (public_id,),
        )
        row = await cursor.fetchone()
        return _row_to_user(tuple(row))


async def get_user_by_token_hash(db_path: str, auth_token_hash: str) -> Optional[User]:
    """Look up user by hashed auth token."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, public_id, auth_token_hash, telegram_chat_id, "
            "telegram_connected_at, created_at, updated_at FROM users WHERE auth_token_hash = ?",
            (auth_token_hash,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return _row_to_user(tuple(row))


async def get_user_by_public_id(db_path: str, public_id: str) -> Optional[User]:
    """Look up user by public_id UUID."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, public_id, auth_token_hash, telegram_chat_id, "
            "telegram_connected_at, created_at, updated_at FROM users WHERE public_id = ?",
            (public_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return _row_to_user(tuple(row))


async def get_user_by_chat_id(db_path: str, chat_id: int) -> Optional[User]:
    """Look up user by linked Telegram chat ID."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, public_id, auth_token_hash, telegram_chat_id, "
            "telegram_connected_at, created_at, updated_at FROM users WHERE telegram_chat_id = ?",
            (chat_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return _row_to_user(tuple(row))


async def link_user_telegram(db_path: str, user_id: int, chat_id: int) -> bool:
    """Link a user account to a Telegram chat ID."""
    now = _now_iso()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "UPDATE users SET telegram_chat_id = ?, telegram_connected_at = ?, updated_at = ? "
            "WHERE id = ?",
            (chat_id, now, now, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def unlink_user_telegram(db_path: str, user_id: int) -> bool:
    """Disconnect Telegram chat ID from a user account."""
    now = _now_iso()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "UPDATE users SET telegram_chat_id = NULL, telegram_connected_at = NULL, updated_at = ? "
            "WHERE id = ?",
            (now, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


def _row_to_user(row: tuple) -> User:
    return User(
        id=row[0],
        public_id=row[1],
        auth_token_hash=row[2],
        telegram_chat_id=row[3],
        telegram_connected_at=_parse_dt(row[4]),
        created_at=_parse_dt(row[5]),
        updated_at=_parse_dt(row[6]),
    )


# ── TELEGRAM LINK TOKENS ───────────────────────────────────────────────────

async def create_link_token(
    db_path: str,
    user_id: int,
    token_hash: str,
    expires_at: datetime,
) -> TelegramLinkToken:
    """Save a temporary link token."""
    now = _now_iso()
    exp_str = expires_at.isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO telegram_link_tokens (user_id, token_hash, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, token_hash, exp_str, now),
        )
        await db.commit()

        cursor = await db.execute(
            "SELECT id, user_id, token_hash, expires_at, used_at, created_at "
            "FROM telegram_link_tokens WHERE token_hash = ?",
            (token_hash,),
        )
        row = await cursor.fetchone()
        return _row_to_token(tuple(row))


async def consume_link_token(db_path: str, token_hash: str) -> Optional[TelegramLinkToken]:
    """Find and consume a link token. Returns token if valid, None if invalid/expired/used."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, user_id, token_hash, expires_at, used_at, created_at "
            "FROM telegram_link_tokens WHERE token_hash = ?",
            (token_hash,),
        )
        row = await cursor.fetchone()
        if not row:
            return None

        token = _row_to_token(tuple(row))
        if not token.is_valid:
            return None

        now = _now_iso()
        await db.execute(
            "UPDATE telegram_link_tokens SET used_at = ? WHERE id = ?",
            (now, token.id),
        )
        await db.commit()
        token.used_at = _parse_dt(now)
        return token


def _row_to_token(row: tuple) -> TelegramLinkToken:
    return TelegramLinkToken(
        id=row[0],
        user_id=row[1],
        token_hash=row[2],
        expires_at=_parse_dt(row[3]),
        used_at=_parse_dt(row[4]),
        created_at=_parse_dt(row[5]),
    )


# ── SHARED PRODUCTS CRUD ───────────────────────────────────────────────────

async def get_or_create_product(
    db_path: str,
    asin: str,
    canonical_url: str,
) -> Product:
    """Get an existing Product by ASIN, or create it if not found."""
    now = _now_iso()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, asin, canonical_url, title, status, price, currency, "
            "consecutive_failures, last_checked_at, next_check_at, created_at, updated_at "
            "FROM products WHERE asin = ?",
            (asin,),
        )
        row = await cursor.fetchone()
        if row:
            return _row_to_product(tuple(row))

        # Insert new product
        await db.execute(
            """
            INSERT INTO products (asin, canonical_url, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (asin, canonical_url, now, now),
        )
        await db.commit()

        cursor = await db.execute(
            "SELECT id, asin, canonical_url, title, status, price, currency, "
            "consecutive_failures, last_checked_at, next_check_at, created_at, updated_at "
            "FROM products WHERE asin = ?",
            (asin,),
        )
        row = await cursor.fetchone()
        return _row_to_product(tuple(row))


async def get_product_by_asin(db_path: str, asin: str) -> Optional[Product]:
    """Get product by ASIN."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, asin, canonical_url, title, status, price, currency, "
            "consecutive_failures, last_checked_at, next_check_at, created_at, updated_at "
            "FROM products WHERE asin = ?",
            (asin,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return _row_to_product(tuple(row))


async def get_product_by_id_product(db_path: str, product_id: int) -> Optional[Product]:
    """Get product by DB ID."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, asin, canonical_url, title, status, price, currency, "
            "consecutive_failures, last_checked_at, next_check_at, created_at, updated_at "
            "FROM products WHERE id = ?",
            (product_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return _row_to_product(tuple(row))


async def list_active_shared_products(db_path: str) -> List[Product]:
    """List all products that have at least one active user_watch."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            SELECT DISTINCT p.id, p.asin, p.canonical_url, p.title, p.status, p.price, p.currency,
                            p.consecutive_failures, p.last_checked_at, p.next_check_at, p.created_at, p.updated_at
            FROM products p
            JOIN user_watches uw ON uw.product_id = p.id
            WHERE uw.monitoring_enabled = 1
            ORDER BY p.next_check_at ASC NULLS FIRST
            """
        )
        rows = await cursor.fetchall()
        return [_row_to_product(tuple(r)) for r in rows]


async def update_shared_product_state(
    db_path: str,
    product_id: int,
    *,
    status: Optional[StockStatus] = None,
    title: Optional[str] = None,
    price: Optional[str] = None,
    consecutive_failures: Optional[int] = None,
    next_check_at: Optional[datetime] = None,
    last_checked_at: Optional[datetime] = None,
) -> None:
    """Update shared product Amazon status and check schedule."""
    updates: list[str] = []
    params: list = []

    def _add(col: str, val) -> None:
        updates.append(f"{col} = ?")
        params.append(val)

    if status is not None:
        _add("status", status.value)
    if title is not None:
        _add("title", title)
    if price is not None:
        _add("price", price)
    if consecutive_failures is not None:
        _add("consecutive_failures", consecutive_failures)
    if next_check_at is not None:
        _add("next_check_at", _dt_str(next_check_at))
    if last_checked_at is not None:
        _add("last_checked_at", _dt_str(last_checked_at))

    if not updates:
        return

    _add("updated_at", _now_iso())
    params.append(product_id)

    sql = f"UPDATE products SET {', '.join(updates)} WHERE id = ?"
    async with aiosqlite.connect(db_path) as db:
        await db.execute(sql, params)
        await db.commit()


def _row_to_product(row: tuple) -> Product:
    return Product(
        id=row[0],
        asin=row[1],
        canonical_url=row[2],
        title=row[3],
        status=StockStatus(row[4]),
        price=row[5],
        currency=row[6],
        consecutive_failures=row[7],
        last_checked_at=_parse_dt(row[8]),
        next_check_at=_parse_dt(row[9]),
        created_at=_parse_dt(row[10]),
        updated_at=_parse_dt(row[11]),
    )


# ── USER WATCHES CRUD ──────────────────────────────────────────────────────

async def add_user_watch(
    db_path: str,
    user_id: int,
    product_id: int,
) -> UserWatch:
    """Subscribe a user to a product. Raises ValueError if already watching."""
    now = _now_iso()
    async with aiosqlite.connect(db_path) as db:
        try:
            await db.execute(
                """
                INSERT INTO user_watches (user_id, product_id, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, product_id, now, now),
            )
            await db.commit()
        except Exception as e:
            if "UNIQUE constraint failed" in str(e):
                raise ValueError("You are already watching this product")
            raise

        cursor = await db.execute(
            """
            SELECT id, user_id, product_id, monitoring_enabled, monitoring_mode,
                   alert_sent_for_current_stock_state, last_alerted_at, last_status_changed_at,
                   created_at, updated_at
            FROM user_watches WHERE user_id = ? AND product_id = ?
            """,
            (user_id, product_id),
        )
        row = await cursor.fetchone()
        return _row_to_watch(tuple(row))


async def get_user_watch(
    db_path: str,
    user_id: int,
    product_id: int,
) -> Optional[UserWatch]:
    """Get a user's watch for a specific product."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            SELECT id, user_id, product_id, monitoring_enabled, monitoring_mode,
                   alert_sent_for_current_stock_state, last_alerted_at, last_status_changed_at,
                   created_at, updated_at
            FROM user_watches WHERE user_id = ? AND product_id = ?
            """,
            (user_id, product_id),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return _row_to_watch(tuple(row))


async def list_user_watches(db_path: str, user_id: int) -> List[Tuple[UserWatch, Product]]:
    """List all product watches for a user joined with product info."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            SELECT uw.id, uw.user_id, uw.product_id, uw.monitoring_enabled, uw.monitoring_mode,
                   uw.alert_sent_for_current_stock_state, uw.last_alerted_at, uw.last_status_changed_at,
                   uw.created_at, uw.updated_at,
                   p.id, p.asin, p.canonical_url, p.title, p.status, p.price, p.currency,
                   p.consecutive_failures, p.last_checked_at, p.next_check_at, p.created_at, p.updated_at
            FROM user_watches uw
            JOIN products p ON p.id = uw.product_id
            WHERE uw.user_id = ?
            ORDER BY uw.created_at ASC
            """,
            (user_id,),
        )
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            watch = _row_to_watch(r[0:10])
            product = _row_to_product(r[10:22])
            result.append((watch, product))
        return result


async def list_watches_for_product(db_path: str, product_id: int) -> List[Tuple[UserWatch, User]]:
    """List all user subscriptions for a given product (used for alert fan-out)."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            SELECT uw.id, uw.user_id, uw.product_id, uw.monitoring_enabled, uw.monitoring_mode,
                   uw.alert_sent_for_current_stock_state, uw.last_alerted_at, uw.last_status_changed_at,
                   uw.created_at, uw.updated_at,
                   u.id, u.public_id, u.auth_token_hash, u.telegram_chat_id,
                   u.telegram_connected_at, u.created_at, u.updated_at
            FROM user_watches uw
            JOIN users u ON u.id = uw.user_id
            WHERE uw.product_id = ? AND uw.monitoring_enabled = 1
            """,
            (product_id,),
        )
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            watch = _row_to_watch(r[0:10])
            user = _row_to_user(r[10:17])
            result.append((watch, user))
        return result


async def update_user_watch_state(
    db_path: str,
    watch_id: int,
    *,
    monitoring_enabled: Optional[bool] = None,
    monitoring_mode: Optional[MonitoringMode] = None,
    alert_sent_for_current_stock_state: Optional[bool] = None,
    last_alerted_at: Optional[datetime] = None,
    last_status_changed_at: Optional[datetime] = None,
) -> None:
    """Update subscription settings or notification state for a user watch."""
    updates: list[str] = []
    params: list = []

    def _add(col: str, val) -> None:
        updates.append(f"{col} = ?")
        params.append(val)

    if monitoring_enabled is not None:
        _add("monitoring_enabled", int(monitoring_enabled))
    if monitoring_mode is not None:
        _add("monitoring_mode", monitoring_mode.value)
    if alert_sent_for_current_stock_state is not None:
        _add("alert_sent_for_current_stock_state", int(alert_sent_for_current_stock_state))
    if last_alerted_at is not None:
        _add("last_alerted_at", _dt_str(last_alerted_at))
    if last_status_changed_at is not None:
        _add("last_status_changed_at", _dt_str(last_status_changed_at))

    if not updates:
        return

    _add("updated_at", _now_iso())
    params.append(watch_id)

    sql = f"UPDATE user_watches SET {', '.join(updates)} WHERE id = ?"
    async with aiosqlite.connect(db_path) as db:
        await db.execute(sql, params)
        await db.commit()


async def remove_user_watch(db_path: str, user_id: int, product_id: int) -> bool:
    """Delete a user watch. Clean up orphaned Product if no subscribers remain."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "DELETE FROM user_watches WHERE user_id = ? AND product_id = ?",
            (user_id, product_id),
        )
        await db.commit()
        deleted = cursor.rowcount > 0

        if deleted:
            # Check remaining subscribers
            c = await db.execute(
                "SELECT COUNT(*) FROM user_watches WHERE product_id = ?", (product_id,)
            )
            count = (await c.fetchone())[0]
            if count == 0:
                await db.execute("DELETE FROM products WHERE id = ?", (product_id,))
                await db.commit()

        return deleted


async def count_user_watches(db_path: str, user_id: int) -> int:
    """Count total watches for a user."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM user_watches WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


async def count_user_turbo_watches(db_path: str, user_id: int) -> int:
    """Count active turbo watches for a user."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM user_watches WHERE user_id = ? AND monitoring_mode = 'TURBO' AND monitoring_enabled = 1",
            (user_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


def _row_to_watch(row: tuple) -> UserWatch:
    return UserWatch(
        id=row[0],
        user_id=row[1],
        product_id=row[2],
        monitoring_enabled=bool(row[3]),
        monitoring_mode=MonitoringMode(row[4]),
        alert_sent_for_current_stock_state=bool(row[5]),
        last_alerted_at=_parse_dt(row[6]),
        last_status_changed_at=_parse_dt(row[7]),
        created_at=_parse_dt(row[8]),
        updated_at=_parse_dt(row[9]),
    )


# ── BACKWARD COMPATIBILITY HELPERS (FOR LEGACY BOT & TESTS) ────────────────

async def add_product(db_path: str, chat_id: int, asin: str, url: str) -> WatchedProduct:
    """Legacy helper: get or create user for chat_id, add watch, return WatchedProduct."""
    user = await get_user_by_chat_id(db_path, chat_id)
    if not user:
        # Create legacy user if not exists
        import secrets
        pub_id = f"legacy_{chat_id}"
        tok_hash = f"legacy_hash_{chat_id}"
        user = await create_user(db_path, pub_id, tok_hash)
        await link_user_telegram(db_path, user.id, chat_id)

    product = await get_or_create_product(db_path, asin, url)
    watch = await add_user_watch(db_path, user.id, product.id)
    return _build_watched_product(chat_id, product, watch)


async def get_product(db_path: str, chat_id: int, asin: str) -> Optional[WatchedProduct]:
    """Legacy helper: get WatchedProduct for chat_id and asin."""
    user = await get_user_by_chat_id(db_path, chat_id)
    if not user:
        return None
    product = await get_product_by_asin(db_path, asin)
    if not product:
        return None
    watch = await get_user_watch(db_path, user.id, product.id)
    if not watch:
        return None
    return _build_watched_product(chat_id, product, watch)


async def get_product_by_id(db_path: str, product_id: int) -> Optional[WatchedProduct]:
    """Legacy helper: get WatchedProduct by combined watch ID."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            SELECT u.telegram_chat_id, p.id, p.asin, p.canonical_url, p.title, p.status, p.price, p.currency,
                   uw.monitoring_enabled, uw.monitoring_mode, p.last_checked_at, uw.last_status_changed_at,
                   uw.last_alerted_at, p.next_check_at, uw.alert_sent_for_current_stock_state,
                   p.consecutive_failures, uw.created_at, uw.updated_at
            FROM user_watches uw
            JOIN products p ON p.id = uw.product_id
            JOIN users u ON u.id = uw.user_id
            WHERE uw.id = ?
            """,
            (product_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return WatchedProduct(
            id=product_id,
            telegram_chat_id=row[0],
            asin=row[2],
            url=row[3],
            title=row[4],
            status=StockStatus(row[5]),
            price=row[6],
            currency=row[7],
            monitoring_enabled=bool(row[8]),
            monitoring_mode=MonitoringMode(row[9]),
            last_checked_at=_parse_dt(row[10]),
            last_status_changed_at=_parse_dt(row[11]),
            last_alerted_at=_parse_dt(row[12]),
            next_check_at=_parse_dt(row[13]),
            alert_sent_for_current_stock_state=bool(row[14]),
            consecutive_failures=row[15],
            created_at=_parse_dt(row[16]),
            updated_at=_parse_dt(row[17]),
        )


async def list_products_for_chat(db_path: str, chat_id: int) -> List[WatchedProduct]:
    """Legacy helper: list all WatchedProducts for chat_id."""
    user = await get_user_by_chat_id(db_path, chat_id)
    if not user:
        return []
    watches = await list_user_watches(db_path, user.id)
    return [_build_watched_product(chat_id, prod, w) for w, prod in watches]


async def list_active_products(db_path: str) -> List[WatchedProduct]:
    """Legacy helper: list active products as WatchedProduct list."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            SELECT uw.id, COALESCE(u.telegram_chat_id, 0), p.asin, p.canonical_url, p.title, p.status, p.price, p.currency,
                   uw.monitoring_enabled, uw.monitoring_mode, p.last_checked_at, uw.last_status_changed_at,
                   uw.last_alerted_at, p.next_check_at, uw.alert_sent_for_current_stock_state,
                   p.consecutive_failures, uw.created_at, uw.updated_at
            FROM user_watches uw
            JOIN products p ON p.id = uw.product_id
            LEFT JOIN users u ON u.id = uw.user_id
            WHERE uw.monitoring_enabled = 1
            ORDER BY p.next_check_at ASC NULLS FIRST
            """
        )
        rows = await cursor.fetchall()
        res = []
        for r in rows:
            res.append(
                WatchedProduct(
                    id=r[0],
                    telegram_chat_id=r[1],
                    asin=r[2],
                    url=r[3],
                    title=r[4],
                    status=StockStatus(r[5]),
                    price=r[6],
                    currency=r[7],
                    monitoring_enabled=bool(r[8]),
                    monitoring_mode=MonitoringMode(r[9]),
                    last_checked_at=_parse_dt(r[10]),
                    last_status_changed_at=_parse_dt(r[11]),
                    last_alerted_at=_parse_dt(r[12]),
                    next_check_at=_parse_dt(r[13]),
                    alert_sent_for_current_stock_state=bool(r[14]),
                    consecutive_failures=r[15],
                    created_at=_parse_dt(r[16]),
                    updated_at=_parse_dt(r[17]),
                )
            )
        return res


async def update_product_state(
    db_path: str,
    product_id: int,
    *,
    status: Optional[StockStatus] = None,
    title: Optional[str] = None,
    price: Optional[str] = None,
    alert_sent_for_current_stock_state: Optional[bool] = None,
    consecutive_failures: Optional[int] = None,
    next_check_at: Optional[datetime] = None,
    last_checked_at: Optional[datetime] = None,
    last_status_changed_at: Optional[datetime] = None,
    last_alerted_at: Optional[datetime] = None,
) -> None:
    """Legacy helper: update state across Product and UserWatch given watch/product ID."""
    # Lookup watch/product association
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT id, product_id FROM user_watches WHERE id = ?", (product_id,)
        )
        row = await cursor.fetchone()
        if row:
            w_id, p_id = row[0], row[1]
            await update_shared_product_state(
                db_path,
                p_id,
                status=status,
                title=title,
                price=price,
                consecutive_failures=consecutive_failures,
                next_check_at=next_check_at,
                last_checked_at=last_checked_at,
            )
            await update_user_watch_state(
                db_path,
                w_id,
                alert_sent_for_current_stock_state=alert_sent_for_current_stock_state,
                last_status_changed_at=last_status_changed_at,
                last_alerted_at=last_alerted_at,
            )
            return

        # If product_id is directly a product ID
        await update_shared_product_state(
            db_path,
            product_id,
            status=status,
            title=title,
            price=price,
            consecutive_failures=consecutive_failures,
            next_check_at=next_check_at,
            last_checked_at=last_checked_at,
        )


async def set_monitoring_enabled(db_path: str, chat_id: int, asin: str, enabled: bool) -> bool:
    user = await get_user_by_chat_id(db_path, chat_id)
    if not user:
        return False
    product = await get_product_by_asin(db_path, asin)
    if not product:
        return False
    watch = await get_user_watch(db_path, user.id, product.id)
    if not watch:
        return False
    await update_user_watch_state(db_path, watch.id, monitoring_enabled=enabled)
    return True


async def set_monitoring_mode(db_path: str, chat_id: int, asin: str, mode: MonitoringMode) -> bool:
    user = await get_user_by_chat_id(db_path, chat_id)
    if not user:
        return False
    product = await get_product_by_asin(db_path, asin)
    if not product:
        return False
    watch = await get_user_watch(db_path, user.id, product.id)
    if not watch:
        return False
    await update_user_watch_state(db_path, watch.id, monitoring_mode=mode)
    return True


async def get_turbo_product_for_chat(db_path: str, chat_id: int) -> Optional[WatchedProduct]:
    user = await get_user_by_chat_id(db_path, chat_id)
    if not user:
        return None
    watches = await list_user_watches(db_path, user.id)
    for w, p in watches:
        if w.monitoring_mode == MonitoringMode.TURBO and w.monitoring_enabled:
            return _build_watched_product(chat_id, p, w)
    return None


async def remove_product(db_path: str, chat_id: int, asin: str) -> bool:
    user = await get_user_by_chat_id(db_path, chat_id)
    if not user:
        return False
    product = await get_product_by_asin(db_path, asin)
    if not product:
        return False
    return await remove_user_watch(db_path, user.id, product.id)


async def count_products_for_chat(db_path: str, chat_id: int) -> int:
    user = await get_user_by_chat_id(db_path, chat_id)
    if not user:
        return 0
    return await count_user_watches(db_path, user.id)


def _build_watched_product(chat_id: int, product: Product, watch: UserWatch) -> WatchedProduct:
    return WatchedProduct(
        id=watch.id,
        telegram_chat_id=chat_id,
        asin=product.asin,
        url=product.canonical_url,
        title=product.title,
        status=product.status,
        price=product.price,
        currency=product.currency,
        monitoring_enabled=watch.monitoring_enabled,
        monitoring_mode=watch.monitoring_mode,
        last_checked_at=product.last_checked_at,
        last_status_changed_at=watch.last_status_changed_at,
        last_alerted_at=watch.last_alerted_at,
        next_check_at=product.next_check_at,
        alert_sent_for_current_stock_state=watch.alert_sent_for_current_stock_state,
        consecutive_failures=product.consecutive_failures,
        created_at=watch.created_at,
        updated_at=watch.updated_at,
    )
