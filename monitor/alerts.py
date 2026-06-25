"""Alerting with per-metric cooldown.

Alerts are raised from two sources: threshold breaches (from
:mod:`monitor.health`) and baseline anomalies (from :mod:`monitor.baseline`).
A cooldown prevents the same metric from spamming alerts every sample.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List

from .baseline import Anomaly
from .config import Config
from .health import HealthReport, Status


@dataclass
class Alert:
    timestamp: float
    metric: str
    severity: str          # "warning" or "critical"
    source: str            # "threshold" or "anomaly"
    message: str


class AlertManager:
    """Generates alerts, applies cooldown, and logs them to a file."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.cooldown = config["alerts"]["cooldown_seconds"]
        self.log_file = config["alerts"]["log_file"]
        # metric -> last time we alerted on it.
        self._last_alert: Dict[str, float] = {}

    def process(self, health: HealthReport, anomalies: List[Anomaly],
                now: float | None = None) -> List[Alert]:
        """Return the alerts that fire this round (respecting cooldown)."""
        now = now if now is not None else time.time()
        fresh: List[Alert] = []

        for check in health.issues:
            severity = "critical" if check.status == Status.CRITICAL \
                else "warning"
            if self._should_fire(check.metric, now):
                fresh.append(Alert(now, check.metric, severity,
                                   "threshold", check.message))

        for anomaly in anomalies:
            key = f"anomaly:{anomaly.metric}"
            if self._should_fire(key, now):
                msg = (f"{anomaly.metric} = {anomaly.value:.1f} is "
                       f"{anomaly.zscore:+.1f}σ from baseline "
                       f"mean {anomaly.mean:.1f}")
                fresh.append(Alert(now, anomaly.metric, anomaly.severity,
                                   "anomaly", msg))

        if fresh:
            self._write_log(fresh)
        return fresh

    def _should_fire(self, key: str, now: float) -> bool:
        last = self._last_alert.get(key)
        if last is not None and (now - last) < self.cooldown:
            return False
        self._last_alert[key] = now
        return True

    def _write_log(self, alerts: List[Alert]) -> None:
        try:
            with open(self.log_file, "a", encoding="utf-8") as fh:
                for a in alerts:
                    stamp = time.strftime("%Y-%m-%d %H:%M:%S",
                                          time.localtime(a.timestamp))
                    fh.write(f"[{stamp}] {a.severity.upper()} "
                             f"({a.source}) {a.message}\n")
        except OSError:
            # Never let logging failure crash monitoring.
            pass
