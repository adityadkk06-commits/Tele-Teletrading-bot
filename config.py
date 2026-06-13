import os

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

BIRDEYE_API_KEY = os.environ.get("BIRDEYE_API_KEY", "")
GMGN_API_KEY = os.environ.get("GMGN_API_KEY", "")
GOPLUS_API_KEY = os.environ.get("GOPLUS_API_KEY", "")
HELIUS_API_KEY = os.environ.get("HELIUS_API_KEY", "")
BUBBLEMAPS_API_KEY = os.environ.get("BUBBLEMAPS_API_KEY", "")

TIER_S_THRESHOLD = 90
TIER_A_THRESHOLD = 80
TIER_B_THRESHOLD = 70
SCORE_THRESHOLD = TIER_A_THRESHOLD

RESEND_SCORE_IMPROVEMENT = 10
RESEND_MCAP_MULTIPLY = 2.0
RESEND_SMART_MONEY_MULTIPLY = 2.0

CHAINS = ["solana", "bsc"]

DEXSCREENER_POLL_INTERVAL = 4
BIRDEYE_POLL_INTERVAL = 15
GMGN_POLL_INTERVAL = 15

CHAIN_MIN_LIQUIDITY = {
    "solana": 50_000,
    "bsc":    100_000,
    "ethereum": 100_000,
    "base":   50_000,
}

MIN_TOKEN_AGE_HOURS = 0.5
MAX_TOKEN_AGE_HOURS = 72.0

FILTERS = {
    "min_market_cap_usd":          50_000,
    "max_market_cap_usd":       5_000_000,
    "min_liquidity_usd":           50_000,
    "liq_mc_ratio_min":              0.10,
    "min_holder_count":                20,
    "min_volume_mc_ratio":            0.5,
    "min_buy_sell_ratio":             1.1,
    "min_fresh_wallet_ratio":        0.15,
    "max_largest_wallet_pct":         8.0,
    "max_top10_concentration_pct":   30.0,
    "max_dev_wallet_pct":             5.0,
    "max_sniper_holdings_pct":       15.0,
    "max_sniper_cluster_pct":        20.0,
    "max_insider_cluster_pct":       20.0,
    "max_connected_cluster_pct":     25.0,
    "min_unique_traders_24h":          50,
    "max_rug_risk_score":              20,
    "max_gain_24h_pct":            1000.0,
    "max_gain_6h_pct":              300.0,
    "max_price_above_vwap_pct":      30.0,
}

SCORE_WEIGHTS = {
    "buy_pressure":       25,
    "holder_growth":      20,
    "fresh_wallets":      15,
    "volume_quality":     15,
    "smart_money":        10,
    "liquidity_quality":  10,
    "narrative_strength":  5,
}

BONUS_SCORES = {
    "smart_wallet_entry":   5,
    "fresh_wallet_30pct":   5,
    "holder_growth_10pct":  5,
    "volume_mc_2x":         5,
    "mc_growth_30pct":      5,
    "trending_narrative":   3,
    "pumpfun_graduated":    5,
    "buy_sell_2x":          5,
}

MANIA = {
    "max_age_hours":          24,
    "max_market_cap_usd": 1_000_000,
    "min_holder_growth_pct":  20.0,
    "min_fresh_wallet_ratio":  0.30,
    "min_volume_mc_ratio":     2.0,
    "min_buy_sell_ratio":      2.0,
    "mania_bonus_score":       20,
}

WATCHLIST_DURATION_HOURS = 24
ANALYTICS_FILE = "analytics_signals.json"
