"""Excerpt of approve_app/server.py for security review — the signing and login handlers and what they call."""

import asyncio, collections, hmac, json, logging, os, re, secrets, time
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
import aiohttp
import asyncpg
from aiohttp import web
from eth_abi import encode as abi_encode
from eth_account import Account as EthAccount
from eth_account.messages import encode_defunct
from eth_utils import keccak, to_checksum_address
from web3 import Web3
from lighter.signer_client import SignerClient, decode_and_free


log = logging.getLogger(__name__)


LIGHTER_API_BASE = os.environ.get('LIGHTER_API_BASE', 'https://mainnet.zklighter.elliot.ai')


LIGHTER_RH_API_BASE = os.environ.get('LIGHTER_RH_API_BASE', 'https://api.rh.lighter.xyz')


LIGHTER_RH_INTEGRATOR_ACCOUNT_INDEX = int(os.environ.get('LIGHTER_RH_INTEGRATOR_ACCOUNT_INDEX', '41488'))


LIGHTER_RH_CHAIN_ID = ...


class _RHSignerClient(SignerClient):
    """SignerClient with the chain_id fixed to Robinhood Chain's real ID — see LIGHTER_RH_CHAIN_ID above for why the base class's own heuristic gets this wrong for us."""

    def create_client(self, api_key_index):
        err_ptr = self.signer.CreateClient(self.url.encode('utf-8'), self.api_key_dict[api_key_index].encode('utf-8'), LIGHTER_RH_CHAIN_ID, api_key_index, self.account_index)
        err = decode_and_free(err_ptr)
        if err is not None:
            raise Exception(err)


APP_SECRET = os.environ.get('APPROVE_APP_SECRET', '')


PUBLIC_BASE_URL = os.environ.get('APPROVE_APP_PUBLIC_URL', '')


DATABASE_URL = os.environ.get('DATABASE_URL', '')


TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN', '')


TOKEN_TTL = ...


_RATE_PREPARE_MAX = ...


_RATE_PREPARE_WINDOW = ...


_RATE_SUBMIT_MAX = ...


_RATE_SUBMIT_WINDOW = ...


_rate_prepare: dict[str, collections.deque] = collections.defaultdict(collections.deque)


_rate_submit: dict[str, collections.deque] = collections.defaultdict(collections.deque)


_HEX40 = re.compile('^0x[0-9a-fA-F]{40}$')


TRUSTED_PROXIES: frozenset = frozenset({'127.0.0.1', '::1'})


_RISEX_REST = 'https://api.rise.trade'


_RISEX_CHAIN_ID = ...


_RISEX_AUTH = '0x0d919daa3f12ae715744eb648c00066c5dbd66f0'


_RISEX_REGISTER_MSG = 'Register signer for RISEx trading'


_RISEX_LABEL = 'Mimiq Bot'


_RISEX_EXPIRY_SECS = ...


_RISEX_DOMAIN_TYPEHASH = keccak(text='EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)')


_RISEX_REGISTER_TYPEHASH = keccak(text='RegisterSigner(address account,address signer,string message,uint32 expiration,uint48 nonceAnchor,uint8 nonceBitmap)')


_RISEX_VERIFY_TYPEHASH = keccak(text='VerifySigner(address account,uint48 nonceAnchor,uint8 nonceBitmap)')


_RISEX_DOMAIN_SEP = keccak(abi_encode(['bytes32', 'bytes32', 'bytes32', 'uint256', 'address'], [_RISEX_DOMAIN_TYPEHASH, keccak(text='RISEx'), keccak(text='1'), _RISEX_CHAIN_ID, _RISEX_AUTH]))


RISEX_CLAIM_TTL = ...


_risex_store: dict[str, dict] = {}


_perpl_store: dict[str, dict] = {}


ONDO_CLAIM_TTL = ...


ONDO_DEFAULT_API = 'https://api.ondoperps.xyz'


ONDO_KEY_NAME = 'mimiq-copy-bot'


_ondo_store: dict[str, dict] = {}


def _wrong_wallet_response(entry: dict, address: str, label: str):
    """One implementation for every signing flow that learns the connected wallet BEFORE a signature is requested (HL / RiseX typed-data)."""
    expected = str(entry.get('expected_address') or '').lower()
    address = str(address or '').lower()
    if expected and address and (address != expected):
        log.warning(f'[{label}] wallet={entry.get('wallet_id')} wrong browser wallet: got {address}, expected {expected}')
        return web.json_response({'error': f'Wrong wallet connected — please switch to {expected} and try again.'}, status=400)
    return None


HL_API_URL = 'https://api.hyperliquid.xyz'


HL_BUILDER_ADDRESS = os.environ.get('HL_BUILDER_ADDRESS', '0x1ecd56efe5892b34fce1964b35e755eccfece282')


HL_MAX_FEE_RATE = '0.01%'


HL_SIG_CHAIN_ID = '0x66eee'


HL_TOKEN_TTL = ...


_hl_store: dict[str, dict] = {}


def _client_ip(req: web.Request) -> str:
    """Return real client IP."""
    if req.remote in TRUSTED_PROXIES:
        forwarded = req.headers.get('X-Forwarded-For', '').split(',')[0].strip()
        if forwarded:
            return forwarded
    return req.remote or 'unknown'


def _session(store: dict, token: str, ttl: int):
    """The live session for `token`, or None."""
    entry = store.get(token)
    if entry is None:
        return None
    if time.time() - entry.get('created_at', 0) > ttl:
        store.pop(token, None)
        return None
    return entry


def _bot_authed(req: web.Request) -> bool:
    """True if the request carries the bot's shared secret (constant-time compare)."""
    if not APP_SECRET:
        return False
    return hmac.compare_digest(req.headers.get('Authorization', '').encode(), f'Bearer {APP_SECRET}'.encode())


def _prepare_allowed(req, ip: str) -> bool:
    """Rate check for the *-prepare endpoints."""
    if _bot_authed(req):
        return True
    return _check_rate(_rate_prepare, ip, _RATE_PREPARE_MAX, _RATE_PREPARE_WINDOW)


def _check_rate(store: dict, ip: str, max_req: int, window: int) -> bool:
    """Return True if request is allowed, False if rate-limited."""
    now = time.time()
    if len(store) > 5000:
        for k in [k for k, d in store.items() if not d or d[-1] < now - window]:
            del store[k]
    dq = store[ip]
    while dq and dq[0] < now - window:
        dq.popleft()
    if len(dq) >= max_req:
        return False
    dq.append(now)
    return True


INTEGRATOR_ACCOUNT_INDEX = int(os.environ.get('LIGHTER_INTEGRATOR_ACCOUNT_INDEX', '758103'))


INTEGRATOR_PERPS_TAKER_FEE = int(os.environ.get('INTEGRATOR_PERPS_TAKER_FEE', '3'))


INTEGRATOR_PERPS_MAKER_FEE = int(os.environ.get('INTEGRATOR_PERPS_MAKER_FEE', '3'))


INTEGRATOR_SPOT_TAKER_FEE = int(os.environ.get('INTEGRATOR_SPOT_TAKER_FEE', '3'))


INTEGRATOR_SPOT_MAKER_FEE = int(os.environ.get('INTEGRATOR_SPOT_MAKER_FEE', '3'))


LIGHTER_RH_INTEGRATOR_PERPS_TAKER_FEE = int(os.environ.get('LIGHTER_RH_INTEGRATOR_PERPS_TAKER_FEE', '100'))


LIGHTER_RH_INTEGRATOR_PERPS_MAKER_FEE = int(os.environ.get('LIGHTER_RH_INTEGRATOR_PERPS_MAKER_FEE', '100'))


LIGHTER_RH_INTEGRATOR_SPOT_TAKER_FEE = int(os.environ.get('LIGHTER_RH_INTEGRATOR_SPOT_TAKER_FEE', '0'))


LIGHTER_RH_INTEGRATOR_SPOT_MAKER_FEE = int(os.environ.get('LIGHTER_RH_INTEGRATOR_SPOT_MAKER_FEE', '0'))


_APPROVAL_EXPIRY_OVERRIDE = int(os.environ.get('INTEGRATOR_APPROVAL_EXPIRY_MS', '0'))


_APPROVAL_EXPIRY_DAYS = ...


def _approval_expiry_ms() -> int:
    """Return expiry timestamp in ms."""
    if _APPROVAL_EXPIRY_OVERRIDE:
        return _APPROVAL_EXPIRY_OVERRIDE
    return int(time.time() * 1000) + _APPROVAL_EXPIRY_DAYS * 24 * 3600 * 1000


async def _update_approved_in_db(account_index: int, approved: bool, telegram_id: int=0):
    """Writes to mimiq2's live Postgres DB (: this used to connect via raw sqlite3 to <path> — the old, stopped legacy database."""
    if not DATABASE_URL:
        return
    try:
        con = await asyncpg.connect(DATABASE_URL)
        try:
            if telegram_id:
                await con.execute("UPDATE wallets SET integrator_approved = $1, updated_at = $2 WHERE telegram_id = $4 AND (lighter_account_idx = $3 OR id IN (  SELECT wallet_id FROM wallet_platforms WHERE platform = 'lighter' AND account_id = $3::text))", 1 if approved else 0, datetime.now(timezone.utc).isoformat(), account_index, telegram_id)
            else:
                await con.execute('UPDATE wallets SET integrator_approved = $1, updated_at = $2 WHERE lighter_account_idx = $3', 1 if approved else 0, datetime.now(timezone.utc).isoformat(), account_index)
        finally:
            await con.close()
        log.info(f'Set integrator_approved={approved} for account {account_index} in DB')
    except Exception as e:
        log.warning(f'Could not update DB for account {account_index}: {e}')


async def _update_lighter_rh_approved_in_db(account_index: int, approved: bool, telegram_id: int=0):
    """Same purpose as _update_approved_in_db, own column — Lighter-on-Robinhood-Chain has no dedicated `wallets.lighter_rh_account_idx` column (unlike mainnet's legacy lighter_account_idx), its account live"""
    if not DATABASE_URL:
        return
    try:
        con = await asyncpg.connect(DATABASE_URL)
        try:
            if telegram_id:
                await con.execute("UPDATE wallets SET lighter_rh_integrator_approved = $1, updated_at = $2 WHERE telegram_id = $4 AND id IN (SELECT wallet_id FROM wallet_platforms              WHERE platform = 'lighter_rh' AND account_id = $3)", 1 if approved else 0, datetime.now(timezone.utc).isoformat(), str(account_index), telegram_id)
            else:
                await con.execute("UPDATE wallets SET lighter_rh_integrator_approved = $1, updated_at = $2 WHERE id IN (SELECT wallet_id FROM wallet_platforms              WHERE platform = 'lighter_rh' AND account_id = $3)", 1 if approved else 0, datetime.now(timezone.utc).isoformat(), str(account_index))
        finally:
            await con.close()
        log.info(f'Set lighter_rh_integrator_approved={approved} for account {account_index} in DB')
    except Exception as e:
        log.warning(f'Could not update DB for lighter_rh account {account_index}: {e}')


def _notify_unless_quiet(entry: dict, chat_id: int, text: str, reply_markup: dict | None=None, *, bot_token: str=''):
    """Completion message of an approval flow (HL / Lighter / Lighter RH)."""
    if entry.get('quiet'):
        return
    _send_tg_notification(chat_id, text, reply_markup, bot_token=bot_token)


def _send_tg_notification(chat_id: int, text: str, reply_markup: dict | None=None, *, bot_token: str=''):
    token = bot_token or TG_BOT_TOKEN
    if not token or not chat_id:
        return
    try:
        data: dict = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
        if reply_markup:
            data['reply_markup'] = reply_markup
        payload = json.dumps(data).encode()
        req = urllib.request.Request(f'https://api.telegram.org/bot{token}/sendMessage', data=payload, headers={'Content-Type': 'application/json'}, method='POST')
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log.warning(f'Telegram notification failed chat_id={chat_id}: {e}')


def _risex_cleanup():
    now = time.time()
    expired = [t for t, v in _risex_store.items() if now - v['created_at'] > RISEX_CLAIM_TTL]
    for t in expired:
        _risex_store.pop(t, None)


def _risex_register_signer_digest(account: str, signer: str, message: str, expiration: int, nonce_anchor: int, nonce_bitmap: int) -> bytes:
    """Compute the EIP-712 RegisterSigner digest for signature verification."""
    struct_hash = keccak(abi_encode(['bytes32', 'address', 'address', 'bytes32', 'uint32', 'uint48', 'uint8'], [_RISEX_REGISTER_TYPEHASH, account, signer, keccak(text=message), expiration, nonce_anchor, nonce_bitmap]))
    return keccak(b'\x19\x01' + _RISEX_DOMAIN_SEP + struct_hash)


def _risex_sign_verify_signer(session_pk: str, account: str, nonce_anchor: int, nonce_bitmap: int) -> str:
    """Sign the VerifySigner struct with the session key."""
    struct_hash = keccak(abi_encode(['bytes32', 'address', 'uint48', 'uint8'], [_RISEX_VERIFY_TYPEHASH, account, nonce_anchor, nonce_bitmap]))
    digest = keccak(b'\x19\x01' + _RISEX_DOMAIN_SEP + struct_hash)
    sig = EthAccount.unsafe_sign_hash(digest, private_key=session_pk)
    return '0x' + sig.signature.hex()


async def _risex_fetch_nonce(account: str) -> tuple[int, int]:
    """Return (nonce_anchor, nonce_bitmap_index) from RiseX REST API."""
    async with aiohttp.ClientSession() as sess:
        async with sess.get(f'{_RISEX_REST}/v1/nonce-state/{account}', timeout=aiohttp.ClientTimeout(total=10)) as r:
            r.raise_for_status()
            d = (await r.json()).get('data', {})
            anchor = int(d.get('nonce_anchor', '0'))
            bitmap = int(d.get('current_bitmap_index', 0))
            if bitmap >= 256:
                anchor += 1
                bitmap = 0
            return (anchor, bitmap)


async def _risex_call_register(body: dict) -> dict:
    """POST /v1/auth/register-signer."""
    async with aiohttp.ClientSession() as sess:
        async with sess.post(f'{_RISEX_REST}/v1/auth/register-signer', json=body, timeout=aiohttp.ClientTimeout(total=30)) as r:
            text = await r.text()
            if not r.ok:
                raise RuntimeError(f'RiseX API {r.status}: {text[:200]}')
            return json.loads(text)


_store: dict[str, dict] = {}


def _new_token() -> str:
    return secrets.token_urlsafe(24)


def _cleanup():
    now = time.time()
    expired = [t for t, v in _store.items() if now - v['created_at'] > TOKEN_TTL]
    for t in expired:
        _store.pop(t, None)


def _get_approve_payload(account_index: int, api_key_priv: str, api_key_slot: int, revoke: bool=False) -> tuple[Optional[str], Optional[str], Optional[int], Optional[str]]:
    """Build the ApproveIntegrator tx payload WITHOUT an L1 private key."""
    thread_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(thread_loop)

    async def _run():
        try:
            signer = SignerClient(url=LIGHTER_API_BASE, account_index=account_index, api_private_keys={api_key_slot: api_key_priv})
            api_key_index, nonce = signer.nonce_manager.next_nonce()
            perps_taker = 0 if revoke else INTEGRATOR_PERPS_TAKER_FEE
            perps_maker = 0 if revoke else INTEGRATOR_PERPS_MAKER_FEE
            spot_taker = 0 if revoke else INTEGRATOR_SPOT_TAKER_FEE
            spot_maker = 0 if revoke else INTEGRATOR_SPOT_MAKER_FEE
            res = signer.signer.SignApproveIntegrator(INTEGRATOR_ACCOUNT_INDEX, perps_taker, perps_maker, spot_taker, spot_maker, _approval_expiry_ms(), SignerClient.SKIP_NONCE_OFF, nonce, api_key_index, account_index)
            err_str = decode_and_free(res.err)
            tx_info_str = decode_and_free(res.txInfo)
            decode_and_free(res.txHash)
            msg_to_sign = decode_and_free(res.messageToSign)
            try:
                await signer.api_client.close()
            except Exception:
                pass
            if err_str:
                return (None, None, None, err_str)
            return (str(res.txType), tx_info_str, msg_to_sign, None)
        except Exception as e:
            log.exception('_get_approve_payload failed')
            return (None, None, None, str(e))
    try:
        return thread_loop.run_until_complete(_run())
    finally:
        thread_loop.close()
        asyncio.set_event_loop(None)


def _get_lighter_rh_approve_payload(account_index: int, api_key_priv: str, api_key_slot: int, revoke: bool=False) -> tuple[Optional[str], Optional[str], Optional[int], Optional[str]]:
    """Same as _get_approve_payload, isolated for Robinhood-Chain-Lighter (own host, own integrator account, own fee schedule) — see the module-level comment by LIGHTER_RH_API_BASE for why this is a copy, no"""
    thread_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(thread_loop)

    async def _run():
        try:
            signer = _RHSignerClient(url=LIGHTER_RH_API_BASE, account_index=account_index, api_private_keys={api_key_slot: api_key_priv})
            api_key_index, nonce = signer.nonce_manager.next_nonce()
            perps_taker = 0 if revoke else LIGHTER_RH_INTEGRATOR_PERPS_TAKER_FEE
            perps_maker = 0 if revoke else LIGHTER_RH_INTEGRATOR_PERPS_MAKER_FEE
            spot_taker = 0 if revoke else LIGHTER_RH_INTEGRATOR_SPOT_TAKER_FEE
            spot_maker = 0 if revoke else LIGHTER_RH_INTEGRATOR_SPOT_MAKER_FEE
            res = signer.signer.SignApproveIntegrator(LIGHTER_RH_INTEGRATOR_ACCOUNT_INDEX, perps_taker, perps_maker, spot_taker, spot_maker, _approval_expiry_ms(), SignerClient.SKIP_NONCE_OFF, nonce, api_key_index, account_index)
            err_str = decode_and_free(res.err)
            tx_info_str = decode_and_free(res.txInfo)
            decode_and_free(res.txHash)
            msg_to_sign = decode_and_free(res.messageToSign)
            try:
                await signer.api_client.close()
            except Exception:
                pass
            if err_str:
                return (None, None, None, err_str)
            return (str(res.txType), tx_info_str, msg_to_sign, None)
        except Exception as e:
            log.exception('_get_lighter_rh_approve_payload failed')
            return (None, None, None, str(e))
    try:
        return thread_loop.run_until_complete(_run())
    finally:
        thread_loop.close()
        asyncio.set_event_loop(None)


async def _send_approved_tx(account_index: int, api_key_priv: str, api_key_slot: int, tx_type: int, tx_info_with_sig: str) -> tuple[Optional[str], Optional[str]]:
    """Submit the finalised ApproveIntegrator tx to Lighter."""

    def _do():
        thread_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(thread_loop)

        async def _run():
            signer = SignerClient(url=LIGHTER_API_BASE, account_index=account_index, api_private_keys={api_key_slot: api_key_priv})
            try:
                resp = await signer.send_tx(tx_type=tx_type, tx_info=tx_info_with_sig)
                return (getattr(resp, 'tx_hash', None) or str(resp), None)
            except Exception as e:
                return (None, str(e))
            finally:
                try:
                    await signer.api_client.close()
                except Exception:
                    pass
        try:
            return thread_loop.run_until_complete(_run())
        finally:
            thread_loop.close()
            asyncio.set_event_loop(None)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _do)


async def _send_lighter_rh_approved_tx(account_index: int, api_key_priv: str, api_key_slot: int, tx_type: int, tx_info_with_sig: str) -> tuple[Optional[str], Optional[str]]:
    """Same as _send_approved_tx, isolated for Robinhood-Chain-Lighter (own host)."""

    def _do():
        thread_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(thread_loop)

        async def _run():
            signer = _RHSignerClient(url=LIGHTER_RH_API_BASE, account_index=account_index, api_private_keys={api_key_slot: api_key_priv})
            try:
                resp = await signer.send_tx(tx_type=tx_type, tx_info=tx_info_with_sig)
                return (getattr(resp, 'tx_hash', None) or str(resp), None)
            except Exception as e:
                return (None, str(e))
            finally:
                try:
                    await signer.api_client.close()
                except Exception:
                    pass
        try:
            return thread_loop.run_until_complete(_run())
        finally:
            thread_loop.close()
            asyncio.set_event_loop(None)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _do)


async def handle_risex_prepare(req: web.Request) -> web.Response:
    """Called by the bot to start a RiseX session-key registration."""
    ip = _client_ip(req)
    if not _prepare_allowed(req, ip):
        raise web.HTTPTooManyRequests(reason='Rate limit exceeded')
    if not _bot_authed(req):
        raise web.HTTPUnauthorized()
    try:
        body = await req.json()
    except Exception:
        raise web.HTTPBadRequest(reason='Invalid JSON')
    telegram_id = int(body['telegram_id'])
    chat_id = int(body['chat_id'])
    wallet_id = int(body['wallet_id'])
    bot_url = str(body.get('bot_url', '')).strip()
    expected_address = str(body.get('expected_address', '')).strip().lower()
    auto_save = bool(body.get('auto_save', False)) or bool(body.get('quiet', False))
    session_pk = '0x' + secrets.token_hex(32)
    session_addr = EthAccount.from_key(session_pk).address
    _risex_cleanup()
    token = _new_token()
    _risex_store[token] = {'session_pk': session_pk, 'session_addr': session_addr, 'account': '', 'nonce_anchor': 0, 'nonce_bitmap': 0, 'expiration': 0, 'wallet_id': wallet_id, 'telegram_id': telegram_id, 'chat_id': chat_id, 'bot_url': bot_url, 'expected_address': expected_address, 'auto_save': auto_save, 'status': 'pending', 'error': None, 'created_at': time.time()}
    if PUBLIC_BASE_URL:
        from urllib.parse import urlparse as _up
        _p = _up(PUBLIC_BASE_URL)
        _host = f'{_p.scheme}://{_p.netloc}'
        url = f'{_host}/risex/{token}'
    else:
        url = f'/risex/{token}'
    log.info(f'[risex] new session token={token[:8]}… wallet={wallet_id} signer={session_addr[:10]}…')
    return web.json_response({'token': token, 'url': url})


async def handle_risex_typed_data(req: web.Request) -> web.Response:
    """Browser sends {token, account} → server fetches nonce, returns EIP-712 typed data JSON."""
    try:
        body = await req.json()
    except Exception:
        raise web.HTTPBadRequest(reason='Invalid JSON')
    token = str(body.get('token', ''))
    account = str(body.get('account', '')).strip()
    entry = _session(_risex_store, token, RISEX_CLAIM_TTL)
    if not entry:
        return web.json_response({'error': 'Invalid or expired token'}, status=400)
    if entry['status'] != 'pending':
        return web.json_response({'error': f'Session is {entry['status']}'}, status=400)
    if not _HEX40.match(account):
        return web.json_response({'error': 'Invalid account address'}, status=400)
    wrong = _wrong_wallet_response(entry, account, 'risex')
    if wrong is not None:
        return wrong
    try:
        account = to_checksum_address(account)
    except Exception:
        return web.json_response({'error': 'Invalid account address'}, status=400)
    try:
        nonce_anchor, nonce_bitmap = await _risex_fetch_nonce(account)
    except Exception as e:
        log.error(f'[risex] nonce fetch failed for {account}: {e}')
        return web.json_response({'error': 'Could not fetch nonce — try again.'}, status=500)
    expiration = int(time.time()) + _RISEX_EXPIRY_SECS
    entry['account'] = account
    entry['nonce_anchor'] = nonce_anchor
    entry['nonce_bitmap'] = nonce_bitmap
    entry['expiration'] = expiration
    typed_data = {'domain': {'name': 'RISEx', 'version': '1', 'chainId': _RISEX_CHAIN_ID, 'verifyingContract': _RISEX_AUTH}, 'types': {'EIP712Domain': [{'name': 'name', 'type': 'string'}, {'name': 'version', 'type': 'string'}, {'name': 'chainId', 'type': 'uint256'}, {'name': 'verifyingContract', 'type': 'address'}], 'RegisterSigner': [{'name': 'account', 'type': 'address'}, {'name': 'signer', 'type': 'address'}, {'name': 'message', 'type': 'string'}, {'name': 'expiration', 'type': 'uint32'}, {'name': 'nonceAnchor', 'type': 'uint48'}, {'name': 'nonceBitmap', 'type': 'uint8'}]}, 'primaryType': 'RegisterSigner', 'message': {'account': account, 'signer': entry['session_addr'], 'message': _RISEX_REGISTER_MSG, 'expiration': expiration, 'nonceAnchor': nonce_anchor, 'nonceBitmap': nonce_bitmap}}
    return web.json_response({'typed_data': typed_data})


async def handle_risex_submit(req: web.Request) -> web.Response:
    """Browser sends {token, account, account_signature} after eth_signTypedData_v4."""
    ip = _client_ip(req)
    if not _check_rate(_rate_submit, ip, _RATE_SUBMIT_MAX, _RATE_SUBMIT_WINDOW):
        raise web.HTTPTooManyRequests(reason='Rate limit exceeded')
    try:
        body = await req.json()
    except Exception:
        raise web.HTTPBadRequest(reason='Invalid JSON')
    token = str(body.get('token', ''))
    account = str(body.get('account', '')).strip()
    acct_sig = str(body.get('account_signature', '')).strip()
    entry = _session(_risex_store, token, RISEX_CLAIM_TTL)
    if not entry:
        return web.json_response({'error': 'Invalid or expired token'}, status=400)
    if entry['status'] != 'pending':
        return web.json_response({'error': f'Session is {entry['status']}'}, status=400)
    try:
        account = to_checksum_address(account)
    except Exception:
        return web.json_response({'error': 'Invalid account address'}, status=400)
    if account != entry['account']:
        return web.json_response({'error': 'Account mismatch'}, status=400)
    try:
        digest = _risex_register_signer_digest(account=account, signer=entry['session_addr'], message=_RISEX_REGISTER_MSG, expiration=entry['expiration'], nonce_anchor=entry['nonce_anchor'], nonce_bitmap=entry['nonce_bitmap'])
        sig_bytes = bytes.fromhex(acct_sig.lstrip('0x'))
        recovered = EthAccount._recover_hash(digest, signature=sig_bytes)
        if recovered.lower() != account.lower():
            return web.json_response({'error': f'Signature mismatch: recovered {recovered}, expected {account}'}, status=400)
    except Exception as e:
        log.warning(f'[risex] signature verification failed: {e}')
        return web.json_response({'error': 'Signature verification failed'}, status=400)
    entry['status'] = 'submitting'
    try:
        signer_sig = _risex_sign_verify_signer(session_pk=entry['session_pk'], account=account, nonce_anchor=entry['nonce_anchor'], nonce_bitmap=entry['nonce_bitmap'])
    except Exception as e:
        entry['status'] = 'error'
        entry['error'] = 'Internal signing error'
        log.error(f'[risex] VerifySigner signing failed: {e}')
        return web.json_response({'error': 'Internal signing error'}, status=500)
    api_body = {'account': account, 'signer': entry['session_addr'], 'message': _RISEX_REGISTER_MSG, 'nonce_anchor': str(entry['nonce_anchor']), 'nonce_bitmap_index': entry['nonce_bitmap'], 'expiration': str(entry['expiration']), 'account_signature': acct_sig, 'signer_signature': signer_sig, 'label': _RISEX_LABEL}
    try:
        await _risex_call_register(api_body)
    except Exception as e:
        entry['status'] = 'error'
        entry['error'] = 'Internal error during signer registration'
        log.error(f'[risex] register-signer failed: {e}')
        return web.json_response({'error': 'Internal error during signer registration'}, status=500)
    entry['status'] = 'done'
    log.info(f'[risex] registered signer={entry['session_addr'][:10]}… account={account[:10]}… token={token[:8]}…')
    if not entry.get('auto_save'):
        cb_data = f'risex_save_{token}'
        markup = {'inline_keyboard': [[{'text': '✅ Save to Mimiq', 'callback_data': cb_data}]]}
        _send_tg_notification(entry['chat_id'], '✅ *RiseX wallet connected!*\n\nTap below to save the session key to your Mimiq account.', reply_markup=markup)
    return web.json_response({'ok': True, 'bot_url': entry.get('bot_url', '')})


async def handle_risex_claim(req: web.Request) -> web.Response:
    """Called by the bot (with auth) after the user taps the Telegram callback button."""
    if not _bot_authed(req):
        raise web.HTTPUnauthorized()
    token = req.match_info['token']
    entry = _session(_risex_store, token, RISEX_CLAIM_TTL)
    if not entry:
        return web.json_response({'error': 'Token not found or expired'}, status=404)
    if entry['status'] != 'done':
        return web.json_response({'error': f'Session is {entry['status']}'}, status=400)
    result = {'account': entry['account'], 'session_pk': entry['session_pk'], 'wallet_id': entry['wallet_id'], 'user_id': entry['telegram_id']}
    _risex_store.pop(token, None)
    log.info(f'[risex] claimed token={token[:8]}… wallet={result['wallet_id']}')
    return web.json_response(result)


async def handle_risex_status(req: web.Request) -> web.Response:
    """Browser polls this to check session state."""
    token = req.match_info['token']
    entry = _session(_risex_store, token, RISEX_CLAIM_TTL)
    if not entry:
        return web.json_response({'status': 'not_found'}, status=404)
    resp = {'status': entry['status'], 'error': entry['error'], 'session_addr': entry.get('session_addr', ''), 'bot_url': entry.get('bot_url', '')}
    if entry['status'] == 'pending':
        resp['expected_address'] = entry.get('expected_address') or ''
    return web.json_response(resp)


def _perpl_cleanup():
    now = time.time()
    for t in [t for t, v in _perpl_store.items() if now - v['created_at'] > RISEX_CLAIM_TTL]:
        _perpl_store.pop(t, None)


async def handle_perpl_prepare(req: web.Request) -> web.Response:
    """Called by the bot."""
    ip = _client_ip(req)
    if not _prepare_allowed(req, ip):
        raise web.HTTPTooManyRequests(reason='Rate limit exceeded')
    if not _bot_authed(req):
        raise web.HTTPUnauthorized()
    try:
        body = await req.json()
    except Exception:
        raise web.HTTPBadRequest(reason='Invalid JSON')
    expected = str(body.get('expected_address', '')).strip().lower()
    if not (expected.startswith('0x') and len(expected) == 42):
        raise web.HTTPBadRequest(reason='expected_address required')
    _perpl_cleanup()
    token = _new_token()
    _perpl_store[token] = {'wallet_id': int(body['wallet_id']), 'telegram_id': int(body['telegram_id']), 'chat_id': int(body['chat_id']), 'expected_address': expected, 'status': 'pending', 'created_at': time.time()}
    if PUBLIC_BASE_URL:
        from urllib.parse import urlparse as _up
        _p = _up(PUBLIC_BASE_URL)
        url = f'{_p.scheme}://{_p.netloc}/perpl/{token}'
    else:
        url = f'/perpl/{token}'
    log.info(f'[perpl] new session token={token[:8]}… wallet={body['wallet_id']}')
    return web.json_response({'token': token, 'url': url})


async def handle_perpl_status(req: web.Request) -> web.Response:
    """Browser (wallet-guard.load) reads the wallet that must send the transaction."""
    entry = _session(_perpl_store, req.match_info['token'], RISEX_CLAIM_TTL)
    if not entry or time.time() - entry['created_at'] > RISEX_CLAIM_TTL:
        return web.json_response({'status': 'not_found'}, status=404)
    return web.json_response({'status': entry['status'], 'expected_address': entry['expected_address']})


def _ondo_cleanup():
    now = time.time()
    for t in [t for t, v in _ondo_store.items() if now - v['created_at'] > ONDO_CLAIM_TTL]:
        _ondo_store.pop(t, None)


def _ondo_api_base(raw) -> str:
    """The Ondo API base for a session: the default, or another https://*.ondoperps.xyz host."""
    from urllib.parse import urlparse
    url = str(raw or '').strip().rstrip('/')
    u = urlparse(url)
    if u.scheme == 'https' and (u.hostname or '').endswith('.ondoperps.xyz') and (not u.path.strip('/')) and (not u.query):
        return url
    return ONDO_DEFAULT_API


async def _ondo_get_challenge(api_base: str, wallet_address: str, chain_id: str):
    """→ (challenge_id, message)."""
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as http:
        async with http.post(f'{api_base}/v1/auth/erc-4361/login/get_challenge', json={'walletAddress': wallet_address, 'chainId': chain_id}) as r:
            data = await r.json()
    if not data.get('success'):
        raise RuntimeError(f'get_challenge failed: {data}')
    res = data['result']
    return (res['id'], res['message'])


async def _ondo_complete(api_base: str, challenge_id: str, signature: str) -> str:
    """→ JWT token."""
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as http:
        async with http.post(f'{api_base}/v1/auth/erc-4361/login/complete_challenge', json={'id': challenge_id, 'signature': signature}) as r:
            data = await r.json()
    if not data.get('success'):
        raise RuntimeError(f'complete_challenge failed: {data}')
    return data['result']['token']


async def _ondo_create_key(api_base: str, jwt: str):
    """Create a trade-scoped API key (no transfer → cannot withdraw)."""
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as http:
        async with http.post(f'{api_base}/v1/api_keys', json={'name': ONDO_KEY_NAME, 'scopes': ['trade']}, headers={'Authorization': f'Bearer {jwt}'}) as r:
            data = await r.json()
    if not data.get('success'):
        raise RuntimeError(f'create_key failed: {data}')
    res = data['result']
    return (res['keyId'], res['secretKey'])


async def handle_ondo_prepare(req: web.Request) -> web.Response:
    """Bot → server: start an Ondo onboarding session."""
    ip = _client_ip(req)
    if not _prepare_allowed(req, ip):
        raise web.HTTPTooManyRequests(reason='Rate limit exceeded')
    if not _bot_authed(req):
        raise web.HTTPUnauthorized()
    try:
        body = await req.json()
    except Exception:
        raise web.HTTPBadRequest(reason='Invalid JSON')
    token = _new_token()
    _ondo_cleanup()
    _ondo_store[token] = {'wallet_id': int(body['wallet_id']), 'telegram_id': int(body['telegram_id']), 'chat_id': int(body['chat_id']), 'bot_url': str(body.get('bot_url', '')).strip(), 'api_base': _ondo_api_base(body.get('ondo_api_base', '')), 'chain_id': str(body.get('chain_id', '1')), 'account': '', 'challenge_id': '', 'message': '', 'key_id': '', 'secret': '', 'status': 'pending', 'error': None, 'created_at': time.time()}
    if PUBLIC_BASE_URL:
        from urllib.parse import urlparse as _up
        _p = _up(PUBLIC_BASE_URL)
        url = f'{_p.scheme}://{_p.netloc}/ondo/{token}'
    else:
        url = f'/ondo/{token}'
    log.info(f'[ondo] new session token={token[:8]}… wallet={_ondo_store[token]['wallet_id']} base={_ondo_store[token]['api_base']}')
    return web.json_response({'token': token, 'url': url})


async def handle_ondo_challenge(req: web.Request) -> web.Response:
    """Browser → server: {token, account} → fetch the SIWE challenge, return {message} to sign."""
    try:
        body = await req.json()
    except Exception:
        raise web.HTTPBadRequest(reason='Invalid JSON')
    token = str(body.get('token', ''))
    account = str(body.get('account', '')).strip()
    entry = _session(_ondo_store, token, ONDO_CLAIM_TTL)
    if not entry:
        return web.json_response({'error': 'Invalid or expired token'}, status=400)
    if entry['status'] != 'pending':
        return web.json_response({'error': f'Session is {entry['status']}'}, status=400)
    if not _HEX40.match(account):
        return web.json_response({'error': 'Invalid account address'}, status=400)
    try:
        account = to_checksum_address(account)
    except Exception:
        return web.json_response({'error': 'Invalid account address'}, status=400)
    try:
        cid, message = await _ondo_get_challenge(entry['api_base'], account, entry['chain_id'])
    except Exception as e:
        log.error(f'[ondo] challenge failed token={token[:8]}…: {e}')
        return web.json_response({'error': 'Could not get login challenge'}, status=502)
    entry['account'] = account
    entry['challenge_id'] = cid
    entry['message'] = message
    return web.json_response({'message': message})


async def handle_ondo_submit(req: web.Request) -> web.Response:
    """Browser → server: {token, account, signature} → complete SIWE login + create a trade-scoped API key."""
    ip = _client_ip(req)
    if not _check_rate(_rate_submit, ip, _RATE_SUBMIT_MAX, _RATE_SUBMIT_WINDOW):
        raise web.HTTPTooManyRequests(reason='Rate limit exceeded')
    try:
        body = await req.json()
    except Exception:
        raise web.HTTPBadRequest(reason='Invalid JSON')
    token = str(body.get('token', ''))
    account = str(body.get('account', '')).strip()
    signature = str(body.get('signature', '')).strip()
    entry = _session(_ondo_store, token, ONDO_CLAIM_TTL)
    if not entry:
        return web.json_response({'error': 'Invalid or expired token'}, status=400)
    if entry['status'] != 'pending':
        return web.json_response({'error': f'Session is {entry['status']}'}, status=400)
    try:
        account = to_checksum_address(account)
    except Exception:
        return web.json_response({'error': 'Invalid account address'}, status=400)
    if account != entry['account']:
        return web.json_response({'error': 'Account mismatch'}, status=400)
    if not entry['message']:
        return web.json_response({'error': 'No challenge issued — request a challenge first'}, status=400)
    try:
        recovered = Web3().eth.account.recover_message(encode_defunct(text=entry['message']), signature=signature)
        if recovered.lower() != account.lower():
            return web.json_response({'error': f'Signature mismatch: recovered {recovered}, expected {account}'}, status=400)
    except Exception as e:
        log.warning(f'[ondo] invalid signature: {e}')
        return web.json_response({'error': 'Invalid signature'}, status=400)
    entry['status'] = 'submitting'
    try:
        jwt = await _ondo_complete(entry['api_base'], entry['challenge_id'], signature)
        key_id, secret = await _ondo_create_key(entry['api_base'], jwt)
    except Exception as e:
        entry['status'] = 'error'
        entry['error'] = 'Login or key creation failed'
        log.error(f'[ondo] submit failed token={token[:8]}…: {e}')
        return web.json_response({'error': 'Login or key creation failed'}, status=502)
    entry['key_id'] = key_id
    entry['secret'] = secret
    entry['status'] = 'done'
    log.info(f'[ondo] key created token={token[:8]}… keyId={key_id[:10]}…')
    markup = {'inline_keyboard': [[{'text': '💾 Save to Mimiq', 'callback_data': f'ondo_save_{token}'}]]}
    _send_tg_notification(entry['chat_id'], '✅ *Ondo sign-in successful!*\n\nTap *Save to Mimiq* to finish linking your Ondo account.', reply_markup=markup)
    return web.json_response({'ok': True})


async def handle_ondo_claim(req: web.Request) -> web.Response:
    """Bot → server (auth, single-use): retrieve {key_id, secret, wallet_id} and drop the token."""
    if not _bot_authed(req):
        raise web.HTTPUnauthorized()
    token = req.match_info['token']
    entry = _session(_ondo_store, token, ONDO_CLAIM_TTL)
    if not entry:
        return web.json_response({'error': 'Token not found or expired'}, status=404)
    if entry['status'] != 'done':
        return web.json_response({'error': f'Session is {entry['status']}'}, status=400)
    result = {'account': entry['account'], 'key_id': entry['key_id'], 'secret': entry['secret'], 'wallet_id': entry['wallet_id'], 'user_id': entry['telegram_id']}
    _ondo_store.pop(token, None)
    log.info(f'[ondo] claimed token={token[:8]}… wallet={result['wallet_id']}')
    return web.json_response(result)


async def handle_ondo_status(req: web.Request) -> web.Response:
    token = req.match_info['token']
    entry = _session(_ondo_store, token, ONDO_CLAIM_TTL)
    if not entry:
        return web.json_response({'status': 'not_found'}, status=404)
    return web.json_response({'status': entry['status'], 'error': entry['error'], 'bot_url': entry.get('bot_url', '')})


_db_pool: Optional[asyncpg.Pool] = None


@asynccontextmanager
async def _conn():
    async with _db_pool.acquire() as con:
        yield con


async def _dash_owns_wallet(con: asyncpg.Connection, wallet_id: int, telegram_id: int) -> bool:
    """Ownership gate for every dashboard write endpoint — a valid JWT only proves identity, never wallet ownership."""
    row = await con.fetchrow('SELECT 1 FROM wallets WHERE id = $1 AND telegram_id = $2', wallet_id, telegram_id)
    return row is not None


DASH_JWT_SECRET = os.environ.get('DASHBOARD_JWT_SECRET', '')


DASH_JWT_TTL = ...


DASH_NONCE_TTL = ...


_RATE_DASH_MAX = ...


_RATE_DASH_WINDOW = ...


_rate_dash: dict[str, collections.deque] = collections.defaultdict(collections.deque)


def _dash_domain() -> str:
    """The domain shown in the sign-in message; wallets compare it with the page's origin (EIP-4361)."""
    from urllib.parse import urlparse
    return urlparse(PUBLIC_BASE_URL).netloc or 'mimiq.tech'


def _dash_nonce_message(address: str, nonce: str, issued_at: int) -> str:
    """EIP-4361 (Sign-In with Ethereum) message."""
    domain = _dash_domain()
    issued = datetime.fromtimestamp(issued_at, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    return f'{domain} wants you to sign in with your Ethereum account:\n{address}\n\nSign in to the Mimiq dashboard. This signature does not authorize any transaction or spending.\n\nURI: https://{domain}\nVersion: 1\nChain ID: 1\nNonce: {nonce}\nIssued At: {issued}'


async def _dash_resolve_telegram_id(con: asyncpg.Connection, address: str) -> Optional[int]:
    """address -> telegram_id, matching either wallets.l1_address (our generated wallet) or any wallet_platforms.account_id (a platform-specific externally-connected address) — see module comment above for w"""
    rows = await con.fetch('\n        SELECT telegram_id FROM wallets WHERE lower(l1_address) = lower($1)\n        UNION\n        SELECT w.telegram_id FROM wallets w\n          JOIN wallet_platforms wp ON wp.wallet_id = w.id\n          WHERE lower(wp.account_id) = lower($1)\n        ', address)
    ids = {r['telegram_id'] for r in rows}
    if len(ids) > 1:
        log.warning(f'[dash] address {address[:10]}… is linked to {len(ids)} users — refusing login')
        return None
    return next(iter(ids)) if ids else None


async def _dash_redeem_invite_code(con: asyncpg.Connection, code: str, telegram_id: int) -> str:
    """Same logic as mimiq2's database.redeem_invite_code — reimplemented here rather than imported since this process deliberately doesn't share Python modules with mimiq2 (see this file's own isolation-ove"""
    already = await con.fetchrow('SELECT 1 FROM invite_uses WHERE telegram_id = $1', telegram_id)
    if already:
        return 'already_joined'
    row = await con.fetchrow('SELECT max_uses FROM invite_codes WHERE code = $1', code)
    if not row:
        return 'invalid'
    tag = await con.execute('UPDATE invite_codes SET uses = uses + 1 WHERE code = $1 AND uses < max_uses', code)
    if int(tag.split()[-1]) == 0:
        return 'used_up'
    now = datetime.now(timezone.utc).isoformat()
    await con.execute('INSERT INTO invite_uses (code, telegram_id, used_at) VALUES ($1, $2, $3)', code, telegram_id, now)
    await con.execute('UPDATE users SET invite_verified = 1, updated_at = $1 WHERE telegram_id = $2', now, telegram_id)
    return 'ok'


def _dash_issue_token(telegram_id: int) -> str:
    import jwt
    now = int(time.time())
    return jwt.encode({'telegram_id': telegram_id, 'iat': now, 'exp': now + DASH_JWT_TTL}, DASH_JWT_SECRET, algorithm='HS256')


async def handle_dash_nonce(req: web.Request) -> web.Response:
    """Browser -> server: {address} -> a one-time nonce to sign, stored keyed by address."""
    ip = _client_ip(req)
    if not _check_rate(_rate_dash, ip, _RATE_DASH_MAX, _RATE_DASH_WINDOW):
        raise web.HTTPTooManyRequests(reason='Rate limit exceeded')
    try:
        body = await req.json()
    except Exception:
        raise web.HTTPBadRequest(reason='Invalid JSON')
    address = str(body.get('address', '')).strip()
    if not _HEX40.match(address):
        return web.json_response({'error': 'Invalid address'}, status=400)
    try:
        address = to_checksum_address(address)
    except Exception:
        return web.json_response({'error': 'Invalid address'}, status=400)
    nonce = secrets.token_hex(16)
    issued_at = int(time.time())
    if _db_pool is None:
        return web.json_response({'error': 'Server misconfigured'}, status=500)
    async with _conn() as con:
        await con.execute('INSERT INTO login_nonces (address, nonce, expires_at) VALUES ($1, $2, $3) ON CONFLICT (address) DO UPDATE SET nonce = EXCLUDED.nonce, expires_at = EXCLUDED.expires_at WHERE login_nonces.expires_at < $4', address, nonce, issued_at + DASH_NONCE_TTL, float(issued_at))
        row = await con.fetchrow('SELECT nonce, expires_at FROM login_nonces WHERE address = $1', address)
    issued_at = int(round(row['expires_at'] - DASH_NONCE_TTL))
    return web.json_response({'message': _dash_nonce_message(address, row['nonce'], issued_at)})


async def handle_dash_login(req: web.Request) -> web.Response:
    """Browser -> server: {address, signature[, code]} -> verify the signed sign-in message, resolve the identity and issue a session JWT."""
    ip = _client_ip(req)
    if not _check_rate(_rate_dash, ip, _RATE_DASH_MAX, _RATE_DASH_WINDOW):
        raise web.HTTPTooManyRequests(reason='Rate limit exceeded')
    try:
        body = await req.json()
    except Exception:
        raise web.HTTPBadRequest(reason='Invalid JSON')
    address = str(body.get('address', '')).strip()
    signature = str(body.get('signature', '')).strip()
    code = str(body.get('code', '')).strip()
    try:
        address = to_checksum_address(address)
    except Exception:
        return web.json_response({'error': 'Invalid address'}, status=400)
    if _db_pool is None:
        return web.json_response({'error': 'Server misconfigured'}, status=500)
    async with _conn() as con:
        row = await con.fetchrow('SELECT nonce, expires_at FROM login_nonces WHERE address = $1', address)
        if not row or row['expires_at'] < time.time():
            return web.json_response({'error': 'No pending nonce — request one first'}, status=400)
        issued_at = int(round(row['expires_at'] - DASH_NONCE_TTL))
        message = _dash_nonce_message(address, row['nonce'], issued_at)
        try:
            recovered = Web3().eth.account.recover_message(encode_defunct(text=message), signature=signature)
        except Exception as e:
            log.warning(f'[dash] signature recovery failed: {e}')
            return web.json_response({'error': 'Invalid signature'}, status=400)
        if recovered.lower() != address.lower():
            return web.json_response({'error': 'Signature does not match address'}, status=400)
        consumed = await con.fetchval('DELETE FROM login_nonces WHERE address = $1 AND nonce = $2 RETURNING 1', address, row['nonce'])
        if not consumed:
            return web.json_response({'error': 'No pending nonce — request one first'}, status=400)
        telegram_id = await _dash_resolve_telegram_id(con, address)
        if telegram_id is None:
            return web.json_response({'status': 'unknown_wallet'})
        verified_row = await con.fetchrow('SELECT invite_verified FROM users WHERE telegram_id = $1', telegram_id)
        if verified_row and verified_row['invite_verified']:
            return web.json_response({'status': 'ok', 'token': _dash_issue_token(telegram_id)})
        if not code:
            return web.json_response({'status': 'needs_invite', 'address': address})
        locked = await _dash_invite_locked(con, telegram_id)
        if locked:
            return web.json_response({'status': 'locked', 'retry_after': locked}, status=429)
        result = await _dash_redeem_invite_code(con, code, telegram_id)
        if result not in ('ok', 'already_joined'):
            left = await _dash_invite_record_failure(con, telegram_id)
            if left == 0:
                return web.json_response({'status': 'locked'}, status=429)
            return web.json_response({'status': result}, status=400)
        return web.json_response({'status': 'ok', 'token': _dash_issue_token(telegram_id)})


_DASH_INVITE_MAX_ATTEMPTS = ...


_DASH_INVITE_LOCKOUT_SECS = ...


async def _dash_invite_locked(con: asyncpg.Connection, telegram_id: int) -> Optional[int]:
    """Remaining lockout seconds if the user is locked out of invite redemption, else None."""
    row = await con.fetchrow('SELECT locked_until FROM invite_lockouts WHERE telegram_id = $1', telegram_id)
    if not row or row['locked_until'] <= 0:
        return None
    remaining = row['locked_until'] - time.time()
    if remaining <= 0:
        await con.execute('DELETE FROM invite_lockouts WHERE telegram_id = $1', telegram_id)
        return None
    return int(remaining) + 1


async def _dash_invite_record_failure(con: asyncpg.Connection, telegram_id: int) -> int:
    """Count a failed code attempt; returns the attempts left (0 = just locked)."""
    async with con.transaction():
        row = await con.fetchrow('SELECT fail_count, locked_until FROM invite_lockouts WHERE telegram_id = $1 FOR UPDATE', telegram_id)
        fail_count = (row['fail_count'] if row else 0) + 1
        locked_until = row['locked_until'] if row else 0.0
        remaining = _DASH_INVITE_MAX_ATTEMPTS - fail_count
        new_locked = time.time() + _DASH_INVITE_LOCKOUT_SECS if remaining <= 0 else locked_until
        await con.execute('INSERT INTO invite_lockouts (telegram_id, fail_count, locked_until) VALUES ($1, $2, $3) ON CONFLICT (telegram_id) DO UPDATE SET fail_count = EXCLUDED.fail_count, locked_until = EXCLUDED.locked_until', telegram_id, 0 if remaining <= 0 else fail_count, new_locked)
    return max(remaining, 0)


def _dash_auth(req: web.Request) -> Optional[int]:
    """Verify the Authorization: Bearer <jwt> header, return telegram_id or None."""
    import jwt
    auth = req.headers.get('Authorization', '')
    if not DASH_JWT_SECRET or not auth.startswith('Bearer '):
        return None
    try:
        payload = jwt.decode(auth[7:], DASH_JWT_SECRET, algorithms=['HS256'])
        return int(payload['telegram_id'])
    except Exception:
        return None


def _dash_require_auth(req: web.Request) -> int:
    telegram_id = _dash_auth(req)
    if telegram_id is None:
        raise web.HTTPUnauthorized(reason='Invalid or expired session')
    return telegram_id


def _hl_cleanup():
    now = time.time()
    for t in [t for t, v in _hl_store.items() if now - v['created_at'] > HL_TOKEN_TTL]:
        _hl_store.pop(t, None)


def _hl_split_signature(sig_hex: str) -> dict:
    """Convert a wallet's raw eth_signTypedData_v4 hex signature into HL's {r, s, v} shape."""
    sig = sig_hex[2:] if sig_hex.startswith('0x') else sig_hex
    return {'r': '0x' + sig[0:64], 's': '0x' + sig[64:128], 'v': int(sig[128:130], 16)}


async def _update_hl_approved_in_db(wallet_id: int, approved: bool):
    """Mirrors _update_approved_in_db (Lighter) — direct write to mimiq2's live Postgres, same reasoning: this process is separate from mimiq2's, so it writes raw SQL rather than importing mimiq2's database."""
    if not DATABASE_URL:
        return
    try:
        con = await asyncpg.connect(DATABASE_URL)
        try:
            await con.execute("UPDATE wallet_platforms SET hl_builder_fee_approved = $1, updated_at = $2 WHERE platform = 'hyperliquid'   AND lower(account_id) = lower((SELECT account_id FROM wallet_platforms                                   WHERE wallet_id = $3 AND platform = 'hyperliquid'))   AND wallet_id IN (SELECT id FROM wallets WHERE telegram_id =                     (SELECT telegram_id FROM wallets WHERE id = $3))", 1 if approved else 0, datetime.now(timezone.utc).isoformat(), wallet_id)
        finally:
            await con.close()
        log.info(f'Set hl_builder_fee_approved={approved} for wallet {wallet_id} in DB')
    except Exception as e:
        log.warning(f'Could not update DB for wallet {wallet_id}: {e}')


async def handle_hl_prepare(req: web.Request) -> web.Response:
    """Bot → server: start an HL builder-fee approval session."""
    ip = _client_ip(req)
    if not _prepare_allowed(req, ip):
        raise web.HTTPTooManyRequests(reason='Rate limit exceeded')
    if not _bot_authed(req):
        raise web.HTTPUnauthorized()
    try:
        body = await req.json()
    except Exception:
        raise web.HTTPBadRequest(reason='Invalid JSON')
    wallet_id = int(body['wallet_id'])
    expected_address = ''
    if DATABASE_URL:
        try:
            con = await asyncpg.connect(DATABASE_URL)
            try:
                row = await con.fetchrow("SELECT account_id FROM wallet_platforms WHERE wallet_id = $1 AND platform = 'hyperliquid'", wallet_id)
            finally:
                await con.close()
            if row and row['account_id']:
                expected_address = str(row['account_id']).lower()
        except Exception as e:
            log.warning(f'[hl] could not look up expected address for wallet {wallet_id}: {e}')
    if not expected_address:
        log.error(f'[hl] no linked account known for wallet {wallet_id} — refusing to open a signing session')
        return web.json_response({'error': 'Could not determine the linked account — try again.'}, status=400)
    token = _new_token()
    _hl_cleanup()
    _hl_store[token] = {'wallet_id': wallet_id, 'expected_address': expected_address, 'quiet': bool(body.get('quiet', False)), 'telegram_id': int(body['telegram_id']), 'chat_id': int(body['chat_id']), 'bot_url': str(body.get('bot_url', '')).strip(), 'nonce': None, 'status': 'pending', 'error': None, 'created_at': time.time()}
    if PUBLIC_BASE_URL:
        from urllib.parse import urlparse as _up
        _p = _up(PUBLIC_BASE_URL)
        url = f'{_p.scheme}://{_p.netloc}/hyperliquid/{token}'
    else:
        url = f'/hyperliquid/{token}'
    log.info(f'[hl] new session token={token[:8]}… wallet={_hl_store[token]['wallet_id']}')
    return web.json_response({'token': token, 'url': url})


async def handle_hl_status(req: web.Request) -> web.Response:
    """Browser → server: {status, expected_address} for an HL signing session, so the page can refuse a wrong wallet at connect time."""
    entry = _session(_hl_store, req.match_info['token'], HL_TOKEN_TTL)
    if not entry:
        return web.json_response({'status': 'not_found'}, status=404)
    resp = {'status': entry['status']}
    if entry['status'] == 'pending':
        resp['expected_address'] = str(entry.get('expected_address') or '').lower()
    return web.json_response(resp)


async def handle_hl_typed_data(req: web.Request) -> web.Response:
    """Browser → server: {token, chain_id} → EIP-712 typed data for ApproveBuilderFee."""
    try:
        body = await req.json()
    except Exception:
        raise web.HTTPBadRequest(reason='Invalid JSON')
    token = str(body.get('token', ''))
    chain_id = str(body.get('chain_id', '')).strip() or HL_SIG_CHAIN_ID
    address = str(body.get('address', '')).strip().lower()
    entry = _session(_hl_store, token, HL_TOKEN_TTL)
    if not entry:
        return web.json_response({'error': 'Invalid or expired token'}, status=400)
    if entry['status'] != 'pending':
        return web.json_response({'error': f'Session is {entry['status']}'}, status=400)
    wrong = _wrong_wallet_response(entry, address, 'hl')
    if wrong is not None:
        return wrong
    try:
        chain_id_int = int(chain_id, 16)
    except ValueError:
        return web.json_response({'error': 'Invalid chain_id'}, status=400)
    nonce = int(time.time() * 1000)
    entry['nonce'] = nonce
    entry['chain_id'] = chain_id
    return web.json_response({'typed_data': _hl_approve_typed_data(chain_id_int, chain_id, nonce)})


def _hl_approve_typed_data(chain_id_int: int, chain_id_hex: str, nonce: int) -> dict:
    """Same dict shape used both to send to the browser for signing and, server-side, to reconstruct the exact signed payload for recovering the signer (handle_hl_submit)."""
    return {'domain': {'name': 'HyperliquidSignTransaction', 'version': '1', 'chainId': chain_id_int, 'verifyingContract': '0x0000000000000000000000000000000000000000'}, 'types': {'EIP712Domain': [{'name': 'name', 'type': 'string'}, {'name': 'version', 'type': 'string'}, {'name': 'chainId', 'type': 'uint256'}, {'name': 'verifyingContract', 'type': 'address'}], 'HyperliquidTransaction:ApproveBuilderFee': [{'name': 'hyperliquidChain', 'type': 'string'}, {'name': 'maxFeeRate', 'type': 'string'}, {'name': 'builder', 'type': 'address'}, {'name': 'nonce', 'type': 'uint64'}]}, 'primaryType': 'HyperliquidTransaction:ApproveBuilderFee', 'message': {'hyperliquidChain': 'Mainnet', 'maxFeeRate': HL_MAX_FEE_RATE, 'builder': HL_BUILDER_ADDRESS, 'nonce': nonce, 'signatureChainId': chain_id_hex}}


async def handle_hl_submit(req: web.Request) -> web.Response:
    """Browser → server: {token, account, signature} after eth_signTypedData_v4."""
    ip = _client_ip(req)
    if not _check_rate(_rate_submit, ip, _RATE_SUBMIT_MAX, _RATE_SUBMIT_WINDOW):
        raise web.HTTPTooManyRequests(reason='Rate limit exceeded')
    try:
        body = await req.json()
    except Exception:
        raise web.HTTPBadRequest(reason='Invalid JSON')
    token = str(body.get('token', ''))
    signature = str(body.get('signature', '')).strip()
    entry = _session(_hl_store, token, HL_TOKEN_TTL)
    if not entry:
        return web.json_response({'error': 'Invalid or expired token'}, status=400)
    if entry['status'] != 'pending':
        return web.json_response({'error': f'Session is {entry['status']}'}, status=400)
    if entry.get('nonce') is None:
        return web.json_response({'error': 'No pending signature request for this session'}, status=400)
    expected = entry.get('expected_address') or ''
    if expected:
        try:
            from eth_account import Account
            from eth_account.messages import encode_typed_data
            chain_id_hex = entry.get('chain_id', HL_SIG_CHAIN_ID)
            typed_data = _hl_approve_typed_data(int(chain_id_hex, 16), chain_id_hex, entry['nonce'])
            signable = encode_typed_data(full_message=typed_data)
            recovered = Account.recover_message(signable, signature=signature).lower()
        except Exception as e:
            entry['status'] = 'error'
            entry['error'] = 'Could not verify signature'
            log.error(f'[hl] signature recovery failed: {e}')
            return web.json_response({'error': 'Could not verify signature — try again.'}, status=400)
        if recovered != expected:
            entry['status'] = 'error'
            entry['error'] = f'Signed by {recovered}, expected {expected}'
            log.warning(f'[hl] wallet={entry['wallet_id']} signer mismatch: got {recovered}, expected {expected}')
            return web.json_response({'error': f'Wrong wallet connected — please switch to {expected} and try again.'}, status=400)
    entry['status'] = 'submitting'
    action = {'type': 'approveBuilderFee', 'hyperliquidChain': 'Mainnet', 'maxFeeRate': HL_MAX_FEE_RATE, 'builder': HL_BUILDER_ADDRESS, 'nonce': entry['nonce'], 'signatureChainId': entry.get('chain_id', HL_SIG_CHAIN_ID)}
    payload = {'action': action, 'nonce': entry['nonce'], 'signature': _hl_split_signature(signature), 'vaultAddress': None}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as http:
            async with http.post(f'{HL_API_URL}/exchange', json=payload) as r:
                data = await r.json()
    except Exception as e:
        entry['status'] = 'error'
        entry['error'] = 'Could not reach Hyperliquid — try again.'
        log.error(f'[hl] /exchange call failed: {e}')
        return web.json_response({'error': 'Could not reach Hyperliquid — try again.'}, status=500)
    if not isinstance(data, dict) or data.get('status') != 'ok':
        entry['status'] = 'error'
        entry['error'] = 'Hyperliquid rejected the approval.'
        log.warning(f'[hl] approveBuilderFee rejected: {data}')
        return web.json_response({'error': 'Hyperliquid rejected the approval — please try again.'}, status=400)
    entry['status'] = 'done'
    await _update_hl_approved_in_db(entry['wallet_id'], approved=True)
    log.info(f'[hl] builder fee approved wallet={entry['wallet_id']} token={token[:8]}…')
    menu_markup = {'inline_keyboard': [[{'text': '← Back to Menu', 'callback_data': 'menu_back'}]]}
    _notify_unless_quiet(entry, entry['chat_id'], '✅ Builder fee approved!', reply_markup=menu_markup)
    return web.json_response({'ok': True, 'bot_url': entry.get('bot_url', '')})


async def handle_prepare(req: web.Request) -> web.Response:
    """Called by the bot to generate a signing session."""
    ip = _client_ip(req)
    if not _prepare_allowed(req, ip):
        raise web.HTTPTooManyRequests(reason='Rate limit exceeded')
    if not _bot_authed(req):
        raise web.HTTPUnauthorized()
    try:
        body = await req.json()
    except Exception:
        raise web.HTTPBadRequest(reason='Invalid JSON')
    account_index = int(body['account_index'])
    api_key = str(body['api_key'])
    api_key_slot = int(body.get('api_key_slot', 3))
    l1_address = str(body.get('l1_address', '')).lower().strip()
    if not l1_address:
        log.error('[approve] prepare without l1_address — refusing to open a signing session')
        return web.json_response({'error': 'Could not determine the account owner — try again.'}, status=400)
    bot_url = str(body.get('bot_url', '')).strip()
    revoke = bool(body.get('revoke', False))
    telegram_id = int(body.get('telegram_id', 0))
    chat_id = int(body.get('chat_id', 0))
    _cleanup()
    loop = asyncio.get_running_loop()
    tx_type, tx_info, msg_to_sign, err = await loop.run_in_executor(None, _get_approve_payload, account_index, api_key, api_key_slot, revoke)
    if err:
        log.error(f'prepare failed: {err}')
        return web.json_response({'error': 'Could not prepare approval — try again.'}, status=500)
    token = _new_token()
    _store[token] = {'account_index': account_index, 'api_key': api_key, 'api_key_slot': api_key_slot, 'l1_address': l1_address, 'bot_url': bot_url, 'revoke': revoke, 'quiet': bool(body.get('quiet', False)), 'telegram_id': telegram_id, 'chat_id': chat_id, 'tx_type': int(tx_type), 'tx_info': tx_info, 'msg_to_sign': msg_to_sign, 'status': 'pending', 'tx_hash': None, 'error': None, 'created_at': time.time()}
    url = f'{PUBLIC_BASE_URL}/{token}' if PUBLIC_BASE_URL else f'/approve/{token}'
    log.info(f'New approval session token={token[:8]}… account={account_index}')
    return web.json_response({'token': token, 'url': url, 'message_to_sign': msg_to_sign})


async def handle_submit(req: web.Request) -> web.Response:
    """Called by the browser after the user signs the message."""
    ip = _client_ip(req)
    if not _check_rate(_rate_submit, ip, _RATE_SUBMIT_MAX, _RATE_SUBMIT_WINDOW):
        raise web.HTTPTooManyRequests(reason='Rate limit exceeded')
    try:
        body = await req.json()
    except Exception:
        raise web.HTTPBadRequest(reason='Invalid JSON')
    token = str(body.get('token', ''))
    signature = str(body.get('signature', ''))
    address = str(body.get('address', '')).lower().strip()
    entry = _session(_store, token, TOKEN_TTL)
    if not entry:
        return web.json_response({'error': 'Invalid or expired token'}, status=400)
    if entry['status'] != 'pending':
        return web.json_response({'error': f'Session is {entry['status']}'}, status=400)
    try:
        msg = encode_defunct(text=entry['msg_to_sign'])
        recovered = Web3().eth.account.recover_message(msg, signature=signature).lower()
    except Exception as e:
        log.warning(f'[approve] invalid signature: {e}')
        return web.json_response({'error': 'Invalid signature'}, status=400)
    if address and recovered != address:
        return web.json_response({'error': f'Signature address mismatch: recovered {recovered}, claimed {address}'}, status=400)
    expected = entry['l1_address']
    if expected and recovered != expected:
        return web.json_response({'error': f'Signature address mismatch: got {recovered}, expected {expected}'}, status=400)
    entry['recovered_address'] = recovered
    try:
        tx_info_obj = json.loads(entry['tx_info'])
        tx_info_obj['L1Sig'] = signature
        tx_info_final = json.dumps(tx_info_obj)
    except Exception as e:
        log.error(f'tx_info manipulation failed: {e}')
        return web.json_response({'error': 'Could not process signature — try again.'}, status=500)
    entry['status'] = 'submitting'
    tx_hash, err = await _send_approved_tx(account_index=entry['account_index'], api_key_priv=entry['api_key'], api_key_slot=entry['api_key_slot'], tx_type=entry['tx_type'], tx_info_with_sig=tx_info_final)
    entry['api_key'] = ''
    if err:
        entry['status'] = 'error'
        entry['error'] = 'Submission failed'
        log.error(f'submit failed token={token[:8]}…: {err}')
        return web.json_response({'error': 'Submission failed — try again.'}, status=500)
    entry['status'] = 'done'
    entry['tx_hash'] = tx_hash
    is_revoke = entry.get('revoke', False)
    log.info(f'{('Revoke' if is_revoke else 'Approval')} confirmed token={token[:8]}… tx_hash={tx_hash}')
    await _update_approved_in_db(entry['account_index'], approved=not is_revoke, telegram_id=entry.get('telegram_id', 0))
    chat_id = entry.get('chat_id', 0)
    menu_markup = {'inline_keyboard': [[{'text': '← Back to Menu', 'callback_data': 'menu_back'}]]}
    if is_revoke:
        _send_tg_notification(chat_id, "🔓 *Revoked.*\n\nMimiq's integrator fee no longer applies to your Lighter trades.", reply_markup=menu_markup)
    else:
        _notify_unless_quiet(entry, chat_id, '✅ Integrator fee approved!', reply_markup=menu_markup)
    _store.pop(token, None)
    return web.json_response({'ok': True, 'tx_hash': tx_hash, 'revoked': is_revoke})


async def handle_lighter_rh_prepare(req: web.Request) -> web.Response:
    """Same as handle_prepare, isolated for Robinhood-Chain-Lighter — see the module-level comment by LIGHTER_RH_API_BASE for why this is a copy, not a shared/parameterized handler."""
    ip = _client_ip(req)
    if not _prepare_allowed(req, ip):
        raise web.HTTPTooManyRequests(reason='Rate limit exceeded')
    if not _bot_authed(req):
        raise web.HTTPUnauthorized()
    try:
        body = await req.json()
    except Exception:
        raise web.HTTPBadRequest(reason='Invalid JSON')
    account_index = int(body['account_index'])
    api_key = str(body['api_key'])
    api_key_slot = int(body.get('api_key_slot', 3))
    l1_address = str(body.get('l1_address', '')).lower().strip()
    if not l1_address:
        log.error('[approve] prepare without l1_address — refusing to open a signing session')
        return web.json_response({'error': 'Could not determine the account owner — try again.'}, status=400)
    bot_url = str(body.get('bot_url', '')).strip()
    revoke = bool(body.get('revoke', False))
    telegram_id = int(body.get('telegram_id', 0))
    chat_id = int(body.get('chat_id', 0))
    _cleanup()
    loop = asyncio.get_running_loop()
    tx_type, tx_info, msg_to_sign, err = await loop.run_in_executor(None, _get_lighter_rh_approve_payload, account_index, api_key, api_key_slot, revoke)
    if err:
        log.error(f'[lighter_rh] prepare failed: {err}')
        return web.json_response({'error': 'Could not prepare approval — try again.'}, status=500)
    token = _new_token()
    _store[token] = {'account_index': account_index, 'api_key': api_key, 'api_key_slot': api_key_slot, 'l1_address': l1_address, 'bot_url': bot_url, 'revoke': revoke, 'quiet': bool(body.get('quiet', False)), 'telegram_id': telegram_id, 'chat_id': chat_id, 'tx_type': int(tx_type), 'tx_info': tx_info, 'msg_to_sign': msg_to_sign, 'status': 'pending', 'tx_hash': None, 'error': None, 'created_at': time.time()}
    if PUBLIC_BASE_URL:
        from urllib.parse import urlparse as _up
        _p = _up(PUBLIC_BASE_URL)
        _host = f'{_p.scheme}://{_p.netloc}'
        url = f'{_host}/lighter-rh/{token}'
    else:
        url = f'/lighter-rh/{token}'
    log.info(f'[lighter_rh] New approval session token={token[:8]}… account={account_index}')
    return web.json_response({'token': token, 'url': url, 'message_to_sign': msg_to_sign})


async def handle_lighter_rh_submit(req: web.Request) -> web.Response:
    """Same as handle_submit, isolated for Robinhood-Chain-Lighter."""
    ip = _client_ip(req)
    if not _check_rate(_rate_submit, ip, _RATE_SUBMIT_MAX, _RATE_SUBMIT_WINDOW):
        raise web.HTTPTooManyRequests(reason='Rate limit exceeded')
    try:
        body = await req.json()
    except Exception:
        raise web.HTTPBadRequest(reason='Invalid JSON')
    token = str(body.get('token', ''))
    signature = str(body.get('signature', ''))
    address = str(body.get('address', '')).lower().strip()
    entry = _session(_store, token, TOKEN_TTL)
    if not entry:
        return web.json_response({'error': 'Invalid or expired token'}, status=400)
    if entry['status'] != 'pending':
        return web.json_response({'error': f'Session is {entry['status']}'}, status=400)
    try:
        msg = encode_defunct(text=entry['msg_to_sign'])
        recovered = Web3().eth.account.recover_message(msg, signature=signature).lower()
    except Exception as e:
        log.warning(f'[lighter_rh approve] invalid signature: {e}')
        return web.json_response({'error': 'Invalid signature'}, status=400)
    if address and recovered != address:
        return web.json_response({'error': f'Signature address mismatch: recovered {recovered}, claimed {address}'}, status=400)
    expected = entry['l1_address']
    if expected and recovered != expected:
        return web.json_response({'error': f'Signature address mismatch: got {recovered}, expected {expected}'}, status=400)
    entry['recovered_address'] = recovered
    try:
        tx_info_obj = json.loads(entry['tx_info'])
        tx_info_obj['L1Sig'] = signature
        tx_info_final = json.dumps(tx_info_obj)
    except Exception as e:
        log.error(f'[lighter_rh] tx_info manipulation failed: {e}')
        return web.json_response({'error': 'Could not process signature — try again.'}, status=500)
    entry['status'] = 'submitting'
    tx_hash, err = await _send_lighter_rh_approved_tx(account_index=entry['account_index'], api_key_priv=entry['api_key'], api_key_slot=entry['api_key_slot'], tx_type=entry['tx_type'], tx_info_with_sig=tx_info_final)
    entry['api_key'] = ''
    if err:
        entry['status'] = 'error'
        entry['error'] = 'Submission failed'
        log.error(f'[lighter_rh] submit failed token={token[:8]}…: {err}')
        return web.json_response({'error': 'Submission failed — try again.'}, status=500)
    entry['status'] = 'done'
    entry['tx_hash'] = tx_hash
    is_revoke = entry.get('revoke', False)
    log.info(f'[lighter_rh] {('Revoke' if is_revoke else 'Approval')} confirmed token={token[:8]}… tx_hash={tx_hash}')
    await _update_lighter_rh_approved_in_db(entry['account_index'], approved=not is_revoke, telegram_id=entry.get('telegram_id', 0))
    chat_id = entry.get('chat_id', 0)
    menu_markup = {'inline_keyboard': [[{'text': '← Back to Menu', 'callback_data': 'menu_back'}]]}
    if is_revoke:
        _send_tg_notification(chat_id, "🔓 *Revoked.*\n\nMimiq's integrator fee no longer applies to your Lighter (Robinhood Chain) trades.", reply_markup=menu_markup)
    else:
        _notify_unless_quiet(entry, chat_id, '✅ Integrator fee approved!', reply_markup=menu_markup)
    _store.pop(token, None)
    return web.json_response({'ok': True, 'tx_hash': tx_hash, 'revoked': is_revoke})


async def handle_status(req: web.Request) -> web.Response:
    token = req.match_info['token']
    entry = _session(_store, token, TOKEN_TTL)
    if not entry:
        return web.json_response({'status': 'not_found'}, status=404)
    resp = {'status': entry['status'], 'tx_hash': entry['tx_hash'], 'error': entry['error'], 'bot_url': entry.get('bot_url', ''), 'revoke': entry.get('revoke', False)}
    if entry['status'] == 'pending' and entry.get('msg_to_sign'):
        resp['msg_to_sign'] = entry['msg_to_sign']
    if entry['status'] == 'pending':
        resp['expected_address'] = str(entry.get('l1_address') or '').lower()
    return web.json_response(resp)
