"""Health analysis: turn raw metrics into status levels and a score.

A snapshot is evaluated metric-by-metric against the configured thresholds.
Each metric gets a status (HEALTHY / WARNING / CRITICAL) and the worst
statuses drive an overall 0-100 health score.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, List

from .config import Config


class Status(IntEnum):
    """Ordered so that ``max()`` yields the most severe status."""

    HEALTHY = 0
    WARNING = 1
    CRITICAL = 2

    @property
    def label(self) -> str:
        return {0: "HEALTHY", 1: "WARNING", 2: "CRITICAL"}[int(self)]


@dataclass
class Check:
    """The result of evaluating one metric against its thresholds."""

    metric: str
    value: float
    status: Status
    message: str


@dataclass
class HealthReport:
    """Aggregate health for a snapshot."""

    score: int
    overall: Status
    checks: List[Check]

    @property
    def issues(self) -> List[Check]:
        return [c for c in self.checks if c.status != Status.HEALTHY]


# Maps a threshold config key to the (snapshot path, label) it evaluates.
_METRIC_SPECS = [
    ("cpu_percent", ("cpu", "percent"), "CPU usage"),
    ("memory_percent", ("memory", "percent"), "Memory usage"),
    ("swap_percent", ("memory", "swap_percent"), "Swap usage"),
    ("disk_percent", ("disk", "max_percent"), "Disk usage"),
    ("load_per_core", ("cpu", "load_per_core"), "Load per core"),
    ("temperature", ("cpu", "temperature"), "CPU temperature"),
]


def evaluate(snapshot: Dict[str, Any], config: Config) -> HealthReport:
    """Evaluate *snapshot* and return a :class:`HealthReport`."""
    thresholds = config["thresholds"]
    checks: List[Check] = []

    for key, path, label in _METRIC_SPECS:
        value = _dig(snapshot, path)
        if value is None:  # e.g. temperature with no sensor
            continue
        limits = thresholds.get(key)
        if not limits:
            continue
        status = _classify(value, limits["warning"], limits["critical"])
        unit = "C" if key == "temperature" else (
            "" if key == "load_per_core" else "%")
        checks.append(
            Check(
                metric=key,
                value=value,
                status=status,
                message=f"{label} at {value:.1f}{unit}"
                + ("" if status == Status.HEALTHY else f" ({status.label})"),
            )
        )

    overall = max((c.status for c in checks), default=Status.HEALTHY)
    return HealthReport(score=_score(checks), overall=overall, checks=checks)


def _classify(value: float, warning: float, critical: float) -> Status:
    if value >= critical:
        return Status.CRITICAL
    if value >= warning:
        return Status.WARNING
    return Status.HEALTHY


def _score(checks: List[Check]) -> int:
    """Compute a 0-100 score by penalising warnings and criticals.

    Each warning costs 10 points, each critical 25. Clamped to [0, 100].
    """
    penalty = sum(
        10 if c.status == Status.WARNING else 25 if c.status == Status.CRITICAL
        else 0
        for c in checks
    )
    return max(0, 100 - penalty)


def _dig(data: Dict[str, Any], path: tuple[str, ...]) -> Any:
    """Walk a nested dict by *path*, returning None if any key is missing."""
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur
