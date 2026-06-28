"""Watchlist and global assumptions for the valuation tool.

Loads ``watchlist.yaml`` (override with ``$VALUATION_CONFIG``) and merges it
over built-in defaults — same pattern as the system-monitor's config. The
watchlist is fully user-editable: add any Yahoo ticker (``MSFT``,
``RELIANCE.NS``) and optional per-ticker assumption overrides.
"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

_REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
_DEFAULT_PATH = os.environ.get(
    "VALUATION_CONFIG", os.path.join(_REPO_ROOT, "watchlist.yaml")
)

DEFAULTS: Dict[str, Any] = {
    # Tickers to value by default (Yahoo symbols). Indian: append .NS / .BO.
    "watchlist": ["MSFT", "META", "GOOGL", "NVDA"],
    # Margin of safety you want before buying (drives the buy-below price).
    "target_margin_of_safety": 0.25,
    # DCF projection horizon in years.
    "projection_years": 10,
    # Weights for blending model outputs into one intrinsic value. Models
    # with no data are dropped and the remaining weights re-normalised.
    "model_weights": {
        "dcf": 0.50,
        "multiples": 0.25,
        "dividend": 0.15,
        "graham": 0.10,
    },
    # Market assumptions by region. CAPM: r = risk_free + beta * equity_premium.
    "regions": {
        "US": {"risk_free": 0.043, "equity_premium": 0.05, "terminal_growth": 0.025},
        "IN": {"risk_free": 0.068, "equity_premium": 0.055, "terminal_growth": 0.045},
    },
    # Per-ticker assumption overrides, e.g. {"NVDA": {"growth_stage1": 0.25}}.
    "overrides": {},
}


@dataclass
class Config:
    data: Dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULTS))

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        cfg = copy.deepcopy(DEFAULTS)
        path = path or _DEFAULT_PATH
        if path and os.path.exists(path) and yaml is not None:
            with open(path, "r", encoding="utf-8") as fh:
                user = yaml.safe_load(fh) or {}
            _deep_merge(cfg, user)
        return cls(data=cfg)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    @property
    def watchlist(self) -> List[str]:
        return list(self.data.get("watchlist", []))

    def region_params(self, region: str) -> Dict[str, Any]:
        regions = self.data.get("regions", {})
        return regions.get(region, regions.get("US", {}))

    def overrides_for(self, symbol: str) -> Dict[str, Any]:
        return dict(self.data.get("overrides", {}).get(symbol.upper(), {}))


def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> None:
    for key, value in overlay.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
