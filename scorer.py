import logging
from state import TokenState
from config import FILTERS, SCORE_WEIGHTS, BONUS_SCORES, MANIA

logger = logging.getLogger(__name__)


# ─── Component scorers ───────────────────────────────────────────────────────

def score_buy_pressure(tok: TokenState) -> int:
    """Buy Pressure: 25pts — based on buy/sell ratio + buy count momentum."""
    w = SCORE_WEIGHTS["buy_pressure"]
    ratio = tok.buy_sell_ratio
    buys = tok.buys_24h

    if ratio >= 3.0 and buys >= 500:
        return w
    if ratio >= 2.5 and buys >= 200:
        return int(w * 0.90)
    if ratio >= 2.0 and buys >= 100:
        return int(w * 0.80)
    if ratio >= 1.5:
        return int(w * 0.65)
    if ratio >= 1.2:
        return int(w * 0.45)
    if ratio >= 1.1:
        return int(w * 0.25)
    return 0


def score_holder_growth(tok: TokenState) -> int:
    """Holder Growth: 20pts."""
    w = SCORE_WEIGHTS["holder_growth"]
    g = tok.holder_growth_pct
    if g >= 30:
        return w
    if g >= 20:
        return int(w * 0.85)
    if g >= 10:
        return int(w * 0.65)
    if g >= 5:
        return int(w * 0.40)
    if g > 0:
        return int(w * 0.20)
    return 0


def score_fresh_wallets(tok: TokenState) -> int:
    """Fresh Wallets: 15pts."""
    w = SCORE_WEIGHTS["fresh_wallets"]
    r = tok.fresh_wallet_ratio
    if r >= 0.50:
        return w
    if r >= 0.40:
        return int(w * 0.85)
    if r >= 0.30:
        return int(w * 0.70)
    if r >= 0.20:
        return int(w * 0.50)
    if r >= 0.15:
        return int(w * 0.25)
    if r == 0:
        return int(w * 0.30)
    return 0


def score_volume_quality(tok: TokenState) -> int:
    """Volume Quality: 15pts — Vol/MC ratio + unique traders + trend."""
    w = SCORE_WEIGHTS["volume_quality"]
    mc = tok.market_cap_usd
    vol_mc = (tok.volume_24h_usd / mc) if mc > 0 else 0
    traders = tok.unique_traders_24h
    trend = tok.volume_trend

    if vol_mc >= 3.0:
        base = w
    elif vol_mc >= 2.0:
        base = int(w * 0.85)
    elif vol_mc >= 1.0:
        base = int(w * 0.70)
    elif vol_mc >= 0.5:
        base = int(w * 0.50)
    else:
        base = 0

    trader_bonus = 0
    if traders >= 500:
        trader_bonus = 2
    elif traders >= 200:
        trader_bonus = 1

    trend_penalty = -2 if trend == "decreasing" else 0

    return max(0, min(w, base + trader_bonus + trend_penalty))


def score_smart_money(tok: TokenState) -> int:
    """Smart Money: 10pts."""
    w = SCORE_WEIGHTS["smart_money"]
    count = tok.smart_money_count
    inflow = tok.smart_money_inflow_usd
    if count >= 10 or inflow >= 100_000:
        return w
    if count >= 5 or inflow >= 50_000:
        return int(w * 0.80)
    if count >= 3 or inflow >= 20_000:
        return int(w * 0.60)
    if count >= 1 or inflow >= 5_000:
        return int(w * 0.35)
    return 0


def score_liquidity_quality(tok: TokenState) -> int:
    """Liquidity Quality: 10pts — absolute liq + liq/mc ratio."""
    w = SCORE_WEIGHTS["liquidity_quality"]
    liq = tok.liquidity_usd
    mc  = tok.market_cap_usd
    liq_mc = (liq / mc) if mc > 0 else 0

    if liq >= 500_000:
        liq_score = w
    elif liq >= 200_000:
        liq_score = int(w * 0.85)
    elif liq >= 100_000:
        liq_score = int(w * 0.70)
    elif liq >= 50_000:
        liq_score = int(w * 0.50)
    else:
        liq_score = 0

    ratio_bonus = 2 if liq_mc >= 0.25 else (1 if liq_mc >= 0.15 else 0)
    return min(w, liq_score + ratio_bonus)


def score_narrative_strength(tok: TokenState) -> int:
    """Narrative Strength: 5pts — Pump.fun graduation, trending signals."""
    w = SCORE_WEIGHTS["narrative_strength"]
    pts = 0
    if tok.pumpfun_graduated:
        pts += 3
        if 0 <= tok.pumpfun_graduation_age_h <= 12:
            pts += 2
    elif tok.pumpfun_lp_created:
        pts += 2
    return min(w, pts)


def compute_bonus_score(tok: TokenState) -> int:
    """Bonus points on top of base score."""
    bonus = 0
    b = BONUS_SCORES

    if tok.smart_money_count >= 3:
        bonus += b["smart_wallet_entry"]

    if tok.fresh_wallet_ratio >= 0.30:
        bonus += b["fresh_wallet_30pct"]

    if tok.holder_growth_pct >= 10:
        bonus += b["holder_growth_10pct"]

    mc = tok.market_cap_usd
    if mc > 0 and (tok.volume_24h_usd / mc) >= 2.0:
        bonus += b["volume_mc_2x"]

    if tok.market_cap_prev > 0:
        mc_growth = ((mc - tok.market_cap_prev) / tok.market_cap_prev) * 100
        if mc_growth >= 30:
            bonus += b["mc_growth_30pct"]

    if tok.pumpfun_graduated:
        bonus += b["pumpfun_graduated"]

    if tok.buy_sell_ratio >= 2.0:
        bonus += b["buy_sell_2x"]

    return bonus


def compute_mania_check(tok: TokenState) -> tuple[bool, int]:
    """Returns (is_mania, mania_bonus). Mania requires all conditions pass."""
    m = MANIA
    if tok.age_hours > 0 and tok.age_hours > m["max_age_hours"]:
        return False, 0
    if tok.market_cap_usd > m["max_market_cap_usd"]:
        return False, 0
    if tok.holder_growth_pct < m["min_holder_growth_pct"]:
        return False, 0
    if tok.fresh_wallet_ratio > 0 and tok.fresh_wallet_ratio < m["min_fresh_wallet_ratio"]:
        return False, 0
    mc = tok.market_cap_usd
    if mc > 0 and (tok.volume_24h_usd / mc) < m["min_volume_mc_ratio"]:
        return False, 0
    if tok.buy_sell_ratio < m["min_buy_sell_ratio"]:
        return False, 0
    if not tok.bubblemaps_ok and tok.security_checked:
        return False, 0
    return True, m["mania_bonus_score"]


def compute_score(tok: TokenState) -> tuple[int, int, bool, int]:
    """
    Returns (final_score, base_score, is_mania, mania_bonus).
    Hard rejects must be checked before calling this.
    """
    base = 0
    base += score_buy_pressure(tok)
    base += score_holder_growth(tok)
    base += score_fresh_wallets(tok)
    base += score_volume_quality(tok)
    base += score_smart_money(tok)
    base += score_liquidity_quality(tok)
    base += score_narrative_strength(tok)
    base = min(100, base)

    bonus = compute_bonus_score(tok)
    is_mania, mania_bonus = compute_mania_check(tok)

    total = min(100, base + bonus + mania_bonus)
    return total, base, is_mania, mania_bonus


def assign_tier(score: int) -> str:
    from config import TIER_S_THRESHOLD, TIER_A_THRESHOLD, TIER_B_THRESHOLD
    if score >= TIER_S_THRESHOLD:
        return "S"
    if score >= TIER_A_THRESHOLD:
        return "A"
    if score >= TIER_B_THRESHOLD:
        return "B"
    return ""
