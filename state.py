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

    market_cap_usd: float = 0.0
    liquidity_usd: float = 0.0
    volume_24h_usd: float = 0.0
    price_usd: float = 0.0
    price_change_24h: float = 0.0

    buys_24h: int = 0
    sells_24h: int = 0
    buy_sell_ratio: float = 0.0

    holder_count: int = 0
    holder_count_prev: int = 0
    holder_growth_pct: float = 0.0

    smart_money_count: int = 0
    smart_money_inflow_usd: float = 0.0

    top10_concentration_pct: float = 100.0
    bubblemaps_ok: bool = False

    score: int = 0
    alerted: bool = False
    alert_score: int = 0
    alert_mcap: float = 0.0

    last_updated: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)


class TokenStateEngine:
    _instance = None

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
                total = tok.buys_24h + tok.sells_24h
                tok.buy_sell_ratio = tok.buys_24h / total if total > 0 else 0

            if tok.holder_count_prev > 0 and tok.holder_count > 0:
                tok.holder_growth_pct = (
                    (tok.holder_count - tok.holder_count_prev) / tok.holder_count_prev
                ) * 100

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

    def push_event(self, address: str, chain: str):
        try:
            self._event_queue.put_nowait((address, chain))
        except asyncio.QueueFull:
            pass

    async def pop_event(self) -> tuple[str, str]:
        return await self._event_queue.get()


engine = TokenStateEngine()
