"""Stock intrinsic-value & fair-price toolkit.

A personal-use valuation engine that blends a two-stage DCF with dividend
discount, multiples and Graham models, then derives a margin-of-safety entry
point. Works for US tickers and Indian (NSE/BSE) tickers via Yahoo Finance,
with an offline snapshot fallback.

Quick start::

    from valuation.providers import get_provider
    from valuation.engine import value_stock

    f = get_provider("offline").fetch("MSFT")
    v = value_stock(f)
    print(v.intrinsic_value, v.signal.rating)
"""
from __future__ import annotations

from .config import Config
from .engine import Valuation, value_stock
from .providers import Fundamentals, get_provider

__all__ = ["Config", "Valuation", "value_stock", "Fundamentals", "get_provider"]
