"""Excerpt of mimiq2/snapshot.py for security review — only the code shown here."""

from typing import Optional
import database
from dex.spec import WalletCreds


def _decrypt(blob: Optional[str], telegram_id: int) -> str:
    """Headless decrypt (no PIN)."""
    if not blob:
        return ''
    from encryption import decrypt
    try:
        return decrypt(blob, telegram_id)
    except Exception as e:
        logger.error('[snapshot] decrypt failed (tg=%s): %s', telegram_id, e)
        return ''


async def _dest_creds(row: dict, dest: Optional[str]=None) -> WalletCreds:
    """Decrypt the credentials for `dest` (an explicit venue override — DN/positions callers building an adapter for a SPECIFIC linked platform, which may differ from the wallet's active one) or, if not give"""
    wid = int(row['id'])
    telegram_id = int(row.get('telegram_id', 0))
    dest = (dest or row.get('active_platform') or 'lighter').lower()
    try:
        from encryption import preload_enc_salt
        await preload_enc_salt(telegram_id)
    except Exception as e:
        logger.error('[snapshot] preload_enc_salt failed (tg=%s): %s', telegram_id, e)
    lighter_slot = int(row.get('lighter_api_key_idx') or 0) if dest == 'lighter' else int(row.get('lighter_rh_api_key_idx') or 0) if dest == 'lighter_rh' else 0
    integrator_approved = bool(row.get('integrator_approved')) if dest == 'lighter' else bool(row.get('lighter_rh_integrator_approved')) if dest == 'lighter_rh' else False
    tier_paid = bool(row.get('lighter_tier_paid')) if dest == 'lighter' else bool(row.get('lighter_rh_tier_paid')) if dest == 'lighter_rh' else True
    plat = await database.get_wallet_platform(wid, dest)
    if not plat:
        if dest == 'lighter' and row.get('lighter_api_key_enc'):
            return WalletCreds(account_id=str(row.get('lighter_account_idx') or ''), api_key=_decrypt(row.get('lighter_api_key_enc'), telegram_id), api_key_slot=lighter_slot, integrator_fee_approved=integrator_approved, tier_paid=tier_paid, owner_id=telegram_id)
        return WalletCreds()
    return WalletCreds(account_id=str(plat.get('account_id') or ''), api_key=_decrypt(plat.get('api_key_enc'), telegram_id), private_key=_decrypt(plat.get('private_key_enc'), telegram_id), api_key_slot=lighter_slot, builder_fee_approved=bool(plat.get('risex_builder_fee_approved')) if dest == 'risex' else bool(plat.get('hl_builder_fee_approved')) if dest == 'hyperliquid' else False, integrator_fee_approved=integrator_approved, tier_paid=tier_paid, public_key=_decrypt(plat.get('public_key_enc'), telegram_id), vault_id=int(plat.get('vault_id') or 0), owner_id=telegram_id)
