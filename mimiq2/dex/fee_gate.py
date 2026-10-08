"""dex.fee_gate — "no fee approval, no new exposure" ()."""

def is_fee_gate_error(err) -> bool:
    """True for a failed order that was refused by the gate — retrying it can never help."""
    ...

def enforced_for(owner_id: int) -> bool:
    """Is this wallet owner subject to the gate right now?"""
    ...

def decide(venue: str, creds, reduce_only: bool) -> Optional[str]:
    """None = let the order through, "block" = refuse it, "log" = would refuse (log mode)."""
    ...

def _wrap(adapter, name: str, venue: str, creds) -> None:
    ...

def install(adapter, venue: str, creds) -> None:
    ...

def gated(venue: str, factory):
    """Wrap an `adapter_factory(creds, transport)` so every adapter it returns is gated."""
    ...
