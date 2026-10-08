"""Excerpt of mimiq2/dex/spec.py for security review — only the code shown here."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WalletCreds:
    """Platform credentials as stored in the generic `wallet_platform` DB row (decrypted)."""
    account_id: str = ''
    api_key: str = ''
    private_key: str = ''
    api_key_slot: int = 0
    builder_fee_approved: bool = False
    integrator_fee_approved: bool = False
    tier_paid: bool = True
    public_key: str = ''
    owner_id: int = 0
    vault_id: int = 0
