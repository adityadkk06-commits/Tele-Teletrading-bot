import os

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
BIRDEYE_API_KEY = os.environ.get("BIRDEYE_API_KEY", "")
GMGN_API_KEY = os.environ.get("GMGN_API_KEY", "")

SCORE_THRESHOLD = 85
RESEND_SCORE_IMPROVEMENT = 10
RESEND_MCAP_INCREASE_PCT = 50.0

CHAINS = ["solana", "ethereum", "bsc", "base"]
PRIMARY_CHAIN = "solana"

DEXSCREENER_POLL_INTERVAL = 4
BIRDEYE_POLL_INTERVAL = 10
GMGN_POLL_INTERVAL = 10

FILTERS = {
    "min_liquidity_usd": 20_000,
    "min_volume_24h_usd": 50_000,
    "min_market_cap_usd": 100_000,
    "max_market_cap_usd": 50_000_000,
    "min_buy_sell_ratio": 1.2,
    "min_holder_count": 100,
    "max_top10_concentration_pct": 60.0,
}

SCORE_WEIGHTS = {
    "market_cap":    15,
    "liquidity":     15,
    "volume_24h":    15,
    "buy_sell_ratio":15,
    "holder_count":  10,
    "holder_growth": 10,
    "smart_money":   10,
    "concentration": 10,
}
