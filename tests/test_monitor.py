"""Unit tests for the system monitor.

These avoid depending on real machine state where possible by building
synthetic snapshots, so they run deterministically anywhere.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from monitor import baseline as bl
from monitor import collectors
from monitor.alerts import AlertManager
from monitor.config import Config
from monitor.health import Status, evaluate
from monitor.storage import HEADLINE_METRICS, Storage, flatten


def make_snapshot(cpu=10.0, mem=20.0, swap=0.0, disk=30.0, load=0.1,
                  ts=1000.0):
    """Build a minimal but complete snapshot for testing."""
    return {
        "timestamp": ts,
        "cpu": {
            "percent": cpu, "per_core": [cpu], "core_count": 1,
            "physical_cores": 1, "frequency_mhz": 2000.0,
            "load_avg": {"1m": load, "5m": load, "15m": load},
            "load_per_core": load, "temperature": None,
        },
        "memory": {
            "total": 1000, "available": 800, "used": 200, "percent": mem,
            "swap_total": 100, "swap_used": 0, "swap_percent": swap,
        },
        "disk": {
            "partitions": [{"device": "/dev/sda1", "mountpoint": "/",
                            "fstype": "ext4", "total": 100, "used": 30,
                            "free": 70, "percent": disk}],
            "max_percent": disk, "read_bytes": 0, "write_bytes": 0,
        },
        "network": {
            "bytes_sent": 1000, "bytes_recv": 2000, "packets_sent": 10,
            "packets_recv": 20, "errin": 0, "errout": 0, "connections": 5,
            "interfaces": {},
        },
        "processes": {
            "count": 50, "statuses": {"running": 1, "sleeping": 49,
                                      "zombie": 0, "other": 0},
            "top_cpu": [], "top_memory": [],
        },
        "system": {
            "hostname": "test", "os": "Linux test", "platform": "test",
            "boot_time": 0.0, "uptime_seconds": 3600, "users": [],
        },
    }


# --- config -----------------------------------------------------------------

def test_config_defaults_and_merge(tmp_path):
    cfg = Config.load(None)
    assert cfg["interval"] > 0
    # YAML override deep-merges.
    p = tmp_path / "config.yaml"
    p.write_text("interval: 99\nthresholds:\n  cpu_percent:\n    warning: 5\n")
    cfg2 = Config.load(str(p))
    assert cfg2["interval"] == 99
    assert cfg2["thresholds"]["cpu_percent"]["warning"] == 5
    # Untouched defaults survive the merge.
    assert cfg2["thresholds"]["cpu_percent"]["critical"] == 90


# --- health -----------------------------------------------------------------

def test_health_all_green():
    cfg = Config.load(None)
    report = evaluate(make_snapshot(), cfg)
    assert report.overall == Status.HEALTHY
    assert report.score == 100
    assert report.issues == []


def test_health_critical_disk_lowers_score():
    cfg = Config.load(None)
    report = evaluate(make_snapshot(disk=99.0), cfg)
    assert report.overall == Status.CRITICAL
    assert report.score < 100
    assert any(c.metric == "disk_percent" for c in report.issues)


def test_health_warning_classification():
    cfg = Config.load(None)
    report = evaluate(make_snapshot(cpu=75.0), cfg)  # warn 70, crit 90
    cpu_check = next(c for c in report.checks if c.metric == "cpu_percent")
    assert cpu_check.status == Status.WARNING


def test_temperature_skipped_when_absent():
    cfg = Config.load(None)
    report = evaluate(make_snapshot(), cfg)  # temperature is None
    assert all(c.metric != "temperature" for c in report.checks)


# --- storage ----------------------------------------------------------------

def test_storage_roundtrip():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        with Storage(path) as st:
            st.record(make_snapshot(cpu=42.0, ts=1.0))
            st.record(make_snapshot(cpu=44.0, ts=2.0))
            assert st.sample_count() == 2
            cpu_vals = st.values_for("cpu_percent")
            assert cpu_vals == [42.0, 44.0]
            latest = st.latest_snapshot()
            assert latest["cpu"]["percent"] == 44.0
    finally:
        os.remove(path)


def test_flatten_covers_all_headline_metrics():
    flat = flatten(make_snapshot())
    assert set(flat.keys()) == set(HEADLINE_METRICS)


def test_prune_removes_old_rows():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        with Storage(path) as st:
            st.record(make_snapshot(ts=1.0))  # ancient
            removed = st.prune(retention_days=1)
            assert removed > 0
            assert st.sample_count() == 0
    finally:
        os.remove(path)


# --- baseline ---------------------------------------------------------------

def test_baseline_stats_and_zscore():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        cfg = Config.load(None)
        cfg.data["anomaly"]["min_samples"] = 5
        with Storage(path) as st:
            for i in range(10):
                st.record(make_snapshot(cpu=50.0, ts=float(i)))
            baselines = bl.build_baseline(st, cfg)
        cpu_base = baselines["cpu_percent"]
        assert cpu_base.mean == pytest.approx(50.0)
        assert cpu_base.std == pytest.approx(0.0)
        assert cpu_base.trustworthy is True
    finally:
        os.remove(path)


def test_anomaly_detected_for_spike():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        cfg = Config.load(None)
        cfg.data["anomaly"]["min_samples"] = 5
        with Storage(path) as st:
            # Build a baseline of ~10% CPU with some variance.
            for i in range(20):
                st.record(make_snapshot(cpu=10.0 + (i % 3), ts=float(i)))
            baselines = bl.build_baseline(st, cfg)
            spike = make_snapshot(cpu=95.0, ts=100.0)
            anomalies = bl.detect_anomalies(spike, baselines, cfg)
        cpu_anoms = [a for a in anomalies if a.metric == "cpu_percent"]
        assert cpu_anoms, "expected a CPU anomaly for a 95% spike"
        assert cpu_anoms[0].severity in ("warning", "critical")
    finally:
        os.remove(path)


def test_no_anomaly_when_baseline_untrustworthy():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        cfg = Config.load(None)  # min_samples default 30
        with Storage(path) as st:
            st.record(make_snapshot(cpu=10.0, ts=1.0))
            baselines = bl.build_baseline(st, cfg)
            anomalies = bl.detect_anomalies(make_snapshot(cpu=95.0),
                                            baselines, cfg)
        assert anomalies == []  # not enough samples to trust
    finally:
        os.remove(path)


# --- alerts -----------------------------------------------------------------

def test_alert_cooldown(tmp_path):
    cfg = Config.load(None)
    cfg.data["alerts"]["log_file"] = str(tmp_path / "alerts.log")
    cfg.data["alerts"]["cooldown_seconds"] = 60
    mgr = AlertManager(cfg)
    report = evaluate(make_snapshot(disk=99.0), cfg)

    first = mgr.process(report, [], now=1000.0)
    assert len(first) == 1  # disk critical fires
    # Same metric within cooldown -> suppressed.
    second = mgr.process(report, [], now=1010.0)
    assert second == []
    # After cooldown -> fires again.
    third = mgr.process(report, [], now=1100.0)
    assert len(third) == 1


# --- collectors (light integration) -----------------------------------------

def test_collect_all_has_expected_shape():
    collectors.prime()
    snap = collectors.collect_all()
    for key in ("cpu", "memory", "disk", "network", "processes", "system"):
        assert key in snap
    assert isinstance(snap["cpu"]["percent"], (int, float))
    assert snap["memory"]["total"] > 0
