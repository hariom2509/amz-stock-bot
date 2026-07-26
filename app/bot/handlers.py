"""
Telegram Bot Command Handlers (Telegram-First Architecture).

Implements user-facing Telegram commands & direct Amazon URL watching:
  /start, /help, /list, /status, /check, /remove, /pause, /resume, /turbo, /normal

User Experience:
  - User opens bot and sends any Amazon.in product link directly.
  - Bare Amazon URLs automatically add the product to the user's watchlist.
  - Instant response under 100ms, with async live stock checking.
  - Interactive /list view with Stop (Pause), Start (Resume), Remove, and Open buttons.
  - Identity is 100% managed via Telegram chat_id.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, TYPE_CHECKING

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.error import TelegramError

from app.config import Settings
from app.database import repository as repo
from app.database.models import WatchedProduct, StockStatus, MonitoringMode
from app.utils.urls import normalize_url, looks_like_amazon_url
from app.bot.keyboards import (
    buy_now_keyboard,
    product_action_keyboard,
    confirm_remove_keyboard,
    list_item_keyboard,
)
from app.alerts.telegram import AlertManager, _escape
from app.telegram import linking as telegram_linking

if TYPE_CHECKING:
    from app.monitoring.scheduler import MonitoringScheduler

logger = logging.getLogger(__name__)


def _format_last_checked(product: WatchedProduct) -> str:
    if not product.last_checked_at:
        return "Just now"
    ts = product.last_checked_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    diff = now - ts
    if diff < timedelta(minutes=1):
        return f"{max(0, int(diff.total_seconds()))} seconds ago"
    elif diff < timedelta(hours=1):
        return f"{int(diff.total_seconds() // 60)} minutes ago"
    else:
        return ts.strftime("%H:%M UTC")


async def _reply(
    update: Update, text: str, reply_markup=None, parse_mode: str = "HTML"
) -> Optional[any]:
    if update.message:
        return await update.message.reply_text(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    elif update.callback_query:
        return await update.callback_query.message.reply_text(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    return None


def _is_authorized(chat_id: int, settings: Settings) -> bool:
    allowed = settings.allowed_chat_ids
    if not allowed:
        return True
    return chat_id in allowed


async def _check_auth(update: Update, settings: Settings) -> bool:
    chat_id = update.effective_chat.id
    if not _is_authorized(chat_id, settings):
        logger.warning(f"Unauthorized access attempt from chat_id={chat_id}")
        await _reply(update, "⛔ You are not authorized to use this bot.")
        return False
    return True


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start or /start <token> command."""
    settings: Settings = context.bot_data["settings"]
    if not await _check_auth(update, settings):
        return

    chat_id = update.effective_chat.id

    if context.args:
        raw_token = context.args[0].strip()
        linked_user = await telegram_linking.consume_telegram_link_token(
            settings.database_path, raw_token, chat_id
        )
        if linked_user:
            await _reply(
                update,
                "🎉 <b>Telegram Connected Successfully!</b>\n\n"
                "Your Telegram account is now linked to your Extension device.\n"
                "Stock alerts will be delivered right here!",
            )
            return

    text = (
        "⚡ <b>Amazon Stock Watcher</b>\n\n"
        "This is an automated 24/7 Amazon stock monitoring bot. "
        "It continuously monitors Amazon products and sends you an instant alert within seconds when stock is updated!\n\n"
        "👨‍💻 <b>Specifically created by Hari</b>\n\n"
        "📌 <b>How to use:</b>\n"
        "Send me an Amazon.in product link and I'll monitor it automatically:\n"
        "<code>https://www.amazon.in/dp/B0XXXXXXXXXX</code>\n\n"
        "<b>Commands:</b>\n"
        "/list — View all your active watches\n"
        "/help — Command reference"
    )
    await _reply(update, text)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    if not await _check_auth(update, settings):
        return

    text = (
        "📖 <b>Command Reference</b>\n\n"
        "<b>Adding Products:</b>\n"
        "Simply send any Amazon.in product link directly to the bot.\n\n"
        "<b>Managing Products:</b>\n"
        "/list — Show your active watches with Stop / Start buttons\n"
        "/status &lt;ASIN&gt; — Detailed status\n"
        "/check &lt;ASIN&gt; — Force an immediate check\n"
        "/remove &lt;ASIN&gt; — Stop monitoring and remove\n"
        "/pause &lt;ASIN&gt; — Stop monitoring\n"
        "/resume &lt;ASIN&gt; — Resume monitoring\n\n"
        "<b>Speed:</b>\n"
        "/turbo &lt;ASIN&gt; — Enable Turbo monitoring (⚡)\n"
        "/normal &lt;ASIN&gt; — Return to Normal monitoring"
    )
    await _reply(update, text)


async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    scheduler: "MonitoringScheduler" = context.bot_data["scheduler"]

    if not await _check_auth(update, settings):
        return

    if not context.args:
        await _reply(
            update,
            "❌ Please provide an Amazon URL.\n\n"
            "Example: <code>https://www.amazon.in/dp/B0XXXXXXXXXX</code>"
        )
        return

    url = context.args[0].strip()
    await _handle_watch_url(update, context, url, settings, scheduler)


async def _handle_watch_url(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    settings: Settings,
    scheduler: "MonitoringScheduler",
) -> None:
    chat_id = update.effective_chat.id

    result = normalize_url(url)
    if result is None:
        await _reply(
            update,
            "❌ I couldn't recognize that Amazon product URL.\n\n"
            "Please send a valid Amazon.in product link.\n"
            "Example: <code>https://www.amazon.in/dp/B0XXXXXXXXXX</code>"
        )
        return

    canonical_url, asin = result

    # Check watch count limit for user
    count = await repo.count_products_for_chat(settings.database_path, chat_id)
    if count >= settings.max_watches_per_user:
        await _reply(
            update,
            f"⚠️ <b>Watch limit reached.</b>\n\n"
            f"You're already monitoring {count} products (max limit: {settings.max_watches_per_user}).\n"
            f"Use /remove &lt;ASIN&gt; to remove one before adding another."
        )
        return

    existing = await repo.get_product(settings.database_path, chat_id, asin)
    if existing:
        await _reply(
            update,
            f"ℹ️ You're already watching this product.\n\n"
            f"<b>{_escape(existing.display_title)}</b>\n"
            f"ASIN: <code>{asin}</code>\n"
            f"Status: {existing.status_emoji} {existing.display_status}\n\n"
            f"Use /list to manage your watches.",
            reply_markup=list_item_keyboard(existing.asin, existing.monitoring_enabled, existing.url),
        )
        return

    # Instant response under 50ms with full card and action buttons
    item_kb = list_item_keyboard(asin, True, canonical_url)
    initial_msg = await _reply(
        update,
        f"👀 <b>Added to 24/7 Watchlist!</b>\n\n"
        f"ASIN: <code>{asin}</code>\n\n"
        f"⏳ <b>Monitoring Active (Checking status...)</b>\n\n"
        f"I'll alert you automatically as soon as stock updates.",
        reply_markup=item_kb,
    )


    try:
        product = await repo.add_product(
            settings.database_path, chat_id, asin, canonical_url
        )
    except ValueError as e:
        if initial_msg:
            await initial_msg.edit_text(f"ℹ️ {e}", parse_mode="HTML")
        return
    except Exception as e:
        logger.error(f"Error adding product ASIN={asin}: {e}", exc_info=True)
        if initial_msg:
            await initial_msg.edit_text("⚠️ Failed to add product. Please try again.", parse_mode="HTML")
        return

    # Trigger async check and update message
    asyncio.create_task(
        _do_immediate_check_and_report(
            product, settings, scheduler, update, context, initial_msg
        )
    )


async def _do_immediate_check_and_report(
    product: WatchedProduct,
    settings: Settings,
    scheduler: "MonitoringScheduler",
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    initial_msg: Optional[any] = None,
) -> None:
    from app.amazon.client import AmazonClient
    from app.amazon.parser import parse_product_page
    from app.amazon.models import StockStatus as AmazonStatus

    http_client: AmazonClient = context.bot_data["http_client"]
    alert_manager: AlertManager = context.bot_data["alert_manager"]
    chat_id = update.effective_chat.id

    html, error = None, None
    for attempt in range(3):
        html, error = await http_client.fetch_product_page(product.url, product.asin)
        if not error:
            break
        await asyncio.sleep(1.0)

    if error:
        err_text = (
            f"👀 <b>WATCHING (24/7)</b>\n\n"
            f"ASIN: <code>{product.asin}</code>\n\n"
            f"⏳ <b>Monitoring Active (Checking status...)</b>\n\n"
            f"I'll alert you automatically as soon as stock updates."
        )
        item_kb = list_item_keyboard(product.asin, True, product.url)
        if initial_msg:
            try:
                await initial_msg.edit_text(err_text, reply_markup=item_kb, parse_mode="HTML")
            except Exception:
                await alert_manager.send_message(chat_id, err_text, reply_markup=item_kb)
        else:
            await alert_manager.send_message(chat_id, err_text, reply_markup=item_kb)

        await scheduler.trigger_immediate_check(product)
        return



    state = parse_product_page(html, product.asin)

    new_status = StockStatus(state.status.value)
    await repo.update_product_state(
        settings.database_path,
        product.id,
        status=new_status,
        title=state.title,
        price=state.price,
        consecutive_failures=0,
    )

    title = state.title or f"ASIN: {product.asin}"
    price_line = f"₹{state.price}" if state.price else "Price: Unknown"

    if state.status == AmazonStatus.IN_STOCK and state.is_confident_in_stock:
        await repo.update_product_state(
            settings.database_path,
            product.id,
            alert_sent_for_current_stock_state=True,
            last_alerted_at=datetime.now(timezone.utc),
        )
        keyboard = buy_now_keyboard(product.url)
        in_stock_text = (
            f"🚨 <b>THIS PRODUCT IS CURRENTLY AVAILABLE</b>\n\n"
            f"<b>{_escape(title)}</b>\n\n"
            f"🟢 <b>IN STOCK</b>\n"
            f"💰 {price_line}\n\n"
            f"ASIN: <code>{product.asin}</code>"
        )
        if initial_msg:
            try:
                await initial_msg.edit_text(in_stock_text, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                await alert_manager.send_message(chat_id, in_stock_text, reply_markup=keyboard)
        else:
            await alert_manager.send_message(chat_id, in_stock_text, reply_markup=keyboard)
    else:
        item_kb = list_item_keyboard(product.asin, True, product.url)
        oos_text = (
            f"👀 <b>WATCHING (24/7)</b>\n\n"
            f"<b>{_escape(title)}</b>\n\n"
            f"🔴 <b>Currently Out of Stock</b>\n"
            f"💰 {price_line}\n\n"
            f"Monitoring: <b>Active 24/7</b>\n\n"
            f"I'll alert you automatically when this becomes available."
        )
        if initial_msg:
            try:
                await initial_msg.edit_text(oos_text, reply_markup=item_kb, parse_mode="HTML")
            except Exception:
                await alert_manager.send_message(chat_id, oos_text, reply_markup=item_kb)
        else:
            await alert_manager.send_message(chat_id, oos_text, reply_markup=item_kb)


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send interactive cards concurrently for each watched product with Stop / Start / Remove buttons."""
    settings: Settings = context.bot_data["settings"]
    if not await _check_auth(update, settings):
        return

    chat_id = update.effective_chat.id
    products = await repo.list_products_for_chat(settings.database_path, chat_id)

    if not products:
        await _reply(
            update,
            "👀 You're not watching any products yet.\n\n"
            "Send me an Amazon.in link to start watching!"
        )
        return

    await _reply(update, f"👀 <b>YOUR WATCHES ({len(products)})</b>")

    tasks = []
    for i, p in enumerate(products, 1):
        status_text = "Active (Watching 24/7)" if p.monitoring_enabled else "Stopped (Paused)"
        card_text = (
            f"<b>{i}. {_escape(p.display_title)}</b>\n\n"
            f"Status: {p.status_emoji} <b>{p.display_status}</b>\n"
            f"Price: <b>{p.display_price}</b>\n"
            f"ASIN: <code>{p.asin}</code>\n"
            f"Monitoring: <b>{status_text}</b>\n"
            f"Last Checked: {_format_last_checked(p)}"
        )
        kb = list_item_keyboard(p.asin, p.monitoring_enabled, p.url)
        tasks.append(_reply(update, card_text, reply_markup=kb))

    if tasks:
        await asyncio.gather(*tasks)



async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    if not await _check_auth(update, settings):
        return

    if not context.args:
        await _reply(update, "Usage: <code>/status ASIN</code>")
        return

    asin = context.args[0].strip().upper()
    chat_id = update.effective_chat.id

    product = await repo.get_product(settings.database_path, chat_id, asin)
    if not product:
        await _reply(update, f"❌ No product with ASIN <code>{asin}</code> found in your watchlist.")
        return

    await _reply(
        update,
        _format_product_detail(product),
        reply_markup=list_item_keyboard(product.asin, product.monitoring_enabled, product.url),
    )


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    scheduler: "MonitoringScheduler" = context.bot_data["scheduler"]
    if not await _check_auth(update, settings):
        return

    if not context.args:
        await _reply(update, "Usage: <code>/check ASIN</code>")
        return

    asin = context.args[0].strip().upper()
    chat_id = update.effective_chat.id

    product = await repo.get_product(settings.database_path, chat_id, asin)
    if not product:
        await _reply(update, f"❌ No product with ASIN <code>{asin}</code> found.")
        return

    await _reply(update, f"🔄 Checking <code>{asin}</code> now...")
    await scheduler.trigger_immediate_check(product)


async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    if not await _check_auth(update, settings):
        return

    if not context.args:
        await _reply(update, "Usage: <code>/remove ASIN</code>")
        return

    asin = context.args[0].strip().upper()
    chat_id = update.effective_chat.id

    removed = await repo.remove_product(settings.database_path, chat_id, asin)
    if removed:
        await _reply(update, f"🗑 Removed <code>{asin}</code> from your watchlist.")
    else:
        await _reply(update, f"❌ Product <code>{asin}</code> not found in your watchlist.")



async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    if not await _check_auth(update, settings):
        return

    if not context.args:
        await _reply(update, "Usage: <code>/pause ASIN</code>")
        return

    asin = context.args[0].strip().upper()
    chat_id = update.effective_chat.id

    found = await repo.set_monitoring_enabled(settings.database_path, chat_id, asin, False)
    if not found:
        await _reply(update, f"❌ No product with ASIN <code>{asin}</code> found.")
        return

    await _reply(
        update,
        f"🛑 Monitoring <b>stopped</b> for <code>{asin}</code>.\n\n"
        f"Use /resume {asin} to start watching again."
    )


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    if not await _check_auth(update, settings):
        return

    if not context.args:
        await _reply(update, "Usage: <code>/resume ASIN</code>")
        return

    asin = context.args[0].strip().upper()
    chat_id = update.effective_chat.id

    found = await repo.set_monitoring_enabled(settings.database_path, chat_id, asin, True)
    if not found:
        await _reply(update, f"❌ No product with ASIN <code>{asin}</code> found.")
        return

    product = await repo.get_product(settings.database_path, chat_id, asin)
    if product:
        scheduler: "MonitoringScheduler" = context.bot_data["scheduler"]
        await scheduler.trigger_immediate_check(product)

    await _reply(
        update,
        f"▶️ Monitoring <b>resumed</b> for <code>{asin}</code>.\n\n"
        f"I'll check it again shortly."
    )


async def cmd_turbo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    if not await _check_auth(update, settings):
        return

    if not context.args:
        await _reply(update, "Usage: <code>/turbo ASIN</code>")
        return

    asin = context.args[0].strip().upper()
    chat_id = update.effective_chat.id

    existing_turbo = await repo.get_turbo_product_for_chat(settings.database_path, chat_id)
    if existing_turbo and existing_turbo.asin != asin:
        await _reply(
            update,
            f"⚠️ You already have another product in ⚡ Turbo mode:\n\n"
            f"<b>{_escape(existing_turbo.display_title)}</b>\n"
            f"ASIN: <code>{existing_turbo.asin}</code>\n\n"
            f"Use /normal {existing_turbo.asin} first, then retry."
        )
        return

    product = await repo.get_product(settings.database_path, chat_id, asin)
    if not product:
        await _reply(update, f"❌ No product with ASIN <code>{asin}</code> found.")
        return

    await repo.set_monitoring_mode(
        settings.database_path, chat_id, asin, MonitoringMode.TURBO
    )

    await _reply(
        update,
        f"⚡ <b>Turbo mode enabled</b> for:\n\n"
        f"<b>{_escape(product.display_title)}</b>\n"
        f"ASIN: <code>{asin}</code>"
    )


async def cmd_normal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    if not await _check_auth(update, settings):
        return

    if not context.args:
        await _reply(update, "Usage: <code>/normal ASIN</code>")
        return

    asin = context.args[0].strip().upper()
    chat_id = update.effective_chat.id

    found = await repo.set_monitoring_mode(
        settings.database_path, chat_id, asin, MonitoringMode.NORMAL
    )
    if not found:
        await _reply(update, f"❌ No product with ASIN <code>{asin}</code> found.")
        return

    await _reply(
        update,
        f"🔄 Returned to <b>Normal mode</b> for <code>{asin}</code>."
    )


async def handle_bare_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle plain Amazon URLs sent without any command."""
    settings: Settings = context.bot_data["settings"]
    scheduler: "MonitoringScheduler" = context.bot_data["scheduler"]

    if not await _check_auth(update, settings):
        return

    text = update.message.text.strip()
    if looks_like_amazon_url(text):
        await _handle_watch_url(update, context, text, settings, scheduler)


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    scheduler: "MonitoringScheduler" = context.bot_data["scheduler"]
    query = update.callback_query
    await query.answer()

    chat_id = update.effective_chat.id
    data = query.data or ""

    if data.startswith("confirm_remove:"):
        asin = data.split(":", 1)[1]
        removed = await repo.remove_product(settings.database_path, chat_id, asin)
        if removed:
            await query.edit_message_text(
                f"🗑 Removed <code>{asin}</code> from your watchlist.",
                parse_mode="HTML",
            )
        else:
            await query.edit_message_text("❌ Product not found.", parse_mode="HTML")

    elif data.startswith("cancel_remove:"):
        await query.edit_message_text("✅ Removal cancelled.", parse_mode="HTML")

    elif data.startswith("status:"):
        asin = data.split(":", 1)[1]
        product = await repo.get_product(settings.database_path, chat_id, asin)
        if product:
            await query.message.reply_text(
                _format_product_detail(product),
                parse_mode="HTML",
                reply_markup=list_item_keyboard(product.asin, product.monitoring_enabled, product.url),
                disable_web_page_preview=True,
            )
        else:
            await query.edit_message_text("❌ Product not found.", parse_mode="HTML")

    elif data.startswith("check:"):
        asin = data.split(":", 1)[1]
        product = await repo.get_product(settings.database_path, chat_id, asin)
        if product:
            await query.message.reply_text(
                f"🔄 Checking <code>{asin}</code>...",
                parse_mode="HTML",
            )
            await scheduler.trigger_immediate_check(product)

    elif data.startswith("pause:"):
        asin = data.split(":", 1)[1]
        await repo.set_monitoring_enabled(settings.database_path, chat_id, asin, False)
        product = await repo.get_product(settings.database_path, chat_id, asin)
        if product:
            try:
                kb = list_item_keyboard(asin, False, product.url)
                await query.edit_message_reply_markup(reply_markup=kb)
            except Exception:
                pass
        await query.message.reply_text(
            f"🛑 Monitoring <b>stopped</b> for <code>{asin}</code>.\nTap ▶️ Start anytime to resume.",
            parse_mode="HTML",
        )

    elif data.startswith("resume:"):
        asin = data.split(":", 1)[1]
        await repo.set_monitoring_enabled(settings.database_path, chat_id, asin, True)
        product = await repo.get_product(settings.database_path, chat_id, asin)
        if product:
            await scheduler.trigger_immediate_check(product)
            try:
                kb = list_item_keyboard(asin, True, product.url)
                await query.edit_message_reply_markup(reply_markup=kb)
            except Exception:
                pass
        await query.message.reply_text(
            f"▶️ Monitoring <b>resumed</b> for <code>{asin}</code>.\nChecking Amazon now...",
            parse_mode="HTML",
        )

    elif data.startswith("remove:"):
        asin = data.split(":", 1)[1]
        product = await repo.get_product(settings.database_path, chat_id, asin)
        if product:
            await query.message.reply_text(
                f"⚠️ Remove <b>{_escape(product.display_title)}</b>?",
                parse_mode="HTML",
                reply_markup=confirm_remove_keyboard(asin),
            )


def _format_product_detail(product: WatchedProduct) -> str:
    mode_str = "⚡ Turbo" if product.monitoring_mode == MonitoringMode.TURBO else "🔄 Normal"
    monitoring_str = "✅ Active (24/7)" if product.monitoring_enabled else "🛑 Stopped (Paused)"

    lines = [
        f"📦 <b>{_escape(product.display_title)}</b>",
        "",
        f"ASIN: <code>{product.asin}</code>",
        f"Status: {product.status_emoji} <b>{product.display_status}</b>",
        f"Price: <b>{product.display_price}</b>",
        f"Mode: {mode_str} | {monitoring_str}",
        f"Last check: {_format_last_checked(product)}",
    ]

    if product.last_status_changed_at:
        ts = product.last_status_changed_at
        lines.append(f"Status changed: {ts.strftime('%Y-%m-%d %H:%M UTC')}")

    if product.consecutive_failures > 0:
        lines.append(f"⚠️ Consecutive failures: {product.consecutive_failures}")

    lines.append(f"\n🔗 {product.url}")
    return "\n".join(lines)


def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("turbo", cmd_turbo))
    app.add_handler(CommandHandler("normal", cmd_normal))

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bare_url)
    )

    app.add_handler(CallbackQueryHandler(handle_callback_query))

    logger.info("All Telegram handlers registered (Telegram-First Architecture)")
