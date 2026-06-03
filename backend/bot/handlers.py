from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from telegram import Update
from telegram.ext import ContextTypes

from app.db.models import TelegramActionToken, TelegramLink
from app.db.session import session_scope
from app.services.action_tokens import find_pending_reply, redeem_token, set_awaiting_reply
from bot.actions import (
    execute_action,
    execute_action_with_reason,
    execute_silence_depth,
    execute_silence_step1,
)


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
                TelegramLink.is_verified == False,  # noqa: E712
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


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all free-text messages: pending-reply first, then verification code."""
    text = (update.message.text or "").strip()
    chat_id = update.effective_chat.id

    # 1. Check if this chat is waiting to provide a rejection reason
    with session_scope() as session:
        pending = find_pending_reply(session, chat_id=chat_id)
        if pending is not None:
            pending.awaiting_text_from_chat_id = None
            pending.used_at = datetime.now(timezone.utc)
            result = execute_action_with_reason(pending, session, reason=text)
            session.commit()
            await update.message.reply_text(result)
            return

    # 2. Try as a 6-char verification code
    upper = text.upper()
    if len(upper) == 6 and upper.isalnum():
        await _do_verify(update, upper)
    else:
        await update.message.reply_text(
            "קוד לא תקין. הקוד צריך להיות 6 תווים. אנא העתק אותו מהאתר ונסה שוב."
        )


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline-keyboard button presses."""
    query = update.callback_query
    await query.answer()
    token = query.data
    chat_id = query.message.chat_id
    now = datetime.now(timezone.utc)

    with session_scope() as session:
        t = session.execute(
            select(TelegramActionToken).where(
                TelegramActionToken.token == token,
                TelegramActionToken.used_at.is_(None),
                TelegramActionToken.expires_at > now,
            )
        ).scalar_one_or_none()

        if t is None:
            await query.message.reply_text("הפעולה פגה תוקף או שכבר בוצעה.")
            return

        if t.action == "silence:step1":
            result = execute_silence_step1(t, session, chat_id)
            t.used_at = now
            session.commit()
            if isinstance(result, tuple):
                text, markup = result
                await query.message.reply_text(text, reply_markup=markup)
            else:
                await query.message.reply_text(result)
            return

        if t.action == "silence:depth":
            result = execute_silence_depth(t, session, chat_id)
            t.used_at = now
            session.commit()
            await query.message.reply_text(result)
            return

        if t.action.endswith(":reject"):
            # Ask for reason — leave token unconsumed, mark as awaiting reply
            t.awaiting_text_from_chat_id = chat_id
            session.commit()
            await query.message.reply_text("נא כתוב את סיבת הדחייה:")
            return

        # Approve / claim actions: redeem and execute
        validated = redeem_token(session, token=token, chat_id=chat_id)
        if validated is None:
            await query.message.reply_text("הפעולה פגה תוקף, כבר בוצעה, או שאין לך הרשאה.")
            return
        result = execute_action(validated, session)
        session.commit()
        await query.message.reply_text(result)


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
