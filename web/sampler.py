"""Background sampling thread for the web dashboard.

The web server can't block on metric collection per request, so a daemon
thread samples on the configured interval, writes history to SQLite, and
keeps the latest computed state (snapshot + health + anomalies) in memory
behind a lock for instant reads. The baseline is rebuilt periodically as
history grows.
"""
from __future__ import annotations

import threading
import time
from dataclasses import asdict
from typing import Any, Dict, List

from monitor import baseline as baseline_mod
from monitor import collectors
from monitor.alerts import Alert, AlertManager
from monitor.config import Config
from monitor.health import HealthReport, evaluate
from monitor.storage import Storage


class Sampler:
    """Owns the write connection and the in-memory latest state."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._snapshot: Dict[str, Any] | None = None
        self._health: HealthReport | None = None
        self._anomalies: list = []
        self._baselines: Dict[str, Any] = {}
        self._recent_alerts: List[Alert] = []

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="metric-sampler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        collectors.prime()
        # This thread owns its own DB connection.
        storage = Storage(self.config["database"])
        alert_mgr = AlertManager(self.config)
        self._baselines = baseline_mod.build_baseline(storage, self.config)
        last_rebuild = 0.0
        last_prune = time.time()

        # Take an immediate first reading so the UI isn't empty on load.
        time.sleep(0.3)
        self._sample_once(storage, alert_mgr)

        interval = self.config["interval"]
        while not self._stop.wait(interval):
            now = self._sample_once(storage, alert_mgr)
            if now - last_rebuild > 60:
                self._baselines = baseline_mod.build_baseline(
                    storage, self.config)
                last_rebuild = now
            if self.config["retention_days"] and now - last_prune > 3600:
                storage.prune(self.config["retention_days"])
                last_prune = now
        storage.close()

    def _sample_once(self, storage: Storage, alert_mgr: AlertManager) -> float:
        snapshot = collectors.collect_all()
        storage.record(snapshot)
        health = evaluate(snapshot, self.config)
        anomalies = baseline_mod.detect_anomalies(
            snapshot, self._baselines, self.config)
        fired = alert_mgr.process(health, anomalies)
        with self._lock:
            self._snapshot = snapshot
            self._health = health
            self._anomalies = anomalies
            if fired:
                self._recent_alerts = (fired + self._recent_alerts)[:50]
        return snapshot["timestamp"]

    # -- read API (called from Flask request threads) ------------------------

    def current_state(self) -> Dict[str, Any]:
        """Latest snapshot, health verdict and anomalies as plain JSON."""
        with self._lock:
            snapshot = self._snapshot
            health = self._health
            anomalies = list(self._anomalies)
        if snapshot is None or health is None:
            return {"ready": False}
        return {
            "ready": True,
            "snapshot": snapshot,
            "health": {
                "score": health.score,
                "overall": health.overall.label,
                "checks": [
                    {"metric": c.metric, "value": c.value,
                     "status": c.status.label, "message": c.message}
                    for c in health.checks
                ],
            },
            "anomalies": [asdict(a) for a in anomalies],
        }

    def recent_alerts(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [asdict(a) for a in self._recent_alerts]

    def baseline(self) -> Dict[str, Any]:
        with self._lock:
            return {m: asdict(b) for m, b in self._baselines.items()}
