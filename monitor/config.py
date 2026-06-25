"""Configuration loading and defaults.

Thresholds and intervals live here so behaviour can be tuned without
touching code. A YAML file (``config.yaml``) overrides these defaults.
"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from typing import Any, Dict

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - yaml is a declared dependency
    yaml = None


# Default configuration. Every value here can be overridden by config.yaml.
DEFAULTS: Dict[str, Any] = {
    # How often (seconds) to sample metrics in live/collect modes.
    "interval": 2.0,
    # SQLite database file for the time-series history.
    "database": "monitor_history.db",
    # How many days of history to keep; older rows are pruned.
    "retention_days": 7,
    # Thresholds drive the healthy/warning/critical status of each metric.
    # Each is a percentage (0-100) unless noted.
    "thresholds": {
        "cpu_percent": {"warning": 70, "critical": 90},
        "memory_percent": {"warning": 75, "critical": 90},
        "swap_percent": {"warning": 50, "critical": 80},
        "disk_percent": {"warning": 80, "critical": 95},
        # Load average per core (1.0 == fully loaded core).
        "load_per_core": {"warning": 1.0, "critical": 2.0},
        # CPU temperature in Celsius (skipped if sensor unavailable).
        "temperature": {"warning": 75, "critical": 90},
    },
    # Anomaly detection: how many standard deviations from the learned
    # baseline mean counts as an anomaly.
    "anomaly": {
        "z_warning": 2.5,
        "z_critical": 3.5,
        # Minimum samples before a baseline is considered trustworthy.
        "min_samples": 30,
    },
    # Alerting behaviour.
    "alerts": {
        # Suppress repeat alerts for the same metric within this many seconds.
        "cooldown_seconds": 60,
        "log_file": "alerts.log",
    },
}


@dataclass
class Config:
    """Resolved configuration object with convenient accessors."""

    data: Dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULTS))

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        """Load config from *path*, deep-merging over the defaults."""
        cfg = copy.deepcopy(DEFAULTS)
        if path and os.path.exists(path) and yaml is not None:
            with open(path, "r", encoding="utf-8") as fh:
                user = yaml.safe_load(fh) or {}
            _deep_merge(cfg, user)
        return cls(data=cfg)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> None:
    """Recursively merge *overlay* into *base* in place."""
    for key, value in overlay.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
        ):
            _deep_merge(base[key], value)
        else:
            base[key] = value
