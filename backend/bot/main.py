from __future__ import annotations

import asyncio
import logging
import os

from telegram import Bot
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from app.logging_config import setup_logging
from app.settings import get_settings
from bot.handlers import (
    callback_query_handler,
    handle_text_message,
    help_command,
    start,
    status,
    unlink,
    verify,
)
from bot.outbox import poll_outbox

logger = logging.getLogger(__name__)


async def outbox_loop(app: Application) -> None:
    while True:
        try:
            await poll_outbox(app.bot)
        except Exception:
            logger.exception("outbox poll failed")
        await asyncio.sleep(2)


async def _post_init(app: Application) -> None:
    asyncio.ensure_future(outbox_loop(app))


def main() -> None:
    setup_logging("bot.log")
    settings = get_settings()
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set; bot not starting")
        return

    app = Application.builder().token(settings.telegram_bot_token).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("verify", verify))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("unlink", unlink))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    logger.info("=== STARTUP pid=%d ===", os.getpid())
    try:
        app.run_polling()
    except Exception:
        logger.critical("=== BOT CRASHED ===", exc_info=True)
        raise
    else:
        logger.info("=== CLEAN SHUTDOWN ===")


if __name__ == "__main__":
    main()
