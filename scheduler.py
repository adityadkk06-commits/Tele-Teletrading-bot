import io
import logging
import json
import os
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot
from telegram.constants import ParseMode
from stocks import check_signals, get_market_heatmap, format_signal, get_symbol_data, SYMBOLS
from chart import generate_chart

logger = logging.getLogger(__name__)

SUBSCRIBERS_FILE = os.path.join(os.path.dirname(__file__), "subscribers.json")

# ── IDX market hours (WIB = UTC+7) ─────────────────────────────────────────────
_WIB = timezone(timedelta(hours=7))


def is_market_open() -> bool:
    """True during IDX trading sessions Mon–Fri."""
    now = datetime.now(_WIB)
    if now.weekday() >= 5:          # Saturday=5, Sunday=6
        return False
    h, m = now.hour, now.minute
    in_session1 = (9, 0) <= (h, m) < (12, 0)    # 09:00–12:00
    in_session2 = (13, 30) <= (h, m) < (15, 50)  # 13:30–15:49
    return in_session1 or in_session2


def load_subscribers() -> set[int]:
    if os.path.exists(SUBSCRIBERS_FILE):
        try:
            with open(SUBSCRIBERS_FILE, "r") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def save_subscribers(chat_ids: set[int]) -> None:
    with open(SUBSCRIBERS_FILE, "w") as f:
        json.dump(list(chat_ids), f)


class SignalScheduler:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler()
        self.subscribers: set[int] = load_subscribers()
        self.last_signals: list = []
        self.last_heatmap = None
        self.last_scan_time: str = "Never"

    def subscribe(self, chat_id: int) -> bool:
        already = chat_id in self.subscribers
        self.subscribers.add(chat_id)
        save_subscribers(self.subscribers)
        return not already

    def unsubscribe(self, chat_id: int) -> bool:
        if chat_id in self.subscribers:
            self.subscribers.discard(chat_id)
            save_subscribers(self.subscribers)
            return True
        return False

    def is_subscribed(self, chat_id: int) -> bool:
        return chat_id in self.subscribers

    def start(self) -> None:
        self.scheduler.add_job(
            self._check_and_alert,
            trigger="interval",
            minutes=5,
            id="signal_check",
            replace_existing=True,
        )
        self.scheduler.start()
        logger.info("Signal scheduler started — checking every 5 minutes.")

    def stop(self) -> None:
        self.scheduler.shutdown(wait=False)

    async def _check_and_alert(self) -> None:
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

        if not is_market_open():
            logger.info("Signal check: IDX market closed (WIB) — skipping auto-scan.")
            return

        if not self.subscribers:
            logger.info("Signal check: no subscribers, skipping.")
            return

        logger.info("Signal check: scanning %d symbols...", len(SYMBOLS))
        signals = check_signals(SYMBOLS)
        self.last_signals = signals
        self.last_scan_time = now

        if not signals:
            logger.info("Signal check: no signals detected.")
            return

        logger.info("Signal check: %d signal(s) found.", len(signals))

        for sig in signals:
            message = format_signal(sig)

            # Generate chart once per signal (reuse bytes for all subscribers)
            ohlcv       = get_symbol_data(sig.symbol)
            chart_bytes = generate_chart(sig, ohlcv) if ohlcv else None
            if chart_bytes:
                logger.info("Chart generated for %s (%d bytes)", sig.symbol, len(chart_bytes))
            else:
                logger.warning("Chart unavailable for %s", sig.symbol)

            dead = set()
            for chat_id in list(self.subscribers):
                try:
                    if chart_bytes:
                        # Send chart with full signal text as caption (one message)
                        await self.bot.send_photo(
                            chat_id=chat_id,
                            photo=io.BytesIO(chart_bytes),
                            caption=message,
                            parse_mode=ParseMode.MARKDOWN,
                        )
                    else:
                        # Fallback: text-only alert
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text=message,
                            parse_mode=ParseMode.MARKDOWN,
                        )
                except Exception as e:
                    logger.warning("Failed to send to %d: %s", chat_id, e)
                    dead.add(chat_id)

            if dead:
                self.subscribers -= dead
                save_subscribers(self.subscribers)

    async def run_check_now(self) -> list:
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        signals = check_signals(SYMBOLS)
        self.last_signals = signals
        self.last_scan_time = now
        return signals

    async def run_heatmap_now(self):
        hm = get_market_heatmap()
        self.last_heatmap = hm
        return hm
