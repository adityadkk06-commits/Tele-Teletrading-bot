import logging
from state import TokenState
from config import FILTERS, SCORE_WEIGHTS

logger = logging.getLogger(__name__)


def score_market_cap(mcap: float) -> int:
    w = SCORE_WEIGHTS["market_cap"]
    if 500_000 <= mcap < 5_000_000:
        return w
    if 200_000 <= mcap < 500_000:
        return int(w * 0.75)
    if 100_000 <= mcap < 200_000:
        return int(w * 0.5)
    if 5_000_000 <= mcap < 20_000_000:
        return int(w * 0.7)
    if 20_000_000 <= mcap < 50_000_000:
        return int(w * 0.4)
    return 0


def score_liquidity(liq: float) -> int:
    w = SCORE_WEIGHTS["liquidity"]
    if liq >= 200_000:
        return w
    if liq >= 100_000:
        return int(w * 0.85)
    if liq >= 50_000:
        return int(w * 0.65)
    if liq >= 20_000:
        return int(w * 0.4)
    return 0


def score_volume(vol: float) -> int:
    w = SCORE_WEIGHTS["volume_24h"]
    if vol >= 1_000_000:
        return w
    if vol >= 500_000:
        return int(w * 0.9)
    if vol >= 200_000:
        return int(w * 0.75)
    if vol >= 50_000:
        return int(w * 0.5)
    return 0


def score_buy_sell_ratio(ratio: float) -> int:
    w = SCORE_WEIGHTS["buy_sell_ratio"]
    if ratio >= 2.5:
        return w
    if ratio >= 2.0:
        return int(w * 0.9)
    if ratio >= 1.5:
        return int(w * 0.7)
    if ratio >= 1.2:
        return int(w * 0.45)
    return 0


def score_holder_count(count: int) -> int:
    w = SCORE_WEIGHTS["holder_count"]
    if count >= 1000:
        return w
    if count >= 500:
        return int(w * 0.85)
    if count >= 200:
        return int(w * 0.65)
    if count >= 100:
        return int(w * 0.4)
    return 0


def score_holder_growth(growth_pct: float) -> int:
    w = SCORE_WEIGHTS["holder_growth"]
    if growth_pct >= 30:
        return w
    if growth_pct >= 20:
        return int(w * 0.85)
    if growth_pct >= 10:
        return int(w * 0.65)
    if growth_pct >= 5:
        return int(w * 0.4)
    return 0


def score_smart_money(count: int, inflow: float) -> int:
    w = SCORE_WEIGHTS["smart_money"]
    if count >= 5 or inflow >= 50_000:
        return w
    if count >= 3 or inflow >= 20_000:
        return int(w * 0.8)
    if count >= 1 or inflow >= 5_000:
        return int(w * 0.5)
    return 0


def score_concentration(top10_pct: float) -> int:
    w = SCORE_WEIGHTS["concentration"]
    if top10_pct <= 20:
        return w
    if top10_pct <= 30:
        return int(w * 0.85)
    if top10_pct <= 45:
        return int(w * 0.6)
    if top10_pct <= 60:
        return int(w * 0.3)
    return 0


def compute_score(tok: TokenState) -> int:
    total = 0
    total += score_market_cap(tok.market_cap_usd)
    total += score_liquidity(tok.liquidity_usd)
    total += score_volume(tok.volume_24h_usd)
    total += score_buy_sell_ratio(tok.buy_sell_ratio)
    total += score_holder_count(tok.holder_count)
    total += score_holder_growth(tok.holder_growth_pct)
    total += score_smart_money(tok.smart_money_count, tok.smart_money_inflow_usd)
    total += score_concentration(tok.top10_concentration_pct)
    return min(100, total)


def passes_security_filters(tok: TokenState) -> tuple[bool, list[str]]:
    fails = []
    f = FILTERS
    if tok.liquidity_usd < f["min_liquidity_usd"]:
        fails.append(f"Low liquidity (${tok.liquidity_usd:,.0f})")
    if tok.volume_24h_usd < f["min_volume_24h_usd"]:
        fails.append(f"Low volume (${tok.volume_24h_usd:,.0f})")
    if tok.market_cap_usd < f["min_market_cap_usd"]:
        fails.append(f"MCap too low (${tok.market_cap_usd:,.0f})")
    if tok.market_cap_usd > f["max_market_cap_usd"]:
        fails.append(f"MCap too high (${tok.market_cap_usd:,.0f})")
    if tok.buy_sell_ratio < f["min_buy_sell_ratio"] and (tok.buys_24h + tok.sells_24h) > 0:
        fails.append(f"Low B/S ratio ({tok.buy_sell_ratio:.2f})")
    if tok.holder_count > 0 and tok.holder_count < f["min_holder_count"]:
        fails.append(f"Few holders ({tok.holder_count})")
    if tok.top10_concentration_pct > f["max_top10_concentration_pct"]:
        fails.append(f"High concentration ({tok.top10_concentration_pct:.1f}%)")
    return len(fails) == 0, fails
