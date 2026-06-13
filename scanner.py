import asyncio
import logging
import time
from telegram import Bot

import fetchers as f
from state import TokenStateEngine, TokenState, engine
from scorer import compute_score, assign_tier
from security import hard_reject, passes_token_filters
from alerts import should_alert, send_alert, send_status_message
from analytics import analytics
from config import (
    TELEGRAM_CHAT_ID,
    DEXSCREENER_POLL_INTERVAL,
    CHAINS,
    SCORE_THRESHOLD,
    TIER_B_THRESHOLD,
    WATCHLIST_DURATION_HOURS,
)

logger = logging.getLogger(__name__)

_bot: Bot = None
_seen_dex_pairs: set[str] = set()

CHAIN_MAP_DEX = {c: c for c in ["solana", "bsc", "ethereum", "base"]}


# ─── Core evaluation ─────────────────────────────────────────────────────────

async def evaluate_and_alert(tok: TokenState):
    import config
    chat_id = config.TELEGRAM_CHAT_ID

    if tok.hard_rejected:
        return

    rejected, reason = hard_reject(tok)
    if rejected:
        tok.hard_rejected = True
        tok.hard_reject_reason = reason
        logger.debug(f"[REJECT] {tok.symbol or tok.address[:8]} — {reason}")
        return

    final, base, is_mania, mania_bonus = compute_score(tok)
    tok.score = final
    tok.bonus_score = base
    tok.is_mania = is_mania
    tok.mania_score = mania_bonus
    tok.tier = assign_tier(final)

    passes, fails = passes_token_filters(tok)

    if final >= TIER_B_THRESHOLD and passes:
        if final >= SCORE_THRESHOLD:
            do_alert, reason_str = should_alert(tok, final)
            if do_alert and _bot and chat_id:
                await send_alert(_bot, chat_id, tok, final, reason_str, tok.tier)
                tok.alerted = True
                tok.alert_score = final
                tok.alert_mcap = tok.market_cap_usd
                tok.alert_smart_money_inflow = tok.smart_money_inflow_usd
                tok.watchlist_until = time.time() + WATCHLIST_DURATION_HOURS * 3600
                await analytics.record_signal(
                    address=tok.address, chain=tok.chain, symbol=tok.symbol,
                    score=final, tier=tok.tier, is_mania=is_mania,
                    mcap=tok.market_cap_usd, liquidity=tok.liquidity_usd,
                    smart_money=tok.smart_money_inflow_usd,
                )
            elif do_alert:
                logger.info(f"[SIGNAL Tier{tok.tier}] {tok.symbol} score={final} — no chat_id")
        else:
            logger.debug(
                f"[TIER B] {tok.symbol} score={final} — watchlist only"
            )
    elif final >= TIER_B_THRESHOLD:
        logger.debug(
            f"[NEAR Tier{tok.tier}] {tok.symbol} score={final} fails={fails[:2]}"
        )


# ─── Security enrichment ─────────────────────────────────────────────────────

async def enrich_security(address: str, chain: str):
    tok = await engine.get(address, chain)
    if not tok or tok.security_checked:
        return

    updates = {}

    if chain == "solana":
        rc = await f.rugcheck_report(address)
        if rc:
            parsed = f.parse_rugcheck(rc)
            updates.update(parsed)
    else:
        hp = await f.honeypot_check(address, chain)
        if hp:
            parsed = f.parse_honeypot(hp)
            updates.update(parsed)

    gp = await f.goplus_token_security(address, chain)
    if gp:
        parsed = f.parse_goplus(gp)
        for k, v in parsed.items():
            if k not in updates or not updates.get(k):
                updates[k] = v

    if chain == "solana":
        pf = await f.pumpfun_token(address)
        if pf:
            parsed = f.parse_pumpfun(pf)
            updates.update(parsed)

    updates["security_checked"] = True
    await engine.upsert(address, chain, **updates)
    tok = await engine.get(address, chain)
    if tok:
        await evaluate_and_alert(tok)


async def enrich_from_birdeye(address: str, chain: str):
    tok = await engine.get(address, chain)
    if not tok:
        return

    overview = await f.birdeye_token_overview(address, chain)
    if overview:
        updates = {}
        hc = int(overview.get("holder") or 0)
        if hc:
            prev = tok.holder_count
            if prev and prev != hc:
                updates["holder_count_prev"] = prev
            updates["holder_count"] = hc
        mc_prev = tok.market_cap_usd
        if mc_prev > 0:
            updates["market_cap_prev"] = mc_prev
        await engine.upsert(address, chain, **updates)

    smart = await f.birdeye_smart_money(address, chain)
    if smart:
        items = smart.get("items", []) or []
        inflow = sum(float(t.get("volume", 0) or 0) for t in items)
        prev_inflow = tok.smart_money_inflow_usd
        await engine.upsert(
            address, chain,
            smart_money_count=len(items),
            smart_money_inflow_usd=inflow,
            smart_money_prev_inflow=prev_inflow,
        )

    tok = await engine.get(address, chain)
    if tok:
        await evaluate_and_alert(tok)


async def enrich_from_gmgn(address: str, chain: str):
    tok = await engine.get(address, chain)
    if not tok:
        return

    info = await f.gmgn_token_info(address, chain)
    if info:
        hc = int(info.get("holder_count") or info.get("holders") or 0)
        if hc:
            prev = tok.holder_count
            upd = {"holder_count": hc}
            if prev and prev != hc:
                upd["holder_count_prev"] = prev
            await engine.upsert(address, chain, **upd)

    smart = await f.gmgn_smart_money(address, chain)
    if smart:
        traders = smart.get("traders", []) or (smart if isinstance(smart, list) else [])
        inflow = sum(
            float(t.get("inflow_usd", 0) or t.get("buy_volume", 0) or 0)
            for t in traders
        )
        await engine.upsert(
            address, chain,
            smart_money_count=len(traders),
            smart_money_inflow_usd=inflow,
        )

    fresh = await f.gmgn_fresh_wallets(address, chain)
    if fresh:
        ratio = float(
            fresh.get("fresh_wallet_ratio") or
            fresh.get("fresh_ratio") or
            fresh.get("ratio") or 0
        )
        if ratio > 0:
            await engine.upsert(address, chain, fresh_wallet_ratio=ratio)

    tok = await engine.get(address, chain)
    if tok:
        await evaluate_and_alert(tok)


async def enrich_from_bubblemaps(address: str, chain: str):
    bm_chain = {"solana": "sol", "ethereum": "eth", "bsc": "bsc", "base": "base"}.get(chain, "sol")
    data = await f.bubblemaps_token(address, bm_chain)
    parsed = f.parse_bubblemaps(data)
    await engine.upsert(
        address, chain,
        top10_concentration_pct=parsed["top10_pct"],
        bubblemaps_ok=parsed["ok"],
        insider_cluster_pct=parsed["insider_cluster_pct"],
        connected_cluster_pct=parsed["connected_cluster_pct"],
        largest_wallet_pct=parsed["largest_wallet_pct"],
    )
    tok = await engine.get(address, chain)
    if tok:
        await evaluate_and_alert(tok)


# ─── DEX Screener processing ─────────────────────────────────────────────────

async def process_dexscreener_pair(pair_raw: dict):
    parsed = f.parse_dexscreener_pair(pair_raw)
    address = parsed.get("token_address", "")
    chain   = parsed.get("chain", "").lower()

    if not address or chain not in CHAIN_MAP_DEX:
        return

    age = parsed.get("age_hours", -1)
    if age is not None and age > 0:
        from config import MIN_TOKEN_AGE_HOURS, MAX_TOKEN_AGE_HOURS
        if age < MIN_TOKEN_AGE_HOURS or age > MAX_TOKEN_AGE_HOURS:
            return

    mc = parsed.get("market_cap_usd", 0)
    from config import FILTERS
    if mc > 0 and (mc < FILTERS["min_market_cap_usd"] * 0.5 or mc > FILTERS["max_market_cap_usd"] * 2):
        return

    tok, _ = await engine.upsert(
        address, chain,
        symbol=parsed["symbol"],
        name=parsed["name"],
        pair_address=parsed["pair_address"],
        dex_url=parsed["dex_url"],
        price_usd=parsed["price_usd"],
        price_change_24h=parsed["price_change_24h"],
        price_change_6h=parsed["price_change_6h"],
        price_change_1h=parsed["price_change_1h"],
        market_cap_usd=parsed["market_cap_usd"],
        liquidity_usd=parsed["liquidity_usd"],
        volume_24h_usd=parsed["volume_24h_usd"],
        volume_6h_usd=parsed["volume_6h_usd"],
        volume_1h_usd=parsed["volume_1h_usd"],
        buys_24h=parsed["buys_24h"],
        sells_24h=parsed["sells_24h"],
        pair_created_at=parsed["pair_created_at"],
    )

    await evaluate_and_alert(tok)

    asyncio.create_task(enrich_security(address, chain))
    asyncio.create_task(enrich_from_birdeye(address, chain))
    asyncio.create_task(enrich_from_gmgn(address, chain))
    asyncio.create_task(enrich_from_bubblemaps(address, chain))


# ─── Polling loops ────────────────────────────────────────────────────────────

async def poll_dexscreener_latest():
    logger.info("DEX Screener latest poller started")
    while True:
        try:
            tokens = await f.dexscreener_latest_tokens()
            for profile in tokens:
                token_address = profile.get("tokenAddress", "")
                chain_id      = profile.get("chainId", "").lower()
                if not token_address or chain_id not in CHAINS:
                    continue
                pairs = await f.dexscreener_token_pairs(chain_id, token_address)
                for pair in pairs:
                    pair_addr = pair.get("pairAddress", "")
                    if pair_addr and pair_addr not in _seen_dex_pairs:
                        _seen_dex_pairs.add(pair_addr)
                        asyncio.create_task(process_dexscreener_pair(pair))

            boosted = await f.dexscreener_boosted_tokens()
            for profile in boosted:
                token_address = profile.get("tokenAddress", "")
                chain_id      = profile.get("chainId", "").lower()
                if not token_address or chain_id not in CHAINS:
                    continue
                pairs = await f.dexscreener_token_pairs(chain_id, token_address)
                for pair in pairs:
                    pair_addr = pair.get("pairAddress", "")
                    if pair_addr and pair_addr not in _seen_dex_pairs:
                        _seen_dex_pairs.add(pair_addr)
                        asyncio.create_task(process_dexscreener_pair(pair))

        except Exception as e:
            logger.error(f"DEX Screener latest error: {e}")
        await asyncio.sleep(DEXSCREENER_POLL_INTERVAL)


async def poll_dexscreener_hot():
    logger.info("DEX Screener hot pairs poller started")
    queries = ["trending", "new", "pump", "moon", "gem", "meme", "pepe", "doge"]
    idx = 0
    while True:
        try:
            query = queries[idx % len(queries)]
            pairs = await f.dexscreener_search(query)
            for pair in pairs:
                pair_addr = pair.get("pairAddress", "")
                chain_id  = pair.get("chainId", "").lower()
                if chain_id not in CHAINS:
                    continue
                if pair_addr and pair_addr not in _seen_dex_pairs:
                    _seen_dex_pairs.add(pair_addr)
                    asyncio.create_task(process_dexscreener_pair(pair))
            idx += 1
        except Exception as e:
            logger.error(f"DEX Screener hot error: {e}")
        await asyncio.sleep(DEXSCREENER_POLL_INTERVAL * 2)


async def refresh_known_tokens():
    logger.info("Token refresh loop started")
    while True:
        await asyncio.sleep(30)
        try:
            all_toks = await engine.all()
            now = time.time()
            for tok in all_toks:
                if tok.hard_rejected:
                    continue
                if now - tok.last_updated < 25:
                    continue
                if not tok.pair_address and not tok.address:
                    continue
                pairs = await f.dexscreener_token_pairs(tok.chain, tok.address)
                if pairs:
                    asyncio.create_task(process_dexscreener_pair(pairs[0]))
                    if tok.alerted and tok.alert_mcap > 0:
                        await analytics.update_snapshot(tok.address, tok.chain, tok.market_cap_usd)
                await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Token refresh error: {e}")


async def watchlist_monitor():
    """Re-evaluate and track watchlisted tokens every 60s."""
    logger.info("Watchlist monitor started")
    while True:
        await asyncio.sleep(60)
        try:
            wl_toks = await engine.watchlist()
            for tok in wl_toks:
                pairs = await f.dexscreener_token_pairs(tok.chain, tok.address)
                if pairs:
                    parsed = f.parse_dexscreener_pair(pairs[0])
                    await engine.upsert(
                        tok.address, tok.chain,
                        market_cap_usd=parsed["market_cap_usd"],
                        liquidity_usd=parsed["liquidity_usd"],
                        volume_24h_usd=parsed["volume_24h_usd"],
                        buy_sell_ratio=parsed["buy_sell_ratio"],
                        buys_24h=parsed["buys_24h"],
                        sells_24h=parsed["sells_24h"],
                    )
                    await analytics.update_snapshot(tok.address, tok.chain, parsed["market_cap_usd"])
                    updated = await engine.get(tok.address, tok.chain)
                    if updated:
                        await evaluate_and_alert(updated)
                await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Watchlist monitor error: {e}")


async def mania_scanner():
    """Dedicated mania scanner — fires on ultra-early explosions."""
    logger.info("Mania scanner started")
    while True:
        await asyncio.sleep(20)
        try:
            all_toks = await engine.all()
            for tok in all_toks:
                if tok.hard_rejected or tok.is_mania:
                    continue
                from scorer import compute_mania_check
                is_mania, _ = compute_mania_check(tok)
                if is_mania and tok.score > 0:
                    final, base, im, mb = compute_score(tok)
                    tok.score = final
                    tok.is_mania = im
                    tok.mania_score = mb
                    tok.tier = assign_tier(final)
                    if final >= SCORE_THRESHOLD:
                        do_alert, reason = should_alert(tok, final)
                        if do_alert and _bot:
                            import config
                            chat_id = config.TELEGRAM_CHAT_ID
                            if chat_id:
                                await send_alert(_bot, chat_id, tok, final, reason, tok.tier)
                                tok.alerted = True
                                tok.alert_score = final
                                tok.alert_mcap = tok.market_cap_usd
                                tok.alert_smart_money_inflow = tok.smart_money_inflow_usd
                                tok.watchlist_until = time.time() + WATCHLIST_DURATION_HOURS * 3600
        except Exception as e:
            logger.error(f"Mania scanner error: {e}")


async def cleanup_loop():
    while True:
        await asyncio.sleep(3600)
        await engine.remove_stale(max_age_hours=96)


async def stats_logger():
    while True:
        await asyncio.sleep(120)
        try:
            count = await engine.count()
            all_toks = await engine.all()
            alerted = sum(1 for t in all_toks if t.alerted)
            tier_s  = sum(1 for t in all_toks if t.tier == "S")
            tier_a  = sum(1 for t in all_toks if t.tier == "A")
            tier_b  = sum(1 for t in all_toks if t.tier == "B")
            mania   = sum(1 for t in all_toks if t.is_mania)
            rejected = sum(1 for t in all_toks if t.hard_rejected)
            logger.info(
                f"[STATS] Tracked:{count} | Alerts:{alerted} | "
                f"S:{tier_s} A:{tier_a} B:{tier_b} | "
                f"Mania:{mania} | Rejected:{rejected} | "
                f"Pairs seen:{len(_seen_dex_pairs)}"
            )
        except Exception as e:
            logger.debug(f"Stats error: {e}")


async def run_scanner(bot: Bot):
    global _bot
    _bot = bot

    import config
    chat_id = config.TELEGRAM_CHAT_ID

    logger.info("Starting MEME GEM HUNTER PRO V5...")
    await send_status_message(bot, chat_id, "started")

    retry = 0
    while True:
        try:
            await asyncio.gather(
                poll_dexscreener_latest(),
                poll_dexscreener_hot(),
                refresh_known_tokens(),
                watchlist_monitor(),
                mania_scanner(),
                cleanup_loop(),
                stats_logger(),
            )
        except Exception as e:
            retry += 1
            logger.error(f"Scanner crash (attempt {retry}): {e}", exc_info=True)
            await send_status_message(bot, chat_id, "error", str(e))
            await asyncio.sleep(min(30 * retry, 300))
            logger.info("Scanner restarting...")
            await send_status_message(bot, chat_id, "restarted")
