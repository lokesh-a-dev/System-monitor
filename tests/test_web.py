"""Tests for the Flask web API.

The background sampler thread is stopped immediately and state is injected
directly, so these tests are deterministic and don't depend on timing.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from monitor.config import Config
from monitor.health import evaluate
from tests.test_monitor import make_snapshot

flask = pytest.importorskip("flask")


@pytest.fixture()
def client():
    from web.app import create_app

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    cfg = Config.load(None)
    cfg.data["database"] = path
    app = create_app(cfg)
    sampler = app.config["SAMPLER"]
    sampler.stop()  # don't let the background thread interfere with assertions

    # Inject a known state so endpoints return deterministic data.
    snap = make_snapshot(cpu=55.0, disk=99.0)
    sampler._snapshot = snap
    sampler._health = evaluate(snap, cfg)
    sampler._anomalies = []

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
    os.remove(path)


def test_index_served(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"System Health Monitor" in resp.data


def test_snapshot_endpoint(client):
    resp = client.get("/api/snapshot")
    data = resp.get_json()
    assert data["ready"] is True
    assert data["snapshot"]["cpu"]["percent"] == 55.0
    assert data["health"]["overall"] == "CRITICAL"  # disk at 99%


def test_metrics_endpoint(client):
    data = client.get("/api/metrics").get_json()
    assert "cpu_percent" in data


def test_history_rejects_unknown_metric(client):
    resp = client.get("/api/history?metric=does_not_exist")
    assert resp.status_code == 400


def test_history_known_metric_ok(client):
    resp = client.get("/api/history?metric=cpu_percent&minutes=5")
    assert resp.status_code == 200
    assert resp.get_json()["metric"] == "cpu_percent"


def test_baseline_and_alerts_endpoints(client):
    assert client.get("/api/baseline").status_code == 200
    assert client.get("/api/alerts").status_code == 200
