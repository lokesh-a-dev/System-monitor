"""Live terminal dashboard built with rich.

Renders a refreshing, colour-coded view of system health. The dashboard is
purely presentational: it receives an already-collected snapshot, an
evaluated :class:`HealthReport`, and any anomalies, and lays them out.
"""
from __future__ import annotations

from typing import Any, Dict, List

from rich.console import Group
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from monitor.baseline import Anomaly
from monitor.health import HealthReport, Status
from monitor.utils import human_bytes, human_duration

_STATUS_COLOR = {
    Status.HEALTHY: "green",
    Status.WARNING: "yellow",
    Status.CRITICAL: "red",
}


def render(snapshot: Dict[str, Any], health: HealthReport,
           anomalies: List[Anomaly]) -> Layout:
    """Build the full dashboard layout for one frame."""
    layout = Layout()
    layout.split_column(
        Layout(_header(snapshot, health), name="header", size=3),
        Layout(name="body"),
        Layout(_footer(anomalies), name="footer", size=_footer_size(anomalies)),
    )
    layout["body"].split_row(
        Layout(_gauges_panel(snapshot, health), name="left"),
        Layout(name="right"),
    )
    layout["body"]["right"].split_column(
        Layout(_network_panel(snapshot), name="net"),
        Layout(_process_panel(snapshot), name="procs"),
    )
    return layout


def _header(snapshot: Dict[str, Any], health: HealthReport) -> Panel:
    sys = snapshot["system"]
    color = _STATUS_COLOR[health.overall]
    text = Text()
    text.append(f" {sys['hostname']} ", style="bold")
    text.append(f"({sys['os']})  ", style="dim")
    text.append(f"up {human_duration(sys['uptime_seconds'])}", style="dim")
    text.append("    Health: ")
    text.append(f"{health.score}/100 {health.overall.label}",
                style=f"bold {color}")
    return Panel(text, style=color)


def _gauges_panel(snapshot: Dict[str, Any], health: HealthReport) -> Panel:
    cpu = snapshot["cpu"]
    mem = snapshot["memory"]
    disk = snapshot["disk"]

    status_by_metric = {c.metric: c.status for c in health.checks}
    rows: List[Any] = []

    rows.append(_gauge("CPU", cpu["percent"],
                       status_by_metric.get("cpu_percent", Status.HEALTHY)))
    load = cpu["load_avg"]
    rows.append(Text(f"  load {load['1m']:.2f} / {load['5m']:.2f} "
                     f"/ {load['15m']:.2f}  ({cpu['core_count']} cores)",
                     style="dim"))
    if cpu.get("temperature") is not None:
        rows.append(_gauge("Temp", cpu["temperature"],
                           status_by_metric.get("temperature", Status.HEALTHY),
                           unit="C", scale=100))
    rows.append(_gauge("Memory", mem["percent"],
                       status_by_metric.get("memory_percent", Status.HEALTHY)))
    rows.append(Text(f"  {human_bytes(mem['used'])} / "
                     f"{human_bytes(mem['total'])}", style="dim"))
    if mem["swap_total"] > 0:
        rows.append(_gauge("Swap", mem["swap_percent"],
                           status_by_metric.get("swap_percent",
                                                Status.HEALTHY)))
    rows.append(_gauge("Disk", disk["max_percent"],
                       status_by_metric.get("disk_percent", Status.HEALTHY)))
    for part in disk["partitions"][:4]:
        rows.append(Text(f"  {part['mountpoint']}: {part['percent']:.0f}% "
                         f"({human_bytes(part['free'])} free)", style="dim"))

    return Panel(Group(*rows), title="Resources", border_style="blue")


def _gauge(label: str, value: float, status: Status, unit: str = "%",
           scale: float = 100, width: int = 24) -> Text:
    color = _STATUS_COLOR[status]
    filled = int(min(value, scale) / scale * width)
    bar = "█" * filled + "░" * (width - filled)
    text = Text()
    text.append(f"{label:>7} ")
    text.append(bar, style=color)
    text.append(f" {value:5.1f}{unit}", style=f"bold {color}")
    return text


def _network_panel(snapshot: Dict[str, Any]) -> Panel:
    net = snapshot["network"]
    table = Table.grid(padding=(0, 2))
    table.add_column(justify="right", style="cyan")
    table.add_column()
    table.add_row("Sent", human_bytes(net["bytes_sent"]))
    table.add_row("Received", human_bytes(net["bytes_recv"]))
    table.add_row("Errors", f"{net['errin']} in / {net['errout']} out")
    conns = net["connections"]
    table.add_row("Connections", str(conns) if conns is not None else "n/a")
    return Panel(table, title="Network", border_style="magenta")


def _process_panel(snapshot: Dict[str, Any]) -> Panel:
    procs = snapshot["processes"]
    table = Table(expand=True, box=None)
    table.add_column("PID", justify="right", style="dim", width=7)
    table.add_column("Process")
    table.add_column("CPU%", justify="right", style="yellow", width=7)
    table.add_column("MEM%", justify="right", style="cyan", width=7)
    for p in procs["top_cpu"][:5]:
        table.add_row(
            str(p.get("pid", "?")),
            str(p.get("name", "?"))[:20],
            f"{p.get('cpu_percent') or 0:.1f}",
            f"{p.get('memory_percent') or 0:.1f}",
        )
    title = (f"Top processes  ({procs['count']} total, "
             f"{procs['statuses']['running']} running)")
    return Panel(table, title=title, border_style="green")


def _footer(anomalies: List[Anomaly]) -> Panel:
    if not anomalies:
        return Panel(Text("No anomalies detected — behaviour within baseline.",
                          style="green"),
                     title="Baseline", border_style="green")
    lines = []
    for a in anomalies:
        color = "red" if a.severity == "critical" else "yellow"
        lines.append(Text(
            f"⚠ {a.metric}: {a.value:.1f} ({a.zscore:+.1f}σ from "
            f"mean {a.mean:.1f})", style=color))
    return Panel(Group(*lines), title="Anomalies vs baseline",
                 border_style="red")


def _footer_size(anomalies: List[Anomaly]) -> int:
    return max(3, len(anomalies) + 2)
