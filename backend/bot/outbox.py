from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from telegram import Bot, InlineKeyboardMarkup

from app.db.models import TelegramOutbox
from app.db.session import session_scope

logger = logging.getLogger(__name__)


async def poll_outbox(bot: Bot) -> None:
    with session_scope() as session:
        rows = list(
            session.execute(
                select(TelegramOutbox).where(TelegramOutbox.sent_at.is_(None))
                .order_by(TelegramOutbox.created_at)
                .limit(20)
            ).scalars().all()
        )
        for row in rows:
            try:
                markup: InlineKeyboardMarkup | None = None
                if row.reply_markup_json:
                    markup = InlineKeyboardMarkup.de_json(
                        json.loads(row.reply_markup_json), bot
                    )
                await bot.send_message(
                    chat_id=row.telegram_chat_id,
                    text=row.message_text,
                    reply_markup=markup,
                )
                row.sent_at = datetime.now(timezone.utc)
            except Exception as e:
                logger.warning("failed to send to chat %s: %s", row.telegram_chat_id, e)
                row.error = str(e)
            session.commit()
