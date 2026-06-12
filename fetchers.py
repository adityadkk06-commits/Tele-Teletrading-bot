import asyncio
import logging
import aiohttp
from typing import Optional
from config import BIRDEYE_API_KEY

logger = logging.getLogger(__name__)

DEXSCREENER_BASE = "https://api.dexscreener.com"
BIRDEYE_BASE = "https://public-api.birdeye.so"
GMGN_BASE = "https://gmgn.ai/api/v1"
BUBBLEMAPS_BASE = "https://api-legacy.bubblemaps.io"

_session: Optional[aiohttp.ClientSession] = None


async def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        timeout = aiohttp.ClientTimeout(total=10)
        _session = aiohttp.ClientSession(timeout=timeout)
    return _session


async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()


async def _get(url: str, headers: dict = None, params: dict = None) -> Optional[dict]:
    session = await get_session()
    try:
        async with session.get(url, headers=headers or {}, params=params or {}) as resp:
            if resp.status == 200:
                return await resp.json()
            logger.debug(f"HTTP {resp.status} for {url}")
            return None
    except asyncio.TimeoutError:
        logger.debug(f"Timeout fetching {url}")
        return None
    except Exception as e:
        logger.debug(f"Error fetching {url}: {e}")
        return None


async def dexscreener_latest_tokens() -> list[dict]:
    data = await _get(f"{DEXSCREENER_BASE}/token-profiles/latest/v1")
    if not data:
        return []
    if isinstance(data, list):
        return data
    return data.get("data", [])


async def dexscreener_search(query: str) -> list[dict]:
    data = await _get(f"{DEXSCREENER_BASE}/latest/dex/search", params={"q": query})
    if not data:
        return []
    return data.get("pairs", [])


async def dexscreener_token_pairs(chain_id: str, token_address: str) -> list[dict]:
    data = await _get(f"{DEXSCREENER_BASE}/latest/dex/tokens/{token_address}")
    if not data:
        return []
    pairs = data.get("pairs", [])
    return [p for p in pairs if p.get("chainId", "").lower() == chain_id.lower()]


async def dexscreener_boosted_tokens() -> list[dict]:
    data = await _get(f"{DEXSCREENER_BASE}/token-boosts/latest/v1")
    if not data:
        return []
    if isinstance(data, list):
        return data
    return data.get("data", [])


def parse_dexscreener_pair(pair: dict) -> dict:
    info = pair.get("info", {}) or {}
    txns = pair.get("txns", {}) or {}
    h24 = txns.get("h24", {}) or {}
    volume = pair.get("volume", {}) or {}
    liq = pair.get("liquidity", {}) or {}

    buys = h24.get("buys", 0) or 0
    sells = h24.get("sells", 0) or 0
    total = buys + sells
    bs_ratio = buys / total if total > 0 else 0

    mcap = pair.get("marketCap") or pair.get("fdv") or 0
    liq_usd = liq.get("usd", 0) or 0
    vol_24h = volume.get("h24", 0) or 0

    base = pair.get("baseToken", {}) or {}
    price_change = pair.get("priceChange", {}) or {}

    return {
        "chain": pair.get("chainId", ""),
        "pair_address": pair.get("pairAddress", ""),
        "dex_id": pair.get("dexId", ""),
        "dex_url": pair.get("url", ""),
        "token_address": base.get("address", ""),
        "symbol": base.get("symbol", ""),
        "name": base.get("name", ""),
        "price_usd": float(pair.get("priceUsd") or 0),
        "price_change_24h": float(price_change.get("h24") or 0),
        "market_cap_usd": float(mcap),
        "liquidity_usd": float(liq_usd),
        "volume_24h_usd": float(vol_24h),
        "buys_24h": int(buys),
        "sells_24h": int(sells),
        "buy_sell_ratio": bs_ratio,
        "age_hours": None,
    }


async def birdeye_token_overview(token_address: str, chain: str = "solana") -> Optional[dict]:
    if not BIRDEYE_API_KEY:
        return None
    chain_map = {"solana": "solana", "ethereum": "ethereum", "bsc": "bsc", "base": "base"}
    chain_id = chain_map.get(chain, "solana")
    headers = {
        "X-API-KEY": BIRDEYE_API_KEY,
        "x-chain": chain_id,
    }
    data = await _get(
        f"{BIRDEYE_BASE}/defi/token_overview",
        headers=headers,
        params={"address": token_address},
    )
    if not data or not data.get("success"):
        return None
    return data.get("data")


async def birdeye_holder_data(token_address: str, chain: str = "solana") -> Optional[dict]:
    if not BIRDEYE_API_KEY:
        return None
    chain_map = {"solana": "solana", "ethereum": "ethereum", "bsc": "bsc", "base": "base"}
    chain_id = chain_map.get(chain, "solana")
    headers = {
        "X-API-KEY": BIRDEYE_API_KEY,
        "x-chain": chain_id,
    }
    data = await _get(
        f"{BIRDEYE_BASE}/defi/v2/token_holders",
        headers=headers,
        params={"address": token_address, "limit": 20},
    )
    if not data or not data.get("success"):
        return None
    return data.get("data")


async def birdeye_smart_money(token_address: str, chain: str = "solana") -> Optional[dict]:
    if not BIRDEYE_API_KEY:
        return None
    chain_id = chain if chain != "bsc" else "bsc"
    headers = {
        "X-API-KEY": BIRDEYE_API_KEY,
        "x-chain": chain_id,
    }
    data = await _get(
        f"{BIRDEYE_BASE}/trader/token-smart-wallet-trades",
        headers=headers,
        params={"address": token_address, "tx_type": "buy", "limit": 10},
    )
    if not data or not data.get("success"):
        return None
    return data.get("data")


async def gmgn_token_info(token_address: str, chain: str = "sol") -> Optional[dict]:
    chain_map = {"solana": "sol", "ethereum": "eth", "bsc": "bsc", "base": "base"}
    c = chain_map.get(chain, chain)
    data = await _get(f"{GMGN_BASE}/token_info/{c}/{token_address}")
    if not data:
        return None
    return data.get("data") or data


async def gmgn_smart_money(token_address: str, chain: str = "sol") -> Optional[dict]:
    chain_map = {"solana": "sol", "ethereum": "eth", "bsc": "bsc", "base": "base"}
    c = chain_map.get(chain, chain)
    data = await _get(
        f"{GMGN_BASE}/smart_money_token/{c}/{token_address}",
        params={"limit": 10},
    )
    if not data:
        return None
    return data.get("data") or data


async def bubblemaps_token(token_address: str, chain: str = "sol") -> Optional[dict]:
    chain_map = {"solana": "sol", "ethereum": "eth", "bsc": "bsc", "base": "base"}
    c = chain_map.get(chain, chain)
    data = await _get(
        f"{BUBBLEMAPS_BASE}/map-data",
        params={"chain": c, "token": token_address},
    )
    return data


def parse_bubblemaps(data: dict) -> dict:
    if not data:
        return {"top10_pct": 100.0, "ok": False}
    nodes = data.get("nodes", [])
    if not nodes:
        return {"top10_pct": 100.0, "ok": False}

    sorted_nodes = sorted(nodes, key=lambda n: n.get("percentage", 0), reverse=True)
    top10 = sum(n.get("percentage", 0) for n in sorted_nodes[:10])
    return {"top10_pct": top10, "ok": True}
