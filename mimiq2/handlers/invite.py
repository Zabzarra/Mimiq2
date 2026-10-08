"""Invite-code gate — ported verbatim from the live handler ([M] shared, security invariant)."""

import secrets

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup

from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters

import database

from config import ADMIN_TELEGRAM_ID

from lighter_utils import TELEGRAM_BOT_URL

from .base import CONVO_TIMEOUT_S

from .waitlist import CB_WAITLIST_START, cmd_leave

logger = logging.getLogger(__name__)

MIN_SAFE_CODE_LEN = ...

ASK_CODE = ...

CB_INVITE_APPROVE = 'invite_approve_'

CB_HAVE_CODE = 'invite_havecode'

WELCOME_TEXT = '👋 Welcome to Mimiq\n\nMimiq automates perp trading across DEXes from Telegram — copy top traders, or run market-neutral funding strategies.\n\nMimiq is currently invite-only. No invite code yet? Join our waitlist.'

async def invite_gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point: pass through if already verified; a deep-link code (t.me/<bot>?start=CODE → Telegram sends "/start CODE", landing in context.args) redeems immediately, same as typing it; otherwise ask fo"""
    user_id = update.effective_user.id
    args = getattr(context, 'args', None)
    waitlist_link = bool(args) and args[0].strip().lower() == 'waitlist'
    if await database.is_invite_verified(user_id) and (not (waitlist_link and _is_admin(user_id))):
        from .menu import show_menu
        await show_menu(update, context)
        return ConversationHandler.END
    if args and (not waitlist_link):
        return await _try_redeem(update, context, args[0].strip())
    kb = InlineKeyboardMarkup([[InlineKeyboardButton('📝 Join waitlist', callback_data=CB_WAITLIST_START)], [InlineKeyboardButton('🔑 I already have a code', callback_data=CB_HAVE_CODE)]])
    await update.effective_message.reply_text(WELCOME_TEXT, reply_markup=kb)
    return ASK_CODE

async def have_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """"I already have a code": the user is already in ASK_CODE (the welcome screen put them there), so this only tells them what to do next."""
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton('📝 Join waitlist instead', callback_data=CB_WAITLIST_START)]])
    await query.edit_message_text('🔑 Send your invite code here as a message.', reply_markup=kb)

async def got_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    try:
        await update.message.delete()
    except Exception:
        pass
    return await _try_redeem(update, context, code)

async def _try_redeem(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    """Shared by got_code (typed message) and invite_gate (deep-link /start payload) — identical lockout/already-joined/invalid/used-up handling regardless of how the code arrived."""
    user_id = update.effective_user.id
    remaining_secs = await database.invite_check_locked(user_id)
    if remaining_secs:
        mins, secs = (remaining_secs // 60, remaining_secs % 60)
        await update.effective_chat.send_message(f'⛔ Too many failed attempts. Try again in {mins}m {secs}s.')
        return ConversationHandler.END
    if not await database.user_exists(user_id):
        await database.create_user(user_id)
    result = await database.redeem_invite_code(code, user_id)
    if result == 'ok':
        logger.info('User %s joined with invite code', user_id)
        from .menu import show_menu
        await show_menu(update, context)
        return ConversationHandler.END
    if result == 'already_joined':
        await update.effective_chat.send_message("✅ You're already verified. Use /start to continue.")
        return ConversationHandler.END
    left = await database.invite_record_failure(user_id)
    if left == 0:
        await update.effective_chat.send_message('⛔ Too many failed attempts. Please try again later.')
        return ConversationHandler.END
    if result == 'used_up':
        await update.effective_chat.send_message(f'❌ This invite code has already been fully used.\nPlease ask for a new one. ({left} attempt{('s' if left != 1 else '')} left)')
        return ASK_CODE
    await update.effective_chat.send_message(f'❌ Invalid invite code. Please try again. ({left} attempt{('s' if left != 1 else '')} left)')
    return ASK_CODE

def _is_admin(user_id: int) -> bool:
    return ADMIN_TELEGRAM_ID != 0 and user_id == ADMIN_TELEGRAM_ID

async def issue_code(context: ContextTypes.DEFAULT_TYPE, target_id: int, admin_id: int):
    """Single-use code for target_id, DMed to them."""
    code = secrets.token_urlsafe(16)
    await database.create_invite_code(code, max_uses=1, created_by=admin_id)
    sent_ok = True
    try:
        await context.bot.send_message(target_id, f"🎉 *You've been approved!*\n\nYour invite code:\n`{code}`\n\nSend it here to get started.", parse_mode='Markdown')
    except Exception:
        logger.exception('Failed to DM invite code to user %s', target_id)
        sent_ok = False
    return (code, sent_ok)

async def approve_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not _is_admin(update.effective_user.id):
        await query.answer('Not authorized.', show_alert=True)
        return
    target_id = int(query.data[len(CB_INVITE_APPROVE):])
    code, sent_ok = await issue_code(context, target_id, update.effective_user.id)
    await query.answer()
    suffix = '\n\n✅ Approved — code sent.' if sent_ok else f"\n\n⚠️ Approved but couldn't DM the user (blocked the bot?). Code: {code}"
    await query.edit_message_text(query.message.text + suffix)

async def cmd_newcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/newcode [max_uses] [custom_code], order-independent (live fix — a user typed "/newcode alice 10" expecting code="alice" uses=10, but the original fixed-position parsing read args[0] as max"""
    if not _is_admin(update.effective_user.id):
        return
    args = context.args or []
    max_uses = 1
    custom_code = None
    for a in args:
        if a.isdigit():
            max_uses = int(a)
        else:
            custom_code = a
    code = custom_code or secrets.token_urlsafe(16)
    try:
        await database.create_invite_code(code, max_uses=max_uses, created_by=update.effective_user.id)
    except Exception as e:
        logger.error('newcode failed (code=%s): %s', code, e)
        await update.message.reply_text(f"❌ Couldn't create `{code}` — it may already be taken. Try a different one.", parse_mode='Markdown')
        return
    warn = '\n\n⚠️ Short codes can be guessed. Use 10 or more characters for a code you hand out publicly.' if custom_code and len(custom_code) < MIN_SAFE_CODE_LEN else ''
    await update.message.reply_text(f'✅ New invite code created:\n\n`{code}`\n\nUses: {max_uses}{warn}', parse_mode='Markdown')
    if TELEGRAM_BOT_URL:
        await update.message.reply_text(f"You're invited to Mimiq! 🎉\n\n{TELEGRAM_BOT_URL}?start={code}")

async def cmd_codes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    codes = await database.list_invite_codes()
    if not codes:
        await update.message.reply_text('No invite codes yet. Use /newcode to create one.')
        return
    lines = ['📋 *Invite Codes*\n']
    for c in codes:
        bar = '█' * c['uses'] + '░' * (c['max_uses'] - c['uses'])
        lines.append(f'`{c['code']}` — {c['uses']}/{c['max_uses']} {bar}')
    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')

def build_handler() -> ConversationHandler:
    return ConversationHandler(conversation_timeout=CONVO_TIMEOUT_S, entry_points=[CommandHandler('start', invite_gate), CommandHandler('leavewaitlist', cmd_leave)], states={ASK_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_code)]}, fallbacks=[], per_message=False, name='invite')
