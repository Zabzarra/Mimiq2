"""base_executor — the ONE copy-trading executor for every DEX."""

class BaseExecutor:

    def __init__(self, wallet_id: int, spec: DEXSpec, adapter: DestAdapter, *, scale_override: Optional[float]=..., notify_fn=..., notify_flags: int=..., wallet_name: str=..., stops: Optional[dict]=..., max_leverage_cap: Optional[float]=..., copy_current: bool=..., copy_current_exclude: frozenset=..., trader_key: str=...):
        ...

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    async def refresh_own_positions(self, hub: Optional[Any]=...) -> None:
        ...

    async def refresh_equity(self, trader_equity: float) -> None:
        ...

    async def converge(self, hl_coin: str, trader_szi: float, entry_px: float, is_attach: bool=...) -> None:
        ...

    async def reconcile(self, trader_positions: Dict[str, float]) -> None:
        ...

    async def reconcile_cached(self, trader_positions: Dict[str, float]) -> None:
        ...

    async def manage_stops(self, symbol: str, direction: str, size: float, sl_px: float=..., tp_px: float=...) -> Tuple[bool, str]:
        ...
