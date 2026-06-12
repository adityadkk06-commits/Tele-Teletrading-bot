# Real-Time Token Scanner Bot

Event-driven crypto token scanner with Telegram alerts.

## Features
- Real-time event-driven detection (no fixed scan intervals)
- Multi-source: DEX Screener, Birdeye, GMGN, BubbleMaps
- In-memory state engine with per-metric re-evaluation
- Score-based signal generation (threshold: 85/100)
- Deduplication: one alert unless score jumps 10+ or MCap up 50%

## Scoring (100 pts total)
- Market Cap (15) · Liquidity (15) · Volume 24h (15) · Buy/Sell Ratio (15)
- Holder Count (10) · Holder Growth (10) · Smart Money (10) · Concentration (10)

## Commands
- `/start` — Main menu
- `/status` — Scanner statistics
- `/top` — Top scoring tokens
- `/filters` — Active filter config
- `/setchat` — Register current chat for alerts

## Tech Stack
- Python 3.11
- python-telegram-bot
- aiohttp (async HTTP)
- DEX Screener API (free)
- Birdeye API (optional key)
- GMGN API (optional key)
- BubbleMaps API (public)

## Running
Requires `TELEGRAM_BOT_TOKEN` secret. Run with:
```
python bot.py
```

## User preferences
