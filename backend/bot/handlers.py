from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from telegram import Update
from telegram.ext import ContextTypes

from app.db.models import TelegramLink
from app.db.session import session_scope


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "ברוכים הבאים! כדי לקשר את חשבון הטלגרם שלך, פתח את האתר, "
        "לחץ על 'קשר חשבון טלגרם' באזור האישי, הזן את הקוד שתראה שם."
    )


async def _do_verify(update: Update, code: str) -> None:
    with session_scope() as session:
        link = session.execute(
            select(TelegramLink).where(
                TelegramLink.verification_code == code,
                TelegramLink.is_verified == False,
            )
        ).scalar_one_or_none()
        if link is None or (link.verification_expires_at and link.verification_expires_at < datetime.now(timezone.utc)):
            await update.message.reply_text("קוד לא תקין או שפג תוקפו. אנא צור קוד חדש באתר.")
            return
        link.telegram_chat_id = update.effective_chat.id
        link.telegram_username = update.effective_user.username
        link.is_verified = True
        link.verified_at = datetime.now(timezone.utc)
        link.verification_code = None
        link.verification_expires_at = None
        session.commit()
    await update.message.reply_text("החשבון שלך אומת בהצלחה!")


async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0]:
        await update.message.reply_text("אנא הזן קוד: /verify <קוד>")
        return
    await _do_verify(update, context.args[0].strip().upper())


async def handle_code_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Accept a bare 6-character code sent as a plain message."""
    text = (update.message.text or "").strip().upper()
    if len(text) == 6 and text.isalnum():
        await _do_verify(update, text)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    with session_scope() as session:
        link = session.execute(
            select(TelegramLink).where(TelegramLink.telegram_chat_id == chat_id)
        ).scalar_one_or_none()
    if link and link.is_verified:
        await update.message.reply_text(f"✅ חשבון טלגרם מקושר ל-@{link.telegram_username or '?'}.")
    else:
        await update.message.reply_text("❌ חשבון טלגרם לא מקושר. פתח את האתר לצורך קישור.")


async def unlink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    with session_scope() as session:
        link = session.execute(
            select(TelegramLink).where(TelegramLink.telegram_chat_id == chat_id)
        ).scalar_one_or_none()
        if link:
            link.telegram_chat_id = None
            link.telegram_username = None
            link.is_verified = False
            link.verified_at = None
            session.commit()
    await update.message.reply_text("החשבון בוטל בהצלחה.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "/start - הוראות התחלה\n"
        "/verify <קוד> - אימות חשבון טלגרם\n"
        "/status - בדיקת סטטוס חיבור\n"
        "/unlink - ביטול קישור חשבון טלגרם"
    )
