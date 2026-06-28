"""Live fundamentals provider backed by Yahoo Finance (``yfinance``).

Works for US tickers (``MSFT``, ``NVDA``) and Indian tickers using Yahoo's
suffixes (``RELIANCE.NS`` for NSE, ``500325.BO`` for BSE). ``yfinance`` is an
optional dependency: importing this module without it raises a clear error
only when you actually try to use the provider.

Yahoo's schema shifts often, so every field is pulled defensively and falls
back to ``None`` rather than throwing. Region/currency are inferred from the
ticker suffix so the engine picks sensible India-vs-US discount defaults.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from .base import Fundamentals


def _region_for(symbol: str) -> tuple[str, str]:
    """Return (region, default_currency) inferred from the ticker suffix."""
    s = symbol.upper()
    if s.endswith(".NS") or s.endswith(".BO"):
        return "IN", "INR"
    return "US", "USD"


def _num(value: Any) -> Optional[float]:
    """Coerce to float, treating missing/NaN as None."""
    try:
        if value is None:
            return None
        f = float(value)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


class YahooProvider:
    """Fetch live :class:`Fundamentals` from Yahoo Finance."""

    name = "yahoo"

    def __init__(self) -> None:
        try:
            import yfinance  # noqa: F401
        except Exception as exc:  # pragma: no cover - depends on env
            raise RuntimeError(
                "yfinance is not installed. Run `pip install yfinance` or use "
                "the snapshot provider (--offline)."
            ) from exc

    def fetch(self, symbol: str) -> Fundamentals:  # pragma: no cover - network
        import yfinance as yf

        region, default_ccy = _region_for(symbol)
        tkr = yf.Ticker(symbol)

        info: dict = {}
        try:
            info = tkr.get_info() or {}
        except Exception:
            info = {}

        price = _num(info.get("currentPrice")) or _num(
            info.get("regularMarketPrice")
        )
        try:
            fi = tkr.fast_info
            price = price or _num(getattr(fi, "last_price", None))
        except Exception:
            pass

        cash = _num(info.get("totalCash"))
        debt = _num(info.get("totalDebt"))
        net_cash = None
        if cash is not None or debt is not None:
            net_cash = (cash or 0.0) - (debt or 0.0)

        # Prefer the explicit annual dividend rate; fall back to yield * price.
        dps = _num(info.get("dividendRate"))
        if dps is None:
            dy = _num(info.get("dividendYield"))
            if dy is not None and price is not None:
                # Yahoo reports yield as a fraction in newer versions.
                dy = dy / 100.0 if dy > 1 else dy
                dps = dy * price

        # Recent daily closes for technical signals (best-effort).
        history: list[float] = []
        try:
            hist = tkr.history(period="1y", interval="1d")
            if hist is not None and "Close" in hist:
                history = [float(x) for x in hist["Close"].dropna().tolist()]
        except Exception:
            history = []

        growth = _num(info.get("earningsGrowth")) or _num(
            info.get("revenueGrowth")
        )

        return Fundamentals(
            symbol=symbol.upper(),
            name=info.get("shortName") or info.get("longName") or symbol,
            currency=info.get("currency") or default_ccy,
            region=region,
            price=price,
            shares_outstanding=_num(info.get("sharesOutstanding")),
            free_cash_flow=_num(info.get("freeCashflow")),
            net_cash=net_cash,
            eps=_num(info.get("trailingEps")),
            book_value_per_share=_num(info.get("bookValue")),
            dividend_per_share=dps,
            beta=_num(info.get("beta")),
            growth_rate=growth,
            pe_ratio=_num(info.get("trailingPE")),
            week52_high=_num(info.get("fiftyTwoWeekHigh")),
            week52_low=_num(info.get("fiftyTwoWeekLow")),
            price_history=history,
            as_of=_dt.date.today().isoformat(),
            source="yahoo",
        )
