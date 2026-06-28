"""Data provider abstraction.

A *provider* turns a ticker symbol into a :class:`Fundamentals` snapshot —
the handful of inputs every valuation model needs. Two concrete providers
ship with the tool:

* :class:`~valuation.providers.yahoo.YahooProvider` — live data from Yahoo
  Finance via ``yfinance`` (US tickers like ``MSFT`` and Indian tickers like
  ``RELIANCE.NS``).
* :class:`~valuation.providers.snapshot.SnapshotProvider` — offline figures
  bundled in ``data/fundamentals.yaml`` so the tool runs (and tests) with no
  network access.

Keeping models behind this interface means the DCF/DDM/multiples code never
talks to a network and is therefore trivial to unit-test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Protocol


@dataclass
class Fundamentals:
    """Everything the valuation models need about one company.

    Monetary fields are in the company's *reporting currency* and in absolute
    units (not millions/billions) unless the name says otherwise. Per-share
    fields are obviously per share. Any field may be ``None`` when a source
    cannot supply it — models skip gracefully when an input is missing.
    """

    symbol: str
    name: str = ""
    currency: str = "USD"
    region: str = "US"  # "US" or "IN"; drives default discount/terminal rates

    price: Optional[float] = None              # current share price
    shares_outstanding: Optional[float] = None  # diluted share count

    free_cash_flow: Optional[float] = None     # levered (to-equity) FCF, TTM
    net_cash: Optional[float] = None           # cash & equivalents minus total debt
    eps: Optional[float] = None                # trailing EPS
    book_value_per_share: Optional[float] = None
    dividend_per_share: Optional[float] = None  # trailing annual dividend

    beta: Optional[float] = None
    growth_rate: Optional[float] = None        # expected stage-1 growth (decimal)
    pe_ratio: Optional[float] = None
    fcf_growth_5y: Optional[float] = None      # historical FCF CAGR (decimal)

    # Optional price history for technical signals: most-recent-last closes.
    price_history: List[float] = field(default_factory=list)

    week52_high: Optional[float] = None
    week52_low: Optional[float] = None

    as_of: str = ""        # ISO date the data represents
    source: str = ""       # provider label, e.g. "yahoo" / "snapshot"

    @property
    def market_cap(self) -> Optional[float]:
        if self.price is None or self.shares_outstanding is None:
            return None
        return self.price * self.shares_outstanding


class Provider(Protocol):
    """Anything that can produce a :class:`Fundamentals` for a symbol."""

    name: str

    def fetch(self, symbol: str) -> Fundamentals:  # pragma: no cover - protocol
        ...
