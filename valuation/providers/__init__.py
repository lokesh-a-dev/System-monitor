"""Fundamentals data providers (live Yahoo + offline snapshot)."""
from __future__ import annotations

from .base import Fundamentals, Provider
from .snapshot import SnapshotProvider


def get_provider(name: str = "auto", **kwargs):
    """Return a provider instance.

    ``"yahoo"`` / ``"live"`` → live Yahoo Finance.
    ``"snapshot"`` / ``"offline"`` → bundled YAML snapshot.
    ``"auto"`` → try Yahoo, fall back to the snapshot if yfinance is missing.
    """
    name = (name or "auto").lower()
    if name in {"snapshot", "offline"}:
        return SnapshotProvider(**kwargs)
    if name in {"yahoo", "live"}:
        from .yahoo import YahooProvider

        return YahooProvider()
    # auto
    try:
        from .yahoo import YahooProvider

        return YahooProvider()
    except Exception:
        return SnapshotProvider(**kwargs)


__all__ = ["Fundamentals", "Provider", "SnapshotProvider", "get_provider"]
