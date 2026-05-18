"""
chart.py — Candlestick chart generator for IHSG signals.
Produces a PNG (bytes) for each Signal using matplotlib (Agg backend).
"""
import io
import logging

import matplotlib
matplotlib.use("Agg")          # headless — must be set before importing pyplot
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

logger = logging.getLogger(__name__)

# ── Chart constants ─────────────────────────────────────────────────────────────
CHART_CANDLES = 30      # number of candles to display
CHART_DPI     = 100     # PNG resolution
CHART_SIZE    = (10, 7) # inches (width × height) — good for mobile

# Colour palette (dark theme)
BG          = "#0d0d1a"
PANEL_BG    = "#12122a"
GREEN       = "#00e676"
RED         = "#ff1744"
GOLD        = "#ffd740"     # breakout candle
EMA9_CLR    = "#40c4ff"
EMA21_CLR   = "#ff9800"
BUY_CLR     = "#00e676"
TP1_CLR     = "#69f0ae"
TP2_CLR     = "#b9f6ca"
SL_CLR      = "#ff5252"
RES_CLR     = "#ff6d00"
GRID_CLR    = "#1e1e3a"
TEXT_CLR    = "#cccccc"


# ── EMA helper (independent copy — no circular import with stocks.py) ───────────
def _ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k   = 2 / (period + 1)
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


# ── Main chart function ─────────────────────────────────────────────────────────
def generate_chart(sig, ohlcv: dict) -> bytes | None:
    """
    Generate a candlestick chart PNG for a Signal.

    Args:
        sig:   Signal dataclass with buy_low/high, tp1, tp2, sl, score, flags.
        ohlcv: dict with keys closes/opens/highs/lows/volumes (full history).

    Returns:
        Raw PNG bytes, or None if generation failed.
    """
    try:
        return _build_chart(sig, ohlcv)
    except Exception as exc:
        logger.warning("Chart generation failed for %s: %s", sig.symbol, exc)
        try:
            plt.close("all")
        except Exception:
            pass
        return None


def _build_chart(sig, ohlcv: dict) -> bytes:
    closes  = ohlcv["closes"]
    opens   = ohlcv["opens"]
    highs   = ohlcv["highs"]
    lows    = ohlcv["lows"]
    volumes = ohlcv["volumes"]

    # ── Slice to last CHART_CANDLES ────────────────────────────────────────────
    n       = min(CHART_CANDLES, len(closes))
    closes  = closes[-n:]
    opens   = opens[-n:]
    highs   = highs[-n:]
    lows    = lows[-n:]
    volumes = volumes[-n:]

    # ── EMAs (computed on full history, then slice to chart window) ────────────
    ema9_full  = _ema(ohlcv["closes"], 9)
    ema21_full = _ema(ohlcv["closes"], 21)
    ema9_vals  = ema9_full[-n:]   if len(ema9_full)  >= n else ema9_full
    ema21_vals = ema21_full[-n:]  if len(ema21_full) >= n else ema21_full
    ema9_x     = list(range(n - len(ema9_vals),  n))
    ema21_x    = list(range(n - len(ema21_vals), n))

    # ── Resistance = highest high in older portion (excluding last 5 candles) ──
    resistance = max(highs[:-5]) if len(highs) > 5 else max(highs)

    avg_vol                = np.mean(volumes)
    breakout_vol_threshold = avg_vol * 1.5

    xs = list(range(n))

    # ── Figure layout ──────────────────────────────────────────────────────────
    fig, (ax_p, ax_v) = plt.subplots(
        2, 1,
        figsize=CHART_SIZE,
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.04},
        facecolor=BG,
    )

    for ax in (ax_p, ax_v):
        ax.set_facecolor(PANEL_BG)
        ax.tick_params(colors=TEXT_CLR, labelsize=7, length=2)
        for spine in ax.spines.values():
            spine.set_color(GRID_CLR)
        ax.yaxis.grid(True, color=GRID_CLR, linewidth=0.5, linestyle="--")
        ax.set_axisbelow(True)

    # ── Candlesticks ───────────────────────────────────────────────────────────
    for i in range(n):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        is_breakout = c > resistance and volumes[i] > breakout_vol_threshold
        if is_breakout:
            clr = GOLD
        elif c >= o:
            clr = GREEN
        else:
            clr = RED

        # Wick
        ax_p.plot([i, i], [l, h], color=clr, linewidth=0.9, zorder=2)
        # Body
        body_bot = min(o, c)
        body_h   = max(abs(c - o), (h - l) * 0.008)
        ax_p.bar(i, body_h, bottom=body_bot, color=clr, width=0.65,
                 linewidth=0, zorder=2)

    # ── EMA lines ──────────────────────────────────────────────────────────────
    ax_p.plot(ema9_x,  ema9_vals,  color=EMA9_CLR,  linewidth=1.3,
              label="EMA 9",  zorder=3)
    ax_p.plot(ema21_x, ema21_vals, color=EMA21_CLR, linewidth=1.3,
              label="EMA 21", zorder=3)

    # ── Resistance line ────────────────────────────────────────────────────────
    ax_p.hlines(resistance, 0, n - 1, colors=RES_CLR,
                linestyles="--", linewidth=1.0, zorder=3)

    # ── Buy zone (shaded band) ─────────────────────────────────────────────────
    ax_p.axhspan(sig.buy_low, sig.buy_high,
                 alpha=0.13, color=BUY_CLR, zorder=1)
    ax_p.hlines([sig.buy_low, sig.buy_high], 0, n - 1,
                colors=BUY_CLR, linewidths=0.7, zorder=3)

    # ── TP1, TP2, SL ──────────────────────────────────────────────────────────
    ax_p.hlines(sig.tp1, 0, n - 1, colors=TP1_CLR,
                linestyles="-.", linewidth=1.0, zorder=3)
    ax_p.hlines(sig.tp2, 0, n - 1, colors=TP2_CLR,
                linestyles="-.", linewidth=1.0, zorder=3)
    ax_p.hlines(sig.sl,  0, n - 1, colors=SL_CLR,
                linestyles=":",  linewidth=1.0, zorder=3)

    # ── Right-side labels ──────────────────────────────────────────────────────
    label_x = n - 0.5
    for level, label, color in [
        (sig.buy_low,  f"BUY {sig.buy_low:,.0f}",  BUY_CLR),
        (sig.buy_high, f"    {sig.buy_high:,.0f}",  BUY_CLR),
        (sig.tp1,      f"TP1 {sig.tp1:,.0f}",       TP1_CLR),
        (sig.tp2,      f"TP2 {sig.tp2:,.0f}",       TP2_CLR),
        (sig.sl,       f"SL  {sig.sl:,.0f}",        SL_CLR),
        (resistance,   f"RES {resistance:,.0f}",     RES_CLR),
    ]:
        ax_p.text(label_x + 0.2, level, label,
                  color=color, fontsize=6.2, va="center",
                  fontweight="bold", clip_on=True)

    # ── Y-axis padding so labels don't clip ────────────────────────────────────
    price_range = max(highs) - min(lows)
    ax_p.set_ylim(min(lows) - price_range * 0.05,
                  max(highs) + price_range * 0.12)
    ax_p.set_xlim(-0.5, n + 4.5)   # extra right space for labels

    # ── Title & legend ─────────────────────────────────────────────────────────
    flag_str = "  ".join(sig.flags[:3]) if sig.flags else "Momentum Signal"
    ax_p.set_title(
        f"{sig.symbol}  ·  Score {sig.score}/100  ·  {flag_str}",
        color="white", fontsize=9, fontweight="bold", pad=7,
    )

    legend_handles = [
        mpatches.Patch(color=EMA9_CLR,  label="EMA 9"),
        mpatches.Patch(color=EMA21_CLR, label="EMA 21"),
        mpatches.Patch(color=RES_CLR,   label="Resistance"),
        mpatches.Patch(color=BUY_CLR,   label="Buy Zone"),
        mpatches.Patch(color=TP1_CLR,   label="TP1"),
        mpatches.Patch(color=TP2_CLR,   label="TP2"),
        mpatches.Patch(color=SL_CLR,    label="SL"),
        mpatches.Patch(color=GOLD,      label="Breakout"),
    ]
    ax_p.legend(
        handles=legend_handles,
        loc="upper left", fontsize=5.5, ncol=4,
        facecolor="#1a1a40", edgecolor=GRID_CLR,
        labelcolor="white", framealpha=0.85,
    )

    ax_p.set_ylabel("Price (Rp)", color=TEXT_CLR, fontsize=7)
    ax_p.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"{v:,.0f}")
    )
    ax_p.set_xticks([])   # no x-axis ticks on price panel

    # ── Volume bars ────────────────────────────────────────────────────────────
    vol_colors = []
    for i in range(n):
        if volumes[i] > breakout_vol_threshold:
            vol_colors.append(GOLD)
        elif closes[i] >= opens[i]:
            vol_colors.append(GREEN)
        else:
            vol_colors.append(RED)

    ax_v.bar(xs, volumes, color=vol_colors, width=0.65, linewidth=0, alpha=0.85)
    ax_v.axhline(avg_vol, color=TEXT_CLR, linewidth=0.6,
                 linestyle="--", alpha=0.5)
    ax_v.set_xlim(-0.5, n + 4.5)
    ax_v.set_ylabel("Volume", color=TEXT_CLR, fontsize=7)
    ax_v.yaxis.set_major_formatter(
        plt.FuncFormatter(
            lambda v, _: f"{v/1_000_000:.1f}M" if v >= 1_000_000 else f"{v/1_000:.0f}K"
        )
    )
    ax_v.set_xticks(range(0, n, 5))
    ax_v.set_xticklabels(
        [f"-{n-1-i}d" for i in range(0, n, 5)],
        color=TEXT_CLR, fontsize=6,
    )

    # ── Render to bytes ────────────────────────────────────────────────────────
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=CHART_DPI,
                bbox_inches="tight", facecolor=BG)
    buf.seek(0)
    plt.close(fig)
    return buf.getvalue()
