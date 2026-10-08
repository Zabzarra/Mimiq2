"""Excerpt of mimiq2/database.py for security review — only the code shown here."""

import re
import time
from contextlib import asynccontextmanager
from typing import Optional, List


_SAFE_IDENT = re.compile('^[a-z_][a-z0-9_]*$')


def _safe_col(name: str) -> str:
    if not _SAFE_IDENT.match(name):
        raise ValueError(f'unsafe column identifier: {name!r}')
    return name


@asynccontextmanager
async def _conn():
    async with _pool.acquire() as con:
        async with con.transaction():
            yield con


async def user_exists(telegram_id: int) -> bool:
    async with _conn() as con:
        row = await con.fetchrow('SELECT 1 FROM users WHERE telegram_id = $1', telegram_id)
        return row is not None


async def get_enc_salt(telegram_id: int) -> Optional[bytes]:
    async with _conn() as con:
        row = await con.fetchrow('SELECT enc_salt FROM users WHERE telegram_id = $1', telegram_id)
        if row and row['enc_salt']:
            return bytes.fromhex(row['enc_salt'])
        return None


async def get_or_create_enc_salt(telegram_id: int, new_salt: bytes) -> bytes:
    """The user's encryption salt, created with `new_salt` if there is none yet."""
    async with _conn() as con:
        row = await con.fetchrow("UPDATE users SET enc_salt = $1, updated_at = $2 WHERE telegram_id = $3 AND (enc_salt IS NULL OR enc_salt = '') RETURNING enc_salt", new_salt.hex(), _now(), telegram_id)
        if row is None:
            row = await con.fetchrow('SELECT enc_salt FROM users WHERE telegram_id = $1', telegram_id)
    if row is None or not row['enc_salt']:
        raise ValueError(f'no users row for telegram_id {telegram_id} - cannot store an encryption salt')
    return bytes.fromhex(row['enc_salt'])


async def get_wallet_owned(wallet_id: int, telegram_id: int) -> Optional[dict]:
    """Ownership-enforced variant of get_wallet() — returns None if wallet_id doesn't actually belong to telegram_id, instead of trusting the caller to have already checked."""
    async with _conn() as con:
        row = await con.fetchrow('SELECT * FROM wallets WHERE id = $1 AND telegram_id = $2', wallet_id, telegram_id)
        return dict(row) if row else None


async def get_wallets(telegram_id: int) -> List[dict]:
    async with _conn() as con:
        rows = await con.fetch('SELECT * FROM wallets WHERE telegram_id = $1 ORDER BY created_at ASC', telegram_id)
        return [dict(r) for r in rows]


async def redeem_invite_code(code: str, telegram_id: int) -> str:
    """Try to redeem an invite code for a user."""
    async with _conn() as con:
        already = await con.fetchrow('SELECT 1 FROM invite_uses WHERE telegram_id = $1', telegram_id)
        if already:
            return 'already_joined'
        row = await con.fetchrow('SELECT max_uses FROM invite_codes WHERE code = $1', code)
        if not row:
            return 'invalid'
        tag = await con.execute('UPDATE invite_codes SET uses = uses + 1 WHERE code = $1 AND uses < max_uses', code)
        if int(tag.split()[-1]) == 0:
            return 'used_up'
        now = _now()
        await con.execute('INSERT INTO invite_uses (code, telegram_id, used_at) VALUES ($1, $2, $3)', code, telegram_id, now)
        await con.execute('UPDATE users SET invite_verified = 1, updated_at = $1 WHERE telegram_id = $2', now, telegram_id)
        return 'ok'


_INVITE_MAX_ATTEMPTS = ...


_INVITE_LOCKOUT_SECS = ...


async def invite_record_failure(telegram_id: int) -> int:
    """Record a failed invite-code attempt."""
    now = time.time()
    async with _conn() as con:
        async with con.transaction():
            row = await con.fetchrow('SELECT fail_count, locked_until FROM invite_lockouts WHERE telegram_id = $1 FOR UPDATE', telegram_id)
            fail_count = (row['fail_count'] if row else 0) + 1
            locked_until = row['locked_until'] if row else 0.0
            remaining = _INVITE_MAX_ATTEMPTS - fail_count
            new_locked = now + _INVITE_LOCKOUT_SECS if remaining <= 0 else locked_until
            await con.execute('\n                INSERT INTO invite_lockouts (telegram_id, fail_count, locked_until)\n                VALUES ($1, $2, $3)\n                ON CONFLICT (telegram_id) DO UPDATE\n                    SET fail_count = EXCLUDED.fail_count, locked_until = EXCLUDED.locked_until\n            ', telegram_id, 0 if remaining <= 0 else fail_count, new_locked)
    return max(remaining, 0)


async def invite_check_locked(telegram_id: int) -> Optional[int]:
    """Return remaining lockout seconds if locked, else None."""
    async with _conn() as con:
        row = await con.fetchrow('SELECT locked_until FROM invite_lockouts WHERE telegram_id = $1', telegram_id)
    if not row or row['locked_until'] <= 0:
        return None
    remaining = row['locked_until'] - time.time()
    if remaining <= 0:
        async with _conn() as con:
            await con.execute('DELETE FROM invite_lockouts WHERE telegram_id = $1', telegram_id)
        return None
    return int(remaining) + 1


async def save_waitlist_entry(telegram_id: int, username: Optional[str], interest: str, venues: str, volume: Optional[str]) -> None:
    async with _conn() as con:
        await con.execute('\n            INSERT INTO waitlist (telegram_id, username, interest, venues, volume, created_at)\n            VALUES ($1, $2, $3, $4, $5, $6)\n            ON CONFLICT (telegram_id) DO UPDATE SET\n                username = EXCLUDED.username, interest = EXCLUDED.interest,\n                venues = EXCLUDED.venues, volume = EXCLUDED.volume,\n                created_at = EXCLUDED.created_at\n        ', telegram_id, username, interest, venues, volume, time.time())


async def delete_waitlist_entry(telegram_id: int) -> bool:
    async with _conn() as con:
        res = await con.execute('DELETE FROM waitlist WHERE telegram_id = $1', telegram_id)
    return res.endswith(' 1')
