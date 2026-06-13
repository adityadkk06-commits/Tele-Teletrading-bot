import asyncio
import json
import logging
import time
import os
from dataclasses import dataclass, asdict, field
from typing import Optional
from config import ANALYTICS_FILE

logger = logging.getLogger(__name__)


@dataclass
class SignalRecord:
    address: str
    chain: str
    symbol: str
    score: int
    tier: str
    is_mania: bool
    mcap_at_alert: float
    liquidity_at_alert: float
    smart_money_at_alert: float
    alerted_at: float = field(default_factory=time.time)
    mcap_1h: float = 0.0
    mcap_6h: float = 0.0
    mcap_24h: float = 0.0
    return_1h: float = 0.0
    return_6h: float = 0.0
    return_24h: float = 0.0
    snapshot_1h_at: float = 0.0
    snapshot_6h_at: float = 0.0
    snapshot_24h_at: float = 0.0


class AnalyticsEngine:
    def __init__(self):
        self._signals: list[SignalRecord] = []
        self._lock = asyncio.Lock()
        self._load()

    def _load(self):
        if os.path.exists(ANALYTICS_FILE):
            try:
                with open(ANALYTICS_FILE, "r") as f:
                    data = json.load(f)
                self._signals = [SignalRecord(**d) for d in data]
                logger.info(f"Analytics: loaded {len(self._signals)} historical signals")
            except Exception as e:
                logger.warning(f"Analytics load error: {e}")

    def _save(self):
        try:
            with open(ANALYTICS_FILE, "w") as f:
                json.dump([asdict(s) for s in self._signals], f, indent=2)
        except Exception as e:
            logger.warning(f"Analytics save error: {e}")

    async def record_signal(self, address: str, chain: str, symbol: str,
                            score: int, tier: str, is_mania: bool,
                            mcap: float, liquidity: float, smart_money: float):
        async with self._lock:
            existing = next((s for s in self._signals
                             if s.address == address and s.chain == chain), None)
            if existing and (time.time() - existing.alerted_at) < 3600:
                return
            rec = SignalRecord(
                address=address, chain=chain, symbol=symbol,
                score=score, tier=tier, is_mania=is_mania,
                mcap_at_alert=mcap, liquidity_at_alert=liquidity,
                smart_money_at_alert=smart_money,
            )
            self._signals.append(rec)
            self._save()
            logger.info(f"Analytics: recorded signal {symbol} tier={tier} score={score}")

    async def update_snapshot(self, address: str, chain: str, current_mcap: float):
        now = time.time()
        async with self._lock:
            for rec in self._signals:
                if rec.address != address or rec.chain != chain:
                    continue
                elapsed = now - rec.alerted_at
                if elapsed >= 3600 and rec.snapshot_1h_at == 0:
                    rec.mcap_1h = current_mcap
                    rec.snapshot_1h_at = now
                    if rec.mcap_at_alert > 0:
                        rec.return_1h = ((current_mcap - rec.mcap_at_alert) / rec.mcap_at_alert) * 100
                if elapsed >= 21600 and rec.snapshot_6h_at == 0:
                    rec.mcap_6h = current_mcap
                    rec.snapshot_6h_at = now
                    if rec.mcap_at_alert > 0:
                        rec.return_6h = ((current_mcap - rec.mcap_at_alert) / rec.mcap_at_alert) * 100
                if elapsed >= 86400 and rec.snapshot_24h_at == 0:
                    rec.mcap_24h = current_mcap
                    rec.snapshot_24h_at = now
                    if rec.mcap_at_alert > 0:
                        rec.return_24h = ((current_mcap - rec.mcap_at_alert) / rec.mcap_at_alert) * 100
            self._save()

    async def get_stats(self) -> dict:
        async with self._lock:
            total = len(self._signals)
            if total == 0:
                return {"total_signals": 0}

            completed_24h = [s for s in self._signals if s.snapshot_24h_at > 0]
            if completed_24h:
                returns = [s.return_24h for s in completed_24h]
                winners = [r for r in returns if r > 0]
                win_rate = len(winners) / len(returns) * 100
                avg_return = sum(returns) / len(returns)
                best = max(returns)
                worst = min(returns)
                best_tok = next(s for s in completed_24h if s.return_24h == best)
                worst_tok = next(s for s in completed_24h if s.return_24h == worst)
            else:
                win_rate = avg_return = best = worst = 0.0
                best_tok = worst_tok = None

            tier_s = sum(1 for s in self._signals if s.tier == "S")
            tier_a = sum(1 for s in self._signals if s.tier == "A")
            mania = sum(1 for s in self._signals if s.is_mania)

            return {
                "total_signals": total,
                "tier_s": tier_s,
                "tier_a": tier_a,
                "mania": mania,
                "completed_24h": len(completed_24h),
                "win_rate": win_rate,
                "avg_return_24h": avg_return,
                "best_return": best,
                "worst_return": worst,
                "best_token": best_tok.symbol if best_tok else "",
                "worst_token": worst_tok.symbol if worst_tok else "",
            }

    async def recent_signals(self, limit: int = 10) -> list[SignalRecord]:
        async with self._lock:
            sorted_sigs = sorted(self._signals, key=lambda s: s.alerted_at, reverse=True)
            return sorted_sigs[:limit]


analytics = AnalyticsEngine()
