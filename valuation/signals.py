"""Entry-point signals.

Combines a *value* signal (margin of safety vs. intrinsic value) with a
*technical* signal (trend + momentum from price history) into a single,
plain-English recommendation and a suggested buy-below price.

Nothing here is investment advice — it's a transparent rule set you can tune.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Signal:
    rating: str                      # STRONG BUY / BUY / HOLD / OVERVALUED / SELL
    margin_of_safety: Optional[float]  # (intrinsic - price) / intrinsic
    buy_below: Optional[float]       # price giving the target margin of safety
    upside: Optional[float]          # (intrinsic - price) / price
    technical: str = "n/a"           # trend/momentum summary
    rsi: Optional[float] = None
    sma50: Optional[float] = None
    sma200: Optional[float] = None
    week52_position: Optional[float] = None  # 0=at low, 1=at high
    reasons: List[str] = field(default_factory=list)


def _sma(values: List[float], window: int) -> Optional[float]:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def rsi(values: List[float], period: int = 14) -> Optional[float]:
    """Wilder's RSI over the most recent ``period`` changes."""
    if len(values) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(-period, 0):
        change = values[i] - values[i - 1]
        if change >= 0:
            gains += change
        else:
            losses -= change
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1 + rs))


def evaluate(
    price: Optional[float],
    intrinsic: Optional[float],
    *,
    target_mos: float = 0.25,
    price_history: Optional[List[float]] = None,
    week52_high: Optional[float] = None,
    week52_low: Optional[float] = None,
) -> Signal:
    """Produce an entry-point :class:`Signal`.

    ``target_mos`` is the margin of safety you want before buying (default
    25%); ``buy_below`` is the price that delivers it.
    """
    reasons: List[str] = []
    mos = upside = buy_below = None
    rating = "N/A"

    if price and intrinsic and intrinsic > 0:
        mos = (intrinsic - price) / intrinsic
        upside = (intrinsic - price) / price
        buy_below = intrinsic * (1 - target_mos)
        if price < intrinsic * (1 - target_mos):
            rating = "STRONG BUY"
            reasons.append(
                f"Trades {mos*100:.0f}% below intrinsic value (>{target_mos*100:.0f}% margin of safety)."
            )
        elif price < intrinsic:
            rating = "BUY"
            reasons.append(f"Below intrinsic value with a {mos*100:.0f}% margin of safety.")
        elif price < intrinsic * 1.15:
            rating = "HOLD"
            reasons.append("Trading near fair value (within 15%).")
        elif price < intrinsic * 1.35:
            rating = "OVERVALUED"
            reasons.append(f"About {(-mos)*100:.0f}% above intrinsic value.")
        else:
            rating = "SELL"
            reasons.append(f"Roughly {(-mos)*100:.0f}% above intrinsic value.")

    # Technical context (best-effort; informational, not part of the rating).
    hist = price_history or []
    r = rsi(hist)
    sma50 = _sma(hist, 50)
    sma200 = _sma(hist, 200)
    tech_bits: List[str] = []
    if sma50 and sma200:
        if sma50 > sma200:
            tech_bits.append("uptrend (50d > 200d)")
        else:
            tech_bits.append("downtrend (50d < 200d)")
    if r is not None:
        if r < 30:
            tech_bits.append(f"oversold (RSI {r:.0f})")
        elif r > 70:
            tech_bits.append(f"overbought (RSI {r:.0f})")
        else:
            tech_bits.append(f"neutral momentum (RSI {r:.0f})")
    technical = ", ".join(tech_bits) if tech_bits else "n/a"

    week52_position = None
    if week52_high and week52_low and price and week52_high > week52_low:
        week52_position = (price - week52_low) / (week52_high - week52_low)

    return Signal(
        rating=rating,
        margin_of_safety=mos,
        buy_below=buy_below,
        upside=upside,
        technical=technical,
        rsi=r,
        sma50=sma50,
        sma200=sma200,
        week52_position=week52_position,
        reasons=reasons,
    )
