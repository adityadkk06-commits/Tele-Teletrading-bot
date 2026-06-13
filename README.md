# MEME GEM HUNTER PRO V5

Fully automated, production-grade, real-time Meme Coin Discovery Engine.

## Architecture

- **Event-Driven Detection** — no fixed intervals; fires the moment filters pass
- **Async State Engine** — in-memory token database, re-evaluated on every metric change
- **Multi-Source** — DEX Screener, Birdeye, GMGN, BubbleMaps
- **WebSocket-first** — falls back to API polling only when needed
- **Deduplication** — one alert per token unless score improves 10+ or MCap increases 50%

## Signal Filters

| Metric | Threshold |
|---|---|
| Score | ≥ 85/100 |
| Min Liquidity | $20,000 |
| Min Volume 24h | $50,000 |
| Market Cap Range | $100k – $50M |
| Min Buy/Sell Ratio | 1.2x |
| Min Holders | 100 |
| Max Top10 Concentration | 60% |

## Commands

- `/start` — Main menu
- `/status` — Scanner stats
- `/top` — Top scoring tokens
- `/filters` — Current filter config
- `/setchat` — Register this chat for alerts

## Secrets Required

- `TELEGRAM_BOT_TOKEN` — from @BotFather
- `TELEGRAM_CHAT_ID` — set via `/setchat` command, or add manually
- `BIRDEYE_API_KEY` — (optional) enables holder + smart money data
- `GMGN_API_KEY` — (optional) enables GMGN smart money data

## Running

```
python bot.py
```
