"""Flask web dashboard for the system monitor.

Exposes a small JSON API consumed by the front-end (``static/app.js``):

  GET /                 -> dashboard HTML
  GET /api/snapshot     -> latest snapshot + health + anomalies
  GET /api/history      -> recent time-series for a metric (?metric=&minutes=)
  GET /api/baseline     -> learned baseline statistics
  GET /api/alerts       -> recent fired alerts

The heavy lifting (collection, storage, analysis) is shared with the CLI;
this module only wires it to HTTP and a background :class:`Sampler`.
"""
from __future__ import annotations

import time
from typing import Any

from flask import Flask, jsonify, render_template, request

from monitor.config import Config
from monitor.storage import HEADLINE_METRICS, Storage
from web.sampler import Sampler


def create_app(config: Config) -> Flask:
    app = Flask(__name__)
    sampler = Sampler(config)
    sampler.start()
    app.config["SAMPLER"] = sampler
    app.config["MONITOR_CONFIG"] = config

    @app.route("/")
    def index() -> str:
        return render_template("index.html")

    @app.route("/api/snapshot")
    def api_snapshot() -> Any:
        return jsonify(sampler.current_state())

    @app.route("/api/baseline")
    def api_baseline() -> Any:
        return jsonify(sampler.baseline())

    @app.route("/api/alerts")
    def api_alerts() -> Any:
        return jsonify(sampler.recent_alerts())

    @app.route("/api/history")
    def api_history() -> Any:
        metric = request.args.get("metric", "cpu_percent")
        if metric not in HEADLINE_METRICS:
            return jsonify({"error": "unknown metric",
                            "available": list(HEADLINE_METRICS)}), 400
        minutes = request.args.get("minutes", default=10, type=float)
        since = time.time() - minutes * 60
        # Short-lived read connection scoped to this request thread.
        with Storage(config["database"]) as storage:
            cur = storage.conn.execute(
                "SELECT timestamp, value FROM metrics "
                "WHERE metric = ? AND timestamp >= ? ORDER BY timestamp",
                (metric, since),
            )
            points = [{"t": row["timestamp"], "v": row["value"]}
                      for row in cur.fetchall()]
        return jsonify({"metric": metric, "points": points})

    @app.route("/api/metrics")
    def api_metrics() -> Any:
        """List the metrics available for history charts."""
        return jsonify(list(HEADLINE_METRICS))

    return app


def run(config: Config, host: str = "127.0.0.1", port: int = 8000,
        debug: bool = False) -> None:
    app = create_app(config)
    # use_reloader=False so the background sampler thread isn't duplicated.
    app.run(host=host, port=port, debug=debug, use_reloader=False)
