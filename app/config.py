"""
Amazon Stock Watcher — Configuration

Loads and validates all settings from environment variables / .env file.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, List

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Telegram ────────────────────────────────────────────────────────────
    telegram_bot_token: str
    bot_username: str = "AmazonStockWatcherBot"

    # Comma-separated list of allowed chat IDs (empty = allow all)
    allowed_telegram_chat_ids: str = ""

    # ── API Server ──────────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_allowed_origins: str = "*"

    # ── Database ────────────────────────────────────────────────────────────
    database_path: str = "data/watcher.db"

    # ── Security & Limits ───────────────────────────────────────────────────
    link_token_ttl_seconds: int = 900  # 15 minutes
    max_watches_per_user: int = 50     # Support up to 50 products per user
    max_turbo_watches_per_user: int = 5
    max_active_unique_products: int = 250

    # ── Monitoring Intervals (Low Latency with Smart Staggering) ─────────────
    fast_check_interval_seconds: int = 4
    fast_jitter_seconds: int = 2
    normal_check_interval_seconds: int = 15
    normal_jitter_seconds: int = 5
    turbo_check_interval_seconds: int = 3
    turbo_jitter_seconds: int = 1

    # ── Backoff ─────────────────────────────────────────────────────────────
    max_failure_backoff_seconds: int = 120
    max_consecutive_failures: int = 3
    blocked_cooldown_seconds: int = 30

    # ── Concurrency ─────────────────────────────────────────────────────────
    max_concurrent_checks: int = 5

    # ── HTTP Client ─────────────────────────────────────────────────────────
    request_timeout_seconds: int = 15

    # ── Logging ─────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_file: Optional[str] = None

    # ── Computed Properties ─────────────────────────────────────────────────
    @property
    def allowed_chat_ids(self) -> List[int]:
        if not self.allowed_telegram_chat_ids.strip():
            return []
        result = []
        for part in self.allowed_telegram_chat_ids.split(","):
            part = part.strip()
            if part:
                try:
                    result.append(int(part))
                except ValueError:
                    pass
        return result

    @property
    def cors_origins(self) -> List[str]:
        if not self.cors_allowed_origins.strip():
            return ["*"]
        return [p.strip() for p in self.cors_allowed_origins.split(",") if p.strip()]

    @property
    def database_dir(self) -> Path:
        return Path(self.database_path).parent

    @property
    def log_dir(self) -> Optional[Path]:
        if self.log_file:
            return Path(self.log_file).parent
        return None

    # ── Validators ──────────────────────────────────────────────────────────
    @field_validator("telegram_bot_token")
    @classmethod
    def validate_bot_token(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError(
                "TELEGRAM_BOT_TOKEN is required. "
                "Get one from @BotFather on Telegram."
            )
        v = v.strip()
        if ":" not in v:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN appears malformed. "
                "It should look like: 123456789:ABCdefGHI..."
            )
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"LOG_LEVEL must be one of {valid}, got: {v}")
        return upper


def load_settings() -> Settings:
    return Settings()
