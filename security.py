import logging
from state import TokenState
from config import FILTERS

logger = logging.getLogger(__name__)


def hard_reject(tok: TokenState) -> tuple[bool, str]:
    """
    Run hard-reject checks. Returns (rejected, reason).
    If rejected, no score calculation should happen.
    """
    if tok.honeypot_detected:
        return True, "Honeypot detected"

    if not tok.sell_allowed:
        return True, "Sell blocked"

    if not tok.transfer_allowed:
        return True, "Transfer blocked"

    if tok.mint_enabled:
        return True, "Mint enabled"

    if tok.freeze_enabled:
        return True, "Freeze enabled"

    lp_ok = tok.lp_locked_pct >= 90 or tok.lp_burned
    if not lp_ok and tok.security_checked:
        return True, "LP not locked/burned"

    if tok.insider_cluster_pct > FILTERS["max_insider_cluster_pct"]:
        return True, f"Insider cluster {tok.insider_cluster_pct:.1f}%"

    if tok.connected_cluster_pct > FILTERS["max_connected_cluster_pct"]:
        return True, f"Connected wallet cluster {tok.connected_cluster_pct:.1f}%"

    if tok.dev_dumping:
        return True, "Dev dumping detected"

    if tok.dev_wallet_pct > 20:
        return True, f"Dev sold >20% (currently {tok.dev_wallet_pct:.1f}%)"

    if tok.sniper_cluster_pct > FILTERS["max_sniper_cluster_pct"]:
        return True, f"Sniper cluster {tok.sniper_cluster_pct:.1f}%"

    if tok.sniper_holdings_pct > FILTERS["max_sniper_holdings_pct"]:
        return True, f"Sniper holdings {tok.sniper_holdings_pct:.1f}%"

    if tok.wash_trading:
        return True, "Wash trading detected"

    if tok.fake_volume:
        return True, "Fake volume detected"

    if tok.blacklist_function:
        return True, "Blacklist function in contract"

    if tok.proxy_risk:
        return True, "Proxy upgrade risk"

    if tok.rug_risk_score > FILTERS["max_rug_risk_score"]:
        return True, f"Rug risk score {tok.rug_risk_score:.0f}"

    return False, ""


def passes_age_filter(tok: TokenState) -> tuple[bool, str]:
    from config import MIN_TOKEN_AGE_HOURS, MAX_TOKEN_AGE_HOURS
    if tok.age_hours < 0:
        return True, ""
    if tok.age_hours < MIN_TOKEN_AGE_HOURS:
        return False, f"Too new ({tok.age_hours * 60:.0f}m old)"
    if tok.age_hours > MAX_TOKEN_AGE_HOURS:
        return False, f"Too old ({tok.age_hours:.1f}h)"
    return True, ""


def passes_anti_fomo(tok: TokenState) -> tuple[bool, str]:
    f = FILTERS
    if tok.price_change_24h > f["max_gain_24h_pct"]:
        return False, f"24H pump {tok.price_change_24h:.0f}% (FOMO)"
    if tok.price_change_6h > f["max_gain_6h_pct"]:
        return False, f"6H pump {tok.price_change_6h:.0f}% (FOMO)"
    if tok.vwap > 0 and tok.price_usd > 0:
        above_vwap_pct = ((tok.price_usd - tok.vwap) / tok.vwap) * 100
        if above_vwap_pct > f["max_price_above_vwap_pct"]:
            return False, f"Price {above_vwap_pct:.0f}% above VWAP"
    return True, ""


def passes_token_filters(tok: TokenState) -> tuple[bool, list[str]]:
    """All soft filters — returns (passes, list_of_failures)."""
    fails = []
    f = FILTERS

    age_ok, age_msg = passes_age_filter(tok)
    if not age_ok:
        fails.append(age_msg)

    fomo_ok, fomo_msg = passes_anti_fomo(tok)
    if not fomo_ok:
        fails.append(fomo_msg)

    from config import CHAIN_MIN_LIQUIDITY
    min_liq = CHAIN_MIN_LIQUIDITY.get(tok.chain, f["min_liquidity_usd"])
    if tok.liquidity_usd < min_liq:
        fails.append(f"Low liquidity ${tok.liquidity_usd:,.0f} (min ${min_liq:,.0f})")

    if tok.market_cap_usd > 0 and tok.liquidity_usd > 0:
        liq_mc = tok.liquidity_usd / tok.market_cap_usd
        if liq_mc < f["liq_mc_ratio_min"]:
            fails.append(f"Liq/MC {liq_mc:.1%} < 10%")

    if tok.market_cap_usd < f["min_market_cap_usd"]:
        fails.append(f"MCap ${tok.market_cap_usd:,.0f} < ${f['min_market_cap_usd']:,.0f}")
    if tok.market_cap_usd > f["max_market_cap_usd"]:
        fails.append(f"MCap ${tok.market_cap_usd:,.0f} > ${f['max_market_cap_usd']:,.0f}")

    if tok.holder_count > 0 and tok.holder_count < f["min_holder_count"]:
        fails.append(f"Holders {tok.holder_count} < {f['min_holder_count']}")

    if tok.market_cap_usd > 0:
        vol_mc = tok.volume_24h_usd / tok.market_cap_usd
        if vol_mc < f["min_volume_mc_ratio"]:
            fails.append(f"Vol/MC {vol_mc:.2f} < {f['min_volume_mc_ratio']}")

    if (tok.buys_24h + tok.sells_24h) > 0:
        if tok.buy_sell_ratio < f["min_buy_sell_ratio"]:
            fails.append(f"B/S ratio {tok.buy_sell_ratio:.2f} < {f['min_buy_sell_ratio']}")

    if tok.fresh_wallet_ratio > 0 and tok.fresh_wallet_ratio < f["min_fresh_wallet_ratio"]:
        fails.append(f"Fresh wallets {tok.fresh_wallet_ratio:.1%} < 15%")

    if tok.largest_wallet_pct > f["max_largest_wallet_pct"]:
        fails.append(f"Largest wallet {tok.largest_wallet_pct:.1f}% > 8%")

    if tok.top10_concentration_pct > f["max_top10_concentration_pct"]:
        fails.append(f"Top10 concentration {tok.top10_concentration_pct:.1f}% > 30%")

    if tok.dev_wallet_pct > f["max_dev_wallet_pct"]:
        fails.append(f"Dev wallet {tok.dev_wallet_pct:.1f}% > 5%")

    if tok.unique_traders_24h > 0 and tok.unique_traders_24h < f["min_unique_traders_24h"]:
        fails.append(f"Unique traders {tok.unique_traders_24h} < 50")

    if tok.holder_growth_pct < 0 and tok.holder_count_prev > 0:
        fails.append("Holder growth negative")

    if tok.smart_money_inflow_usd < 0:
        fails.append("Smart money flow negative")

    return len(fails) == 0, fails
