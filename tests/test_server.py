"""Tests for the central collector hub (ingest auth + multi-host API)."""
from __future__ import annotations

import os
import tempfile
import time

import pytest

from monitor.config import Config
from tests.test_monitor import make_snapshot

pytest.importorskip("flask")

API_KEY = "unit-test-key"


@pytest.fixture()
def client():
    from server.app import create_app

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    cfg = Config.load(None)
    app = create_app(cfg, api_key=API_KEY, db_path=path, stale_after=30)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
    app.config["HOST_STORE"].close()
    os.remove(path)


def _ingest(client, host, snapshot, key=API_KEY):
    headers = {"X-API-Key": key} if key is not None else {}
    return client.post("/api/ingest",
                       json={"host": host, "label": host, "snapshot": snapshot},
                       headers=headers)


def test_ingest_requires_valid_key(client):
    snap = make_snapshot()
    assert _ingest(client, "h1", snap, key=None).status_code == 401
    assert _ingest(client, "h1", snap, key="wrong").status_code == 401
    assert _ingest(client, "h1", snap, key=API_KEY).status_code == 200


def test_ingest_then_hosts_overview(client):
    now = time.time()
    _ingest(client, "web1", make_snapshot(cpu=12.0, disk=40.0, ts=now))
    _ingest(client, "db1", make_snapshot(cpu=99.0, disk=50.0, ts=now))

    data = client.get("/api/hosts").get_json()
    hosts = {h["host"]: h for h in data["hosts"]}
    assert set(hosts) == {"web1", "db1"}
    assert hosts["web1"]["overall"] == "HEALTHY"
    assert hosts["db1"]["overall"] == "CRITICAL"   # cpu 99% > critical
    assert hosts["web1"]["online"] is True


def test_snapshot_requires_host(client):
    assert client.get("/api/snapshot").status_code == 400


def test_per_host_snapshot_and_history(client):
    now = time.time()
    for i in range(6):
        _ingest(client, "web1", make_snapshot(cpu=10.0 + i, ts=now - (5 - i)))

    snap = client.get("/api/snapshot?host=web1").get_json()
    assert snap["ready"] is True
    assert snap["health"]["overall"] == "HEALTHY"

    hist = client.get(
        "/api/history?host=web1&metric=cpu_percent&minutes=10").get_json()
    assert hist["metric"] == "cpu_percent"
    assert len(hist["points"]) == 6


def test_history_rejects_unknown_metric(client):
    _ingest(client, "web1", make_snapshot())
    resp = client.get("/api/history?host=web1&metric=nope")
    assert resp.status_code == 400


def test_unknown_host_snapshot_not_ready(client):
    data = client.get("/api/snapshot?host=ghost").get_json()
    assert data["ready"] is False


def test_pages_render(client):
    _ingest(client, "web1", make_snapshot())
    assert client.get("/").status_code == 200                 # fleet overview
    assert client.get("/host/web1").status_code == 200        # detail
