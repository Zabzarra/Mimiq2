"""handlers.link — the link-handler MASK."""

from __future__ import annotations

import logging

import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup

from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, CallbackQueryHandler, filters

import database

import rate_limiter

from encryption import encrypt, preload_enc_salt

from dex.spec import DEXSpec, WalletCreds

from .base import CB_BACK, BACK_ROW, _resolve_wallet, _wallet_from_start_callback, _try_delete, edit_or_send, CONVO_TIMEOUT_S, safe_md, flash_message

from .menu import show_menu

from . import menu as _menu

from http_ctx import SSL_CTX

logger = logging.getLogger(__name__)

_FIELD_PROMPT = {'account_id': '🆔 Enter your *account ID*:', 'api_key': '🔑 Enter your *API key*:', 'private_key': '🔐 Enter your *private key* (needed for order signing):\n\n⚠️ The key is stored encrypted and only used by the trading bot.', 'public_key': '🔐 Enter your *public key*:', 'vault_id': '🆔 Enter your *vault ID*:'}

_SECRET_FIELDS = {'api_key', 'private_key', 'public_key'}

REFERRAL_LINKS = {'arcus': 'https://app.arcus.xyz/ref/MIMIQ2', 'hibachi': 'https://hibachi.xyz/r/mimiq', 'hyperliquid': 'https://app.hyperliquid.xyz/join/MIMIQ', 'risex': 'https://www.rise.trade/invite/mimiq', 'lighter': 'https://app.lighter.xyz/?referral=MIMIQ&source=none', 'lighter_rh': 'https://robinhoodchain.lighter.xyz/?referral=MIMIQ&source=none', 'ondo': 'https://app.ondoperps.xyz/?ref=M14GSK'}

CB_CHOOSE = 'linkacc_'

CB_SLOT = 'linkslot_'

CB_RETRY = 'link_retry'

CB_ARCUS_CONTINUE = 'link_arcus_continue'

CB_DUP_CONTINUE = 'link_dup_continue'

async def _approve_risex_builder_fee(account_id: str, signer_private_key: str, wallet_id) -> None:
    """One-time (account, builder) approval so RiseX will honor our builder fee on this wallet's orders — docs.risechain.com/docs/risex/trading/builder-codes step 3."""
    import risex_utils as rx
    if not rx.RISEX_BUILDER_ID:
        return
    try:
        import httpx
        async with httpx.AsyncClient(verify=SSL_CTX) as http:
            nm = rx.RiseXNonceManager(account_id)
            try:
                await rx.approve_builder_fee(http, rx.RISEX_REST_MAINNET, account_id, signer_private_key, nm, builder_id=rx.RISEX_BUILDER_ID, max_fee_bps=rx.RISEX_BUILDER_FEE_BPS)
            except Exception as e:
                if not rx.is_nonce_failure(str(e)):
                    raise
                await nm.resync(http, rx.RISEX_REST_MAINNET)
                await rx.approve_builder_fee(http, rx.RISEX_REST_MAINNET, account_id, signer_private_key, nm, builder_id=rx.RISEX_BUILDER_ID, max_fee_bps=rx.RISEX_BUILDER_FEE_BPS)
        await database.set_risex_builder_fee_approved(wallet_id)
        logger.info('[link_risex] wallet=%s builder-fee approved', wallet_id)
    except Exception as e:
        logger.error('[link_risex] wallet=%s builder-fee approve failed: %s', wallet_id, e)

LIGHTER_TIER_NOTICE = "⚠️  Linking switches your Lighter account to Premium. Lighter's trading fees apply."

def _with_tier_notice(spec, text: str) -> str:
    """First field prompt; Lighter / Lighter RH get the Premium notice up front."""
    if spec.name in ('lighter', 'lighter_rh'):
        text = f'{LIGHTER_TIER_NOTICE}\n\n{text}'
    return text

GATED_PLATFORMS = frozenset({'lighter', 'lighter_rh', 'hyperliquid', 'perpl'})

def build_link_handler(spec: DEXSpec, transport_provider=None) -> ConversationHandler:
    """One ConversationHandler for linking `spec`'s DEX."""
    cb_start = f'link_{spec.name}_start'
    cb_add = f'add_{spec.name}_only'
    fields = spec.cred_fields
    prompts = spec.field_prompts or {}
    choose_state = len(fields)
    slot_state = len(fields) + 1
    fail_state = len(fields) + 2
    notice_state = len(fields) + 3
    dup_state = len(fields) + 5
    back_kb = InlineKeyboardMarkup(BACK_ROW)
    end_kb = InlineKeyboardMarkup([[InlineKeyboardButton('← Back', callback_data='menu_back')]])

    def _prompt(field: str) -> str:
        return prompts.get(field, _FIELD_PROMPT[field])

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        if not rate_limiter.check_rate(user_id, 'link_account'):
            await query.answer('Too many attempts — try again in a minute.', show_alert=True)
            return ConversationHandler.END
        if query.data == cb_add:
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
        context.user_data['_link'] = {'wallet_id': wallet_id, 'creds': {}}
        if spec.name in REFERRAL_LINKS:
            return await _render_notice_screen(update, context)
        await query.edit_message_text(f'{spec.emoji} *Link {spec.label}*\n\n{_with_tier_notice(spec, _prompt(fields[0]))}', parse_mode='Markdown', reply_markup=back_kb)
        return 0

    async def _render_notice_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Factored out of start() (back-navigation fix) so field 0's "← Back" can re-render this exact screen for referral-nudge platforms."""
        ref_url = REFERRAL_LINKS[spec.name]
        nudge_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Join via Mimiq's link", url=ref_url)], [InlineKeyboardButton('I already have a wallet →', callback_data=CB_ARCUS_CONTINUE)], BACK_ROW[0]])
        await edit_or_send(update, context, f'{spec.emoji} *Link {spec.label}*\n\nNew to {spec.label}? Join via our link first — it supports Mimiq at no extra cost to you. Already have an account? Just continue.', parse_mode='Markdown', reply_markup=nudge_kb)
        return notice_state

    async def arcus_continue(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """'I already have a wallet' — proceeds past the referral nudge into normal field collection, same as start()'s non-referral path."""
        query = update.callback_query
        await query.answer()
        if '_link' not in context.user_data:
            return ConversationHandler.END
        await query.edit_message_text(f'{spec.emoji} *Link {spec.label}*\n\n{_with_tier_notice(spec, _prompt(fields[0]))}', parse_mode='Markdown', reply_markup=back_kb)
        return 0

    def _collector(idx: int):
        """Handler for credential field `idx`: store it, then prompt the next / validate+save."""
        field = fields[idx]

        async def collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
            raw = (update.message.text or '').strip()
            await _try_delete(update)
            sess = context.user_data.get('_link')
            if not sess:
                return ConversationHandler.END
            if not raw:
                await edit_or_send(update, context, '⚠️ Input must not be empty.', reply_markup=back_kb)
                return idx
            sess['creds'][field] = raw
            found_note = ''
            if spec.name in ('lighter', 'lighter_rh') and field == 'account_id':
                if spec.name == 'lighter':
                    import lighter_utils as lu
                else:
                    import lighter_rh_utils as lu
                if re.fullmatch('0x[0-9a-fA-F]{40}', raw):
                    sess['l1_address'] = raw.lower()
                    acct_idx, err = await lu.lookup_account_index(raw)
                    if err:
                        logger.error('[link_lighter] L1 lookup failed: %s', err)
                        await edit_or_send(update, context, '❌ Lighter lookup failed — try again:', reply_markup=back_kb)
                        return idx
                    if acct_idx is None:
                        await edit_or_send(update, context, '❌ No Lighter account found for this address. Try again:', reply_markup=back_kb)
                        return idx
                    sess['creds'][field] = str(acct_idx)
                    found_note = f'✅ Found Lighter account `#{acct_idx}`\n\n'
                elif raw.isdigit():
                    data, err = await lu.get_lighter_account(int(raw))
                    if err or data is None:
                        await edit_or_send(update, context, f'❌ Account #{raw} not found on Lighter. Try again:', reply_markup=back_kb)
                        return idx
                else:
                    await edit_or_send(update, context, '⚠️ Enter your `0x…` L1 address or a numeric account index:', parse_mode='Markdown', reply_markup=back_kb)
                    return idx
            nxt = idx + 1
            if nxt < len(fields):
                await edit_or_send(update, context, found_note + _prompt(fields[nxt]), parse_mode='Markdown', reply_markup=back_kb)
                return nxt
            if spec.name in ('lighter', 'lighter_rh'):
                return await _ask_slot(update, context)
            return await _validate_and_save(update, context)
        return collect

    def _field_back(idx: int):
        """← Back from credential field `idx` () — re-prompts field `idx-1`, or (for idx==0, only ever wired up for referral-nudge platforms — see states[0] below) returns to the notice screen."""

        async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
            query = update.callback_query
            await query.answer()
            if idx == 0:
                return await _render_notice_screen(update, context)
            await edit_or_send(update, context, _prompt(fields[idx - 1]), parse_mode='Markdown', reply_markup=back_kb)
            return idx - 1
        return back

    async def _ask_slot(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lighter only: the API key is registered in a user-chosen slot (0-9) — ask for it before validating, so verify_credentials signs with the correct index."""
        rows = [[InlineKeyboardButton(str(i), callback_data=f'{CB_SLOT}{i}') for i in range(0, 5)], [InlineKeyboardButton(str(i), callback_data=f'{CB_SLOT}{i}') for i in range(5, 10)]]
        rows.append(BACK_ROW[0])
        await edit_or_send(update, context, '🔢 Which *API key slot* is this key registered in?\n_(default is 3)_', parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(rows))
        return slot_state

    async def slot_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """← Back from slot_state → the last credential field ()."""
        query = update.callback_query
        await query.answer()
        await edit_or_send(update, context, _prompt(fields[-1]), parse_mode='Markdown', reply_markup=back_kb)
        return len(fields) - 1

    async def got_slot(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        sess = context.user_data.get('_link')
        if not sess:
            return ConversationHandler.END
        sess['api_key_slot'] = int(query.data[len(CB_SLOT):])
        return await _validate_and_save(update, context)

    async def _validate_and_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        sess = context.user_data.get('_link', {})
        wallet_id = sess.get('wallet_id')
        collected = sess.get('creds', {})
        try:
            vault_id = int(collected.get('vault_id') or 0)
        except ValueError:
            vault_id = 0
        creds = WalletCreds(account_id=collected.get('account_id') or (str(vault_id) if 'vault_id' in fields else ''), api_key=collected.get('api_key', ''), private_key=collected.get('private_key', ''), api_key_slot=int(sess.get('api_key_slot') or 0), public_key=collected.get('public_key', ''), vault_id=vault_id)
        await edit_or_send(update, context, '⏳ Checking connection…')
        transport = None
        if transport_provider is not None:
            try:
                transport = await transport_provider(spec, creds)
                adapter = spec.adapter_factory(creds, transport)
                ok = await adapter.verify_credentials()
            except Exception as e:
                logger.error('[link_%s] wallet=%s validation error: %s', spec.name, wallet_id, e)
                ok = False
            if not ok:
                retry_kb = InlineKeyboardMarkup([[InlineKeyboardButton('🔄 Try Again', callback_data=CB_RETRY)], [InlineKeyboardButton('← Back', callback_data=CB_BACK)]])
                await edit_or_send(update, context, '❌ Validation failed. Please check your credentials and try again.', reply_markup=retry_kb)
                return fail_state
        if spec.link_resolver is not None:
            try:
                candidates = list(await spec.link_resolver(creds, transport) or [])
            except Exception as e:
                logger.error('[link_%s] wallet=%s resolver error: %s', spec.name, wallet_id, e)
                candidates = []
            if not candidates:
                context.user_data.pop('_link', None)
                await edit_or_send(update, context, '⚠️ No tradeable account found. Please create one first and try again.', reply_markup=end_kb)
                return ConversationHandler.END
            sess['candidates'] = candidates
            return await _render_choose_screen(update, context, sess)
        return await _do_save(update, context, creds, creds.account_id)

    async def _render_pre_validation_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Whatever screen was showing right before validation ran (back-navigation fix) — slot_state's prompt for Lighter/Lighter-RH (the last real choice before validating), or the last credential f"""
        if spec.name in ('lighter', 'lighter_rh'):
            return await _ask_slot(update, context)
        await edit_or_send(update, context, _prompt(fields[-1]), parse_mode='Markdown', reply_markup=back_kb)
        return len(fields) - 1

    async def fail_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """← Back from fail_state → the pre-validation screen () — distinct from "🔄 Try Again" (retry(), which resets ALL the way to field 0): this just lets the user fix the one thing that was actuall"""
        query = update.callback_query
        await query.answer()
        return await _render_pre_validation_screen(update, context)

    async def _render_choose_screen(update: Update, context: ContextTypes.DEFAULT_TYPE, sess: dict):
        """Factored out of _validate_and_save (back-navigation fix) so dup_state's "← Back" (on resolver specs) can re-render this exact screen."""
        candidates = sess.get('candidates', [])
        rows = [[InlineKeyboardButton(c.get('label') or c['accountId'], callback_data=f'{CB_CHOOSE}{i}')] for i, c in enumerate(candidates)]
        rows.append(BACK_ROW[0])
        await edit_or_send(update, context, '✅ Verified. *Which account should be traded?*', parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(rows))
        return choose_state

    async def choose_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """← Back from choose_state → the pre-validation screen ()."""
        query = update.callback_query
        await query.answer()
        return await _render_pre_validation_screen(update, context)

    async def choose_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """CHOOSE state: the user picked a resolver candidate → save with its accountId."""
        query = update.callback_query
        await query.answer()
        sess = context.user_data.get('_link', {})
        candidates = sess.get('candidates', [])
        idx = int(query.data[len(CB_CHOOSE):])
        if idx >= len(candidates):
            context.user_data.pop('_link', None)
            return ConversationHandler.END
        collected = sess.get('creds', {})
        creds = WalletCreds(account_id=candidates[idx]['accountId'], api_key=collected.get('api_key', ''), private_key=collected.get('private_key', ''))
        return await _do_save(update, context, creds, creds.account_id)

    async def _activate_and_finish(update, context, wallet_id, user_id):
        """Actually flips the wallet live: set_active_platform + cache-drop + confirmation + back to the main menu."""
        await database.set_active_platform(wallet_id, spec.name, user_id)
        _menu._tx_cache.pop((int(wallet_id), spec.name), None)
        context.user_data.pop('_link', None)
        logger.info('[link_%s] wallet=%s linked by user=%s', spec.name, wallet_id, user_id)
        await flash_message(context, update.effective_chat.id, f'✅ {spec.emoji} *{spec.label}* linked and activated.')
        await show_menu(update, context)
        return ConversationHandler.END

    async def _do_save(update, context, creds, account_id):
        link_sess = context.user_data.get('_link', {})
        wallet_id = link_sess.get('wallet_id')
        dup = await database.find_other_wallet_with_account(spec.name, account_id, wallet_id)
        if dup:
            link_sess['_pending_save'] = {'creds': creds, 'account_id': account_id}
            status = 'active' if dup['active'] else 'inactive'
            dup_kb = InlineKeyboardMarkup([[InlineKeyboardButton('⚠️ Link anyway', callback_data=CB_DUP_CONTINUE)], BACK_ROW[0]])
            await edit_or_send(update, context, f'⚠️ *This {spec.label} account is already linked* to {safe_md(dup['name'] or dup['wallet_id'])} ({dup['mode']} mode, {status}). Running the same account from two wallets can cause conflicting trades and margin double-booking.\n\nContinue anyway?', parse_mode='Markdown', reply_markup=dup_kb)
            return dup_state
        return await _finish_save(update, context, creds, account_id)

    async def confirm_dup(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        link_sess = context.user_data.get('_link', {})
        pending = link_sess.pop('_pending_save', None)
        if not pending:
            return ConversationHandler.END
        return await _finish_save(update, context, pending['creds'], pending['account_id'])

    async def dup_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """← Back from dup_state → wherever it was reached from (): the account-choose screen for resolver specs (Propr), the pre-validation screen otherwise."""
        query = update.callback_query
        await query.answer()
        if spec.link_resolver is not None:
            sess = context.user_data.get('_link', {})
            return await _render_choose_screen(update, context, sess)
        return await _render_pre_validation_screen(update, context)

    async def _finish_save(update, context, creds, account_id):
        user_id = update.effective_user.id
        link_sess = context.user_data.get('_link', {})
        wallet_id = link_sess.get('wallet_id')
        try:
            await preload_enc_salt(user_id)
            api_key_enc = encrypt(creds.api_key, user_id) if 'api_key' in fields else None
            pk_enc = encrypt(creds.private_key, user_id) if 'private_key' in fields else None
            pub_enc = encrypt(creds.public_key, user_id) if 'public_key' in fields else None
            await database.upsert_wallet_platform(wallet_id=wallet_id, platform=spec.name, account_id=account_id, api_key_enc=api_key_enc, private_key_enc=pk_enc, public_key_enc=pub_enc, vault_id=creds.vault_id)
            if spec.name == 'lighter':
                await database.set_lighter_api_key_idx(wallet_id, creds.api_key_slot, user_id)
            if spec.name == 'lighter_rh':
                await database.set_lighter_rh_api_key_idx(wallet_id, creds.api_key_slot, user_id)
            if spec.name == 'risex':
                await _approve_risex_builder_fee(account_id, creds.private_key, wallet_id)
        except Exception as e:
            logger.error('[link_%s] wallet=%s save failed: %s', spec.name, wallet_id, e)
            await edit_or_send(update, context, '⚠️ Something went wrong saving your credentials — please try again.')
            await show_menu(update, context)
            return ConversationHandler.END
        finally:
            link_sess['creds'] = {}
        if spec.name in GATED_PLATFORMS:
            from .fee_reapprove import send_link_approval
            try:
                result = await send_link_approval(context, wallet_id, spec.name)
            except Exception as e:
                logger.error('[link_%s] wallet=%s approval message failed: %s', spec.name, wallet_id, e)
                result = 'error'
            if result == 'sent':
                context.user_data.pop('_link', None)
                logger.info('[link_%s] wallet=%s saved by user=%s — waiting for the fee signature', spec.name, wallet_id, user_id)
                return ConversationHandler.END
            if result != 'nothing pending':
                await edit_or_send(update, context, '⚠️ Something went wrong — please try again.')
                await show_menu(update, context)
                return ConversationHandler.END
        return await _activate_and_finish(update, context, wallet_id, user_id)

    async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data.pop('_link', None)
        await show_menu(update, context)
        return ConversationHandler.END

    async def retry(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        sess = context.user_data.get('_link')
        if not sess:
            return ConversationHandler.END
        sess['creds'] = {}
        sess.pop('api_key_slot', None)
        await edit_or_send(update, context, _with_tier_notice(spec, _prompt(fields[0])), parse_mode='Markdown', reply_markup=back_kb)
        return 0
    states = {i: [MessageHandler(filters.TEXT & ~filters.COMMAND, _collector(i)), CallbackQueryHandler(_field_back(i), pattern=f'^{CB_BACK}$')] if i > 0 or spec.name in REFERRAL_LINKS else [MessageHandler(filters.TEXT & ~filters.COMMAND, _collector(i))] for i in range(len(fields))}
    states[fail_state] = [CallbackQueryHandler(retry, pattern=f'^{CB_RETRY}$'), CallbackQueryHandler(fail_back, pattern=f'^{CB_BACK}$')]
    if spec.link_resolver is not None:
        states[choose_state] = [CallbackQueryHandler(choose_account, pattern=f'^{CB_CHOOSE}\\d+$'), CallbackQueryHandler(choose_back, pattern=f'^{CB_BACK}$')]
    if spec.name in ('lighter', 'lighter_rh'):
        states[slot_state] = [CallbackQueryHandler(got_slot, pattern=f'^{CB_SLOT}\\d$'), CallbackQueryHandler(slot_back, pattern=f'^{CB_BACK}$')]
    if spec.name in REFERRAL_LINKS:
        states[notice_state] = [CallbackQueryHandler(arcus_continue, pattern=f'^{CB_ARCUS_CONTINUE}$')]
    states[dup_state] = [CallbackQueryHandler(confirm_dup, pattern=f'^{CB_DUP_CONTINUE}$'), CallbackQueryHandler(dup_back, pattern=f'^{CB_BACK}$')]
    return ConversationHandler(conversation_timeout=CONVO_TIMEOUT_S, entry_points=[CallbackQueryHandler(start, pattern=f'^{cb_start}(_\\d+)?$'), CallbackQueryHandler(start, pattern=f'^{cb_add}$')], states=states, fallbacks=[CallbackQueryHandler(cancel, pattern=f'^{CB_BACK}$')], per_message=False, name=f'link_{spec.name}')
