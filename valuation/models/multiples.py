"""Relative (multiples) valuation.

Estimates fair value by applying a "fair" earnings multiple to trailing EPS:

    fair_value = fair_pe * eps

``fair_pe`` defaults to a PEG-anchored multiple (PEG = 1.5 → fair P/E roughly
1.5 x growth%), bounded to a reasonable band so a hyper-growth input doesn't
produce a nonsensical multiple. Override ``fair_pe`` to pin a sector or
historical-median multiple instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..providers.base import Fundamentals


@dataclass
class MultiplesResult:
    value_per_share: Optional[float]
    fair_pe: Optional[float]
    assumptions: dict
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.value_per_share is not None


def value(
    f: Fundamentals,
    *,
    fair_pe: Optional[float] = None,
    peg: float = 1.5,
    pe_floor: float = 8.0,
    pe_cap: float = 45.0,
) -> MultiplesResult:
    if f.eps is None or f.eps <= 0:
        return MultiplesResult(None, None, {}, note="no positive EPS")

    if fair_pe is None:
        growth_pct = (f.growth_rate or 0.08) * 100.0
        fair_pe = max(pe_floor, min(pe_cap, peg * growth_pct))

    return MultiplesResult(
        value_per_share=fair_pe * f.eps,
        fair_pe=fair_pe,
        assumptions={"fair_pe": fair_pe, "eps": f.eps, "peg": peg},
    )
