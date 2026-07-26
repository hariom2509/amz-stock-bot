-- Migration 001: Initial Multi-User Schema

CREATE TABLE IF NOT EXISTS users (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id               TEXT NOT NULL UNIQUE,
    auth_token_hash         TEXT NOT NULL UNIQUE,
    telegram_chat_id        INTEGER UNIQUE,
    telegram_connected_at    TEXT,
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS telegram_link_tokens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT NOT NULL UNIQUE,
    expires_at  TEXT NOT NULL,
    used_at     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    asin                    TEXT NOT NULL UNIQUE,
    canonical_url           TEXT NOT NULL,
    title                   TEXT,
    status                  TEXT NOT NULL DEFAULT 'UNKNOWN',
    price                   TEXT,
    currency                TEXT NOT NULL DEFAULT 'INR',
    consecutive_failures    INTEGER NOT NULL DEFAULT 0,
    last_checked_at         TEXT,
    next_check_at           TEXT,
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_watches (
    id                                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id                             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id                          INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    monitoring_enabled                  INTEGER NOT NULL DEFAULT 1,
    monitoring_mode                     TEXT NOT NULL DEFAULT 'NORMAL',
    alert_sent_for_current_stock_state  INTEGER NOT NULL DEFAULT 0,
    last_alerted_at                     TEXT,
    last_status_changed_at              TEXT,
    created_at                          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at                          TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(user_id, product_id)
);

CREATE INDEX IF NOT EXISTS idx_users_public_id ON users(public_id);
CREATE INDEX IF NOT EXISTS idx_users_auth_token_hash ON users(auth_token_hash);
CREATE INDEX IF NOT EXISTS idx_users_telegram_chat ON users(telegram_chat_id);

CREATE INDEX IF NOT EXISTS idx_tokens_hash ON telegram_link_tokens(token_hash);

CREATE INDEX IF NOT EXISTS idx_products_asin ON products(asin);
CREATE INDEX IF NOT EXISTS idx_products_next_check ON products(next_check_at);

CREATE INDEX IF NOT EXISTS idx_user_watches_user ON user_watches(user_id);
CREATE INDEX IF NOT EXISTS idx_user_watches_product ON user_watches(product_id);
CREATE INDEX IF NOT EXISTS idx_user_watches_enabled ON user_watches(monitoring_enabled);
