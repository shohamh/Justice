from __future__ import annotations

import asyncio
import logging

from telegram import Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from app.settings import get_settings
from bot.handlers import start, verify, status, unlink, help_command, handle_code_message
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code_message))

    app.run_polling()


if __name__ == "__main__":
    main()
