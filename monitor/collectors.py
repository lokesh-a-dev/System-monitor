"""Metric collectors.

Each collector reads one subsystem (CPU, memory, disk, network, processes,
system info) using :mod:`psutil` and returns plain dictionaries. Keeping the
collectors free of any judgement (no thresholds here) means storage, health
analysis and the UI can all consume the same raw data.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

import psutil


def collect_cpu() -> Dict[str, Any]:
    """CPU utilisation, per-core usage, frequency, load average and temp."""
    # interval=None gives non-blocking usage since the previous call.
    overall = psutil.cpu_percent(interval=None)
    per_core = psutil.cpu_percent(interval=None, percpu=True)

    freq = psutil.cpu_freq()
    load1, load5, load15 = _load_average()
    cores = psutil.cpu_count(logical=True) or 1

    return {
        "percent": overall,
        "per_core": per_core,
        "core_count": cores,
        "physical_cores": psutil.cpu_count(logical=False) or cores,
        "frequency_mhz": round(freq.current, 1) if freq else None,
        "load_avg": {"1m": load1, "5m": load5, "15m": load15},
        "load_per_core": round(load1 / cores, 3) if cores else None,
        "temperature": _cpu_temperature(),
    }


def collect_memory() -> Dict[str, Any]:
    """Virtual memory and swap usage."""
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    return {
        "total": vm.total,
        "available": vm.available,
        "used": vm.used,
        "percent": vm.percent,
        "swap_total": sw.total,
        "swap_used": sw.used,
        "swap_percent": sw.percent,
    }


def collect_disk() -> Dict[str, Any]:
    """Per-partition usage plus aggregate read/write counters."""
    partitions: List[Dict[str, Any]] = []
    worst_percent = 0.0
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            # Some mountpoints (e.g. CD drives) can't be read; skip them.
            continue
        partitions.append(
            {
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": usage.percent,
            }
        )
        worst_percent = max(worst_percent, usage.percent)

    io = psutil.disk_io_counters()
    return {
        "partitions": partitions,
        # The fullest partition drives the disk health status.
        "max_percent": worst_percent,
        "read_bytes": io.read_bytes if io else 0,
        "write_bytes": io.write_bytes if io else 0,
    }


def collect_network() -> Dict[str, Any]:
    """Aggregate and per-interface network counters plus connection count."""
    total = psutil.net_io_counters()
    per_nic = psutil.net_io_counters(pernic=True)
    interfaces = {
        name: {
            "bytes_sent": c.bytes_sent,
            "bytes_recv": c.bytes_recv,
            "packets_sent": c.packets_sent,
            "packets_recv": c.packets_recv,
            "errin": c.errin,
            "errout": c.errout,
            "dropin": c.dropin,
            "dropout": c.dropout,
        }
        for name, c in per_nic.items()
    }
    try:
        connections = len(psutil.net_connections())
    except (psutil.AccessDenied, PermissionError):
        connections = None

    return {
        "bytes_sent": total.bytes_sent,
        "bytes_recv": total.bytes_recv,
        "packets_sent": total.packets_sent,
        "packets_recv": total.packets_recv,
        "errin": total.errin,
        "errout": total.errout,
        "connections": connections,
        "interfaces": interfaces,
    }


def collect_processes(top_n: int = 5) -> Dict[str, Any]:
    """Process count plus the top CPU and memory consumers."""
    procs: List[Dict[str, Any]] = []
    statuses = {"running": 0, "sleeping": 0, "zombie": 0, "other": 0}

    for proc in psutil.process_iter(["pid", "name", "cpu_percent",
                                     "memory_percent", "status"]):
        try:
            info = proc.info
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        procs.append(info)
        status = info.get("status")
        if status == psutil.STATUS_RUNNING:
            statuses["running"] += 1
        elif status == psutil.STATUS_SLEEPING:
            statuses["sleeping"] += 1
        elif status == psutil.STATUS_ZOMBIE:
            statuses["zombie"] += 1
        else:
            statuses["other"] += 1

    top_cpu = sorted(procs, key=lambda p: p.get("cpu_percent") or 0,
                     reverse=True)[:top_n]
    top_mem = sorted(procs, key=lambda p: p.get("memory_percent") or 0,
                     reverse=True)[:top_n]

    return {
        "count": len(procs),
        "statuses": statuses,
        "top_cpu": top_cpu,
        "top_memory": top_mem,
    }


def collect_system() -> Dict[str, Any]:
    """Static-ish system info: uptime, boot time, users, OS details."""
    import platform

    boot = psutil.boot_time()
    uptime = time.time() - boot
    try:
        users = [u.name for u in psutil.users()]
    except Exception:
        users = []

    return {
        "hostname": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "platform": platform.platform(),
        "boot_time": boot,
        "uptime_seconds": uptime,
        "users": users,
    }


def collect_all(top_n: int = 5) -> Dict[str, Any]:
    """Collect a full snapshot of every subsystem with a timestamp."""
    return {
        "timestamp": time.time(),
        "cpu": collect_cpu(),
        "memory": collect_memory(),
        "disk": collect_disk(),
        "network": collect_network(),
        "processes": collect_processes(top_n=top_n),
        "system": collect_system(),
    }


def prime() -> None:
    """Prime psutil's interval-based counters.

    ``cpu_percent(interval=None)`` returns 0.0 on its very first call because
    it has no previous reading to diff against. Call this once at startup so
    the first real sample is meaningful.
    """
    psutil.cpu_percent(interval=None)
    psutil.cpu_percent(interval=None, percpu=True)
    for proc in psutil.process_iter():
        try:
            proc.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def _load_average() -> tuple[float, float, float]:
    """Return the 1/5/15-minute load average, or zeros if unsupported."""
    try:
        import os
        return os.getloadavg()  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        # Not available on some platforms (e.g. Windows).
        return (0.0, 0.0, 0.0)


def _cpu_temperature() -> float | None:
    """Best-effort CPU temperature in Celsius, or None if no sensor."""
    if not hasattr(psutil, "sensors_temperatures"):
        return None
    try:
        temps = psutil.sensors_temperatures()
    except Exception:
        return None
    if not temps:
        return None
    # Prefer common CPU sensor names, otherwise take the first reading.
    for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
        if key in temps and temps[key]:
            return temps[key][0].current
    for entries in temps.values():
        if entries:
            return entries[0].current
    return None
