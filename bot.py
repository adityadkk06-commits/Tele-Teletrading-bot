import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
import yfinance as yf
import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

IHSG_TICKERS = [
    "BBCA.JK", "BBRI.JK", "TLKM.JK", "ASII.JK", "BMRI.JK",
    "UNVR.JK", "HMSP.JK", "GGRM.JK", "KLBF.JK", "ICBP.JK",
    "INDF.JK", "PGAS.JK", "JSMR.JK", "PTBA.JK", "ANTM.JK",
    "ADRO.JK", "INCO.JK", "MDKA.JK", "MEDC.JK", "SMGR.JK",
    "CPIN.JK", "EXCL.JK", "ISAT.JK", "MNCN.JK", "SCMA.JK",
    "ACES.JK", "MAPI.JK", "LPPF.JK", "ERAA.JK", "SIDO.JK",
    "BSDE.JK", "CTRA.JK", "PWON.JK", "SMRA.JK", "LPKR.JK",
    "WIKA.JK", "WSKT.JK", "PTPP.JK", "ADHI.JK", "TOTL.JK",
    "BBNI.JK", "BBTN.JK", "BNGA.JK", "BTPS.JK", "BNLI.JK",
]


def get_stock_data(ticker: str, period: str = "5d", interval: str = "1d"):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period, interval=interval)
        return hist
    except Exception as e:
        logger.warning(f"Failed to fetch {ticker}: {e}")
        return None


def calculate_signals(hist: pd.DataFrame):
    if hist is None or len(hist) < 14:
        return None
    close = hist["Close"]
    rsi = RSIIndicator(close, window=14).rsi().iloc[-1]
    ema20 = EMAIndicator(close, window=20).ema_indicator().iloc[-1] if len(close) >= 20 else None
    ema50 = EMAIndicator(close, window=50).ema_indicator().iloc[-1] if len(close) >= 50 else None
    return {"rsi": rsi, "ema20": ema20, "ema50": ema50}


def get_change_pct(hist: pd.DataFrame):
    if hist is None or len(hist) < 2:
        return None
    prev = hist["Close"].iloc[-2]
    curr = hist["Close"].iloc[-1]
    if prev == 0:
        return None
    return ((curr - prev) / prev) * 100


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("📈 Top Gainers", callback_data="top_gainers"),
            InlineKeyboardButton("🔍 ARA Hunter", callback_data="ara_hunter"),
        ],
        [
            InlineKeyboardButton("📊 Market Overview", callback_data="market_overview"),
            InlineKeyboardButton("💡 Top Signals", callback_data="top_signals"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🇮🇩 *IHSG Scanner Bot*\n\n"
        "AI-powered Indonesian stock market scanner.\n"
        "Choose a feature below or use /scan for the full menu.",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("📈 Top Gainers", callback_data="top_gainers"),
            InlineKeyboardButton("🔍 ARA Hunter", callback_data="ara_hunter"),
        ],
        [
            InlineKeyboardButton("📊 Market Overview", callback_data="market_overview"),
            InlineKeyboardButton("💡 Top Signals", callback_data="top_signals"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📡 *IHSG Scanner Menu*\n\nSelect a scan to run:",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data

    await query.edit_message_text("⏳ Scanning market data, please wait...")

    if action == "top_gainers":
        await handle_top_gainers(query)
    elif action == "ara_hunter":
        await handle_ara_hunter(query)
    elif action == "market_overview":
        await handle_market_overview(query)
    elif action == "top_signals":
        await handle_top_signals(query)


async def handle_top_gainers(query):
    results = []
    for ticker in IHSG_TICKERS[:20]:
        hist = get_stock_data(ticker, period="5d")
        pct = get_change_pct(hist)
        if pct is not None:
            price = hist["Close"].iloc[-1]
            results.append((ticker.replace(".JK", ""), pct, price))

    results.sort(key=lambda x: x[1], reverse=True)
    top = results[:10]

    if not top:
        await query.edit_message_text("❌ No data available. Try again later.")
        return

    msg = "📈 *Top Gainers (IHSG)*\n\n"
    for i, (sym, pct, price) in enumerate(top, 1):
        arrow = "🟢" if pct >= 0 else "🔴"
        msg += f"{i}. {arrow} *{sym}* — Rp {price:,.0f} ({pct:+.2f}%)\n"

    await query.edit_message_text(msg, parse_mode="Markdown")


async def handle_ara_hunter(query):
    results = []
    for ticker in IHSG_TICKERS:
        hist = get_stock_data(ticker, period="5d")
        pct = get_change_pct(hist)
        if pct is not None and pct >= 20:
            price = hist["Close"].iloc[-1]
            results.append((ticker.replace(".JK", ""), pct, price))

    results.sort(key=lambda x: x[1], reverse=True)

    if not results:
        await query.edit_message_text(
            "🔍 *ARA Hunter Results*\n\nNo stocks at ARA (≥20% gain) today.",
            parse_mode="Markdown",
        )
        return

    msg = "🔍 *ARA Hunter — Auto Reject Atas*\n\n"
    for sym, pct, price in results:
        msg += f"🚀 *{sym}* — Rp {price:,.0f} ({pct:+.2f}%)\n"

    await query.edit_message_text(msg, parse_mode="Markdown")


async def handle_market_overview(query):
    ihsg = get_stock_data("^JKSE", period="5d")
    lq45 = get_stock_data("^JKLQ45", period="5d")

    msg = "📊 *Market Overview — IHSG*\n\n"

    if ihsg is not None and len(ihsg) >= 2:
        ihsg_pct = get_change_pct(ihsg)
        ihsg_price = ihsg["Close"].iloc[-1]
        arrow = "🟢" if ihsg_pct >= 0 else "🔴"
        msg += f"{arrow} *IHSG:* {ihsg_price:,.2f} ({ihsg_pct:+.2f}%)\n"
    else:
        msg += "IHSG: Data tidak tersedia\n"

    if lq45 is not None and len(lq45) >= 2:
        lq45_pct = get_change_pct(lq45)
        lq45_price = lq45["Close"].iloc[-1]
        arrow = "🟢" if lq45_pct >= 0 else "🔴"
        msg += f"{arrow} *LQ45:* {lq45_price:,.2f} ({lq45_pct:+.2f}%)\n"
    else:
        msg += "LQ45: Data tidak tersedia\n"

    gainers = 0
    losers = 0
    for ticker in IHSG_TICKERS[:30]:
        hist = get_stock_data(ticker, period="5d")
        pct = get_change_pct(hist)
        if pct is not None:
            if pct > 0:
                gainers += 1
            elif pct < 0:
                losers += 1

    msg += f"\n📈 Naik: {gainers} saham\n"
    msg += f"📉 Turun: {losers} saham\n"
    msg += f"➖ Flat: {30 - gainers - losers} saham\n"

    await query.edit_message_text(msg, parse_mode="Markdown")


async def handle_top_signals(query):
    results = []
    for ticker in IHSG_TICKERS[:25]:
        hist = get_stock_data(ticker, period="60d")
        sigs = calculate_signals(hist)
        if sigs is None:
            continue

        rsi = sigs["rsi"]
        ema20 = sigs["ema20"]
        ema50 = sigs["ema50"]
        price = hist["Close"].iloc[-1] if hist is not None else 0

        signal = "NEUTRAL"
        score = 0

        if rsi < 30:
            signal = "BUY"
            score += 2
        elif rsi > 70:
            signal = "SELL"
            score -= 2

        if ema20 and ema50:
            if ema20 > ema50:
                score += 1
            else:
                score -= 1

        if score >= 2:
            signal = "🟢 BUY"
        elif score <= -2:
            signal = "🔴 SELL"
        else:
            signal = "🟡 HOLD"

        results.append((ticker.replace(".JK", ""), signal, rsi, price))

    buy_signals = [r for r in results if "BUY" in r[1]]
    sell_signals = [r for r in results if "SELL" in r[1]]

    msg = "💡 *Top Signals (EMA + RSI)*\n\n"

    if buy_signals:
        msg += "🟢 *BUY Signals:*\n"
        for sym, sig, rsi, price in buy_signals[:5]:
            msg += f"  • *{sym}* — Rp {price:,.0f} | RSI: {rsi:.1f}\n"
    else:
        msg += "🟢 BUY Signals: Tidak ada\n"

    if sell_signals:
        msg += "\n🔴 *SELL Signals:*\n"
        for sym, sig, rsi, price in sell_signals[:5]:
            msg += f"  • *{sym}* — Rp {price:,.0f} | RSI: {rsi:.1f}\n"
    else:
        msg += "\n🔴 SELL Signals: Tidak ada\n"

    await query.edit_message_text(msg, parse_mode="Markdown")


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set!")
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Starting IHSG Scanner Bot...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
