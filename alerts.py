import logging
import time
from telegram import Bot
from telegram.constants import ParseMode
from state import TokenState
from config import (
    SCORE_THRESHOLD, TIER_S_THRESHOLD,
    RESEND_SCORE_IMPROVEMENT, RESEND_MCAP_MULTIPLY, RESEND_SMART_MONEY_MULTIPLY,
)

logger = logging.getLogger(__name__)


def should_alert(tok: TokenState, new_score: int) -> tuple[bool, str]:
    if new_score < SCORE_THRESHOLD:
        return False, ""
    if not tok.alerted:
        return True, "first_alert"
    score_jump = new_score - tok.alert_score
    if score_jump >= RESEND_SCORE_IMPROVEMENT:
        return True, f"score_improved_{score_jump}pts"
    if tok.alert_mcap > 0:
        mcap_mult = tok.market_cap_usd / tok.alert_mcap
        if mcap_mult >= RESEND_MCAP_MULTIPLY:
            return True, f"mcap_doubled_{mcap_mult:.1f}x"
    if tok.alert_smart_money_inflow > 0:
        sm_mult = tok.smart_money_inflow_usd / tok.alert_smart_money_inflow
        if sm_mult >= RESEND_SMART_MONEY_MULTIPLY:
            return True, f"smart_money_doubled_{sm_mult:.1f}x"
    return False, ""


def _fmt_age(hours: float) -> str:
    if hours < 0:
        return "Unknown"
    if hours < 1:
        return f"{int(hours * 60)}m"
    if hours < 24:
        return f"{hours:.1f}h"
    return f"{hours / 24:.1f}d"


def _fmt_usd(val: float) -> str:
    if val >= 1_000_000:
        return f"${val / 1_000_000:.2f}M"
    if val >= 1_000:
        return f"${val / 1_000:.1f}K"
    return f"${val:,.0f}"


def _chain_emoji(chain: str) -> str:
    return {
        "solana": "◎",
        "bsc": "🟡",
        "ethereum": "⟠",
        "base": "🔵",
    }.get(chain.lower(), "🔗")


def _risk_label(rug_score: float, bubblemaps_ok: bool) -> str:
    if rug_score > 15 or not bubblemaps_ok:
        return "🔴 HIGH"
    if rug_score > 8:
        return "🟡 MEDIUM"
    return "🟢 LOW"


def _confidence(score: int, has_security: bool) -> str:
    if score >= 90 and has_security:
        return "🔥 VERY HIGH"
    if score >= 80:
        return "✅ HIGH"
    if score >= 70:
        return "⚠️ MEDIUM"
    return "❓ LOW"


def build_gem_alert(tok: TokenState, score: int, reason: str, tier: str) -> str:
    ce = _chain_emoji(tok.chain)
    tier_emoji = {"S": "💎", "A": "🚀", "B": "⚡"}.get(tier, "📡")
    reason_label = {
        "first_alert":     "NEW GEM DETECTED",
        "score_improved":  "SCORE UPGRADED",
        "mcap_doubled":    "MARKET CAP SURGE",
        "smart_money_doubled": "SMART MONEY SURGE",
    }
    label = next((v for k, v in reason_label.items() if reason.startswith(k)), "SIGNAL UPDATE")

    score_bar = "█" * (score // 10) + "░" * (10 - score // 10)
    hp_status = "⛔ YES" if tok.honeypot_detected else "✅ PASS"
    rug_risk   = _risk_label(tok.rug_risk_score, tok.bubblemaps_ok)
    bm_status  = "✅ PASS" if tok.bubblemaps_ok else ("❓ N/A" if not tok.security_checked else "⚠️ FAIL")
    confidence = _confidence(score, tok.security_checked)

    mc = tok.market_cap_usd
    vol_mc = (tok.volume_24h_usd / mc) if mc > 0 else 0.0
    fresh_pct = f"{tok.fresh_wallet_ratio:.1%}" if tok.fresh_wallet_ratio > 0 else "N/A"
    lw_pct    = f"{tok.largest_wallet_pct:.1f}%" if tok.largest_wallet_pct > 0 else "N/A"
    t10_pct   = f"{tok.top10_concentration_pct:.1f}%" if tok.top10_concentration_pct < 100 else "N/A"
    hg_str    = f"{tok.holder_growth_pct:+.1f}%" if tok.holder_count_prev > 0 else "N/A"
    sm_str    = f"${tok.smart_money_inflow_usd:,.0f} ({tok.smart_money_count}w)" if tok.smart_money_count else "N/A"
    rug_str   = f"{tok.rug_risk_score:.0f}/100" if tok.rug_risk_score > 0 else "N/A"

    addr = tok.address
    gmgn_chain = {"solana": "sol", "bsc": "bsc", "ethereum": "eth"}.get(tok.chain, tok.chain)
    dex_link    = tok.dex_url or f"https://dexscreener.com/{tok.chain}/{tok.address}"
    gmgn_link   = f"https://gmgn.ai/{gmgn_chain}/token/{addr}"
    birdeye_link = f"https://birdeye.so/token/{addr}?chain={tok.chain}"

    lines = [
        f"{tier_emoji} *TIER {tier} — {label}*",
        f"",
        f"🏷 Token: *{tok.name}*",
        f"💱 Ticker: `${tok.symbol}`",
        f"⛓ Chain: {ce} `{tok.chain.upper()}`",
        f"",
        f"⏱ Age: `{_fmt_age(tok.age_hours)}`",
        f"",
        f"📊 Market Cap: `{_fmt_usd(mc)}`",
        f"💧 Liquidity: `{_fmt_usd(tok.liquidity_usd)}`",
        f"",
        f"📈 24H Volume: `{_fmt_usd(tok.volume_24h_usd)}`",
        f"⚡ Volume/MC: `{vol_mc:.2f}x`",
        f"",
        f"👥 Holder Count: `{tok.holder_count:,}`",
        f"📊 Holder Growth: `{hg_str}`",
        f"",
        f"🆕 Fresh Wallet Ratio: `{fresh_pct}`",
        f"",
        f"🐋 Largest Wallet: `{lw_pct}`",
        f"🔟 Top 10 Holders: `{t10_pct}`",
        f"",
        f"🟢 Buy/Sell Ratio: `{tok.buy_sell_ratio:.2f}x`",
        f"",
        f"🧠 Smart Money Flow: `{sm_str}`",
        f"",
        f"🗺 BubbleMaps: {bm_status}",
        f"",
        f"🍯 Honeypot: {hp_status}",
        f"",
        f"⚠️ Rug Risk: {rug_risk} ({rug_str})",
        f"",
        f"🎯 Confidence Score: {confidence}",
        f"",
        f"🏆 Final Score: `{score}/100`  `[{score_bar}]`",
        f"",
        f"🚦 Risk Level: {rug_risk}",
        f"",
        f"🔗 [DEX Screener]({dex_link})  |  [GMGN]({gmgn_link})  |  [Birdeye]({birdeye_link})",
        f"`{addr}`",
    ]
    return "\n".join(lines)


def build_mania_alert(tok: TokenState, score: int) -> str:
    ce = _chain_emoji(tok.chain)
    mc = tok.market_cap_usd
    vol_mc = (tok.volume_24h_usd / mc) if mc > 0 else 0.0
    fresh_pct = f"{tok.fresh_wallet_ratio:.1%}" if tok.fresh_wallet_ratio > 0 else "N/A"
    lw_pct    = f"{tok.largest_wallet_pct:.1f}%" if tok.largest_wallet_pct > 0 else "N/A"
    hg_str    = f"{tok.holder_growth_pct:+.1f}%" if tok.holder_count_prev > 0 else "N/A"
    bm_status = "✅ PASS" if tok.bubblemaps_ok else "❓ N/A"
    rug_str   = f"{tok.rug_risk_score:.0f}/100" if tok.rug_risk_score > 0 else "N/A"
    sm_str    = f"${tok.smart_money_inflow_usd:,.0f}" if tok.smart_money_inflow_usd > 0 else "Detected ✅"
    score_bar = "█" * (score // 10) + "░" * (10 - score // 10)

    lines = [
        f"🔥 *MEME MANIA DETECTED*",
        f"",
        f"🏷 Token: *{tok.name}*",
        f"💱 Ticker: `${tok.symbol}`",
        f"⛓ Chain: {ce} `{tok.chain.upper()}`",
        f"",
        f"⏱ Age: `{_fmt_age(tok.age_hours)}`",
        f"",
        f"📊 Market Cap: `{_fmt_usd(mc)}`",
        f"💧 Liquidity: `{_fmt_usd(tok.liquidity_usd)}`",
        f"",
        f"⚡ Volume/MC: `{vol_mc:.2f}x`",
        f"",
        f"👥 Holder Count: `{tok.holder_count:,}`",
        f"📊 Holder Growth: `{hg_str}`",
        f"",
        f"🆕 Fresh Wallet Ratio: `{fresh_pct}`",
        f"",
        f"🐋 Largest Wallet: `{lw_pct}`",
        f"",
        f"🟢 Buy/Sell Ratio: `{tok.buy_sell_ratio:.2f}x`",
        f"",
        f"🧠 Smart Money: `{sm_str}`",
        f"",
        f"🗺 BubbleMaps: {bm_status}",
        f"",
        f"⚠️ Rug Risk: `{rug_str}`",
        f"",
        f"🎯 Confidence Score: {_confidence(score, tok.security_checked)}",
        f"",
        f"🔥 Final Score: `{score}/100`  `[{score_bar}]` *(+20 Mania Bonus)*",
        f"`{tok.address}`",
    ]
    return "\n".join(lines)


async def send_alert(bot: Bot, chat_id: str, tok: TokenState, score: int,
                     reason: str, tier: str):
    if not chat_id:
        logger.warning("No TELEGRAM_CHAT_ID — cannot send alert")
        return
    if tok.is_mania and tier in ("S", "A"):
        msg = build_mania_alert(tok, score)
    else:
        msg = build_gem_alert(tok, score, reason, tier)
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=msg,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
        logger.info(f"Alert sent: {tok.symbol} tier={tier} score={score} reason={reason}")
    except Exception as e:
        logger.error(f"Alert send error for {tok.symbol}: {e}")


async def send_status_message(bot: Bot, chat_id: str, kind: str, detail: str = ""):
    if not chat_id or not bot:
        return
    msgs = {
        "started":   f"✅ *Scanner Started*\nMEME GEM HUNTER PRO V5 is now live and scanning.",
        "restarted": f"⚠️ *Scanner Restarted*\nRecovering from an error. Scanning resumed.",
        "error":     f"❌ *Scanner Error*\n`{detail}`\nAttempting automatic recovery...",
    }
    msg = msgs.get(kind, f"📡 Scanner: {kind}")
    try:
        await bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.debug(f"Status message error: {e}")
