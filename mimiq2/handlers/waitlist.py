"""handlers.waitlist — waitlist for people who have no invite code yet ()."""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup

from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, CommandHandler

import database

from config import ADMIN_TELEGRAM_ID

from dex.registry import DEX_REGISTRY

from .base import CB_BACK, edit_or_send, CONVO_TIMEOUT_S

logger = logging.getLogger(__name__)

INTEREST, VENUES, VOLUME = range(3)

CB_WAITLIST_START = 'wl_start'

CB_INTEREST_PREFIX = 'wl_i_'

CB_INTERESTS_DONE = 'wl_idone'

CB_VENUE_PREFIX = 'wl_v_'

CB_VENUES_DONE = 'wl_vdone'

CB_VOLUME_PREFIX = 'wl_vol_'

CB_STEP_BACK = 'wl_back'

INTERESTS = {'copy': 'Copy Trading', 'dn': 'Delta Neutral'}

VOLUMES = {'1': 'under $10k', '2': '$10k – $100k', '3': '$100k – $1M', '4': 'over $1M'}

FIRST_QUESTION_TEXT = '📝 Mimiq waitlist\n\nTo join our waitlist you need to answer the following questions. We store your Telegram username and your answers; send /leavewaitlist at any time to delete them.\n\nWhat are you interested in? Tap to select, then press Done.'

def _is_admin(user_id: int) -> bool:
    return ADMIN_TELEGRAM_ID != 0 and user_id == ADMIN_TELEGRAM_ID

VENUE_ORDER = ('hyperliquid', 'lighter', 'lighter_rh', 'risex', 'arcus', 'qfex', 'ondo', 'extended', 'perpl', 'hibachi', 'propr')

def _venue_options() -> dict:
    labels = {spec.name: spec.label for spec in DEX_REGISTRY.values()}
    ordered = [n for n in VENUE_ORDER if n in labels] + [n for n in labels if n not in VENUE_ORDER]
    return {n: labels[n] for n in ordered}

def _nav_row() -> list:
    return [InlineKeyboardButton('⬅ Back', callback_data=CB_STEP_BACK), InlineKeyboardButton('❌ Cancel', callback_data=CB_BACK)]

def _wl(context) -> dict:
    return context.user_data.setdefault('wl', {'interests': [], 'venues': []})

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if await database.is_invite_verified(user_id) and (not _is_admin(user_id)):
        await edit_or_send(update, context, '✅ You already have access — use /start.')
        return ConversationHandler.END
    context.user_data['wl'] = {'interests': [], 'venues': []}
    return await _show_interests(update, context)

def _interests_kb(selected: list) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(('✅ ' if key in selected else '') + label, callback_data=f'{CB_INTEREST_PREFIX}{key}')] for key, label in INTERESTS.items()]
    rows.append([InlineKeyboardButton('Done ➜', callback_data=CB_INTERESTS_DONE)])
    rows.append(_nav_row())
    return InlineKeyboardMarkup(rows)

async def _show_interests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await edit_or_send(update, context, FIRST_QUESTION_TEXT, reply_markup=_interests_kb(_wl(context)['interests']))
    return INTEREST

async def toggle_interest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.callback_query.data[len(CB_INTEREST_PREFIX):]
    if key not in INTERESTS:
        return INTEREST
    selected = _wl(context)['interests']
    if key in selected:
        selected.remove(key)
    else:
        selected.append(key)
    try:
        await update.callback_query.edit_message_reply_markup(reply_markup=_interests_kb(selected))
        await update.callback_query.answer()
    except Exception:
        return await _show_interests(update, context)
    return INTEREST

async def interests_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _wl(context)['interests']:
        await update.callback_query.answer('Please select at least one.', show_alert=True)
        return INTEREST
    return await _show_venues(update, context)

async def back_to_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Back from the first step: the gate's welcome screen again (the invite conversation is still waiting for a code)."""
    from .invite import WELCOME_TEXT, CB_HAVE_CODE
    context.user_data.pop('wl', None)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton('📝 Join waitlist', callback_data=CB_WAITLIST_START)], [InlineKeyboardButton('🔑 I already have a code', callback_data=CB_HAVE_CODE)]])
    await edit_or_send(update, context, WELCOME_TEXT, reply_markup=kb)
    return ConversationHandler.END

def _venues_kb(selected: list) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(('✅ ' if name in selected else '') + label, callback_data=f'{CB_VENUE_PREFIX}{name}')] for name, label in _venue_options().items()]
    rows.append([InlineKeyboardButton('Done ➜', callback_data=CB_VENUES_DONE)])
    rows.append(_nav_row())
    return InlineKeyboardMarkup(rows)

async def _show_venues(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await edit_or_send(update, context, 'Which venues would you use? Tap to select, then press Done (optional).', reply_markup=_venues_kb(_wl(context)['venues']))
    return VENUES

async def toggle_venue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.callback_query.data[len(CB_VENUE_PREFIX):]
    if name not in _venue_options():
        return VENUES
    selected = _wl(context)['venues']
    if name in selected:
        selected.remove(name)
    else:
        selected.append(name)
    try:
        await update.callback_query.edit_message_reply_markup(reply_markup=_venues_kb(selected))
        await update.callback_query.answer()
    except Exception:
        return await _show_venues(update, context)
    return VENUES

async def venues_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _show_volume(update, context)

async def _show_volume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=f'{CB_VOLUME_PREFIX}{key}')] for key, label in VOLUMES.items()] + [[InlineKeyboardButton('Skip', callback_data=f'{CB_VOLUME_PREFIX}0')], _nav_row()])
    await edit_or_send(update, context, 'Typical trading volume per month? (optional)', reply_markup=kb)
    return VOLUME

async def got_volume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.callback_query.data[len(CB_VOLUME_PREFIX):]
    if key != '0' and key not in VOLUMES:
        return VOLUME
    wl = _wl(context)
    wl['volume'] = VOLUMES.get(key)
    user = update.effective_user
    options = _venue_options()
    venues = ','.join((v for v in wl.get('venues', []) if v in options))
    interests = ','.join((k for k in INTERESTS if k in wl.get('interests', [])))
    await database.save_waitlist_entry(user.id, user.username, interests, venues, wl.get('volume'))
    logger.info('[waitlist] user %s joined', user.id)
    context.user_data.pop('wl', None)
    await edit_or_send(update, context, "✅ You're on the waitlist.\n\nWe will message you here when your invite is ready. Send /leavewaitlist if you want your entry deleted.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop('wl', None)
    await edit_or_send(update, context, 'Cancelled. Send /start to begin again.')
    return ConversationHandler.END

async def cmd_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point of the invite gate's conversation (handlers/invite.build_handler): after the message the user lands where /start would put them — the menu if verified, otherwise the welcome screen, with t"""
    from .invite import invite_gate
    removed = await database.delete_waitlist_entry(update.effective_user.id)
    await update.effective_message.reply_text('Your waitlist entry was deleted.' if removed else 'You have no waitlist entry.')
    context.args = []
    return await invite_gate(update, context)

async def cmd_waitlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from .invite import CB_INVITE_APPROVE
    if not _is_admin(update.effective_user.id):
        return
    show_all = bool(context.args) and context.args[0].lower() == 'all'
    total, rows = await database.list_waitlist_pending(10, include_verified=show_all)
    if not total:
        await update.effective_message.reply_text('Waitlist: nobody pending.')
        return
    await update.effective_message.reply_text(f'Waitlist: {total} {('in total' if show_all else 'pending')}, newest {len(rows)} below.')
    options = _venue_options()
    for r in rows:
        uname = f'@{r['username']}' if r['username'] else '(no username)'
        venues = ', '.join((options.get(v, v) for v in r['venues'].split(',') if v)) or '—'
        text = f'{uname}  (ID {r['telegram_id']})' + ('  ✅ has access' if r.get('has_access') else '') + f'\nInterest: {', '.join((INTERESTS.get(k, k) for k in r['interest'].split(',') if k))}\nVenues: {venues}\nVolume: {r['volume'] or '—'}'
        kb = InlineKeyboardMarkup([[InlineKeyboardButton('✅ Approve & send code', callback_data=f'{CB_INVITE_APPROVE}{r['telegram_id']}')]])
        await update.effective_message.reply_text(text, reply_markup=kb)

async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/approve <telegram id or @username> — send a waitlist entry its invite code."""
    from .invite import issue_code
    if not _is_admin(update.effective_user.id):
        return
    arg = context.args[0].strip() if context.args else ''
    if not arg:
        await update.effective_message.reply_text('Usage: /approve <telegram id or @username>')
        return
    uid, uname = (int(arg), '') if arg.isdigit() else (-1, arg.lstrip('@'))
    entry = await database.get_waitlist_entry(uid, uname)
    if not entry:
        await update.effective_message.reply_text(f'Nobody on the waitlist matches {arg}.')
        return
    code, sent_ok = await issue_code(context, int(entry['telegram_id']), update.effective_user.id)
    await update.effective_message.reply_text(f'✅ Code sent to ID {entry['telegram_id']}.' if sent_ok else f'⚠️ Could not DM ID {entry['telegram_id']} (blocked the bot?). Code: {code}')

def build_handler() -> ConversationHandler:
    return ConversationHandler(conversation_timeout=CONVO_TIMEOUT_S, entry_points=[CallbackQueryHandler(start, pattern=f'^{CB_WAITLIST_START}$')], states={INTEREST: [CallbackQueryHandler(toggle_interest, pattern=f'^{CB_INTEREST_PREFIX}'), CallbackQueryHandler(interests_done, pattern=f'^{CB_INTERESTS_DONE}$'), CallbackQueryHandler(back_to_welcome, pattern=f'^{CB_STEP_BACK}$')], VENUES: [CallbackQueryHandler(toggle_venue, pattern=f'^{CB_VENUE_PREFIX}'), CallbackQueryHandler(venues_done, pattern=f'^{CB_VENUES_DONE}$'), CallbackQueryHandler(_show_interests, pattern=f'^{CB_STEP_BACK}$')], VOLUME: [CallbackQueryHandler(got_volume, pattern=f'^{CB_VOLUME_PREFIX}'), CallbackQueryHandler(_show_venues, pattern=f'^{CB_STEP_BACK}$')]}, fallbacks=[CallbackQueryHandler(cancel, pattern=f'^{CB_BACK}$'), CommandHandler('start', cancel)], per_message=False)
