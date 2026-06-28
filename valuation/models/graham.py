"""Benjamin Graham valuations.

Two classic, conservative yardsticks:

* **Graham number** — ``sqrt(22.5 * EPS * BVPS)``. The 22.5 encodes Graham's
  rule of thumb that P/E x P/B should not exceed 22.5 (15 x 1.5). A pure
  asset/earnings floor; ignores growth, so it reads low for asset-light
  compounders.
* **Revised Graham formula** — ``EPS * (8.5 + 2g) * 4.4 / Y``, where ``g`` is
  the expected growth percent and ``Y`` is the current AAA corporate bond
  yield. Adds a growth term and a discount-rate adjustment.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from ..providers.base import Fundamentals


@dataclass
class GrahamResult:
    graham_number: Optional[float]
    revised_value: Optional[float]
    note: str = ""

    @property
    def value_per_share(self) -> Optional[float]:
        # Prefer the growth-aware revised formula when available.
        return self.revised_value if self.revised_value is not None else self.graham_number

    @property
    def ok(self) -> bool:
        return self.value_per_share is not None


def value(f: Fundamentals, *, aaa_yield: float = 0.055) -> GrahamResult:
    graham_number = None
    if f.eps and f.eps > 0 and f.book_value_per_share and f.book_value_per_share > 0:
        graham_number = math.sqrt(22.5 * f.eps * f.book_value_per_share)

    revised = None
    if f.eps and f.eps > 0:
        g_pct = (f.growth_rate or 0.05) * 100.0
        g_pct = min(g_pct, 20.0)  # Graham capped growth optimism
        revised = f.eps * (8.5 + 2 * g_pct) * 4.4 / (aaa_yield * 100.0)

    note = "" if (graham_number or revised) else "needs positive EPS"
    return GrahamResult(graham_number=graham_number, revised_value=revised, note=note)
