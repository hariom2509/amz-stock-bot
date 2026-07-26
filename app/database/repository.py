"""
Database repository — all CRUD operations for Users, Link Tokens, Products, and UserWatches.

Uses DatabaseConnection wrapper unifying SQLite and PostgreSQL operations.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from app.database.db import DatabaseConnection, is_postgres
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
    now = _now_iso()
    async with DatabaseConnection(db_path) as db:
        await db.execute(
            """
            INSERT INTO users (public_id, auth_token_hash, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (public_id, auth_token_hash, now, now),
        )
        await db.commit()

        row = await db.fetchone(
            "SELECT id, public_id, auth_token_hash, telegram_chat_id, "
            "telegram_connected_at, created_at, updated_at FROM users WHERE public_id = ?",
            (public_id,),
        )
        return _row_to_user(row)


async def get_user_by_token_hash(db_path: str, auth_token_hash: str) -> Optional[User]:
    async with DatabaseConnection(db_path) as db:
        row = await db.fetchone(
            "SELECT id, public_id, auth_token_hash, telegram_chat_id, "
            "telegram_connected_at, created_at, updated_at FROM users WHERE auth_token_hash = ?",
            (auth_token_hash,),
        )
        if not row:
            return None
        return _row_to_user(row)


async def get_user_by_public_id(db_path: str, public_id: str) -> Optional[User]:
    async with DatabaseConnection(db_path) as db:
        row = await db.fetchone(
            "SELECT id, public_id, auth_token_hash, telegram_chat_id, "
            "telegram_connected_at, created_at, updated_at FROM users WHERE public_id = ?",
            (public_id,),
        )
        if not row:
            return None
        return _row_to_user(row)


async def get_user_by_chat_id(db_path: str, chat_id: int) -> Optional[User]:
    async with DatabaseConnection(db_path) as db:
        row = await db.fetchone(
            "SELECT id, public_id, auth_token_hash, telegram_chat_id, "
            "telegram_connected_at, created_at, updated_at FROM users WHERE telegram_chat_id = ?",
            (chat_id,),
        )
        if not row:
            return None
        return _row_to_user(row)


async def link_user_telegram(
    db_path: str, user_id: int, chat_id: int
) -> Optional[User]:
    now = _now_iso()
    async with DatabaseConnection(db_path) as db:
        await db.execute(
            """
            UPDATE users
            SET telegram_chat_id = ?, telegram_connected_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (chat_id, now, now, user_id),
        )
        await db.commit()

        row = await db.fetchone(
            "SELECT id, public_id, auth_token_hash, telegram_chat_id, "
            "telegram_connected_at, created_at, updated_at FROM users WHERE id = ?",
            (user_id,),
        )
        if not row:
            return None
        return _row_to_user(row)


async def disconnect_user_telegram(db_path: str, user_id: int) -> Optional[User]:
    now = _now_iso()
    async with DatabaseConnection(db_path) as db:
        await db.execute(
            """
            UPDATE users
            SET telegram_chat_id = NULL, telegram_connected_at = NULL, updated_at = ?
            WHERE id = ?
            """,
            (now, user_id),
        )
        await db.commit()

        row = await db.fetchone(
            "SELECT id, public_id, auth_token_hash, telegram_chat_id, "
            "telegram_connected_at, created_at, updated_at FROM users WHERE id = ?",
            (user_id,),
        )
        if not row:
            return None
        return _row_to_user(row)


async def create_link_token(
    db_path: str, user_id: int, token_hash: str, expires_at: datetime
) -> TelegramLinkToken:
    return await create_telegram_link_token(db_path, user_id, token_hash, expires_at)


async def unlink_user_telegram(db_path: str, user_id: int) -> Optional[User]:
    return await disconnect_user_telegram(db_path, user_id)


# ── LINK TOKENS CRUD ──────────────────────────────────────────────────────


async def create_telegram_link_token(
    db_path: str, user_id: int, token_hash: str, expires_at: datetime
) -> TelegramLinkToken:
    now = _now_iso()
    exp_str = _dt_str(expires_at)
    async with DatabaseConnection(db_path) as db:
        await db.execute(
            """
            INSERT INTO telegram_link_tokens (user_id, token_hash, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, token_hash, exp_str, now),
        )
        await db.commit()

        row = await db.fetchone(
            "SELECT id, user_id, token_hash, expires_at, used_at, created_at "
            "FROM telegram_link_tokens WHERE token_hash = ?",
            (token_hash,),
        )
        return _row_to_token(row)


async def get_valid_link_token(
    db_path: str, token_hash: str
) -> Optional[TelegramLinkToken]:
    async with DatabaseConnection(db_path) as db:
        row = await db.fetchone(
            "SELECT id, user_id, token_hash, expires_at, used_at, created_at "
            "FROM telegram_link_tokens WHERE token_hash = ? AND used_at IS NULL",
            (token_hash,),
        )
        if not row:
            return None
        token = _row_to_token(row)
        return token if token.is_valid else None


async def mark_link_token_used(db_path: str, token_id: int) -> None:
    now = _now_iso()
    async with DatabaseConnection(db_path) as db:
        await db.execute(
            "UPDATE telegram_link_tokens SET used_at = ? WHERE id = ?",
            (now, token_id),
        )
        await db.commit()


# ── SHARED PRODUCTS CRUD ─────────────────────────────────────────────────

async def get_or_create_shared_product(
    db_path: str, asin: str, canonical_url: str, title: Optional[str] = None
) -> Product:
    now = _now_iso()
    async with DatabaseConnection(db_path) as db:
        row = await db.fetchone(
            "SELECT id, asin, canonical_url, title, status, price, currency, "
            "consecutive_failures, last_checked_at, next_check_at, created_at, updated_at "
            "FROM products WHERE asin = ?",
            (asin,),
        )
        if row:
            return _row_to_shared_product(row)

        await db.execute(
            """
            INSERT INTO products (asin, canonical_url, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (asin, canonical_url, title, now, now),
        )
        await db.commit()

        row = await db.fetchone(
            "SELECT id, asin, canonical_url, title, status, price, currency, "
            "consecutive_failures, last_checked_at, next_check_at, created_at, updated_at "
            "FROM products WHERE asin = ?",
            (asin,),
        )
        return _row_to_shared_product(row)


async def get_or_create_product(
    db_path: str, asin: str, canonical_url: str, title: Optional[str] = None
) -> Product:
    return await get_or_create_shared_product(db_path, asin, canonical_url, title)



async def get_product_by_asin(db_path: str, asin: str) -> Optional[Product]:
    async with DatabaseConnection(db_path) as db:
        row = await db.fetchone(
            "SELECT id, asin, canonical_url, title, status, price, currency, "
            "consecutive_failures, last_checked_at, next_check_at, created_at, updated_at "
            "FROM products WHERE asin = ?",
            (asin,),
        )
        if not row:
            return None
        return _row_to_shared_product(row)


async def get_product_by_id(db_path: str, product_id: int) -> Optional[Product]:
    async with DatabaseConnection(db_path) as db:
        row = await db.fetchone(
            "SELECT id, asin, canonical_url, title, status, price, currency, "
            "consecutive_failures, last_checked_at, next_check_at, created_at, updated_at "
            "FROM products WHERE id = ?",
            (product_id,),
        )
        if not row:
            return None
        return _row_to_shared_product(row)


async def update_shared_product_state(
    db_path: str,
    product_id: int,
    status: Optional[StockStatus] = None,
    title: Optional[str] = None,
    price: Optional[str] = None,
    consecutive_failures: Optional[int] = None,
    last_checked_at: Optional[datetime] = None,
    next_check_at: Optional[datetime] = None,
) -> None:
    now = _now_iso()
    updates = ["updated_at = ?"]
    params = [now]

    if status is not None:
        updates.append("status = ?")
        params.append(status.value)
    if title is not None:
        updates.append("title = ?")
        params.append(title)
    if price is not None:
        updates.append("price = ?")
        params.append(price)
    if consecutive_failures is not None:
        updates.append("consecutive_failures = ?")
        params.append(consecutive_failures)
    if last_checked_at is not None:
        updates.append("last_checked_at = ?")
        params.append(_dt_str(last_checked_at))
    if next_check_at is not None:
        updates.append("next_check_at = ?")
        params.append(_dt_str(next_check_at))

    params.append(product_id)
    sql = f"UPDATE products SET {', '.join(updates)} WHERE id = ?"

    async with DatabaseConnection(db_path) as db:
        await db.execute(sql, tuple(params))
        await db.commit()


async def list_active_shared_products(db_path: str) -> List[Product]:
    async with DatabaseConnection(db_path) as db:
        rows = await db.fetchall(
            """
            SELECT DISTINCT p.id, p.asin, p.canonical_url, p.title, p.status, p.price,
                   p.currency, p.consecutive_failures, p.last_checked_at, p.next_check_at,
                   p.created_at, p.updated_at
            FROM products p
            JOIN user_watches uw ON uw.product_id = p.id
            WHERE uw.monitoring_enabled = 1
            ORDER BY p.next_check_at ASC
            """
        )
        return [_row_to_shared_product(r) for r in rows]


# ── USER WATCHES CRUD ────────────────────────────────────────────────────

async def create_user_watch(
    db_path: str,
    user_id: int,
    product_id: int,
    monitoring_mode: MonitoringMode = MonitoringMode.NORMAL,
) -> UserWatch:
    now = _now_iso()
    async with DatabaseConnection(db_path) as db:
        row = await db.fetchone(
            "SELECT id, user_id, product_id, monitoring_enabled, monitoring_mode, "
            "alert_sent_for_current_stock_state, last_alerted_at, last_status_changed_at, "
            "created_at, updated_at FROM user_watches WHERE user_id = ? AND product_id = ?",
            (user_id, product_id),
        )
        if row:
            return _row_to_user_watch(row)

        await db.execute(
            """
            INSERT INTO user_watches (user_id, product_id, monitoring_mode, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, product_id, monitoring_mode.value, now, now),
        )
        await db.commit()

        row = await db.fetchone(
            "SELECT id, user_id, product_id, monitoring_enabled, monitoring_mode, "
            "alert_sent_for_current_stock_state, last_alerted_at, last_status_changed_at, "
            "created_at, updated_at FROM user_watches WHERE user_id = ? AND product_id = ?",
            (user_id, product_id),
        )
        return _row_to_user_watch(row)


async def add_user_watch(
    db_path: str,
    user_id: int,
    product_id: int,
    monitoring_mode: MonitoringMode = MonitoringMode.NORMAL,
) -> UserWatch:
    return await create_user_watch(db_path, user_id, product_id, monitoring_mode)


async def list_user_watches(
    db_path: str, user_id: int
) -> List[Tuple[UserWatch, Product]]:
    async with DatabaseConnection(db_path) as db:
        rows = await db.fetchall(
            """
            SELECT uw.id, uw.user_id, uw.product_id, uw.monitoring_enabled, uw.monitoring_mode,
                   uw.alert_sent_for_current_stock_state, uw.last_alerted_at, uw.last_status_changed_at,
                   uw.created_at, uw.updated_at,
                   p.id, p.asin, p.canonical_url, p.title, p.status, p.price, p.currency,
                   p.consecutive_failures, p.last_checked_at, p.next_check_at, p.created_at, p.updated_at
            FROM user_watches uw
            JOIN products p ON p.id = uw.product_id
            WHERE uw.user_id = ?
            ORDER BY uw.created_at DESC
            """,
            (user_id,),
        )
        results = []
        for r in rows:
            uw_tuple = r[:10]
            p_tuple = r[10:]
            watch = _row_to_user_watch(uw_tuple)
            prod = _row_to_shared_product(p_tuple)
            results.append((watch, prod))
        return results


async def get_user_watch(
    db_path: str, user_id: int, product_id: int
) -> Optional[UserWatch]:

    async with DatabaseConnection(db_path) as db:
        row = await db.fetchone(
            "SELECT id, user_id, product_id, monitoring_enabled, monitoring_mode, "
            "alert_sent_for_current_stock_state, last_alerted_at, last_status_changed_at, "
            "created_at, updated_at FROM user_watches WHERE user_id = ? AND product_id = ?",
            (user_id, product_id),
        )
        if not row:
            return None
        return _row_to_user_watch(row)


async def update_user_watch_state(
    db_path: str,
    watch_id: int,
    monitoring_enabled: Optional[bool] = None,
    monitoring_mode: Optional[MonitoringMode] = None,
    alert_sent_for_current_stock_state: Optional[bool] = None,
    last_alerted_at: Optional[datetime] = None,
    last_status_changed_at: Optional[datetime] = None,
) -> None:
    now = _now_iso()
    updates = ["updated_at = ?"]
    params = [now]

    if monitoring_enabled is not None:
        updates.append("monitoring_enabled = ?")
        params.append(1 if monitoring_enabled else 0)
    if monitoring_mode is not None:
        updates.append("monitoring_mode = ?")
        params.append(monitoring_mode.value)
    if alert_sent_for_current_stock_state is not None:
        updates.append("alert_sent_for_current_stock_state = ?")
        params.append(1 if alert_sent_for_current_stock_state else 0)
    if last_alerted_at is not None:
        updates.append("last_alerted_at = ?")
        params.append(_dt_str(last_alerted_at))
    if last_status_changed_at is not None:
        updates.append("last_status_changed_at = ?")
        params.append(_dt_str(last_status_changed_at))

    params.append(watch_id)
    sql = f"UPDATE user_watches SET {', '.join(updates)} WHERE id = ?"

    async with DatabaseConnection(db_path) as db:
        await db.execute(sql, tuple(params))
        await db.commit()


async def list_watches_for_product(
    db_path: str, product_id: int
) -> List[Tuple[UserWatch, User]]:
    async with DatabaseConnection(db_path) as db:
        rows = await db.fetchall(
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
        result = []
        for r in rows:
            uw_tuple = r[:10]
            u_tuple = r[10:]
            result.append((_row_to_user_watch(uw_tuple), _row_to_user(u_tuple)))
        return result


async def remove_user_watch(db_path: str, user_id: int, product_id: int) -> bool:
    async with DatabaseConnection(db_path) as db:
        cursor = await db.execute(
            "DELETE FROM user_watches WHERE user_id = ? AND product_id = ?",
            (user_id, product_id),
        )
        await db.commit()
        return True


async def count_user_watches(db_path: str, user_id: int) -> int:
    async with DatabaseConnection(db_path) as db:
        row = await db.fetchone(
            "SELECT COUNT(*) FROM user_watches WHERE user_id = ?", (user_id,)
        )
        return row[0] if row else 0


async def count_user_turbo_watches(db_path: str, user_id: int) -> int:
    async with DatabaseConnection(db_path) as db:
        row = await db.fetchone(
            "SELECT COUNT(*) FROM user_watches WHERE user_id = ? AND monitoring_mode = 'TURBO'",
            (user_id,),
        )
        return row[0] if row else 0



# ── COMPATIBILITY WRAPPERS (LEGACY WATCHEDPRODUCT API) ───────────────────

async def add_product(
    db_path: str, chat_id: int, asin: str, url: str
) -> WatchedProduct:
    user = await get_user_by_chat_id(db_path, chat_id)
    if not user:
        pub_id = f"tg_{chat_id}"
        tok_hash = f"tg_hash_{chat_id}"
        user = await create_user(db_path, pub_id, tok_hash)
        await link_user_telegram(db_path, user.id, chat_id)

    product = await get_or_create_shared_product(db_path, asin, url)
    watch = await create_user_watch(db_path, user.id, product.id)
    return _build_watched_product(watch, product, chat_id)


async def get_product(
    db_path: str, chat_id: int, asin: str
) -> Optional[WatchedProduct]:
    user = await get_user_by_chat_id(db_path, chat_id)
    if not user:
        return None

    product = await get_product_by_asin(db_path, asin)
    if not product:
        return None

    watch = await get_user_watch(db_path, user.id, product.id)
    if not watch:
        return None

    return _build_watched_product(watch, product, chat_id)


async def list_products_for_chat(
    db_path: str, chat_id: int
) -> List[WatchedProduct]:
    user = await get_user_by_chat_id(db_path, chat_id)
    if not user:
        return []

    async with DatabaseConnection(db_path) as db:
        rows = await db.fetchall(
            """
            SELECT uw.id, uw.user_id, uw.product_id, uw.monitoring_enabled, uw.monitoring_mode,
                   uw.alert_sent_for_current_stock_state, uw.last_alerted_at, uw.last_status_changed_at,
                   uw.created_at, uw.updated_at,
                   p.id, p.asin, p.canonical_url, p.title, p.status, p.price, p.currency,
                   p.consecutive_failures, p.last_checked_at, p.next_check_at, p.created_at, p.updated_at
            FROM user_watches uw
            JOIN products p ON p.id = uw.product_id
            WHERE uw.user_id = ?
            ORDER BY uw.created_at DESC
            """,
            (user.id,),
        )
        results = []
        for r in rows:
            uw_tuple = r[:10]
            p_tuple = r[10:]
            watch = _row_to_user_watch(uw_tuple)
            prod = _row_to_shared_product(p_tuple)
            results.append(_build_watched_product(watch, prod, chat_id))
        return results


async def list_active_products(db_path: str) -> List[WatchedProduct]:
    async with DatabaseConnection(db_path) as db:
        rows = await db.fetchall(
            """
            SELECT uw.id, uw.user_id, uw.product_id, uw.monitoring_enabled, uw.monitoring_mode,
                   uw.alert_sent_for_current_stock_state, uw.last_alerted_at, uw.last_status_changed_at,
                   uw.created_at, uw.updated_at,
                   p.id, p.asin, p.canonical_url, p.title, p.status, p.price, p.currency,
                   p.consecutive_failures, p.last_checked_at, p.next_check_at, p.created_at, p.updated_at,
                   u.telegram_chat_id
            FROM user_watches uw
            JOIN products p ON p.id = uw.product_id
            JOIN users u ON u.id = uw.user_id
            WHERE uw.monitoring_enabled = 1
            ORDER BY p.next_check_at ASC
            """
        )
        results = []
        for r in rows:
            uw_tuple = r[:10]
            p_tuple = r[10:22]
            chat_id = r[22]
            watch = _row_to_user_watch(uw_tuple)
            prod = _row_to_shared_product(p_tuple)
            results.append(_build_watched_product(watch, prod, chat_id or 0))
        return results


async def count_products_for_chat(db_path: str, chat_id: int) -> int:
    user = await get_user_by_chat_id(db_path, chat_id)
    if not user:
        return 0
    return await count_user_watches(db_path, user.id)


async def remove_product(db_path: str, chat_id: int, asin: str) -> bool:
    user = await get_user_by_chat_id(db_path, chat_id)
    if not user:
        return False

    product = await get_product_by_asin(db_path, asin)
    if not product:
        return False

    return await remove_user_watch(db_path, user.id, product.id)


async def set_monitoring_enabled(
    db_path: str, chat_id: int, asin: str, enabled: bool
) -> bool:
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


async def set_monitoring_mode(
    db_path: str, chat_id: int, asin: str, mode: MonitoringMode
) -> bool:
    user = await get_user_by_chat_id(db_path, chat_id)
    if not user:
        return False
    product = await get_product_by_asin(db_path, asin)
    if not product:
        return False
    watch = await get_user_watch(db_path, user.id, product.id)
    if not watch:
        return False

    if mode == MonitoringMode.TURBO:
        existing = await get_turbo_product_for_chat(db_path, chat_id)
        if existing and existing.asin != asin:
            raise ValueError(
                f"You already have product {existing.asin} in Turbo mode. "
                "Only one product can be in Turbo mode at a time."
            )

    await update_user_watch_state(db_path, watch.id, monitoring_mode=mode)
    return True


async def get_turbo_product_for_chat(
    db_path: str, chat_id: int
) -> Optional[WatchedProduct]:
    products = await list_products_for_chat(db_path, chat_id)
    for p in products:
        if p.monitoring_mode == MonitoringMode.TURBO and p.monitoring_enabled:
            return p
    return None


async def update_product_state(
    db_path: str,
    product_id: int,
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
    await update_shared_product_state(
        db_path,
        product_id=product_id,
        status=status,
        title=title,
        price=price,
        consecutive_failures=consecutive_failures,
        last_checked_at=last_checked_at,
        next_check_at=next_check_at,
    )
    user_watches = await list_watches_for_product(db_path, product_id)
    for watch, _ in user_watches:
        await update_user_watch_state(
            db_path,
            watch.id,
            alert_sent_for_current_stock_state=alert_sent_for_current_stock_state,
            last_alerted_at=last_alerted_at,
            last_status_changed_at=last_status_changed_at,
        )


# ── ROW MAPPERS ───────────────────────────────────────────────────────────

def _row_to_user(r: tuple) -> User:
    return User(
        id=r[0],
        public_id=r[1],
        auth_token_hash=r[2],
        telegram_chat_id=r[3],
        telegram_connected_at=_parse_dt(r[4]),
        created_at=_parse_dt(r[5]),
        updated_at=_parse_dt(r[6]),
    )


def _row_to_token(r: tuple) -> TelegramLinkToken:
    return TelegramLinkToken(
        id=r[0],
        user_id=r[1],
        token_hash=r[2],
        expires_at=_parse_dt(r[3]) or datetime.now(timezone.utc),
        used_at=_parse_dt(r[4]),
        created_at=_parse_dt(r[5]),
    )


def _row_to_shared_product(r: tuple) -> Product:
    status_val = r[4] if r[4] else "UNKNOWN"
    try:
        status_enum = StockStatus(status_val)
    except ValueError:
        status_enum = StockStatus.UNKNOWN

    return Product(
        id=r[0],
        asin=r[1],
        canonical_url=r[2],
        title=r[3],
        status=status_enum,
        price=r[5],
        currency=r[6] or "INR",
        consecutive_failures=r[7] if r[7] is not None else 0,
        last_checked_at=_parse_dt(r[8]),
        next_check_at=_parse_dt(r[9]),
        created_at=_parse_dt(r[10]),
        updated_at=_parse_dt(r[11]),
    )


def _row_to_user_watch(r: tuple) -> UserWatch:
    mode_val = r[4] if r[4] else "NORMAL"
    try:
        mode_enum = MonitoringMode(mode_val)
    except ValueError:
        mode_enum = MonitoringMode.NORMAL

    return UserWatch(
        id=r[0],
        user_id=r[1],
        product_id=r[2],
        monitoring_enabled=bool(r[3]),
        monitoring_mode=mode_enum,
        alert_sent_for_current_stock_state=bool(r[5]),
        last_alerted_at=_parse_dt(r[6]),
        last_status_changed_at=_parse_dt(r[7]),
        created_at=_parse_dt(r[8]),
        updated_at=_parse_dt(r[9]),
    )


def _build_watched_product(
    watch: UserWatch, product: Product, chat_id: int
) -> WatchedProduct:
    return WatchedProduct(
        id=product.id,
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
