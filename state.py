import asyncio
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TokenState:
    address: str
    chain: str
    symbol: str = ""
    name: str = ""
    pair_address: str = ""
    dex_url: str = ""

    price_usd: float = 0.0
    price_change_24h: float = 0.0
    price_change_6h: float = 0.0
    price_change_1h: float = 0.0
    market_cap_usd: float = 0.0
    market_cap_prev: float = 0.0
    liquidity_usd: float = 0.0
    volume_24h_usd: float = 0.0
    volume_6h_usd: float = 0.0
    volume_1h_usd: float = 0.0
    volume_trend: str = "unknown"
    unique_traders_24h: int = 0

    age_hours: float = -1.0
    pair_created_at: float = 0.0

    buys_24h: int = 0
    sells_24h: int = 0
    buy_sell_ratio: float = 0.0

    holder_count: int = 0
    holder_count_prev: int = 0
    holder_growth_pct: float = 0.0
    fresh_wallet_ratio: float = 0.0
    largest_wallet_pct: float = 0.0
    dev_wallet_pct: float = 0.0

    smart_money_count: int = 0
    smart_money_inflow_usd: float = 0.0
    smart_money_prev_inflow: float = 0.0

    top10_concentration_pct: float = 100.0
    bubblemaps_ok: bool = False
    insider_cluster_pct: float = 0.0
    connected_cluster_pct: float = 0.0

    honeypot_detected: bool = False
    sell_allowed: bool = True
    transfer_allowed: bool = True
    mint_enabled: bool = False
    freeze_enabled: bool = False
    lp_locked_pct: float = 0.0
    lp_burned: bool = False
    contract_verified: bool = False
    blacklist_function: bool = False
    proxy_risk: bool = False

    rug_risk_score: float = 0.0
    sniper_holdings_pct: float = 0.0
    sniper_cluster_pct: float = 0.0
    wash_trading: bool = False
    fake_volume: bool = False
    dev_dumping: bool = False

    is_pumpfun: bool = False
    pumpfun_graduated: bool = False
    pumpfun_lp_created: bool = False
    pumpfun_graduation_age_h: float = -1.0

    vwap: float = 0.0

    score: int = 0
    bonus_score: int = 0
    mania_score: int = 0
    tier: str = ""
    is_mania: bool = False
    alerted: bool = False
    alert_score: int = 0
    alert_mcap: float = 0.0
    alert_smart_money_inflow: float = 0.0

    hard_rejected: bool = False
    hard_reject_reason: str = ""
    security_checked: bool = False

    watchlist_until: float = 0.0

    last_updated: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)


class TokenStateEngine:
    def __init__(self):
        self._tokens: dict[str, TokenState] = {}
        self._lock = asyncio.Lock()
        self._event_queue: asyncio.Queue = asyncio.Queue()

    async def upsert(self, address: str, chain: str, **kwargs) -> tuple[TokenState, bool]:
        async with self._lock:
            key = f"{chain}:{address}"
            if key not in self._tokens:
                self._tokens[key] = TokenState(address=address, chain=chain)
            tok = self._tokens[key]

            changed = False
            for k, v in kwargs.items():
                if hasattr(tok, k) and getattr(tok, k) != v:
                    setattr(tok, k, v)
                    changed = True

            tok.last_updated = time.time()

            if tok.buys_24h > 0 or tok.sells_24h > 0:
                sells = tok.sells_24h if tok.sells_24h > 0 else 1
                tok.buy_sell_ratio = tok.buys_24h / sells

            if tok.holder_count_prev > 0 and tok.holder_count > tok.holder_count_prev:
                tok.holder_growth_pct = (
                    (tok.holder_count - tok.holder_count_prev) / tok.holder_count_prev
                ) * 100
            elif tok.holder_count_prev > 0 and tok.holder_count < tok.holder_count_prev:
                tok.holder_growth_pct = (
                    (tok.holder_count - tok.holder_count_prev) / tok.holder_count_prev
                ) * 100

            if tok.pair_created_at > 0:
                tok.age_hours = (time.time() - tok.pair_created_at) / 3600.0

            if tok.volume_1h_usd > 0 and tok.volume_6h_usd > 0:
                hourly_avg = tok.volume_6h_usd / 6
                if tok.volume_1h_usd > hourly_avg * 1.2:
                    tok.volume_trend = "increasing"
                elif tok.volume_1h_usd < hourly_avg * 0.8:
                    tok.volume_trend = "decreasing"
                else:
                    tok.volume_trend = "stable"

            return tok, changed

    async def get(self, address: str, chain: str) -> Optional[TokenState]:
        async with self._lock:
            return self._tokens.get(f"{chain}:{address}")

    async def all(self) -> list[TokenState]:
        async with self._lock:
            return list(self._tokens.values())

    async def count(self) -> int:
        async with self._lock:
            return len(self._tokens)

    async def watchlist(self) -> list[TokenState]:
        now = time.time()
        async with self._lock:
            return [t for t in self._tokens.values() if t.watchlist_until > now]

    async def remove_stale(self, max_age_hours: float = 96.0):
        cutoff = time.time() - max_age_hours * 3600
        async with self._lock:
            stale = [k for k, t in self._tokens.items() if t.last_updated < cutoff]
            for k in stale:
                del self._tokens[k]
        if stale:
            logger.info(f"Removed {len(stale)} stale tokens")

    def push_event(self, address: str, chain: str):
        try:
            self._event_queue.put_nowait((address, chain))
        except asyncio.QueueFull:
            pass

    async def pop_event(self) -> tuple[str, str]:
        return await self._event_queue.get()


engine = TokenStateEngine()
