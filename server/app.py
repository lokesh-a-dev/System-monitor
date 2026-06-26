"""Central hub: receives pushed metrics from many agents and serves a
multi-host dashboard.

Agents POST snapshots to ``/api/ingest`` (authenticated with an API key).
The hub stores them per host and exposes:

  GET  /                      -> fleet overview (all hosts)
  GET  /host/<host>           -> single-host detail (reuses the local dashboard)
  POST /api/ingest            -> agent metric ingestion (X-API-Key required)
  GET  /api/hosts             -> per-host summary for the overview
  GET  /api/snapshot?host=    -> latest snapshot + health + anomalies
  GET  /api/history?host=&metric=&minutes=
  GET  /api/baseline?host=
  GET  /api/alerts?host=      -> (placeholder; alerts are surfaced as anomalies)
  GET  /api/metrics           -> available metric names

Health and baseline reuse the exact same logic as the local tool.
"""
from __future__ import annotations

import hmac
import os
import time
from typing import Any

from flask import Flask, abort, jsonify, render_template, request

from monitor import baseline as baseline_mod
from monitor.config import Config
from monitor.health import evaluate
from monitor.storage import HEADLINE_METRICS
from server.store import HostBaselineView, HostStore

# web/ holds the shared templates and static assets (reused for host detail).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WEB_DIR = os.path.join(_REPO_ROOT, "web")


def create_app(config: Config, api_key: str, db_path: str,
               stale_after: float = 45.0) -> Flask:
    app = Flask(
        __name__,
        template_folder=os.path.join(_WEB_DIR, "templates"),
        static_folder=os.path.join(_WEB_DIR, "static"),
    )
    store = HostStore(db_path)
    app.config["HOST_STORE"] = store
    app.config["API_KEY"] = api_key
    app.config["STALE_AFTER"] = stale_after

    def _require_key() -> None:
        provided = request.headers.get("X-API-Key", "")
        if not hmac.compare_digest(provided, api_key):
            abort(401, description="invalid or missing API key")

    def _require_host() -> str:
        host = request.args.get("host", "")
        if not host:
            abort(400, description="host query parameter required")
        return host

    # -- pages ---------------------------------------------------------------

    @app.route("/")
    def fleet() -> str:
        return render_template("fleet.html")

    @app.route("/host/<path:host>")
    def host_detail(host: str) -> str:
        return render_template("index.html", monitor_host=host)

    # -- ingestion -----------------------------------------------------------

    @app.post("/api/ingest")
    def api_ingest() -> Any:
        _require_key()
        payload = request.get_json(silent=True)
        if not payload or "snapshot" not in payload:
            abort(400, description="expected JSON with a 'snapshot' field")
        snapshot = payload["snapshot"]
        host = (payload.get("host")
                or snapshot.get("system", {}).get("hostname")
                or "unknown")
        label = payload.get("label") or host
        try:
            store.ingest(host, label, snapshot)
        except (KeyError, TypeError, ValueError) as exc:
            abort(400, description=f"malformed snapshot: {exc}")
        return jsonify({"ok": True, "host": host})

    # -- fleet overview ------------------------------------------------------

    @app.route("/api/hosts")
    def api_hosts() -> Any:
        now = time.time()
        out = []
        for entry in store.hosts():
            snap = entry["snapshot"]
            seconds_ago = now - (entry["last_seen"] or 0)
            summary = {
                "host": entry["host"],
                "label": entry["label"] or entry["host"],
                "seconds_ago": seconds_ago,
                "online": seconds_ago <= stale_after,
            }
            if snap:
                health = evaluate(snap, config)
                summary.update({
                    "score": health.score,
                    "overall": health.overall.label,
                    "cpu": snap["cpu"]["percent"],
                    "memory": snap["memory"]["percent"],
                    "disk": snap["disk"]["max_percent"],
                    "os": snap["system"]["os"],
                    "uptime_seconds": snap["system"]["uptime_seconds"],
                })
            out.append(summary)
        return jsonify({"hosts": out, "stale_after": stale_after})

    # -- per-host detail -----------------------------------------------------

    @app.route("/api/snapshot")
    def api_snapshot() -> Any:
        host = _require_host()
        snap = store.latest_snapshot(host)
        if snap is None:
            return jsonify({"ready": False})
        health = evaluate(snap, config)
        baselines = baseline_mod.build_baseline(
            HostBaselineView(store, host), config)
        anomalies = baseline_mod.detect_anomalies(snap, baselines, config)
        return jsonify({
            "ready": True,
            "snapshot": snap,
            "health": {
                "score": health.score,
                "overall": health.overall.label,
                "checks": [
                    {"metric": c.metric, "value": c.value,
                     "status": c.status.label, "message": c.message}
                    for c in health.checks
                ],
            },
            "anomalies": [
                {"metric": a.metric, "value": a.value, "zscore": a.zscore,
                 "severity": a.severity, "mean": a.mean, "std": a.std}
                for a in anomalies
            ],
        })

    @app.route("/api/baseline")
    def api_baseline() -> Any:
        host = _require_host()
        baselines = baseline_mod.build_baseline(
            HostBaselineView(store, host), config)
        return jsonify({m: vars(b) for m, b in baselines.items()})

    @app.route("/api/history")
    def api_history() -> Any:
        host = _require_host()
        metric = request.args.get("metric", "cpu_percent")
        if metric not in HEADLINE_METRICS:
            return jsonify({"error": "unknown metric",
                            "available": list(HEADLINE_METRICS)}), 400
        minutes = request.args.get("minutes", default=10, type=float)
        since = time.time() - minutes * 60
        return jsonify({"metric": metric,
                        "points": store.history(host, metric, since)})

    @app.route("/api/alerts")
    def api_alerts() -> Any:
        # Alerts are surfaced via anomalies on the detail page; the hub does
        # not keep a separate alert log per host (yet).
        return jsonify([])

    @app.route("/api/metrics")
    def api_metrics() -> Any:
        return jsonify(list(HEADLINE_METRICS))

    return app


def run(config: Config, api_key: str, db_path: str,
        host: str = "0.0.0.0", port: int = 8000,
        stale_after: float = 45.0, debug: bool = False) -> None:
    app = create_app(config, api_key, db_path, stale_after=stale_after)
    app.run(host=host, port=port, debug=debug, use_reloader=False,
            threaded=True)
