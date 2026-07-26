"""
Application main module — FastAPI app with integrated Telegram Bot and Monitoring Scheduler.

Architecture:
  - Single application process running Uvicorn + FastAPI
  - Lifespan context initializes Database, Telegram Bot, and MonitoringScheduler
  - Zero-delay polling updater (0.0s poll_interval with drop_pending_updates=True)
"""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from telegram import Bot
from telegram.ext import Application
from telegram.request import HTTPXRequest

from app.config import Settings, load_settings
from app.database.db import init_db
from app.amazon.client import AmazonClient
from app.alerts.telegram import AlertManager
from app.monitoring.scheduler import MonitoringScheduler
from app.bot.handlers import register_handlers
from app.utils.logging import setup_logging
from app.api.routes import api_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context with zero-latency bot polling.
    """
    try:
        settings = load_settings()
    except Exception as e:
        print(f"❌ Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    setup_logging(level=settings.log_level, log_file=settings.log_file)
    logger.info("=" * 60)
    logger.info("Amazon & Flipkart Stock Watcher (Hosted FastAPI + Bot) starting up")
    logger.info(f"Database: {settings.database_path}")
    logger.info(f"Bot Username: @{settings.bot_username}")
    logger.info(f"Max watches per user: {settings.max_watches_per_user}")
    logger.info("=" * 60)

    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    await init_db(settings.database_path)

    http_client = AmazonClient(timeout_seconds=settings.request_timeout_seconds)

    # Configure Telegram HTTP Request timeouts for zero latency
    tg_request = HTTPXRequest(
        connection_pool_size=20,
        read_timeout=5.0,
        write_timeout=5.0,
        connect_timeout=5.0,
    )

    telegram_app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .request(tg_request)
        .build()
    )

    bot: Bot = telegram_app.bot
    alert_manager = AlertManager(bot)

    scheduler = MonitoringScheduler(
        settings=settings,
        http_client=http_client,
        alert_manager=alert_manager,
    )

    telegram_app.bot_data["settings"] = settings
    telegram_app.bot_data["scheduler"] = scheduler
    telegram_app.bot_data["http_client"] = http_client
    telegram_app.bot_data["alert_manager"] = alert_manager

    register_handlers(telegram_app)

    # Attach components to app.state for API route access
    app.state.settings = settings
    app.state.scheduler = scheduler
    app.state.http_client = http_client
    app.state.alert_manager = alert_manager
    app.state.telegram_app = telegram_app

    # Start background components
    await scheduler.start()

    logger.info("Starting Telegram bot polling (zero-delay mode)...")
    await telegram_app.initialize()
    await telegram_app.start()
    polling_task = asyncio.create_task(
        telegram_app.updater.start_polling(
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=True,
            poll_interval=0.0,
            timeout=5,
            bootstrap_retries=-1,
        )
    )

    logger.info("Application startup complete. API ready!")

    yield

    logger.info("Shutting down application...")
    await scheduler.stop()
    await http_client.close()
    await telegram_app.updater.stop()
    await telegram_app.stop()
    await telegram_app.shutdown()
    polling_task.cancel()
    logger.info("Application shutdown complete")


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(
        title="Amazon Stock Watcher API",
        description="Public API for Amazon stock monitoring Chrome extension and Telegram bot",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)
    return app


app = create_app()
