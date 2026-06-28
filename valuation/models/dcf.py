"""Discounted-cash-flow valuation (two-stage FCFE).

Approach
--------
1. Project levered free cash flow for ``years`` periods. Growth starts at
   ``growth_stage1`` and fades linearly to ``terminal_growth`` over the
   horizon (a smoother, less aggressive assumption than a flat high rate).
2. Discount each year's FCF at the cost of equity.
3. Add a Gordon-growth terminal value at the end of the horizon, discounted
   back to today.
4. The sum is the equity value of the operating business. Optionally add
   ``net_cash`` (cash minus debt) to credit/charge the balance sheet, then
   divide by shares for intrinsic value per share.

Discounting *levered* FCF at the cost of equity yields an equity value
directly (an FCFE model), which keeps the per-share math transparent for a
personal tool. Every assumption is an explicit, overridable input.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ..providers.base import Fundamentals


@dataclass
class DCFResult:
    value_per_share: Optional[float]
    equity_value: Optional[float]
    terminal_value_pv: Optional[float]
    projected_fcf: List[float] = field(default_factory=list)
    discounted_fcf: List[float] = field(default_factory=list)
    assumptions: dict = field(default_factory=dict)
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.value_per_share is not None


def cost_of_equity(beta: Optional[float], risk_free: float, equity_premium: float,
                   floor: float = 0.075) -> float:
    """CAPM cost of equity with a sensible floor."""
    b = beta if beta is not None else 1.0
    return max(floor, risk_free + b * equity_premium)


def two_stage_fcfe(
    fcf0: float,
    shares: float,
    discount_rate: float,
    growth_stage1: float,
    terminal_growth: float,
    years: int = 10,
    net_cash: float = 0.0,
    add_net_cash: bool = True,
) -> DCFResult:
    """Core two-stage DCF math (pure function, no I/O)."""
    if fcf0 is None or shares in (None, 0) or shares <= 0:
        return DCFResult(None, None, None, note="missing FCF or shares")
    if discount_rate <= terminal_growth:
        return DCFResult(
            None, None, None,
            note="discount rate must exceed terminal growth",
        )

    projected: List[float] = []
    discounted: List[float] = []
    fcf = float(fcf0)
    for t in range(1, years + 1):
        # Linear fade of the growth rate from stage 1 to terminal.
        frac = (t - 1) / max(1, years - 1)
        g = growth_stage1 + (terminal_growth - growth_stage1) * frac
        fcf = fcf * (1 + g)
        projected.append(fcf)
        discounted.append(fcf / (1 + discount_rate) ** t)

    terminal = projected[-1] * (1 + terminal_growth) / (discount_rate - terminal_growth)
    terminal_pv = terminal / (1 + discount_rate) ** years

    equity_value = sum(discounted) + terminal_pv
    if add_net_cash:
        equity_value += net_cash or 0.0

    return DCFResult(
        value_per_share=equity_value / shares,
        equity_value=equity_value,
        terminal_value_pv=terminal_pv,
        projected_fcf=projected,
        discounted_fcf=discounted,
        assumptions={
            "fcf0": fcf0,
            "discount_rate": discount_rate,
            "growth_stage1": growth_stage1,
            "terminal_growth": terminal_growth,
            "years": years,
            "net_cash": net_cash,
            "add_net_cash": add_net_cash,
        },
    )


def value(
    f: Fundamentals,
    *,
    discount_rate: Optional[float] = None,
    growth_stage1: Optional[float] = None,
    terminal_growth: Optional[float] = None,
    years: int = 10,
    risk_free: float = 0.043,
    equity_premium: float = 0.05,
    add_net_cash: bool = True,
) -> DCFResult:
    """Value a company from its :class:`Fundamentals` with sane defaults."""
    if f.free_cash_flow is None or not f.shares_outstanding:
        return DCFResult(None, None, None, note="no FCF / shares in data")

    dr = discount_rate if discount_rate is not None else cost_of_equity(
        f.beta, risk_free, equity_premium
    )
    if terminal_growth is None:
        terminal_growth = 0.045 if f.region == "IN" else 0.025
    if growth_stage1 is None:
        growth_stage1 = (
            f.growth_rate
            if f.growth_rate is not None
            else (f.fcf_growth_5y if f.fcf_growth_5y is not None else 0.10)
        )
    # Cap absurd extrapolations: nobody compounds 60% for a decade.
    growth_stage1 = max(min(growth_stage1, 0.30), -0.10)

    return two_stage_fcfe(
        fcf0=f.free_cash_flow,
        shares=f.shares_outstanding,
        discount_rate=dr,
        growth_stage1=growth_stage1,
        terminal_growth=terminal_growth,
        years=years,
        net_cash=f.net_cash or 0.0,
        add_net_cash=add_net_cash,
    )


def reverse_dcf(
    f: Fundamentals,
    *,
    discount_rate: Optional[float] = None,
    terminal_growth: Optional[float] = None,
    years: int = 10,
    risk_free: float = 0.043,
    equity_premium: float = 0.05,
) -> Optional[float]:
    """Solve for the stage-1 growth the *current price* implies.

    Answers "what must this company grow at to justify today's price?" — a
    quick sanity check on whether the market's expectations look reasonable.
    Returns the implied annual growth (decimal) or ``None``.
    """
    if f.price is None or f.free_cash_flow is None or not f.shares_outstanding:
        return None
    dr = discount_rate if discount_rate is not None else cost_of_equity(
        f.beta, risk_free, equity_premium
    )
    tg = terminal_growth if terminal_growth is not None else (
        0.045 if f.region == "IN" else 0.025
    )
    target = f.price
    lo, hi = -0.20, 0.60
    for _ in range(100):  # bisection
        mid = (lo + hi) / 2
        r = two_stage_fcfe(
            f.free_cash_flow, f.shares_outstanding, dr, mid, tg, years,
            f.net_cash or 0.0, True,
        )
        if r.value_per_share is None:
            return None
        if r.value_per_share > target:
            hi = mid
        else:
            lo = mid
    return round((lo + hi) / 2, 4)
