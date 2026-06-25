"""Baseline learning and statistical anomaly detection.

A baseline is the statistical profile of "normal" for *this* machine: the
mean and standard deviation of each headline metric over its recorded
history. New readings are scored with a z-score::

    z = (value - mean) / std_dev

A large |z| means the reading is far from normal and is flagged as an
anomaly. This is more honest than fixed thresholds because it adapts to
whatever "normal" happens to be for the host.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List

from .config import Config
from .storage import HEADLINE_METRICS, Storage, flatten


@dataclass
class MetricBaseline:
    """Learned statistics for a single metric."""

    metric: str
    count: int
    mean: float
    std: float
    minimum: float
    maximum: float
    trustworthy: bool  # True once we have >= min_samples observations

    def zscore(self, value: float) -> float:
        if self.std == 0:
            return 0.0
        return (value - self.mean) / self.std


@dataclass
class Anomaly:
    """A reading that deviates significantly from the baseline."""

    metric: str
    value: float
    zscore: float
    severity: str  # "warning" or "critical"
    mean: float
    std: float


def build_baseline(storage: Storage, config: Config
                   ) -> Dict[str, MetricBaseline]:
    """Compute a baseline for every headline metric from stored history."""
    min_samples = config["anomaly"]["min_samples"]
    result: Dict[str, MetricBaseline] = {}
    for metric in HEADLINE_METRICS:
        values = storage.values_for(metric)
        result[metric] = _stats(metric, values, min_samples)
    return result


def detect_anomalies(
    snapshot: Dict[str, Any],
    baselines: Dict[str, MetricBaseline],
    config: Config,
) -> List[Anomaly]:
    """Compare a live snapshot against the baseline and flag anomalies."""
    z_warn = config["anomaly"]["z_warning"]
    z_crit = config["anomaly"]["z_critical"]
    flat = flatten(snapshot)

    anomalies: List[Anomaly] = []
    for metric, value in flat.items():
        base = baselines.get(metric)
        if base is None or not base.trustworthy:
            continue
        z = base.zscore(value)
        abs_z = abs(z)
        if abs_z >= z_crit:
            severity = "critical"
        elif abs_z >= z_warn:
            severity = "warning"
        else:
            continue
        anomalies.append(
            Anomaly(metric=metric, value=value, zscore=z,
                    severity=severity, mean=base.mean, std=base.std)
        )
    return anomalies


def _stats(metric: str, values: List[float], min_samples: int
           ) -> MetricBaseline:
    n = len(values)
    if n == 0:
        return MetricBaseline(metric, 0, 0.0, 0.0, 0.0, 0.0, False)
    mean = sum(values) / n
    if n > 1:
        variance = sum((v - mean) ** 2 for v in values) / (n - 1)
        std = math.sqrt(variance)
    else:
        std = 0.0
    return MetricBaseline(
        metric=metric,
        count=n,
        mean=mean,
        std=std,
        minimum=min(values),
        maximum=max(values),
        trustworthy=n >= min_samples,
    )
