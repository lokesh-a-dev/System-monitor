"""Host-aware time-series store for the central hub.

Unlike :class:`monitor.storage.Storage` (single local machine), this keeps
metrics and snapshots for *many* hosts, keyed by a host identifier supplied
by each agent. A ``hosts`` table caches each host's latest snapshot and
last-seen time so the fleet overview is a single cheap query.

A single connection guarded by a lock keeps writes from concurrent Flask
request threads safe; WAL mode keeps readers from blocking the writer.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any, Dict, List

from monitor.storage import HEADLINE_METRICS, flatten


class HostStore:
    """Multi-host SQLite store for the hub."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS metrics (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    host      TEXT    NOT NULL,
                    timestamp REAL    NOT NULL,
                    metric    TEXT    NOT NULL,
                    value     REAL    NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_host_metric_time
                    ON metrics (host, metric, timestamp);

                CREATE TABLE IF NOT EXISTS snapshots (
                    host      TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    data      TEXT NOT NULL,
                    PRIMARY KEY (host, timestamp)
                );

                CREATE TABLE IF NOT EXISTS hosts (
                    host          TEXT PRIMARY KEY,
                    label         TEXT,
                    last_seen     REAL,
                    last_snapshot TEXT
                );
                """
            )
            self.conn.commit()

    # -- writes --------------------------------------------------------------

    def ingest(self, host: str, label: str, snapshot: Dict[str, Any]) -> None:
        ts = float(snapshot["timestamp"])
        rows = [(host, ts, name, float(value))
                for name, value in flatten(snapshot).items()]
        data = json.dumps(snapshot)
        with self._lock:
            self.conn.executemany(
                "INSERT INTO metrics (host, timestamp, metric, value) "
                "VALUES (?, ?, ?, ?)", rows)
            self.conn.execute(
                "INSERT OR REPLACE INTO snapshots (host, timestamp, data) "
                "VALUES (?, ?, ?)", (host, ts, data))
            self.conn.execute(
                "INSERT INTO hosts (host, label, last_seen, last_snapshot) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(host) DO UPDATE SET label=excluded.label, "
                "last_seen=excluded.last_seen, "
                "last_snapshot=excluded.last_snapshot",
                (host, label, ts, data))
            self.conn.commit()

    def prune(self, retention_days: float) -> int:
        cutoff = time.time() - retention_days * 86400
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM metrics WHERE timestamp < ?", (cutoff,))
            removed = cur.rowcount
            self.conn.execute(
                "DELETE FROM snapshots WHERE timestamp < ?", (cutoff,))
            self.conn.commit()
        return removed

    # -- reads ---------------------------------------------------------------

    def hosts(self) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self.conn.execute(
                "SELECT host, label, last_seen, last_snapshot FROM hosts "
                "ORDER BY host")
            rows = cur.fetchall()
        out = []
        for r in rows:
            out.append({
                "host": r["host"],
                "label": r["label"],
                "last_seen": r["last_seen"],
                "snapshot": json.loads(r["last_snapshot"])
                if r["last_snapshot"] else None,
            })
        return out

    def latest_snapshot(self, host: str) -> Dict[str, Any] | None:
        with self._lock:
            cur = self.conn.execute(
                "SELECT last_snapshot FROM hosts WHERE host = ?", (host,))
            row = cur.fetchone()
        return json.loads(row["last_snapshot"]) if row and \
            row["last_snapshot"] else None

    def values_for(self, host: str, metric: str,
                   since: float | None = None) -> List[float]:
        with self._lock:
            if since is None:
                cur = self.conn.execute(
                    "SELECT value FROM metrics WHERE host = ? AND metric = ? "
                    "ORDER BY timestamp", (host, metric))
            else:
                cur = self.conn.execute(
                    "SELECT value FROM metrics WHERE host = ? AND metric = ? "
                    "AND timestamp >= ? ORDER BY timestamp",
                    (host, metric, since))
            return [r["value"] for r in cur.fetchall()]

    def history(self, host: str, metric: str,
                since: float) -> List[Dict[str, float]]:
        with self._lock:
            cur = self.conn.execute(
                "SELECT timestamp, value FROM metrics WHERE host = ? "
                "AND metric = ? AND timestamp >= ? ORDER BY timestamp",
                (host, metric, since))
            return [{"t": r["timestamp"], "v": r["value"]}
                    for r in cur.fetchall()]

    def close(self) -> None:
        self.conn.close()


class HostBaselineView:
    """Adapter so :func:`monitor.baseline.build_baseline` works per host.

    ``build_baseline`` only needs ``values_for(metric)``; this binds a host.
    """

    def __init__(self, store: HostStore, host: str) -> None:
        self._store = store
        self._host = host

    def values_for(self, metric: str,
                   since: float | None = None) -> List[float]:
        return self._store.values_for(self._host, metric, since)


__all__ = ["HostStore", "HostBaselineView", "HEADLINE_METRICS"]
