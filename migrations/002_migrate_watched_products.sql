-- Migration 002: Convert single-user watched_products table to multi-user tables (if watched_products exists)

-- Create products from existing watched_products
INSERT OR IGNORE INTO products (
    asin, canonical_url, title, status, price, currency,
    consecutive_failures, last_checked_at, next_check_at, created_at, updated_at
)
SELECT
    asin, url, title, status, price, currency,
    consecutive_failures, last_checked_at, next_check_at, created_at, updated_at
FROM watched_products;

-- Create legacy users for distinct telegram_chat_ids
INSERT OR IGNORE INTO users (public_id, auth_token_hash, telegram_chat_id, telegram_connected_at, created_at, updated_at)
SELECT
    'legacy_' || telegram_chat_id,
    'legacy_hash_' || telegram_chat_id,
    telegram_chat_id,
    datetime('now'),
    created_at,
    updated_at
FROM watched_products
GROUP BY telegram_chat_id;

-- Create user_watches joining legacy users with products
INSERT OR IGNORE INTO user_watches (
    user_id, product_id, monitoring_enabled, monitoring_mode,
    alert_sent_for_current_stock_state, last_alerted_at, last_status_changed_at,
    created_at, updated_at
)
SELECT
    u.id, p.id, wp.monitoring_enabled, wp.monitoring_mode,
    wp.alert_sent_for_current_stock_state, wp.last_alerted_at, wp.last_status_changed_at,
    wp.created_at, wp.updated_at
FROM watched_products wp
JOIN users u ON u.telegram_chat_id = wp.telegram_chat_id
JOIN products p ON p.asin = wp.asin;
