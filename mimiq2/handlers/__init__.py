"""handlers — the Telegram UI layer for mimiq2 (Bereich D)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

async def _global_error_handler(update, context) -> None:
    """Catches whatever no handler's own try/except caught."""
    from config import ADMIN_TELEGRAM_ID
    from telegram import Update
    err = context.error
    logger.error('Unhandled exception', exc_info=err)
    if ADMIN_TELEGRAM_ID:
        uid = update.effective_user.id if isinstance(update, Update) and update.effective_user else '?'
        try:
            await context.bot.send_message(ADMIN_TELEGRAM_ID, f'🔥 Unhandled exception (user {uid}):\n\n{type(err).__name__}: {err}')
        except Exception:
            logger.exception('Failed to notify admin of unhandled exception')
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(update.effective_chat.id, '⚠️ Something went wrong. Please try again.')
        except Exception:
            logger.exception('Failed to notify user of unhandled exception')

_THROTTLE_LOG_EVERY_S = ...

_throttle_logged: dict = {}

async def _throttle(update, context) -> None:
    """Per-user flood limit for EVERY update, registered in group -1 (before the invite gate, so it also covers users who are not verified yet)."""
    import time
    import rate_limit
    from config import ADMIN_TELEGRAM_ID
    from telegram.ext import ApplicationHandlerStop
    user = update.effective_user
    if user is None or user.id == ADMIN_TELEGRAM_ID:
        return
    if rate_limit.check_user_rate(user.id):
        return
    now = time.monotonic()
    if now - _throttle_logged.get(user.id, -_THROTTLE_LOG_EVERY_S) >= _THROTTLE_LOG_EVERY_S:
        _throttle_logged[user.id] = now
        logger.warning('[throttle] user %s is over the per-user rate limit', user.id)
    if update.callback_query is not None:
        try:
            await update.callback_query.answer('⏳ Slow down a little.')
        except Exception:
            pass
    raise ApplicationHandlerStop

async def _throttle_cleanup(context) -> None:
    import time
    import rate_limit
    rate_limit.cleanup_stale_rate_entries()
    cutoff = time.monotonic() - _THROTTLE_LOG_EVERY_S
    for uid in [u for u, t in _throttle_logged.items() if t < cutoff]:
        del _throttle_logged[uid]

def register_all(app, transport_provider=None) -> None:
    """Register every ConversationHandler."""
    from telegram import Update
    from telegram.ext import CommandHandler, CallbackQueryHandler, TypeHandler
    from dex.registry import DEX_REGISTRY
    from .link import build_link_handler
    from .link_risex import build_handler as build_risex_link_handler, handle_risex_save, handle_risex_wc_dup_continue
    from .positions import build_positions_handler
    from .history import build_history_handler
    from .wallet_stats import build_wallet_stats_handlers
    from .watch_trader import build_handler as build_watch_handler
    from . import invite, menu, trader, settings, dn
    if transport_provider is None:
        logger.warning('[handlers] no transport_provider — link validation disabled')
    app.add_error_handler(_global_error_handler)
    app.add_handler(TypeHandler(Update, _throttle), group=-1)
    from . import waitlist
    app.add_handler(waitlist.build_handler(), group=0)
    app.add_handler(CommandHandler('waitlist', waitlist.cmd_waitlist), group=0)
    app.add_handler(CommandHandler('approve', waitlist.cmd_approve), group=0)
    app.add_handler(invite.build_handler(), group=0)
    app.add_handler(CommandHandler('newcode', invite.cmd_newcode))
    app.add_handler(CommandHandler('codes', invite.cmd_codes))
    app.add_handler(CallbackQueryHandler(invite.have_code, pattern=f'^{invite.CB_HAVE_CODE}$'))
    app.add_handler(CallbackQueryHandler(invite.approve_invite, pattern=f'^{invite.CB_INVITE_APPROVE}\\d+$'))
    n = 0
    for spec in DEX_REGISTRY.values():
        if spec.name == 'risex':
            continue
        app.add_handler(build_link_handler(spec, transport_provider))
        n += 1
    app.add_handler(build_risex_link_handler(transport_provider))
    n += 1
    app.add_handler(CallbackQueryHandler(handle_risex_save, pattern='^risex_save_'))
    app.add_handler(CallbackQueryHandler(handle_risex_wc_dup_continue, pattern='^risex_wc_dup_continue$'))
    app.add_handler(build_positions_handler(transport_provider))
    app.add_handler(build_history_handler(transport_provider))
    for h in build_wallet_stats_handlers():
        app.add_handler(h)
    app.add_handler(trader.build_handler())
    app.add_handler(build_watch_handler())
    settings.register(app)
    dn.register(app, transport_provider)
    menu.register(app, transport_provider)
    logger.info('[handlers] registered invite gate + %d link handler(s) + positions + trader + menu', n)
