import asyncio
import logging
import time
import aiohttp
from typing import Optional
from config import BIRDEYE_API_KEY, GOPLUS_API_KEY

logger = logging.getLogger(__name__)

DEXSCREENER_BASE  = "https://api.dexscreener.com"
BIRDEYE_BASE      = "https://public-api.birdeye.so"
GMGN_BASE         = "https://gmgn.ai/api/v1"
BUBBLEMAPS_BASE   = "https://api-legacy.bubblemaps.io"
RUGCHECK_BASE     = "https://api.rugcheck.xyz/v1"
GOPLUS_BASE       = "https://api.gopluslabs.io/api/v1"
HONEYPOT_BASE     = "https://api.honeypot.is/v2"
PUMPFUN_BASE      = "https://frontend-api.pump.fun"

_session: Optional[aiohttp.ClientSession] = None


async def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
        timeout = aiohttp.ClientTimeout(total=12)
        _session = aiohttp.ClientSession(timeout=timeout, connector=connector)
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
                ct = resp.headers.get("Content-Type", "")
                if "json" in ct or "javascript" in ct:
                    return await resp.json(content_type=None)
                return None
            logger.debug(f"HTTP {resp.status} for {url}")
            return None
    except asyncio.TimeoutError:
        logger.debug(f"Timeout: {url}")
        return None
    except Exception as e:
        logger.debug(f"Error fetching {url}: {e}")
        return None


# ─── DEX Screener ────────────────────────────────────────────────────────────

async def dexscreener_latest_tokens() -> list[dict]:
    data = await _get(f"{DEXSCREENER_BASE}/token-profiles/latest/v1")
    if not data:
        return []
    return data if isinstance(data, list) else data.get("data", [])


async def dexscreener_boosted_tokens() -> list[dict]:
    data = await _get(f"{DEXSCREENER_BASE}/token-boosts/latest/v1")
    if not data:
        return []
    return data if isinstance(data, list) else data.get("data", [])


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
    if chain_id:
        pairs = [p for p in pairs if p.get("chainId", "").lower() == chain_id.lower()]
    return pairs


def parse_dexscreener_pair(pair: dict) -> dict:
    txns   = pair.get("txns", {}) or {}
    h24    = txns.get("h24", {}) or {}
    h6     = txns.get("h6", {}) or {}
    h1     = txns.get("h1", {}) or {}
    volume = pair.get("volume", {}) or {}
    liq    = pair.get("liquidity", {}) or {}
    base   = pair.get("baseToken", {}) or {}
    pc     = pair.get("priceChange", {}) or {}

    buys  = int(h24.get("buys", 0) or 0)
    sells = int(h24.get("sells", 0) or 0)
    bs_ratio = buys / sells if sells > 0 else (float(buys) if buys > 0 else 0.0)

    mcap    = float(pair.get("marketCap") or pair.get("fdv") or 0)
    liq_usd = float(liq.get("usd", 0) or 0)
    vol_24h = float(volume.get("h24", 0) or 0)
    vol_6h  = float(volume.get("h6", 0) or 0)
    vol_1h  = float(volume.get("h1", 0) or 0)

    created_ts = pair.get("pairCreatedAt")
    age_hours = -1.0
    pair_created_at = 0.0
    if created_ts:
        pair_created_at = float(created_ts) / 1000.0
        age_hours = (time.time() - pair_created_at) / 3600.0

    return {
        "chain":           pair.get("chainId", ""),
        "pair_address":    pair.get("pairAddress", ""),
        "dex_id":          pair.get("dexId", ""),
        "dex_url":         pair.get("url", ""),
        "token_address":   base.get("address", ""),
        "symbol":          base.get("symbol", ""),
        "name":            base.get("name", ""),
        "price_usd":       float(pair.get("priceUsd") or 0),
        "price_change_24h": float(pc.get("h24") or 0),
        "price_change_6h":  float(pc.get("h6") or 0),
        "price_change_1h":  float(pc.get("h1") or 0),
        "market_cap_usd":  mcap,
        "liquidity_usd":   liq_usd,
        "volume_24h_usd":  vol_24h,
        "volume_6h_usd":   vol_6h,
        "volume_1h_usd":   vol_1h,
        "buys_24h":        buys,
        "sells_24h":       sells,
        "buy_sell_ratio":  bs_ratio,
        "age_hours":       age_hours,
        "pair_created_at": pair_created_at,
    }


# ─── Birdeye ─────────────────────────────────────────────────────────────────

def _birdeye_headers(chain: str) -> dict:
    chain_map = {"solana": "solana", "ethereum": "ethereum", "bsc": "bsc", "base": "base"}
    return {
        "X-API-KEY": BIRDEYE_API_KEY,
        "x-chain": chain_map.get(chain, "solana"),
    }


async def birdeye_token_overview(token_address: str, chain: str = "solana") -> Optional[dict]:
    if not BIRDEYE_API_KEY:
        return None
    data = await _get(
        f"{BIRDEYE_BASE}/defi/token_overview",
        headers=_birdeye_headers(chain),
        params={"address": token_address},
    )
    if not data or not data.get("success"):
        return None
    return data.get("data")


async def birdeye_smart_money(token_address: str, chain: str = "solana") -> Optional[dict]:
    if not BIRDEYE_API_KEY:
        return None
    data = await _get(
        f"{BIRDEYE_BASE}/trader/token-smart-wallet-trades",
        headers=_birdeye_headers(chain),
        params={"address": token_address, "tx_type": "buy", "limit": 20},
    )
    if not data or not data.get("success"):
        return None
    return data.get("data")


async def birdeye_holder_data(token_address: str, chain: str = "solana") -> Optional[dict]:
    if not BIRDEYE_API_KEY:
        return None
    data = await _get(
        f"{BIRDEYE_BASE}/defi/v2/token_holders",
        headers=_birdeye_headers(chain),
        params={"address": token_address, "limit": 20},
    )
    if not data or not data.get("success"):
        return None
    return data.get("data")


# ─── GMGN ────────────────────────────────────────────────────────────────────

def _gmgn_chain(chain: str) -> str:
    return {"solana": "sol", "ethereum": "eth", "bsc": "bsc", "base": "base"}.get(chain, chain)


async def gmgn_token_info(token_address: str, chain: str = "sol") -> Optional[dict]:
    c = _gmgn_chain(chain)
    data = await _get(f"{GMGN_BASE}/token_info/{c}/{token_address}")
    if not data:
        return None
    return data.get("data") or data


async def gmgn_smart_money(token_address: str, chain: str = "sol") -> Optional[dict]:
    c = _gmgn_chain(chain)
    data = await _get(
        f"{GMGN_BASE}/smart_money_token/{c}/{token_address}",
        params={"limit": 20},
    )
    if not data:
        return None
    return data.get("data") or data


async def gmgn_fresh_wallets(token_address: str, chain: str = "sol") -> Optional[dict]:
    c = _gmgn_chain(chain)
    data = await _get(f"{GMGN_BASE}/token_fresh_wallets/{c}/{token_address}")
    if not data:
        return None
    return data.get("data") or data


# ─── BubbleMaps ──────────────────────────────────────────────────────────────

def _bm_chain(chain: str) -> str:
    return {"solana": "sol", "ethereum": "eth", "bsc": "bsc", "base": "base"}.get(chain, "sol")


async def bubblemaps_token(token_address: str, chain: str = "sol") -> Optional[dict]:
    data = await _get(
        f"{BUBBLEMAPS_BASE}/map-data",
        params={"chain": _bm_chain(chain), "token": token_address},
    )
    return data


def parse_bubblemaps(data: dict) -> dict:
    empty = {
        "top10_pct": 100.0, "ok": False,
        "insider_cluster_pct": 0.0, "connected_cluster_pct": 0.0,
        "largest_wallet_pct": 0.0,
    }
    if not data:
        return empty
    nodes = data.get("nodes", [])
    if not nodes:
        return empty

    sorted_nodes = sorted(nodes, key=lambda n: float(n.get("percentage", 0)), reverse=True)
    top10 = sum(float(n.get("percentage", 0)) for n in sorted_nodes[:10])
    largest = float(sorted_nodes[0].get("percentage", 0)) if sorted_nodes else 0.0

    clusters = data.get("clusters", []) or []
    insider_pct = 0.0
    connected_pct = 0.0
    for cl in clusters:
        cl_type = (cl.get("type") or "").lower()
        cl_pct = float(cl.get("percentage", 0) or 0)
        if "insider" in cl_type or "team" in cl_type or "dev" in cl_type:
            insider_pct += cl_pct
        if "connected" in cl_type or "cluster" in cl_type:
            connected_pct += cl_pct

    return {
        "top10_pct":             top10,
        "ok":                    True,
        "insider_cluster_pct":   insider_pct,
        "connected_cluster_pct": connected_pct,
        "largest_wallet_pct":    largest,
    }


# ─── RugCheck ────────────────────────────────────────────────────────────────

async def rugcheck_report(token_address: str) -> Optional[dict]:
    data = await _get(f"{RUGCHECK_BASE}/tokens/{token_address}/report/summary")
    return data


def parse_rugcheck(data: dict) -> dict:
    if not data:
        return {"rug_risk_score": 0.0, "mint_enabled": False,
                "freeze_enabled": False, "lp_locked_pct": 0.0, "lp_burned": False}
    score = float(data.get("score", 0) or 0)
    risks = data.get("risks", []) or []

    mint_enabled  = False
    freeze_enabled = False
    lp_locked_pct  = 0.0
    lp_burned      = False

    for r in risks:
        name = (r.get("name") or "").lower()
        if "mint" in name and "authority" in name:
            mint_enabled = True
        if "freeze" in name:
            freeze_enabled = True

    markets = data.get("markets", []) or []
    for m in markets:
        lp = m.get("lp", {}) or {}
        locked_pct = float(lp.get("pct_locked") or lp.get("locked_pct") or 0)
        burned_val  = lp.get("burned", False) or lp.get("lp_burned", False)
        if locked_pct > lp_locked_pct:
            lp_locked_pct = locked_pct
        if burned_val:
            lp_burned = True

    return {
        "rug_risk_score": score,
        "mint_enabled":   mint_enabled,
        "freeze_enabled": freeze_enabled,
        "lp_locked_pct":  lp_locked_pct,
        "lp_burned":      lp_burned,
    }


# ─── GoPlus Security ─────────────────────────────────────────────────────────

_GOPLUS_CHAIN_ID = {
    "solana":   "solana",
    "bsc":      "56",
    "ethereum": "1",
    "base":     "8453",
}


async def goplus_token_security(token_address: str, chain: str = "solana") -> Optional[dict]:
    chain_id = _GOPLUS_CHAIN_ID.get(chain, "solana")
    headers = {}
    if GOPLUS_API_KEY:
        headers["Authorization"] = GOPLUS_API_KEY

    if chain == "solana":
        url = f"{GOPLUS_BASE}/solana/token_security"
        params = {"contract_addresses": token_address}
    else:
        url = f"{GOPLUS_BASE}/token_security/{chain_id}"
        params = {"contract_addresses": token_address}

    data = await _get(url, headers=headers, params=params)
    if not data or data.get("code") != 1:
        return None
    result = data.get("result", {}) or {}
    return result.get(token_address.lower()) or result.get(token_address) or None


def parse_goplus(data: dict) -> dict:
    if not data:
        return {}
    def _flag(v) -> bool:
        return str(v) in ("1", "true", "True")

    return {
        "honeypot_detected":   _flag(data.get("is_honeypot")),
        "sell_allowed":       not _flag(data.get("cannot_sell_all")),
        "transfer_allowed":   not _flag(data.get("transfer_pausable")),
        "mint_enabled":        _flag(data.get("is_mintable")),
        "freeze_enabled":      _flag(data.get("trading_cooldown")),
        "blacklist_function":  _flag(data.get("is_blacklisted")),
        "proxy_risk":          _flag(data.get("is_proxy")),
        "contract_verified":   _flag(data.get("is_open_source")),
        "dev_wallet_pct":      float(data.get("creator_percent") or 0) * 100,
        "lp_locked_pct":       float(data.get("lp_lock_detail", {}).get("ratio") or
                                     data.get("holder_count") and 0 or 0),
    }


# ─── Honeypot.is (EVM only) ──────────────────────────────────────────────────

_HONEYPOT_CHAIN_ID = {"bsc": "56", "ethereum": "1", "base": "8453"}


async def honeypot_check(token_address: str, chain: str = "bsc") -> Optional[dict]:
    chain_id = _HONEYPOT_CHAIN_ID.get(chain)
    if not chain_id:
        return None
    data = await _get(
        f"{HONEYPOT_BASE}/IsHoneypot",
        params={"address": token_address, "chainID": chain_id},
    )
    return data


def parse_honeypot(data: dict) -> dict:
    if not data:
        return {"honeypot_detected": False}
    hp = data.get("honeypotResult", {}) or {}
    sim = data.get("simulationResult", {}) or {}
    return {
        "honeypot_detected": bool(hp.get("isHoneypot", False)),
        "sell_allowed":      not bool(hp.get("isHoneypot", False)),
        "buy_tax":           float(sim.get("buyTax", 0) or 0),
        "sell_tax":          float(sim.get("sellTax", 0) or 0),
    }


# ─── Pump.fun ─────────────────────────────────────────────────────────────────

async def pumpfun_token(token_address: str) -> Optional[dict]:
    data = await _get(f"{PUMPFUN_BASE}/coins/{token_address}")
    return data


def parse_pumpfun(data: dict, pair_created_at: float = 0) -> dict:
    if not data:
        return {"is_pumpfun": False, "pumpfun_graduated": False, "pumpfun_lp_created": False}
    complete  = bool(data.get("complete", False))
    lp        = bool(data.get("raydium_pool") or data.get("uniswap_pool"))
    grad_ts   = data.get("graduation_timestamp") or data.get("completed_at")
    grad_age  = -1.0
    if grad_ts:
        import time as _t
        grad_age = (_t.time() - float(grad_ts)) / 3600.0

    return {
        "is_pumpfun":              True,
        "pumpfun_graduated":       complete,
        "pumpfun_lp_created":      lp or complete,
        "pumpfun_graduation_age_h": grad_age,
    }
