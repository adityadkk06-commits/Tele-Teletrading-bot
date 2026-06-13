import os
import asyncio
import logging
import time
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
from analytics import analytics
from config import (
    TELEGRAM_BOT_TOKEN,
    TIER_S_THRESHOLD, TIER_A_THRESHOLD, TIER_B_THRESHOLD,
    FILTERS, MANIA, CHAINS,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


WELCOME_MSG = (
    "🔍 *MEME GEM HUNTER PRO V5*\n\n"
    "Event-driven meme coin discovery engine.\n"
    "Scanning Solana & BSC in real-time.\n\n"
    "*Signal Tiers:*\n"
    "💎 Tier S — Score ≥ 90 → Telegram Alert\n"
    "🚀 Tier A — Score ≥ 80 → Telegram Alert\n"
    "⚡ Tier B — Score ≥ 70 → Watchlist only\n\n"
    "🔥 *Mania Mode* fires on ultra-early explosions (<24h, <$1M mcap)\n\n"
    "Use /setchat to register this chat for alerts."
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("📊 Status",     callback_data="status"),
            InlineKeyboardButton("🏆 Top Tokens", callback_data="top"),
        ],
        [
            InlineKeyboardButton("⚙️ Filters",    callback_data="filters"),
            InlineKeyboardButton("📡 Set Chat",   callback_data="setchat"),
        ],
        [
            InlineKeyboardButton("📈 Analytics",  callback_data="analytics"),
            InlineKeyboardButton("👁 Watchlist",  callback_data="watchlist"),
        ],
    ]
    await update.message.reply_text(
        WELCOME_MSG,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_status(update.message.reply_text)


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_top(update.message.reply_text)


async def cmd_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_filters(update.message.reply_text)


async def cmd_setchat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    os.environ["TELEGRAM_CHAT_ID"] = chat_id
    import config
    config.TELEGRAM_CHAT_ID = chat_id
    await update.message.reply_text(
        f"✅ *Alert chat registered!*\n\nChat ID: `{chat_id}`\n\n"
        f"Tier A/S alerts (score ≥ {TIER_A_THRESHOLD}) will be sent here.\n"
        f"Mania alerts fire separately when explosive tokens are detected.",
        parse_mode=ParseMode.MARKDOWN,
    )
    logger.info(f"Alert chat set to {chat_id}")


async def cmd_analytics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_analytics(update.message.reply_text)


async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_watchlist(update.message.reply_text)


async def cmd_mania(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_toks = await engine.all()
    mania = [t for t in all_toks if t.is_mania and not t.hard_rejected]
    if not mania:
        await update.message.reply_text("🔥 No Mania tokens detected yet.")
        return
    mania_sorted = sorted(mania, key=lambda t: t.score, reverse=True)[:10]
    lines = ["🔥 *Mania Mode Tokens*\n"]
    for i, tok in enumerate(mania_sorted, 1):
        age_str = f"{tok.age_hours:.1f}h" if tok.age_hours >= 0 else "?"
        mc_str = f"${tok.market_cap_usd / 1000:.0f}K" if tok.market_cap_usd < 1e6 else f"${tok.market_cap_usd / 1e6:.2f}M"
        lines.append(
            f"{i}. 🔥 *{tok.symbol}* `[{tok.chain[:3].upper()}]` — Score `{tok.score}` | "
            f"Age `{age_str}` | MC `{mc_str}`"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: `/token <address> [chain]`\n\n"
            "Examples:\n`/token EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v sol`\n"
            "`/token 0x... bsc`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    address = context.args[0].strip()
    chain_raw = context.args[1].strip().lower() if len(context.args) > 1 else "solana"
    chain = {"sol": "solana", "eth": "ethereum", "bnb": "bsc", "matic": "polygon"}.get(chain_raw, chain_raw)

    msg = await update.message.reply_text(
        f"🔍 Scanning `{address[:8]}…` on *{chain.upper()}*…",
        parse_mode=ParseMode.MARKDOWN,
    )

    import fetchers as fch
    from state import TokenState
    from scorer import compute_score, assign_tier
    from security import hard_reject, passes_token_filters

    pairs = await fch.dexscreener_token_pairs(chain, address)
    if not pairs:
        await msg.edit_text(
            f"❌ No pairs found for `{address}` on {chain.upper()}.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    pair = pairs[0]
    parsed = fch.parse_dexscreener_pair(pair)
    tok = TokenState(address=address, chain=chain)
    for k, v in parsed.items():
        if hasattr(tok, k):
            setattr(tok, k, v)

    bm = await fch.bubblemaps_token(address, chain)
    if bm:
        bm_parsed = fch.parse_bubblemaps(bm)
        tok.top10_concentration_pct = bm_parsed["top10_pct"]
        tok.bubblemaps_ok = bm_parsed["ok"]
        tok.insider_cluster_pct = bm_parsed["insider_cluster_pct"]
        tok.largest_wallet_pct = bm_parsed["largest_wallet_pct"]

    gp = await fch.goplus_token_security(address, chain)
    if gp:
        gp_parsed = fch.parse_goplus(gp)
        for k, v in gp_parsed.items():
            if hasattr(tok, k):
                setattr(tok, k, v)
        tok.security_checked = True

    if chain == "solana":
        rc = await fch.rugcheck_report(address)
        if rc:
            rc_parsed = fch.parse_rugcheck(rc)
            for k, v in rc_parsed.items():
                if hasattr(tok, k):
                    setattr(tok, k, v)
            tok.security_checked = True

    rejected, rej_reason = hard_reject(tok)
    if rejected:
        tok.hard_rejected = True

    final, base, is_mania, mb = compute_score(tok)
    tok.score = final
    tok.is_mania = is_mania
    tok.tier = assign_tier(final)
    passes, fails = passes_token_filters(tok)

    tier_emoji = {"S": "💎", "A": "🚀", "B": "⚡"}.get(tok.tier, "🔎")
    score_bar = "█" * (final // 10) + "░" * (10 - final // 10)
    ce = {"solana": "◎", "bsc": "🟡", "ethereum": "⟠"}.get(chain, "🔗")

    from alerts import _fmt_age, _fmt_usd
    lines = [
        f"{tier_emoji} *{tok.symbol}* — Tier {tok.tier or '—'} | Score `{final}/100`",
        f"{ce} Chain: `{chain.upper()}` | Age: `{_fmt_age(tok.age_hours)}`",
        f"`[{score_bar}]`",
        f"",
        f"📊 MCap: `{_fmt_usd(tok.market_cap_usd)}` | Liq: `{_fmt_usd(tok.liquidity_usd)}`",
        f"🔄 Vol 24h: `{_fmt_usd(tok.volume_24h_usd)}`",
        f"⚖️ B/S Ratio: `{tok.buy_sell_ratio:.2f}x` | Buys: `{tok.buys_24h}` Sells: `{tok.sells_24h}`",
    ]
    if tok.holder_count:
        lines.append(f"👥 Holders: `{tok.holder_count:,}` (growth `{tok.holder_growth_pct:+.1f}%`)")
    if tok.fresh_wallet_ratio > 0:
        lines.append(f"🆕 Fresh Wallets: `{tok.fresh_wallet_ratio:.1%}`")
    if tok.largest_wallet_pct > 0:
        lines.append(f"🐋 Largest Wallet: `{tok.largest_wallet_pct:.1f}%`")
    if tok.top10_concentration_pct < 100:
        lines.append(f"🔟 Top10 Concentration: `{tok.top10_concentration_pct:.1f}%`")
    if tok.bubblemaps_ok is not None:
        lines.append(f"🗺 BubbleMaps: {'✅ PASS' if tok.bubblemaps_ok else '⚠️ FAIL'}")
    if tok.rug_risk_score > 0:
        lines.append(f"⚠️ Rug Risk: `{tok.rug_risk_score:.0f}/100`")
    lines.append(f"🍯 Honeypot: {'⛔ YES' if tok.honeypot_detected else '✅ PASS'}")
    if tok.security_checked:
        lines.append(f"🔒 LP Locked: `{tok.lp_locked_pct:.0f}%`{'  🔥 Burned' if tok.lp_burned else ''}")

    if rejected:
        lines += ["", f"🚫 *HARD REJECTED:* `{rej_reason}`"]
    elif fails:
        lines += ["", "⚠️ *Filter failures:*"] + [f"  • {fl}" for fl in fails]
    elif passes and final >= TIER_A_THRESHOLD:
        lines.append(f"\n✅ *All filters pass — SIGNAL QUALITY*")

    if is_mania:
        lines.append(f"\n🔥 *MANIA MODE* (+{mb} bonus pts)")

    dex_link = tok.dex_url or f"https://dexscreener.com/{chain}/{address}"
    lines.append(f"\n🔗 [DEX Screener]({dex_link})")

    await msg.edit_text(
        "\n".join(lines), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
    )


# ─── Shared senders ───────────────────────────────────────────────────────────

async def _send_status(reply_fn):
    count    = await engine.count()
    all_toks = await engine.all()
    alerted  = sum(1 for t in all_toks if t.alerted)
    tier_s   = sum(1 for t in all_toks if t.tier == "S")
    tier_a   = sum(1 for t in all_toks if t.tier == "A")
    tier_b   = sum(1 for t in all_toks if t.tier == "B")
    mania    = sum(1 for t in all_toks if t.is_mania)
    rejected = sum(1 for t in all_toks if t.hard_rejected)
    wl_count = sum(1 for t in all_toks if t.watchlist_until > time.time())

    msg = (
        f"📡 *MEME GEM HUNTER PRO V5*\n\n"
        f"🔍 Tokens tracked: `{count}`\n"
        f"🔗 DEX pairs seen: `{len(sc._seen_dex_pairs)}`\n\n"
        f"💎 Tier S (≥90): `{tier_s}`\n"
        f"🚀 Tier A (≥80): `{tier_a}`\n"
        f"⚡ Tier B (≥70): `{tier_b}`\n"
        f"🔥 Mania tokens: `{mania}`\n\n"
        f"🚨 Alerts sent: `{alerted}`\n"
        f"👁 Watchlist: `{wl_count}` tokens\n"
        f"🚫 Hard rejected: `{rejected}`\n\n"
        f"⛓ Chains: `{', '.join(CHAINS)}`\n"
        f"⚙️ Mode: *Real-Time Event-Driven*\n"
        f"🌐 Sources: DEX Screener · Birdeye · GMGN · BubbleMaps · RugCheck · GoPlus"
    )
    await reply_fn(msg, parse_mode=ParseMode.MARKDOWN)


async def _send_top(reply_fn):
    all_toks = await engine.all()
    active = [t for t in all_toks if not t.hard_rejected]
    if not active:
        await reply_fn("No tokens scored yet. Scanner is warming up...")
        return

    sorted_toks = sorted(active, key=lambda t: t.score, reverse=True)[:10]
    lines = ["🏆 *Top Scoring Tokens*\n"]
    for i, tok in enumerate(sorted_toks, 1):
        bar = "█" * (tok.score // 10) + "░" * (10 - tok.score // 10)
        tier_e = {"S": "💎", "A": "🚀", "B": "⚡"}.get(tok.tier, "🔎")
        mania_e = " 🔥" if tok.is_mania else ""
        chain_s = tok.chain[:3].upper()
        age_s = f"{tok.age_hours:.1f}h" if tok.age_hours >= 0 else "?"
        lines.append(
            f"{i}. {tier_e} *{tok.symbol}* `[{chain_s}]`{mania_e}\n"
            f"   Score: `{tok.score}` `[{bar}]`\n"
            f"   MCap: `${tok.market_cap_usd:,.0f}` | Liq: `${tok.liquidity_usd:,.0f}` | Age: `{age_s}`\n"
            f"   B/S: `{tok.buy_sell_ratio:.2f}x` | Vol: `${tok.volume_24h_usd:,.0f}`"
        )
    await reply_fn("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def _send_filters(reply_fn):
    f = FILTERS
    m = MANIA
    msg = (
        f"⚙️ *Active Filters*\n\n"
        f"📅 Token Age: `{int(f['min_market_cap_usd'] / 60)}m – 72h` (30min-72h)\n"
        f"📈 MCap: `${f['min_market_cap_usd']:,.0f} – ${f['max_market_cap_usd']:,.0f}`\n"
        f"💧 Min Liquidity: `$50K (SOL) / $100K (BSC)`\n"
        f"📊 Liq/MC Ratio: `≥ 10%`\n"
        f"👥 Min Holders: `{f['min_holder_count']}`\n"
        f"📉 Vol/MC: `≥ {f['min_volume_mc_ratio']}`\n"
        f"⚖️ Min B/S Ratio: `{f['min_buy_sell_ratio']}x`\n"
        f"🆕 Fresh Wallets: `≥ 15%`\n"
        f"🐋 Max Largest Wallet: `{f['max_largest_wallet_pct']}%`\n"
        f"🔟 Max Top10 Concentration: `{f['max_top10_concentration_pct']}%`\n"
        f"👨‍💻 Max Dev Wallet: `{f['max_dev_wallet_pct']}%`\n"
        f"🎯 Max Sniper Holdings: `{f['max_sniper_holdings_pct']}%`\n"
        f"👥 Min Unique Traders: `{f['min_unique_traders_24h']}`\n"
        f"⚠️ Max Rug Risk: `{f['max_rug_risk_score']}`\n\n"
        f"🔥 *Mania Mode*\n"
        f"  Age ≤ `{m['max_age_hours']}h` | MCap ≤ `${m['max_market_cap_usd']:,.0f}`\n"
        f"  Holder Growth `>{m['min_holder_growth_pct']}%` | Fresh Wallets `>{m['min_fresh_wallet_ratio']:.0%}`\n"
        f"  Vol/MC `>{m['min_volume_mc_ratio']}x` | B/S `>{m['min_buy_sell_ratio']}x`\n\n"
        f"💎 Tier S: `≥ {TIER_S_THRESHOLD}` | 🚀 Tier A: `≥ {TIER_A_THRESHOLD}` | ⚡ Tier B: `≥ {TIER_B_THRESHOLD}`"
    )
    await reply_fn(msg, parse_mode=ParseMode.MARKDOWN)


async def _send_analytics(reply_fn):
    stats = await analytics.get_stats()
    if stats.get("total_signals", 0) == 0:
        await reply_fn("📊 No signals recorded yet.")
        return

    win_rate   = stats.get("win_rate", 0)
    avg_ret    = stats.get("avg_return_24h", 0)
    best_ret   = stats.get("best_return", 0)
    worst_ret  = stats.get("worst_return", 0)
    best_tok   = stats.get("best_token", "?")
    worst_tok  = stats.get("worst_token", "?")

    msg = (
        f"📈 *Self-Learning Analytics*\n\n"
        f"📡 Total Signals: `{stats['total_signals']}`\n"
        f"  💎 Tier S: `{stats.get('tier_s', 0)}`\n"
        f"  🚀 Tier A: `{stats.get('tier_a', 0)}`\n"
        f"  🔥 Mania: `{stats.get('mania', 0)}`\n\n"
        f"📊 Completed 24h Tracking: `{stats.get('completed_24h', 0)}`\n\n"
        f"🏆 Win Rate: `{win_rate:.1f}%`\n"
        f"📊 Avg 24h Return: `{avg_ret:+.1f}%`\n"
        f"🚀 Best Performer: `{best_tok}` (`{best_ret:+.1f}%`)\n"
        f"📉 Worst Performer: `{worst_tok}` (`{worst_ret:+.1f}%`)"
    )
    await reply_fn(msg, parse_mode=ParseMode.MARKDOWN)


async def _send_watchlist(reply_fn):
    wl_toks = await engine.watchlist()
    if not wl_toks:
        await reply_fn("👁 Watchlist is empty. Tokens appear here after being alerted.")
        return

    sorted_wl = sorted(wl_toks, key=lambda t: t.score, reverse=True)
    lines = [f"👁 *Watchlist — {len(sorted_wl)} tokens*\n"]
    now = time.time()
    for tok in sorted_wl[:15]:
        remaining_h = (tok.watchlist_until - now) / 3600
        tier_e = {"S": "💎", "A": "🚀", "B": "⚡"}.get(tok.tier, "🔎")
        mc_str = f"${tok.market_cap_usd / 1000:.0f}K" if tok.market_cap_usd < 1e6 else f"${tok.market_cap_usd / 1e6:.2f}M"
        lines.append(
            f"{tier_e} *{tok.symbol}* `[{tok.chain[:3].upper()}]` — `{tok.score}pts` | "
            f"MC `{mc_str}` | `{remaining_h:.1f}h` left"
        )
    await reply_fn("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ─── Callback handler ────────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    def reply_fn(text, **kw):
        return query.edit_message_text(text, **kw)

    if query.data == "status":
        await _send_status(reply_fn)
    elif query.data == "top":
        await _send_top(reply_fn)
    elif query.data == "filters":
        await _send_filters(reply_fn)
    elif query.data == "analytics":
        await _send_analytics(reply_fn)
    elif query.data == "watchlist":
        await _send_watchlist(reply_fn)
    elif query.data == "setchat":
        chat_id = str(query.message.chat_id)
        os.environ["TELEGRAM_CHAT_ID"] = chat_id
        import config
        config.TELEGRAM_CHAT_ID = chat_id
        await query.edit_message_text(
            f"✅ *Alert chat registered!*\nChat ID: `{chat_id}`\nAlerts ≥ Tier A will appear here.",
            parse_mode=ParseMode.MARKDOWN,
        )
        logger.info(f"Alert chat set to {chat_id}")


# ─── Boot ─────────────────────────────────────────────────────────────────────

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

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("top",       cmd_top))
    app.add_handler(CommandHandler("filters",   cmd_filters))
    app.add_handler(CommandHandler("setchat",   cmd_setchat))
    app.add_handler(CommandHandler("token",     cmd_token))
    app.add_handler(CommandHandler("analytics", cmd_analytics))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
    app.add_handler(CommandHandler("mania",     cmd_mania))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("MEME GEM HUNTER PRO V5 starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
