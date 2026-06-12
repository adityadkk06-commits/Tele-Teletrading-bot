import os
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.constants import ParseMode

import scanner as sc
from state import engine
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SCORE_THRESHOLD, FILTERS

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


WELCOME_MSG = (
    "🤖 *Real-Time Token Scanner*\n\n"
    "Event-driven crypto token monitor.\n"
    "Tracks DEX Screener, Birdeye, GMGN & BubbleMaps.\n\n"
    "Signals fire *instantly* when a token scores ≥ *{threshold}/100*.\n\n"
    "Use /status to see the scanner state.\n"
    "Use /top to see highest-scoring tokens.\n"
    "Use /filters to see the current filter config.\n"
    "Use /setchat to register this chat for alerts."
).format(threshold=SCORE_THRESHOLD)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("📊 Status", callback_data="status"),
            InlineKeyboardButton("🏆 Top Tokens", callback_data="top"),
        ],
        [
            InlineKeyboardButton("⚙️ Filters", callback_data="filters"),
            InlineKeyboardButton("📡 Set Chat", callback_data="setchat"),
        ],
    ]
    await update.message.reply_text(
        WELCOME_MSG,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_status(update.message.reply_text)


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_top(update.message.reply_text)


async def cmd_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_filters(update.message.reply_text)


async def cmd_setchat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    os.environ["TELEGRAM_CHAT_ID"] = chat_id
    sc.engine  # keep reference
    import config
    config.TELEGRAM_CHAT_ID = chat_id

    await update.message.reply_text(
        f"✅ *Alert chat registered!*\n\n"
        f"Chat ID: `{chat_id}`\n\n"
        f"All signals with score ≥ {SCORE_THRESHOLD} will be sent here.",
        parse_mode=ParseMode.MARKDOWN,
    )
    logger.info(f"Alert chat set to {chat_id}")


async def send_status(reply_fn):
    count = await engine.count()
    all_toks = await engine.all()
    alerted = sum(1 for t in all_toks if t.alerted)
    score_70 = [t for t in all_toks if t.score >= 70]
    score_85 = [t for t in all_toks if t.score >= 85]
    seen = len(sc._seen_dex_pairs)

    msg = (
        f"📡 *Scanner Status*\n\n"
        f"🔍 Tokens tracked: `{count}`\n"
        f"🔗 DEX pairs seen: `{seen}`\n"
        f"🏆 Score ≥ 85: `{len(score_85)}`\n"
        f"⚡ Score ≥ 70: `{len(score_70)}`\n"
        f"🚨 Alerts sent: `{alerted}`\n\n"
        f"📊 Threshold: `{SCORE_THRESHOLD}/100`\n"
        f"⚙️ Mode: *Real-Time Event-Driven*\n"
        f"🌐 Sources: DEX Screener · Birdeye · GMGN · BubbleMaps"
    )
    await reply_fn(msg, parse_mode=ParseMode.MARKDOWN)


async def send_top(reply_fn):
    all_toks = await engine.all()
    if not all_toks:
        await reply_fn("No tokens tracked yet. Scanner is warming up...")
        return

    sorted_toks = sorted(all_toks, key=lambda t: t.score, reverse=True)[:10]

    lines = ["🏆 *Top Scoring Tokens*\n"]
    for i, tok in enumerate(sorted_toks, 1):
        bar = "█" * (tok.score // 10) + "░" * (10 - tok.score // 10)
        alert_mark = "🚨" if tok.alerted else " "
        chain_short = tok.chain[:3].upper()
        lines.append(
            f"{i}. {alert_mark} *{tok.symbol}* `[{chain_short}]` — Score: `{tok.score}`\n"
            f"   `[{bar}]`\n"
            f"   MCap: `${tok.market_cap_usd:,.0f}` | Liq: `${tok.liquidity_usd:,.0f}`\n"
            f"   B/S: `{tok.buy_sell_ratio:.2f}x` | Vol: `${tok.volume_24h_usd:,.0f}`"
        )

    await reply_fn("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def send_filters(reply_fn):
    f = FILTERS
    msg = (
        f"⚙️ *Active Filters*\n\n"
        f"📈 Min Market Cap: `${f['min_market_cap_usd']:,.0f}`\n"
        f"📉 Max Market Cap: `${f['max_market_cap_usd']:,.0f}`\n"
        f"💧 Min Liquidity: `${f['min_liquidity_usd']:,.0f}`\n"
        f"🔄 Min Volume 24h: `${f['min_volume_24h_usd']:,.0f}`\n"
        f"⚖️ Min Buy/Sell Ratio: `{f['min_buy_sell_ratio']}x`\n"
        f"👥 Min Holders: `{f['min_holder_count']}`\n"
        f"🗺️ Max Top10 Concentration: `{f['max_top10_concentration_pct']}%`\n\n"
        f"🎯 Score Threshold: `{SCORE_THRESHOLD}/100`"
    )
    await reply_fn(msg, parse_mode=ParseMode.MARKDOWN)


async def cmd_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: `/token <address> [chain]`\n\nExamples:\n"
            "`/token EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`\n"
            "`/token 0x1234... ethereum`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    address = context.args[0].strip()
    chain = context.args[1].strip().lower() if len(context.args) > 1 else "solana"
    chain_alias = {"sol": "solana", "eth": "ethereum", "bnb": "bsc", "matic": "polygon"}
    chain = chain_alias.get(chain, chain)

    msg = await update.message.reply_text(
        f"🔍 Looking up `{address[:8]}...` on *{chain.upper()}* — please wait...",
        parse_mode=ParseMode.MARKDOWN,
    )

    import fetchers as f
    from scorer import compute_score, passes_security_filters
    from state import TokenState

    pairs = await f.dexscreener_token_pairs(chain, address)
    if not pairs:
        await msg.edit_text(
            f"❌ No pairs found for `{address}` on {chain.upper()}.\n\n"
            f"Try specifying the chain: `/token {address} ethereum`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    pair = pairs[0]
    parsed = f.parse_dexscreener_pair(pair)

    tok = TokenState(address=address, chain=chain)
    tok.symbol = parsed["symbol"]
    tok.name = parsed["name"]
    tok.pair_address = parsed["pair_address"]
    tok.dex_url = parsed["dex_url"]
    tok.price_usd = parsed["price_usd"]
    tok.price_change_24h = parsed["price_change_24h"]
    tok.market_cap_usd = parsed["market_cap_usd"]
    tok.liquidity_usd = parsed["liquidity_usd"]
    tok.volume_24h_usd = parsed["volume_24h_usd"]
    tok.buys_24h = parsed["buys_24h"]
    tok.sells_24h = parsed["sells_24h"]
    tok.buy_sell_ratio = parsed["buy_sell_ratio"]

    bm_data = await f.bubblemaps_token(address, chain)
    if bm_data:
        bm = f.parse_bubblemaps(bm_data)
        tok.top10_concentration_pct = bm["top10_pct"]
        tok.bubblemaps_ok = bm["ok"]

    if f.BIRDEYE_API_KEY:
        overview = await f.birdeye_token_overview(address, chain)
        if overview:
            tok.holder_count = int(overview.get("holder") or 0)
        smart = await f.birdeye_smart_money(address, chain)
        if smart:
            items = smart.get("items", []) or []
            tok.smart_money_count = len(items)
            tok.smart_money_inflow_usd = sum(float(t.get("volume", 0) or 0) for t in items)

    score = compute_score(tok)
    tok.score = score
    passes, fails = passes_security_filters(tok)

    chain_emoji = {"solana": "◎", "ethereum": "⟠", "bsc": "🟡", "base": "🔵"}.get(chain, "🔗")
    bar = "█" * (score // 10) + "░" * (10 - score // 10)
    signal_label = "🚨 SIGNAL" if score >= SCORE_THRESHOLD and passes else ("⚡ NEAR" if score >= 70 else "🔎 TRACKED")
    trend = "🟢▲" if tok.price_change_24h >= 0 else "🔴▼"

    lines = [
        f"{signal_label} — *{tok.symbol}* `{tok.name}`",
        f"{chain_emoji} Chain: `{chain.upper()}`",
        f"",
        f"📊 *Score: {score}/100*",
        f"`[{bar}]`",
        f"",
        f"💰 Price: `${tok.price_usd:.8f}` {trend} `{abs(tok.price_change_24h):.1f}%`",
        f"📈 Market Cap: `${tok.market_cap_usd:,.0f}`",
        f"💧 Liquidity: `${tok.liquidity_usd:,.0f}`",
        f"🔄 Volume 24h: `${tok.volume_24h_usd:,.0f}`",
        f"🟢 Buys: `{tok.buys_24h}` | 🔴 Sells: `{tok.sells_24h}` | ⚖️ Ratio: `{tok.buy_sell_ratio:.2f}x`",
    ]

    if tok.holder_count:
        lines.append(f"👥 Holders: `{tok.holder_count:,}`")
    if tok.smart_money_count:
        lines.append(f"🧠 Smart Money: `{tok.smart_money_count} wallets`")
    if tok.top10_concentration_pct < 100:
        conc_e = "✅" if tok.top10_concentration_pct <= 30 else ("⚠️" if tok.top10_concentration_pct <= 50 else "🔴")
        lines.append(f"🗺️ Top10 Concentration: {conc_e} `{tok.top10_concentration_pct:.1f}%`")

    if fails:
        lines += ["", "⚠️ *Failed filters:*"]
        for fl in fails:
            lines.append(f"  • {fl}")
    elif passes and score >= SCORE_THRESHOLD:
        lines.append(f"\n✅ *All filters passed — SIGNAL QUALITY*")

    if tok.dex_url:
        lines.append(f"\n🔗 [View on DEX]({tok.dex_url})")

    await msg.edit_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "status":
        await send_status(
            lambda text, **kw: query.edit_message_text(text, **kw)
        )
    elif query.data == "top":
        await send_top(
            lambda text, **kw: query.edit_message_text(text, **kw)
        )
    elif query.data == "filters":
        await send_filters(
            lambda text, **kw: query.edit_message_text(text, **kw)
        )
    elif query.data == "setchat":
        chat_id = str(query.message.chat_id)
        os.environ["TELEGRAM_CHAT_ID"] = chat_id
        import config
        config.TELEGRAM_CHAT_ID = chat_id
        await query.edit_message_text(
            f"✅ *Alert chat registered!*\n\nChat ID: `{chat_id}`\nSignals ≥ {SCORE_THRESHOLD} will appear here.",
            parse_mode=ParseMode.MARKDOWN,
        )
        logger.info(f"Alert chat set to {chat_id}")


async def post_init(application: Application):
    bot: Bot = application.bot
    asyncio.create_task(sc.run_scanner(bot))
    logger.info("Scanner task launched.")


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set!")

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("filters", cmd_filters))
    app.add_handler(CommandHandler("setchat", cmd_setchat))
    app.add_handler(CommandHandler("token", cmd_token))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Real-Time Token Scanner Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
