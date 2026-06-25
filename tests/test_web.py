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


def test_snapshot_has_network_interfaces(client):
    data = client.get("/api/snapshot").get_json()
    net = data["snapshot"]["network"]
    assert "interfaces" in net
    assert isinstance(net["interfaces"], dict)
    assert "bytes_sent" in net
    assert "bytes_recv" in net
    assert "packets_sent" in net
    assert "errin" in net
    assert "errout" in net


def test_snapshot_has_cpu_per_core(client):
    data = client.get("/api/snapshot").get_json()
    cpu = data["snapshot"]["cpu"]
    assert "per_core" in cpu
    assert isinstance(cpu["per_core"], list)


def test_snapshot_has_memory_swap(client):
    data = client.get("/api/snapshot").get_json()
    mem = data["snapshot"]["memory"]
    assert "swap_total" in mem
    assert "swap_used" in mem
    assert "swap_percent" in mem


def test_snapshot_has_process_status_breakdown(client):
    data = client.get("/api/snapshot").get_json()
    procs = data["snapshot"]["processes"]
    assert "statuses" in procs
    for key in ("running", "sleeping", "zombie", "other"):
        assert key in procs["statuses"]
    assert "top_memory" in procs


def test_snapshot_disk_no_squashfs(client):
    data = client.get("/api/snapshot").get_json()
    disk = data["snapshot"]["disk"]
    for part in disk["partitions"]:
        assert part["fstype"] != "squashfs", (
            f"squashfs partition leaked into snapshot: {part['mountpoint']}"
        )


def test_snapshot_has_system_info(client):
    data = client.get("/api/snapshot").get_json()
    sys = data["snapshot"]["system"]
    for field in ("hostname", "os", "platform", "boot_time", "uptime_seconds", "users"):
        assert field in sys


def test_history_minutes_param(client):
    resp = client.get("/api/history?metric=cpu_percent&minutes=30")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["metric"] == "cpu_percent"
    assert "points" in body


def test_history_invalid_minutes_still_ok(client):
    # Non-numeric minutes defaults gracefully.
    resp = client.get("/api/history?metric=cpu_percent&minutes=notanumber")
    # Flask coerces via type=float — falls back to default 10.
    assert resp.status_code == 200
