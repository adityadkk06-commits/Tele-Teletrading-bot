import logging
from telegram import Bot
from telegram.constants import ParseMode
from state import TokenState
from config import SCORE_THRESHOLD, RESEND_SCORE_IMPROVEMENT, RESEND_MCAP_INCREASE_PCT

logger = logging.getLogger(__name__)


def should_alert(tok: TokenState, new_score: int) -> tuple[bool, str]:
    if not tok.alerted:
        return True, "first_alert"
    score_jump = new_score - tok.alert_score
    if score_jump >= RESEND_SCORE_IMPROVEMENT:
        return True, f"score_improved_{score_jump}pts"
    if tok.alert_mcap > 0:
        mcap_increase_pct = ((tok.market_cap_usd - tok.alert_mcap) / tok.alert_mcap) * 100
        if mcap_increase_pct >= RESEND_MCAP_INCREASE_PCT:
            return True, f"mcap_up_{mcap_increase_pct:.0f}pct"
    return False, ""


def build_alert_message(tok: TokenState, score: int, reason: str, fails: list[str]) -> str:
    chain_emoji = {
        "solana": "◎",
        "ethereum": "⟠",
        "bsc": "🟡",
        "base": "🔵",
    }.get(tok.chain.lower(), "🔗")

    score_bar = "█" * (score // 10) + "░" * (10 - score // 10)
    trend = "▲" if tok.price_change_24h >= 0 else "▼"
    price_color = "🟢" if tok.price_change_24h >= 0 else "🔴"

    reason_map = {
        "first_alert": "✅ New Signal",
        "score_improved": "📈 Score Improved",
        "mcap_up": "🚀 Market Cap Surge",
    }
    reason_label = next(
        (v for k, v in reason_map.items() if reason.startswith(k)),
        "📡 Update"
    )

    msg_lines = [
        f"🚨 *SIGNAL DETECTED* — {reason_label}",
        f"",
        f"{chain_emoji} *{tok.symbol}* `{tok.name}`",
        f"Chain: `{tok.chain.upper()}`",
        f"",
        f"📊 *Score: {score}/100*",
        f"`[{score_bar}]`",
        f"",
        f"💰 Price: `${tok.price_usd:.8f}` {price_color}{trend} {abs(tok.price_change_24h):.1f}%",
        f"📈 Market Cap: `${tok.market_cap_usd:,.0f}`",
        f"💧 Liquidity: `${tok.liquidity_usd:,.0f}`",
        f"🔄 Volume 24h: `${tok.volume_24h_usd:,.0f}`",
        f"",
        f"🟢 Buys: `{tok.buys_24h}` | 🔴 Sells: `{tok.sells_24h}`",
        f"⚖️ Buy/Sell Ratio: `{tok.buy_sell_ratio:.2f}x`",
    ]

    if tok.holder_count > 0:
        growth_str = f" ({tok.holder_growth_pct:+.1f}%)" if tok.holder_growth_pct != 0 else ""
        msg_lines.append(f"👥 Holders: `{tok.holder_count:,}{growth_str}`")

    if tok.smart_money_count > 0:
        msg_lines.append(f"🧠 Smart Money: `{tok.smart_money_count} wallets` (${tok.smart_money_inflow_usd:,.0f} inflow)")

    if tok.top10_concentration_pct < 100:
        conc_emoji = "✅" if tok.top10_concentration_pct <= 30 else ("⚠️" if tok.top10_concentration_pct <= 50 else "🔴")
        msg_lines.append(f"🗺️ Top10 Concentration: {conc_emoji} `{tok.top10_concentration_pct:.1f}%`")

    msg_lines.append(f"")

    if tok.dex_url:
        msg_lines.append(f"🔗 [View on DEX]({tok.dex_url})")

    addr_short = tok.address[:6] + "..." + tok.address[-4:] if len(tok.address) > 12 else tok.address
    msg_lines.append(f"`{tok.address}`")

    return "\n".join(msg_lines)


async def send_alert(bot: Bot, chat_id: str, tok: TokenState, score: int, reason: str, fails: list[str]):
    if not chat_id:
        logger.warning("No TELEGRAM_CHAT_ID configured — cannot send alert")
        return

    msg = build_alert_message(tok, score, reason, fails)
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=msg,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
        logger.info(f"Alert sent for {tok.symbol} ({tok.address[:8]}…) score={score}")
    except Exception as e:
        logger.error(f"Failed to send alert for {tok.symbol}: {e}")
