import io
import os
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, BotCommand
from telegram.error import Conflict, NetworkError
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from agent import Agent
from scheduler import SignalScheduler, is_market_open
from stocks import (
    format_signal, format_signal_deep, format_heatmap,
    format_market_summary, format_leaderboard,
    format_topgainer_header, format_regime,
    get_symbol_data, get_top_gainers, analyze_symbol,
    get_market_regime, SYMBOLS,
)
from chart import generate_chart

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

agent = Agent()
signal_scheduler: SignalScheduler = None

# ── Persistent reply keyboard ───────────────────────────────────────────────────
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("🔍 Scan Now"),     KeyboardButton("🏆 Top Gainers")],
        [KeyboardButton("📈 Top Signals"),  KeyboardButton("📊 Market")],
        [KeyboardButton("🌡 Heatmap"),      KeyboardButton("❓ Help")],
    ],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="Tap a button or /signal BBRI for deep-dive…",
)

# ── Bot command list ────────────────────────────────────────────────────────────
BOT_COMMANDS = [
    BotCommand("scan",        "Live scan — smart money filter"),
    BotCommand("topgainer",   "Top 5 gainers with regime analysis"),
    BotCommand("signal",      "Deep-dive: /signal BBRI"),
    BotCommand("topsignals",  "Top signals from last scan"),
    BotCommand("check",       "Full scan of all stocks"),
    BotCommand("heatmap",     "Sector heatmap"),
    BotCommand("market",      "Overall market condition"),
    BotCommand("status",      "Scanner status"),
    BotCommand("subscribe",   "Subscribe to alerts"),
    BotCommand("unsubscribe", "Stop receiving alerts"),
    BotCommand("clear",       "Clear chat history"),
    BotCommand("help",        "Show all commands"),
]


# ── Chart+signal helper ─────────────────────────────────────────────────────────
async def _send_signal_with_chart(message, sig, deep: bool = False) -> None:
    """Send chart as photo with signal caption. Falls back to text-only."""
    text        = format_signal_deep(sig) if deep else format_signal(sig)
    ohlcv       = get_symbol_data(sig.symbol)
    chart_bytes = generate_chart(sig, ohlcv) if ohlcv else None

    if chart_bytes:
        # Telegram caption limit is 1024 chars — send long deep-dive as separate message
        caption = format_signal(sig)   # always use the shorter card as caption
        try:
            await message.reply_photo(
                photo=io.BytesIO(chart_bytes),
                caption=caption,
                parse_mode="Markdown",
            )
            if deep:
                # Send the extended analysis as a follow-up text message
                extra = text[len(caption):]   # everything after the base signal
                if extra.strip():
                    await message.reply_markdown(extra)
            return
        except Exception as exc:
            logger.warning("send_photo failed for %s: %s", sig.symbol, exc)

    await message.reply_markdown(text)


# ── /start ─────────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user   = update.effective_user
    was_new = signal_scheduler.subscribe(update.effective_chat.id)
    sub_note = "You've been *auto-subscribed* to signals." if was_new else "You're already subscribed."
    await update.message.reply_markdown(
        f"👋 Hi {user.mention_markdown()}!\n\n"
        f"*IHSG Smart Money Scanner* — Institutional-grade analysis.\n\n"
        f"{sub_note}\n\n"
        f"*What I do:*\n"
        f"- Scan *{len(SYMBOLS)} liquid IHSG stocks* every 5 min\n"
        f"- 6-layer Smart Money scoring (max 100)\n"
        f"- Detect Bandar accumulation, breakouts, EMA crossovers\n"
        f"- Market Regime Engine (Trending/Distribution/Sideways)\n"
        f"- Auto-alerts with chart + full analysis\n\n"
        f"*Quick start:*\n"
        f"🔍 Scan Now — run live smart money scan\n"
        f"🏆 Top Gainers — today's top gainers filtered\n"
        f"/signal BBRI — deep-dive any stock\n\n"
        f"Use /help to see all commands.",
        reply_markup=MAIN_KEYBOARD,
    )


# ── /help ──────────────────────────────────────────────────────────────────────
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_markdown(
        "*━━━ IHSG SMART MONEY SCANNER ━━━*\n\n"
        "*Scan Commands:*\n"
        "/scan — Live scan with Market Regime header\n"
        "/topgainer — Top 5 daily gainers, smart money scored\n"
        "/signal BBRI — Deep-dive any ticker (all 6 layers)\n"
        "/check — Full scan, raw results\n"
        "/topsignals — Top signals from last scan\n\n"
        "*Market Intel:*\n"
        "/market — Market condition + regime\n"
        "/heatmap — Sector-by-sector heatmap\n"
        "/status — Bot status + last scan info\n\n"
        "*Account:*\n"
        "/subscribe — Enable auto-alerts\n"
        "/unsubscribe — Disable alerts\n"
        "/clear — Clear AI chat history\n\n"
        "_Auto-scan every 5 min · IDX hours only_\n"
        "_Score ≥65 required to pass Smart Money Filter_",
        reply_markup=MAIN_KEYBOARD,
    )


# ── /subscribe & /unsubscribe ───────────────────────────────────────────────────
async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    was_new = signal_scheduler.subscribe(update.effective_chat.id)
    if was_new:
        await update.message.reply_text(
            "Subscribed! You'll receive IHSG signal alerts during market hours.",
            reply_markup=MAIN_KEYBOARD,
        )
    else:
        await update.message.reply_text("You're already subscribed.", reply_markup=MAIN_KEYBOARD)


async def unsubscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    removed = signal_scheduler.unsubscribe(update.effective_chat.id)
    if removed:
        await update.message.reply_text("Unsubscribed. Use /subscribe to re-enable.", reply_markup=MAIN_KEYBOARD)
    else:
        await update.message.reply_text("You weren't subscribed.", reply_markup=MAIN_KEYBOARD)


# ── /status ────────────────────────────────────────────────────────────────────
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id    = update.effective_chat.id
    subscribed = signal_scheduler.is_subscribed(chat_id)
    last_scan  = signal_scheduler.last_scan_time
    sig_count  = len(signal_scheduler.last_signals)
    market_str = "🟢 OPEN" if is_market_open() else "🔴 CLOSED"
    regime     = get_market_regime()
    await update.message.reply_markdown(
        f"*IHSG Smart Money Scanner*\n\n"
        f"IDX Market: *{market_str}*\n"
        f"Regime: {regime['emoji']} *{regime['label']}*\n"
        f"Your alerts: {'✅ Active' if subscribed else '❌ Inactive'}\n"
        f"Subscribers: `{len(signal_scheduler.subscribers)}`\n"
        f"Symbols: `{len(SYMBOLS)}` stocks (Rp100–500)\n"
        f"Auto-scan: every *5 min* during market hours\n"
        f"Min score: *65/100* (Smart Money Filter)\n\n"
        f"Last scan: `{last_scan}`\n"
        f"Signals found: `{sig_count}`",
        reply_markup=MAIN_KEYBOARD,
    )


# ── /scan (regime-aware check) ─────────────────────────────────────────────────
async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    market_note = "" if is_market_open() else "\n⚠️ Market closed — using last available prices."
    await update.message.reply_text(
        f"🔍 Running Smart Money scan on {len(SYMBOLS)} IHSG stocks...{market_note}",
        reply_markup=MAIN_KEYBOARD,
    )

    # Show market regime while scan runs
    regime = get_market_regime()
    await update.message.reply_markdown(format_regime(regime))

    signals = await signal_scheduler.run_check_now()

    if not signals:
        await update.message.reply_markdown(
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⛔ *NO HIGH PROBABILITY SETUPS — WAIT MODE*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"_No stocks passed the Smart Money Filter right now._\n"
            f"_Regime: {regime['emoji']} {regime['label']} — {regime['desc'][:80]}_\n\n"
            f"_Next auto-scan in 5 minutes. If uncertain → NO TRADE._",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    await update.message.reply_text(
        f"✅ {len(signals)} setup(s) passed the Smart Money Filter. Top results:",
        reply_markup=MAIN_KEYBOARD,
    )
    for sig in signals[:5]:
        await _send_signal_with_chart(update.message, sig)


# ── /check (legacy full scan) ──────────────────────────────────────────────────
async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    market_note = "" if is_market_open() else "\n⚠️ Market closed — using last available prices."
    await update.message.reply_text(
        f"🔍 Scanning {len(SYMBOLS)} IHSG stocks...{market_note}",
        reply_markup=MAIN_KEYBOARD,
    )
    signals = await signal_scheduler.run_check_now()

    if not signals:
        await update.message.reply_text(
            "No high-probability signals right now.\n"
            "Use /scan for full regime analysis.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    await update.message.reply_text(
        f"Found {len(signals)} signal(s). Showing top results:",
        reply_markup=MAIN_KEYBOARD,
    )
    for sig in signals[:5]:
        await _send_signal_with_chart(update.message, sig)


# ── /topgainer ─────────────────────────────────────────────────────────────────
async def topgainer_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🏆 Finding today's top gainers + running Smart Money filter...",
        reply_markup=MAIN_KEYBOARD,
    )
    import asyncio
    gainers = await asyncio.get_event_loop().run_in_executor(None, get_top_gainers, 5)
    regime  = get_market_regime()

    await update.message.reply_markdown(
        format_topgainer_header(gainers, regime),
        reply_markup=MAIN_KEYBOARD,
    )
    for sig in gainers[:3]:
        await _send_signal_with_chart(update.message, sig)


# ── /signal <TICKER> ───────────────────────────────────────────────────────────
async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_markdown(
            "Usage: `/signal BBRI` — replace BBRI with any IDX ticker.\n\n"
            "Example: `/signal ANTM` or `/signal TLKM`",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    ticker = args[0].upper().replace(".JK", "").strip()
    await update.message.reply_text(
        f"🔬 Deep-dive analysis for {ticker}... fetching data.",
        reply_markup=MAIN_KEYBOARD,
    )

    import asyncio
    sig = await asyncio.get_event_loop().run_in_executor(None, analyze_symbol, ticker)

    if sig is None:
        await update.message.reply_markdown(
            f"⚠️ *{ticker}* not found in watchlist.\n\n"
            f"Supported: {len(SYMBOLS)} IDX stocks (Rp100–500 range).\n"
            f"Try: BBRI, ANTM, TLKM, BBCA, ADRO, INCO…\n\n"
            f"_Use /check to see all scannable stocks._",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    sig.rank = 1
    await _send_signal_with_chart(update.message, sig, deep=True)


# ── /topsignals ────────────────────────────────────────────────────────────────
async def topsignals_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cached    = signal_scheduler.last_signals
    scan_time = signal_scheduler.last_scan_time

    if not cached:
        await update.message.reply_text(
            "No cached signals yet.\n"
            "Run /scan first, then /topsignals for instant results.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    await update.message.reply_markdown(
        format_leaderboard(cached, scan_time),
        reply_markup=MAIN_KEYBOARD,
    )
    for sig in cached[:3]:
        await _send_signal_with_chart(update.message, sig)


# ── /heatmap ───────────────────────────────────────────────────────────────────
async def heatmap_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🌡 Building sector heatmap...", reply_markup=MAIN_KEYBOARD)
    hm = await signal_scheduler.run_heatmap_now()
    await update.message.reply_markdown(format_heatmap(hm))


# ── /market ────────────────────────────────────────────────────────────────────
async def market_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Regime card first
    regime = get_market_regime()
    await update.message.reply_markdown(format_regime(regime), reply_markup=MAIN_KEYBOARD)
    # Then sector heatmap summary
    hm = signal_scheduler.last_heatmap
    if hm is None:
        hm = await signal_scheduler.run_heatmap_now()
    await update.message.reply_markdown(format_market_summary(hm))


# ── /clear ─────────────────────────────────────────────────────────────────────
async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    agent.clear_history(update.effective_user.id)
    await update.message.reply_text("Conversation history cleared.", reply_markup=MAIN_KEYBOARD)


# ── Keyboard button → command dispatcher ───────────────────────────────────────
_BUTTON_MAP: dict[str, any] = {
    "🔍 Scan Now":     scan_command,
    "🏆 Top Gainers":  topgainer_command,
    "📈 Top Signals":  topsignals_command,
    "📊 Market":       market_command,
    "🌡 Heatmap":      heatmap_command,
    "❓ Help":          help_command,
}


# ── Free text / button handler ─────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text    = update.message.text
    handler = _BUTTON_MAP.get(text)
    if handler:
        await handler(update, context)
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    response = agent.respond(update.effective_user.id, text)
    await update.message.reply_text(response, reply_markup=MAIN_KEYBOARD)


# ── Error handler ──────────────────────────────────────────────────────────────
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, Conflict):
        logger.warning("Conflict: another instance briefly overlapped. Ignoring.")
        return
    if isinstance(context.error, NetworkError):
        logger.warning("Network error: %s", context.error)
        return
    logger.error("Unhandled exception:", exc_info=context.error)


# ── Lifecycle ──────────────────────────────────────────────────────────────────
async def post_init(application: Application) -> None:
    await application.bot.set_my_commands(BOT_COMMANDS)
    logger.info("Bot commands registered (%d commands).", len(BOT_COMMANDS))
    signal_scheduler.start()


async def post_shutdown(application: Application) -> None:
    signal_scheduler.stop()


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    global signal_scheduler

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set.")

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    signal_scheduler = SignalScheduler(app.bot)

    app.add_handler(CommandHandler("start",        start))
    app.add_handler(CommandHandler("help",         help_command))
    app.add_handler(CommandHandler("subscribe",    subscribe_command))
    app.add_handler(CommandHandler("unsubscribe",  unsubscribe_command))
    app.add_handler(CommandHandler("status",       status_command))
    app.add_handler(CommandHandler("scan",         scan_command))
    app.add_handler(CommandHandler("check",        check_command))
    app.add_handler(CommandHandler("topgainer",    topgainer_command))
    app.add_handler(CommandHandler("signal",       signal_command))
    app.add_handler(CommandHandler("topsignals",   topsignals_command))
    app.add_handler(CommandHandler("heatmap",      heatmap_command))
    app.add_handler(CommandHandler("market",       market_command))
    app.add_handler(CommandHandler("clear",        clear_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("Bot is running...")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
