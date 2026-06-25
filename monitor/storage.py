"""Time-series storage backed by SQLite.

We flatten each snapshot into a handful of headline numeric metrics and
store one row per metric per sample. This keeps the schema simple and makes
baseline statistics a single ``GROUP BY metric`` query. The full raw snapshot
is also stored as JSON for richer reporting.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, Iterable, List, Tuple

# The headline numeric metrics we track over time for baselining.
HEADLINE_METRICS = (
    "cpu_percent",
    "memory_percent",
    "swap_percent",
    "disk_percent",
    "load_per_core",
    "net_bytes_sent",
    "net_bytes_recv",
    "process_count",
)


class Storage:
    """Lightweight SQLite wrapper for metric history."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS metrics (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL    NOT NULL,
                metric    TEXT    NOT NULL,
                value     REAL    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_metric_time
                ON metrics (metric, timestamp);

            CREATE TABLE IF NOT EXISTS snapshots (
                timestamp REAL PRIMARY KEY,
                data      TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def record(self, snapshot: Dict[str, Any]) -> None:
        """Persist the headline metrics and the raw snapshot."""
        ts = snapshot["timestamp"]
        rows = [(ts, name, float(value))
                for name, value in flatten(snapshot).items()]
        self.conn.executemany(
            "INSERT INTO metrics (timestamp, metric, value) VALUES (?, ?, ?)",
            rows,
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO snapshots (timestamp, data) VALUES (?, ?)",
            (ts, json.dumps(snapshot)),
        )
        self.conn.commit()

    def values_for(self, metric: str, since: float | None = None
                   ) -> List[float]:
        """Return all stored values for *metric*, optionally since a time."""
        if since is None:
            cur = self.conn.execute(
                "SELECT value FROM metrics WHERE metric = ? ORDER BY timestamp",
                (metric,),
            )
        else:
            cur = self.conn.execute(
                "SELECT value FROM metrics WHERE metric = ? AND timestamp >= ? "
                "ORDER BY timestamp",
                (metric, since),
            )
        return [row["value"] for row in cur.fetchall()]

    def all_metric_values(self, since: float | None = None
                          ) -> Dict[str, List[float]]:
        """Return {metric: [values...]} for every tracked metric."""
        return {m: self.values_for(m, since) for m in HEADLINE_METRICS}

    def latest_snapshot(self) -> Dict[str, Any] | None:
        cur = self.conn.execute(
            "SELECT data FROM snapshots ORDER BY timestamp DESC LIMIT 1"
        )
        row = cur.fetchone()
        return json.loads(row["data"]) if row else None

    def sample_count(self) -> int:
        cur = self.conn.execute("SELECT COUNT(*) AS n FROM snapshots")
        return cur.fetchone()["n"]

    def prune(self, retention_days: float) -> int:
        """Delete data older than *retention_days*. Returns rows removed."""
        cutoff = time.time() - retention_days * 86400
        cur = self.conn.execute(
            "DELETE FROM metrics WHERE timestamp < ?", (cutoff,)
        )
        removed = cur.rowcount
        self.conn.execute(
            "DELETE FROM snapshots WHERE timestamp < ?", (cutoff,)
        )
        self.conn.commit()
        return removed

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def flatten(snapshot: Dict[str, Any]) -> Dict[str, float]:
    """Reduce a full snapshot to the flat headline metrics dict."""
    cpu = snapshot["cpu"]
    mem = snapshot["memory"]
    disk = snapshot["disk"]
    net = snapshot["network"]
    procs = snapshot["processes"]
    return {
        "cpu_percent": cpu["percent"],
        "memory_percent": mem["percent"],
        "swap_percent": mem["swap_percent"],
        "disk_percent": disk["max_percent"],
        "load_per_core": cpu.get("load_per_core") or 0.0,
        "net_bytes_sent": net["bytes_sent"],
        "net_bytes_recv": net["bytes_recv"],
        "process_count": procs["count"],
    }
