"""On-demand health reports in plain text or HTML.

Reports summarise the latest snapshot, the health verdict, the learned
baseline, and any anomalies — useful for sharing or archiving without a
live terminal.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

from monitor.baseline import Anomaly, MetricBaseline
from monitor.health import HealthReport
from monitor.utils import human_bytes, human_duration


def text_report(snapshot: Dict[str, Any], health: HealthReport,
                baselines: Dict[str, MetricBaseline],
                anomalies: List[Anomaly]) -> str:
    """Render a plain-text health report."""
    sys = snapshot["system"]
    lines: List[str] = []
    add = lines.append

    add("=" * 60)
    add(" SYSTEM HEALTH REPORT")
    add("=" * 60)
    add(f" Host       : {sys['hostname']} ({sys['os']})")
    add(f" Generated  : {time.strftime('%Y-%m-%d %H:%M:%S')}")
    add(f" Uptime     : {human_duration(sys['uptime_seconds'])}")
    add(f" Health     : {health.score}/100  [{health.overall.label}]")
    add("")

    add("-- Resource status " + "-" * 41)
    for check in health.checks:
        add(f"  {check.status.label:<9} {check.message}")
    add("")

    mem = snapshot["memory"]
    add("-- Memory " + "-" * 50)
    add(f"  Used {human_bytes(mem['used'])} / {human_bytes(mem['total'])} "
        f"({mem['percent']:.1f}%)")
    add("")

    add("-- Disk " + "-" * 52)
    for part in snapshot["disk"]["partitions"]:
        add(f"  {part['mountpoint']:<20} {part['percent']:5.1f}%  "
            f"{human_bytes(part['free'])} free of "
            f"{human_bytes(part['total'])}")
    add("")

    net = snapshot["network"]
    add("-- Network " + "-" * 49)
    add(f"  Sent {human_bytes(net['bytes_sent'])} | "
        f"Recv {human_bytes(net['bytes_recv'])} | "
        f"Conns {net['connections']}")
    add("")

    add("-- Baseline (learned normal) " + "-" * 31)
    any_trust = False
    for metric, base in baselines.items():
        if base.count == 0:
            continue
        flag = "" if base.trustworthy else "  (insufficient samples)"
        any_trust = any_trust or base.trustworthy
        add(f"  {metric:<16} mean {base.mean:9.2f}  std {base.std:8.2f}  "
            f"n={base.count}{flag}")
    if not any_trust:
        add("  (Run 'collect' for a while to build a trustworthy baseline.)")
    add("")

    add("-- Anomalies " + "-" * 47)
    if anomalies:
        for a in anomalies:
            add(f"  [{a.severity.upper()}] {a.metric}: {a.value:.1f} "
                f"({a.zscore:+.2f}σ from mean {a.mean:.1f})")
    else:
        add("  None — all metrics within baseline.")
    add("=" * 60)
    return "\n".join(lines)


def html_report(snapshot: Dict[str, Any], health: HealthReport,
                baselines: Dict[str, MetricBaseline],
                anomalies: List[Anomaly]) -> str:
    """Render a simple, self-contained HTML health report."""
    sys = snapshot["system"]
    color = {"HEALTHY": "#2e7d32", "WARNING": "#f9a825",
             "CRITICAL": "#c62828"}[health.overall.label]

    def rows_checks() -> str:
        out = []
        for c in health.checks:
            badge = {"HEALTHY": "#2e7d32", "WARNING": "#f9a825",
                     "CRITICAL": "#c62828"}[c.status.label]
            out.append(
                f"<tr><td><span style='color:{badge};font-weight:bold'>"
                f"{c.status.label}</span></td><td>{c.message}</td></tr>")
        return "".join(out)

    def rows_baseline() -> str:
        out = []
        for metric, b in baselines.items():
            if b.count == 0:
                continue
            note = "" if b.trustworthy else " (low samples)"
            out.append(f"<tr><td>{metric}</td><td>{b.mean:.2f}</td>"
                       f"<td>{b.std:.2f}</td><td>{b.count}{note}</td></tr>")
        return "".join(out)

    def rows_anomaly() -> str:
        if not anomalies:
            return ("<tr><td colspan='3' style='color:#2e7d32'>"
                    "None — within baseline.</td></tr>")
        out = []
        for a in anomalies:
            out.append(f"<tr><td>{a.metric}</td><td>{a.value:.1f}</td>"
                       f"<td>{a.zscore:+.2f}σ</td></tr>")
        return "".join(out)

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>System Health Report</title>
<style>
 body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #222; }}
 h1 {{ margin-bottom: 0; }}
 .score {{ font-size: 2rem; font-weight: bold; color: {color}; }}
 table {{ border-collapse: collapse; margin: 1rem 0; width: 100%; }}
 th, td {{ text-align: left; padding: .4rem .8rem; border-bottom: 1px solid #ddd; }}
 th {{ background: #f5f5f5; }}
 .meta {{ color: #666; }}
</style></head><body>
<h1>System Health Report</h1>
<p class="meta">{sys['hostname']} &middot; {sys['os']} &middot;
 up {human_duration(sys['uptime_seconds'])} &middot;
 {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
<p class="score">{health.score}/100 &mdash; {health.overall.label}</p>
<h2>Resource status</h2>
<table><tr><th>Status</th><th>Detail</th></tr>{rows_checks()}</table>
<h2>Baseline (learned normal)</h2>
<table><tr><th>Metric</th><th>Mean</th><th>Std</th><th>Samples</th></tr>
{rows_baseline()}</table>
<h2>Anomalies</h2>
<table><tr><th>Metric</th><th>Value</th><th>Deviation</th></tr>
{rows_anomaly()}</table>
</body></html>"""
