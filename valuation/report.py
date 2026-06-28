"""Render :class:`~valuation.engine.Valuation` objects as text.

Uses ``rich`` for colour tables when available (already a project dependency)
and degrades to plain text otherwise.
"""
from __future__ import annotations

from typing import List, Optional

from .engine import Valuation

try:
    from rich.console import Console
    from rich.table import Table
    _RICH = True
except Exception:  # pragma: no cover
    _RICH = False

_RATING_STYLE = {
    "STRONG BUY": "bold green",
    "BUY": "green",
    "HOLD": "yellow",
    "OVERVALUED": "red",
    "SELL": "bold red",
    "N/A": "dim",
}


def _fmt(value: Optional[float], currency: str = "") -> str:
    if value is None:
        return "—"
    sym = {"USD": "$", "INR": "₹"}.get(currency, "")
    return f"{sym}{value:,.2f}"


def _pct(value: Optional[float]) -> str:
    return "—" if value is None else f"{value*100:+.1f}%"


def summary_table(results: List[Valuation]) -> None:
    """Print a one-row-per-stock comparison table."""
    if _RICH:
        console = Console()
        table = Table(title="Intrinsic Value & Entry Signals", header_style="bold cyan")
        for col in ("Ticker", "Price", "Fair value", "Upside", "Margin",
                    "Buy below", "Signal"):
            table.add_column(col)
        for v in results:
            sig = v.signal
            rating = sig.rating if sig else "N/A"
            table.add_row(
                f"{v.symbol}",
                _fmt(v.price, v.currency),
                _fmt(v.intrinsic_value, v.currency),
                _pct(sig.upside if sig else None),
                _pct(sig.margin_of_safety if sig else None),
                _fmt(sig.buy_below if sig else None, v.currency),
                f"[{_RATING_STYLE.get(rating, 'white')}]{rating}[/]",
            )
        console.print(table)
    else:
        print(f"{'Ticker':<12}{'Price':>12}{'Fair':>12}{'Upside':>10}{'Signal':>14}")
        for v in results:
            sig = v.signal
            print(f"{v.symbol:<12}{_fmt(v.price, v.currency):>12}"
                  f"{_fmt(v.intrinsic_value, v.currency):>12}"
                  f"{_pct(sig.upside if sig else None):>10}"
                  f"{(sig.rating if sig else 'N/A'):>14}")


def detail(v: Valuation) -> None:
    """Print a full breakdown for one stock."""
    print(f"\n=== {v.symbol} — {v.name} ({v.currency}) ===")
    print(f"  Data: {v.source or 'n/a'} as of {v.as_of or 'n/a'}")
    print(f"  Price:          {_fmt(v.price, v.currency)}")
    print(f"  Intrinsic value:{_fmt(v.intrinsic_value, v.currency)}  (blended)")
    print("  Model estimates:")
    for model, val in v.model_values.items():
        w = v.weights_used.get(model)
        wtxt = f"  (weight {w*100:.0f}%)" if w else "  (excluded)"
        print(f"    - {model:<10}{_fmt(val, v.currency)}{wtxt}")
    if v.implied_growth is not None:
        print(f"  Price implies stage-1 growth of {v.implied_growth*100:.1f}%/yr (reverse DCF)")
    sig = v.signal
    if sig:
        print(f"  Signal: {sig.rating}")
        if sig.buy_below is not None:
            print(f"    Buy below {_fmt(sig.buy_below, v.currency)} "
                  f"(margin of safety target)")
        if sig.upside is not None:
            print(f"    Upside to fair value: {_pct(sig.upside)}")
        if sig.technical != "n/a":
            print(f"    Technical: {sig.technical}")
        if sig.week52_position is not None:
            print(f"    52-week range position: {sig.week52_position*100:.0f}%")
        for reason in sig.reasons:
            print(f"    • {reason}")
