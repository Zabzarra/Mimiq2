"""handlers.link_risex — dedicated RiseX linking flow."""

from __future__ import annotations

import logging

import httpx

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup

from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, CallbackQueryHandler, filters

import config

import database

import rate_limiter

import risex_utils as rx

from encryption import encrypt, preload_enc_salt

from lighter_utils import APPROVE_APP_BASE, APPROVE_APP_PUBLIC, APPROVE_APP_SECRET, TELEGRAM_BOT_URL

from dex.registry import DEX_REGISTRY

from dex.spec import WalletCreds

from .base import CB_BACK, BACK_ROW, _resolve_wallet, _wallet_from_start_callback, _try_delete, edit_or_send, CONVO_TIMEOUT_S, flash_message, safe_md

from .menu import show_menu

from . import menu as _menu

from .link import _approve_risex_builder_fee

from http_ctx import SSL_CTX

logger = logging.getLogger(__name__)

spec = DEX_REGISTRY['risex']

CB_LINK_RISEX = 'link_risex_start'

CB_ADD_RISEX_ONLY = 'add_risex_only'

CB_RETRY = 'link_risex_retry'

CB_DUP_CONTINUE = 'link_risex_dup_continue'

_ACCOUNT_STATE = ...

_PK_STATE = ...

_FAIL_STATE = ...

_DUP_STATE = ...

back_kb = InlineKeyboardMarkup(BACK_ROW)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if not rate_limiter.check_rate(user_id, 'link_account'):
        await query.answer('Too many attempts — try again in a minute.', show_alert=True)
        return ConversationHandler.END
    if query.data == CB_ADD_RISEX_ONLY:
        if not rate_limiter.check_rate(user_id, 'create_wallet'):
            await query.answer('Too many wallets created — try again shortly.', show_alert=True)
            return ConversationHandler.END
        await query.answer()
        wallets = await database.get_wallets(user_id)
        wallet_id = await database.create_wallet(user_id, f'Wallet {len(wallets) + 1}')
        await database.set_default_wallet(user_id, wallet_id)
    else:
        await query.answer()
        wallet = await _wallet_from_start_callback(user_id, context, query.data)
        if wallet is None:
            wallet, _ = await _resolve_wallet(user_id, context)
        if not wallet:
            await query.edit_message_text('No wallet selected.')
            return ConversationHandler.END
        wallet_id = wallet['id']
    context.user_data['_link_risex'] = {'wallet_id': wallet_id}
    await query.edit_message_text(f"{spec.emoji} *Link {spec.label}*\n\n🆔 Enter your *RiseX account's L1 wallet address* (`0x…`):", parse_mode='Markdown', reply_markup=back_kb)
    return _ACCOUNT_STATE

async def handle_risex_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    token = query.data.removeprefix('risex_save_')
    if not token:
        await query.edit_message_text('⚠️ Invalid save token.')
        return
    await query.edit_message_text('⏳ Saving session key…')
    headers = {}
    if APPROVE_APP_SECRET:
        headers['Authorization'] = f'Bearer {APPROVE_APP_SECRET}'
    try:
        async with httpx.AsyncClient(timeout=15, verify=SSL_CTX) as http:
            r = await http.get(f'{APPROVE_APP_BASE}/api/risex-claim/{token}', headers=headers)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.error('[link_risex] claim failed uid=%s token=%s: %s', user_id, token[:8], e)
        await query.edit_message_text('❌ Could not retrieve the session key. The link may have expired — please try linking RiseX again.')
        return
    account = data['account']
    session_pk = data['session_pk']
    wallet_id = int(data['wallet_id'])
    wallet = await database.get_wallet(wallet_id)
    if not wallet or wallet.get('telegram_id') != user_id:
        logger.warning('[link_risex] ownership mismatch uid=%s wallet_id=%s', user_id, wallet_id)
        await query.edit_message_text('⚠️ Wallet not found.')
        return
    from .fee_reapprove import risex_expected_account
    expected = await risex_expected_account(user_id, wallet_id)
    if expected and expected.lower() != str(account).lower():
        logger.warning('[link_risex] re-approve account mismatch uid=%s wallet=%s', user_id, wallet_id)
        await query.edit_message_text('⚠️ *Wrong wallet connected.* Nothing was changed.\n\nPlease connect the wallet of the RiseX account that is linked to this wallet and start again from the re-approval message.', parse_mode='Markdown')
        return
    dup = await database.find_other_wallet_with_account('risex', account, wallet_id)
    if dup:
        context.user_data['_link_risex_wc_pending'] = {'account': account, 'session_pk': session_pk, 'wallet_id': wallet_id}
        status = 'active' if dup['active'] else 'inactive'
        dup_kb = InlineKeyboardMarkup([[InlineKeyboardButton('⚠️ Link anyway', callback_data='risex_wc_dup_continue')]])
        await edit_or_send(update, context, f'⚠️ *This RiseX account is already linked* to {safe_md(dup['name'] or dup['wallet_id'])} ({dup['mode']} mode, {status}). Running the same account from two wallets can cause conflicting trades and margin double-booking.\n\nContinue anyway?', parse_mode='Markdown', reply_markup=dup_kb)
        return
    await _finish_wc_save(update, context, account, session_pk, wallet_id)

async def handle_risex_wc_dup_continue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pending = context.user_data.pop('_link_risex_wc_pending', None)
    if not pending:
        await query.edit_message_text('⚠️ Nothing pending — please link RiseX again.')
        return
    await _finish_wc_save(update, context, pending['account'], pending['session_pk'], pending['wallet_id'])

async def _finish_wc_save(update: Update, context: ContextTypes.DEFAULT_TYPE, account: str, session_pk: str, wallet_id: int):
    user_id = update.effective_user.id
    await preload_enc_salt(user_id)
    private_key_enc = encrypt(session_pk, user_id)
    await database.upsert_wallet_platform(wallet_id=wallet_id, platform='risex', account_id=account, api_key_enc=None, private_key_enc=private_key_enc, account_type='session_key')
    await _approve_risex_builder_fee(account, session_pk, wallet_id)
    await database.set_active_platform(wallet_id, 'risex', user_id)
    _menu._tx_cache.pop((int(wallet_id), 'risex'), None)
    logger.info('[link_risex] saved wallet=%s account=%s uid=%s (walletconnect)', wallet_id, account, user_id)
    await flash_message(context, update.effective_chat.id, f'✅ {spec.emoji} *{spec.label}* linked and activated.')
    await show_menu(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop('_link_risex', None)
    await show_menu(update, context)
    return ConversationHandler.END

def build_handler(transport_provider=None) -> ConversationHandler:
    """transport_provider mirrors link.build_link_handler's param — reused so RiseX validation goes through the exact same Gap-J health-check path as every other DEX."""

    async def _start_walletconnect(update: Update, context: ContextTypes.DEFAULT_TYPE, sess: dict):
        """New RiseX account without a registered signer: ONE message with the one-tap signing link (handlers/fee_reapprove.py, link mode) — the wallet signs once, the bot stores the key by itself and activates """
        user_id = update.effective_user.id
        wallet_id = sess['wallet_id']
        account = sess['account_id']
        if not sess.get('_wc_dup_ok'):
            dup = await database.find_other_wallet_with_account('risex', account, wallet_id)
            if dup:
                sess['_pending_wc'] = True
                status = 'active' if dup['active'] else 'inactive'
                dup_kb = InlineKeyboardMarkup([[InlineKeyboardButton('⚠️ Link anyway', callback_data=CB_DUP_CONTINUE)], [InlineKeyboardButton('← Back', callback_data=CB_BACK)]])
                await edit_or_send(update, context, f'⚠️ *This RiseX account is already linked* to {safe_md(dup['name'] or dup['wallet_id'])} ({dup['mode']} mode, {status}). Running the same account from two wallets can cause conflicting trades and margin double-booking.\n\nContinue anyway?', parse_mode='Markdown', reply_markup=dup_kb)
                return _DUP_STATE
        from .fee_reapprove import send_link_approval
        try:
            await database.clear_risex_builder_fee_approved(wallet_id)
            result = await send_link_approval(context, wallet_id, 'risex', pending_account=account)
        except Exception as e:
            logger.error('[link_risex] wallet=%s wallet-connect message failed: %s', wallet_id, e)
            result = 'error'
        context.user_data.pop('_link_risex', None)
        if result != 'sent':
            await edit_or_send(update, context, '❌ Could not start the wallet-connect flow. Please try again shortly.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('← Back', callback_data='menu_back')]]))
        return ConversationHandler.END

    async def collect_account_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
        raw = (update.message.text or '').strip()
        await _try_delete(update)
        sess = context.user_data.get('_link_risex')
        if not sess:
            return ConversationHandler.END
        if not raw:
            await edit_or_send(update, context, '⚠️ Input must not be empty.', reply_markup=back_kb)
            return _ACCOUNT_STATE
        if not raw.lower().startswith('0x') or len(raw) != 42:
            await edit_or_send(update, context, '⚠️ Not a valid `0x…` address. Try again:', parse_mode='Markdown', reply_markup=back_kb)
            return _ACCOUNT_STATE
        sess['account_id'] = raw
        await edit_or_send(update, context, '⏳ Checking your RiseX account…')
        try:
            async with httpx.AsyncClient(timeout=15, verify=SSL_CTX) as http:
                has_signer = await rx.has_active_signer(http, rx.RISEX_REST_MAINNET, raw)
        except Exception as e:
            logger.error('[link_risex] wallet=%s signer check failed: %s', sess['wallet_id'], e)
            has_signer = True
        if has_signer:
            await edit_or_send(update, context, "🔐 *This account already has a registered signer.*\n\nEnter your *RiseX session-signer private key* (registered as an authorized signer on your RiseX account via `registerSigner`).\n\n⚠️ NOT your wallet's master private key — a separate signer key that can only sign orders. Stored encrypted.", parse_mode='Markdown', reply_markup=back_kb)
            return _PK_STATE
        return await _start_walletconnect(update, context, sess)

    async def _validate_and_save(update: Update, context: ContextTypes.DEFAULT_TYPE, creds: WalletCreds):
        user_id = update.effective_user.id
        sess = context.user_data.get('_link_risex', {})
        wallet_id = sess.get('wallet_id')
        if transport_provider is not None:
            try:
                transport = await transport_provider(spec, creds)
                adapter = spec.adapter_factory(creds, transport)
                ok = await adapter.verify_credentials()
            except Exception as e:
                logger.error('[link_risex] wallet=%s validation error: %s', wallet_id, e)
                ok = False
            if not ok:
                retry_kb = InlineKeyboardMarkup([[InlineKeyboardButton('🔄 Try Again', callback_data=CB_RETRY)], [InlineKeyboardButton('← Back', callback_data=CB_BACK)]])
                await edit_or_send(update, context, '❌ Validation failed. Please check your credentials and try again.', reply_markup=retry_kb)
                return _FAIL_STATE
        dup = await database.find_other_wallet_with_account('risex', creds.account_id, wallet_id)
        if dup:
            sess['_pending_save'] = creds
            status = 'active' if dup['active'] else 'inactive'
            dup_kb = InlineKeyboardMarkup([[InlineKeyboardButton('⚠️ Link anyway', callback_data=CB_DUP_CONTINUE)], [InlineKeyboardButton('← Back', callback_data=CB_BACK)]])
            await edit_or_send(update, context, f'⚠️ *This RiseX account is already linked* to {safe_md(dup['name'] or dup['wallet_id'])} ({dup['mode']} mode, {status}). Running the same account from two wallets can cause conflicting trades and margin double-booking.\n\nContinue anyway?', parse_mode='Markdown', reply_markup=dup_kb)
            return _DUP_STATE
        return await _finish_save(update, context, creds)

    async def confirm_dup(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        sess = context.user_data.get('_link_risex', {})
        if sess.pop('_pending_wc', False):
            sess['_wc_dup_ok'] = True
            return await _start_walletconnect(update, context, sess)
        creds = sess.pop('_pending_save', None)
        if not creds:
            return ConversationHandler.END
        return await _finish_save(update, context, creds)

    async def _finish_save(update: Update, context: ContextTypes.DEFAULT_TYPE, creds: WalletCreds):
        user_id = update.effective_user.id
        sess = context.user_data.get('_link_risex', {})
        wallet_id = sess.get('wallet_id')
        await preload_enc_salt(user_id)
        pk_enc = encrypt(creds.private_key, user_id)
        await database.upsert_wallet_platform(wallet_id=wallet_id, platform='risex', account_id=creds.account_id, api_key_enc=None, private_key_enc=pk_enc, account_type='session_key')
        await _approve_risex_builder_fee(creds.account_id, creds.private_key, wallet_id)
        await database.set_active_platform(wallet_id, 'risex', user_id)
        _menu._tx_cache.pop((int(wallet_id), 'risex'), None)
        context.user_data.pop('_link_risex', None)
        logger.info('[link_risex] wallet=%s linked by user=%s (manual)', wallet_id, user_id)
        await flash_message(context, update.effective_chat.id, f'✅ {spec.emoji} *{spec.label}* linked and activated.')
        await show_menu(update, context)
        return ConversationHandler.END

    async def collect_private_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
        raw = (update.message.text or '').strip()
        await _try_delete(update)
        sess = context.user_data.get('_link_risex')
        if not sess:
            return ConversationHandler.END
        if not raw:
            await edit_or_send(update, context, '⚠️ Input must not be empty.', reply_markup=back_kb)
            return _PK_STATE
        creds = WalletCreds(account_id=sess['account_id'], private_key=raw)
        await edit_or_send(update, context, '⏳ Checking connection…')
        return await _validate_and_save(update, context, creds)

    async def _render_pk_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """The short PK re-entry prompt (: factored out so retry() and the new fail_back/dup_back back-handlers share one source of truth)."""
        await edit_or_send(update, context, '🔐 Enter your *RiseX session-signer private key*:', parse_mode='Markdown', reply_markup=back_kb)
        return _PK_STATE

    async def retry(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        sess = context.user_data.get('_link_risex')
        if not sess:
            return ConversationHandler.END
        return await _render_pk_prompt(update, context)

    async def account_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """← Back from _PK_STATE → _ACCOUNT_STATE (back-navigation fix)."""
        query = update.callback_query
        await query.answer()
        await edit_or_send(update, context, f"{spec.emoji} *Link {spec.label}*\n\n🆔 Enter your *RiseX account's L1 wallet address* (`0x…`):", parse_mode='Markdown', reply_markup=back_kb)
        return _ACCOUNT_STATE

    async def fail_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """← Back from _FAIL_STATE → _PK_STATE ()."""
        query = update.callback_query
        await query.answer()
        return await _render_pk_prompt(update, context)

    async def dup_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """← Back from _DUP_STATE → _PK_STATE (); from the WalletConnect path → the account prompt."""
        query = update.callback_query
        await query.answer()
        sess = context.user_data.get('_link_risex', {})
        if sess.pop('_pending_wc', False):
            return await account_back(update, context)
        return await _render_pk_prompt(update, context)
    entry_points = [CallbackQueryHandler(start, pattern=f'^{CB_LINK_RISEX}(_\\d+)?$'), CallbackQueryHandler(start, pattern=f'^{CB_ADD_RISEX_ONLY}$')]
    return ConversationHandler(conversation_timeout=CONVO_TIMEOUT_S, entry_points=entry_points, states={_ACCOUNT_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_account_id)], _PK_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_private_key), CallbackQueryHandler(account_back, pattern=f'^{CB_BACK}$')], _FAIL_STATE: [CallbackQueryHandler(retry, pattern=f'^{CB_RETRY}$'), CallbackQueryHandler(fail_back, pattern=f'^{CB_BACK}$')], _DUP_STATE: [CallbackQueryHandler(confirm_dup, pattern=f'^{CB_DUP_CONTINUE}$'), CallbackQueryHandler(dup_back, pattern=f'^{CB_BACK}$')]}, fallbacks=[CallbackQueryHandler(cancel, pattern=f'^{CB_BACK}$')] + entry_points, per_message=False, name='link_risex')
