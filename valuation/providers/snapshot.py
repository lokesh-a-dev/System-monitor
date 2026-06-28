"""Offline fundamentals provider.

Reads a bundled YAML file (default ``data/fundamentals.yaml``) so the tool
produces real valuations without any network access — useful for testing,
demos, and environments where Yahoo Finance is unreachable.

The snapshot is necessarily a point-in-time approximation. Prefer the live
:class:`~valuation.providers.yahoo.YahooProvider` for current decisions.
"""
from __future__ import annotations

import os
from typing import Dict, Optional

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - yaml is a declared dependency
    yaml = None

from .base import Fundamentals

_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data",
    "fundamentals.yaml",
)


class SnapshotProvider:
    """Serve :class:`Fundamentals` from a static YAML snapshot."""

    name = "snapshot"

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or _DEFAULT_PATH
        self._cache: Optional[Dict[str, dict]] = None

    def _load(self) -> Dict[str, dict]:
        if self._cache is not None:
            return self._cache
        if yaml is None:
            raise RuntimeError("PyYAML is required for the snapshot provider")
        if not os.path.exists(self.path):
            raise FileNotFoundError(f"snapshot file not found: {self.path}")
        with open(self.path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        # Normalise keys to upper-case for case-insensitive lookups.
        self._cache = {k.upper(): v for k, v in (raw.get("stocks") or {}).items()}
        return self._cache

    def available(self) -> list[str]:
        return sorted(self._load().keys())

    def fetch(self, symbol: str) -> Fundamentals:
        data = self._load()
        key = symbol.upper()
        if key not in data:
            raise KeyError(
                f"{symbol!r} not in snapshot ({self.path}). "
                f"Available: {', '.join(self.available())}"
            )
        row = dict(data[key])
        row.setdefault("symbol", key)
        row.setdefault("source", "snapshot")
        # Drop unknown keys so the dataclass constructor stays strict-ish.
        valid = Fundamentals.__dataclass_fields__.keys()
        clean = {k: _coerce(k, v) for k, v in row.items() if k in valid}
        return Fundamentals(**clean)


# Numeric fields that may arrive as strings (e.g. YAML "7.43e9", which PyYAML
# treats as a string because the exponent is unsigned).
_NUMERIC_FIELDS = {
    "price", "shares_outstanding", "free_cash_flow", "net_cash", "eps",
    "book_value_per_share", "dividend_per_share", "beta", "growth_rate",
    "pe_ratio", "fcf_growth_5y", "week52_high", "week52_low",
}


def _coerce(key: str, value):
    if key in _NUMERIC_FIELDS and isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return value
