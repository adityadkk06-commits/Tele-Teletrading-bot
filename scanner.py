import asyncio
import logging
import time
from telegram import Bot

import fetchers as f
from state import TokenStateEngine, TokenState
from scorer import compute_score, passes_security_filters
from alerts import should_alert, send_alert
from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    DEXSCREENER_POLL_INTERVAL,
    BIRDEYE_POLL_INTERVAL,
    GMGN_POLL_INTERVAL,
    SCORE_THRESHOLD,
    CHAINS,
)

logger = logging.getLogger(__name__)

engine = TokenStateEngine()
_bot: Bot = None

_seen_dex_pairs: set[str] = set()

CHAIN_MAP_DEX = {
    "solana": "solana",
    "ethereum": "ethereum",
    "bsc": "bsc",
    "base": "base",
}


async def evaluate_and_alert(tok: TokenState):
    score = compute_score(tok)
    tok.score = score
    passes, fails = passes_security_filters(tok)

    if score >= SCORE_THRESHOLD and passes:
        do_alert, reason = should_alert(tok, score)
        if do_alert and _bot and TELEGRAM_CHAT_ID:
            await send_alert(_bot, TELEGRAM_CHAT_ID, tok, score, reason, fails)
            tok.alerted = True
            tok.alert_score = score
            tok.alert_mcap = tok.market_cap_usd
        elif do_alert:
            logger.info(
                f"[SIGNAL] {tok.symbol} score={score} — no chat_id configured"
            )
    else:
        if score >= 70:
            logger.debug(
                f"[NEAR SIGNAL] {tok.symbol} score={score} — {'filtered: ' + ', '.join(fails) if fails else 'below threshold'}"
            )


async def enrich_from_birdeye(address: str, chain: str):
    tok = await engine.get(address, chain)
    if not tok:
        return

    overview = await f.birdeye_token_overview(address, chain)
    if overview:
        holder_count = overview.get("holder") or 0
        await engine.upsert(
            address, chain,
            holder_count=int(holder_count),
        )

    smart = await f.birdeye_smart_money(address, chain)
    if smart:
        items = smart.get("items", []) or []
        inflow = sum(float(t.get("volume", 0) or 0) for t in items)
        await engine.upsert(
            address, chain,
            smart_money_count=len(items),
            smart_money_inflow_usd=inflow,
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
        holder_count = info.get("holder_count") or info.get("holders") or 0
        if holder_count:
            await engine.upsert(address, chain, holder_count=int(holder_count))

    smart = await f.gmgn_smart_money(address, chain)
    if smart:
        traders = smart.get("traders", []) or (smart if isinstance(smart, list) else [])
        inflow = sum(float(t.get("inflow_usd", 0) or t.get("buy_volume", 0) or 0) for t in traders)
        await engine.upsert(
            address, chain,
            smart_money_count=len(traders),
            smart_money_inflow_usd=inflow,
        )

    tok = await engine.get(address, chain)
    if tok:
        await evaluate_and_alert(tok)


async def enrich_from_bubblemaps(address: str, chain: str):
    chain_map = {"solana": "sol", "ethereum": "eth", "bsc": "bsc", "base": "base"}
    c = chain_map.get(chain, "sol")
    data = await f.bubblemaps_token(address, c)
    parsed = f.parse_bubblemaps(data)

    await engine.upsert(
        address, chain,
        top10_concentration_pct=parsed["top10_pct"],
        bubblemaps_ok=parsed["ok"],
    )

    tok = await engine.get(address, chain)
    if tok:
        await evaluate_and_alert(tok)


async def process_dexscreener_pair(pair_raw: dict):
    parsed = f.parse_dexscreener_pair(pair_raw)
    address = parsed.get("token_address", "")
    chain = parsed.get("chain", "")

    if not address or not chain:
        return

    if chain not in CHAIN_MAP_DEX.values():
        return

    tok, changed = await engine.upsert(
        address, chain,
        symbol=parsed["symbol"],
        name=parsed["name"],
        pair_address=parsed["pair_address"],
        dex_url=parsed["dex_url"],
        price_usd=parsed["price_usd"],
        price_change_24h=parsed["price_change_24h"],
        market_cap_usd=parsed["market_cap_usd"],
        liquidity_usd=parsed["liquidity_usd"],
        volume_24h_usd=parsed["volume_24h_usd"],
        buys_24h=parsed["buys_24h"],
        sells_24h=parsed["sells_24h"],
    )

    await evaluate_and_alert(tok)

    asyncio.create_task(enrich_from_birdeye(address, chain))
    asyncio.create_task(enrich_from_gmgn(address, chain))
    asyncio.create_task(enrich_from_bubblemaps(address, chain))


async def poll_dexscreener_latest():
    logger.info("DEX Screener: latest token poller started")
    while True:
        try:
            tokens = await f.dexscreener_latest_tokens()
            for profile in tokens:
                token_address = profile.get("tokenAddress", "")
                chain_id = profile.get("chainId", "")
                if not token_address or not chain_id:
                    continue
                if chain_id not in CHAIN_MAP_DEX.values():
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
                chain_id = profile.get("chainId", "")
                if not token_address or chain_id not in CHAIN_MAP_DEX.values():
                    continue
                pairs = await f.dexscreener_token_pairs(chain_id, token_address)
                for pair in pairs:
                    pair_addr = pair.get("pairAddress", "")
                    if pair_addr and pair_addr not in _seen_dex_pairs:
                        _seen_dex_pairs.add(pair_addr)
                        asyncio.create_task(process_dexscreener_pair(pair))

        except Exception as e:
            logger.error(f"DEX Screener latest poll error: {e}")

        await asyncio.sleep(DEXSCREENER_POLL_INTERVAL)


async def poll_dexscreener_hot():
    logger.info("DEX Screener: hot pairs poller started")
    hot_queries = ["trending", "new", "pump", "moon", "gem"]
    idx = 0
    while True:
        try:
            query = hot_queries[idx % len(hot_queries)]
            pairs = await f.dexscreener_search(query)
            for pair in pairs:
                pair_addr = pair.get("pairAddress", "")
                chain_id = pair.get("chainId", "")
                if chain_id not in CHAIN_MAP_DEX.values():
                    continue
                if pair_addr and pair_addr not in _seen_dex_pairs:
                    _seen_dex_pairs.add(pair_addr)
                    asyncio.create_task(process_dexscreener_pair(pair))
            idx += 1
        except Exception as e:
            logger.error(f"DEX Screener hot poll error: {e}")

        await asyncio.sleep(DEXSCREENER_POLL_INTERVAL * 2)


async def refresh_known_tokens():
    logger.info("Token refresh loop started")
    while True:
        await asyncio.sleep(30)
        try:
            all_toks = await engine.all()
            now = time.time()
            for tok in all_toks:
                if now - tok.last_updated < 20:
                    continue
                if not tok.pair_address:
                    continue
                pairs = await f.dexscreener_token_pairs(tok.chain, tok.address)
                if pairs:
                    await process_dexscreener_pair(pairs[0])
        except Exception as e:
            logger.error(f"Token refresh error: {e}")


async def stats_logger():
    while True:
        await asyncio.sleep(60)
        count = await engine.count()
        all_toks = await engine.all()
        alerted = sum(1 for t in all_toks if t.alerted)
        high_score = [t for t in all_toks if t.score >= 70]
        logger.info(
            f"[STATS] Tracking {count} tokens | Alerted: {alerted} | High-score (70+): {len(high_score)} | DEX pairs seen: {len(_seen_dex_pairs)}"
        )


async def run_scanner(bot: Bot):
    global _bot
    _bot = bot

    logger.info("Starting real-time token scanner...")

    await asyncio.gather(
        poll_dexscreener_latest(),
        poll_dexscreener_hot(),
        refresh_known_tokens(),
        stats_logger(),
    )
