"""Valuation engine: run every model, blend them, attach an entry signal.

This is the single entry point the dashboard and CLI both call. Given a
:class:`Fundamentals` snapshot and a :class:`~valuation.config.Config`, it:

1. runs DCF, multiples, dividend-discount and Graham models;
2. blends the available results into one intrinsic value (config-weighted);
3. computes a fair price band and a margin-of-safety entry signal;
4. returns a structured :class:`Valuation` for display/serialisation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

from . import signals
from .config import Config
from .models import dcf, dividend, graham, multiples
from .providers.base import Fundamentals


@dataclass
class Valuation:
    symbol: str
    name: str
    currency: str
    price: Optional[float]
    intrinsic_value: Optional[float]      # blended fair value per share
    model_values: Dict[str, Optional[float]] = field(default_factory=dict)
    weights_used: Dict[str, float] = field(default_factory=dict)
    signal: Optional[signals.Signal] = None
    implied_growth: Optional[float] = None  # reverse-DCF growth the price needs
    dcf_detail: Optional[dcf.DCFResult] = None
    as_of: str = ""
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # DCFResult/Signal serialise via asdict already; trim the bulky arrays.
        if self.dcf_detail is not None:
            d["dcf_detail"] = {
                "value_per_share": self.dcf_detail.value_per_share,
                "assumptions": self.dcf_detail.assumptions,
                "note": self.dcf_detail.note,
            }
        return d


def value_stock(f: Fundamentals, cfg: Optional[Config] = None,
                **assumption_overrides: Any) -> Valuation:
    """Run all models for one company and blend them into a fair value."""
    cfg = cfg or Config.load()
    region = cfg.region_params(f.region)
    rf = region.get("risk_free", 0.043)
    erp = region.get("equity_premium", 0.05)
    term_g = region.get("terminal_growth", 0.025)
    years = cfg.get("projection_years", 10)

    # Per-ticker overrides from config, then explicit kwargs (kwargs win).
    over = cfg.overrides_for(f.symbol)
    over.update({k: v for k, v in assumption_overrides.items() if v is not None})

    dcf_res = dcf.value(
        f,
        discount_rate=over.get("discount_rate"),
        growth_stage1=over.get("growth_stage1"),
        terminal_growth=over.get("terminal_growth", term_g),
        years=over.get("years", years),
        risk_free=rf,
        equity_premium=erp,
        add_net_cash=over.get("add_net_cash", True),
    )
    mult_res = multiples.value(f, fair_pe=over.get("fair_pe"))
    ddm_res = dividend.value(f, risk_free=rf, equity_premium=erp,
                             discount_rate=over.get("discount_rate"))
    gr_res = graham.value(f, aaa_yield=over.get("aaa_yield", 0.055))

    model_values: Dict[str, Optional[float]] = {
        "dcf": dcf_res.value_per_share,
        "multiples": mult_res.value_per_share,
        "dividend": ddm_res.value_per_share,
        "graham": gr_res.value_per_share,
    }

    # Blend: keep only models that produced a positive number, re-normalise.
    base_weights = cfg.get("model_weights", {})
    usable = {
        k: v for k, v in model_values.items()
        if v is not None and v > 0 and base_weights.get(k, 0) > 0
    }
    intrinsic = None
    weights_used: Dict[str, float] = {}
    if usable:
        total_w = sum(base_weights[k] for k in usable)
        weights_used = {k: base_weights[k] / total_w for k in usable}
        intrinsic = sum(usable[k] * weights_used[k] for k in usable)

    sig = signals.evaluate(
        f.price,
        intrinsic,
        target_mos=cfg.get("target_margin_of_safety", 0.25),
        price_history=f.price_history,
        week52_high=f.week52_high,
        week52_low=f.week52_low,
    )

    implied = dcf.reverse_dcf(f, terminal_growth=over.get("terminal_growth", term_g),
                              years=over.get("years", years),
                              risk_free=rf, equity_premium=erp)

    return Valuation(
        symbol=f.symbol,
        name=f.name or f.symbol,
        currency=f.currency,
        price=f.price,
        intrinsic_value=intrinsic,
        model_values=model_values,
        weights_used=weights_used,
        signal=sig,
        implied_growth=implied,
        dcf_detail=dcf_res,
        as_of=f.as_of,
        source=f.source,
    )
