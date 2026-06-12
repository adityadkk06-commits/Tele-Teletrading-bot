# Telegram IHSG Scanner Bot

AI-powered Telegram bot for Indonesian stock market (IHSG) scanning.

## Features
- ARA Hunter Screener (Auto Reject Atas — stocks gaining ≥20%)
- Top Gainers
- Top Signals (EMA + RSI technical analysis)
- Market Overview (IHSG index + breadth)

## Commands
- `/start` — Show the main menu
- `/scan` — Open the scan menu

## Tech Stack
- Python 3.11
- python-telegram-bot
- yfinance (market data)
- ta (technical indicators: EMA, RSI)
- pandas / numpy

## Running
Requires `TELEGRAM_BOT_TOKEN` secret set in Replit Secrets.

```
python bot.py
```

## User preferences
