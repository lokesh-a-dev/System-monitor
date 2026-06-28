"""Dividend Discount Model (Gordon growth).

Values a share as the present value of a perpetually growing dividend:

    V = D1 / (r - g)      where D1 = D0 * (1 + g)

Only meaningful for established dividend payers; returns ``None`` for
non-payers or when growth would exceed the discount rate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..providers.base import Fundamentals
from .dcf import cost_of_equity


@dataclass
class DDMResult:
    value_per_share: Optional[float]
    assumptions: dict
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.value_per_share is not None


def value(
    f: Fundamentals,
    *,
    discount_rate: Optional[float] = None,
    growth: Optional[float] = None,
    risk_free: float = 0.043,
    equity_premium: float = 0.05,
    min_yield: float = 0.015,
) -> DDMResult:
    if not f.dividend_per_share or f.dividend_per_share <= 0:
        return DDMResult(None, {}, note="no dividend")
    # DDM is only a sensible basis for real dividend payers. For low-yield
    # growth names the payout is incidental, so skip it rather than let a tiny
    # dividend understate intrinsic value.
    if f.price and (f.dividend_per_share / f.price) < min_yield:
        return DDMResult(None, {}, note=f"yield below {min_yield*100:.0f}% — DDM skipped")

    r = discount_rate if discount_rate is not None else cost_of_equity(
        f.beta, risk_free, equity_premium
    )
    # Dividend growth: a fraction of earnings growth, capped well below r.
    if growth is None:
        base = f.growth_rate if f.growth_rate is not None else 0.05
        growth = max(min(base * 0.5, r - 0.01, 0.08), 0.0)
    if r <= growth:
        return DDMResult(None, {}, note="growth >= discount rate")

    d1 = f.dividend_per_share * (1 + growth)
    return DDMResult(
        value_per_share=d1 / (r - growth),
        assumptions={"discount_rate": r, "growth": growth,
                     "dividend": f.dividend_per_share},
    )
