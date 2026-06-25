"""Small formatting helpers shared across the UI layer."""
from __future__ import annotations


def human_bytes(num: float) -> str:
    """Format a byte count as a human-readable string (e.g. 1.5 GB)."""
    step = 1024.0
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(num) < step:
            return f"{num:.1f} {unit}"
        num /= step
    return f"{num:.1f} EB"


def human_duration(seconds: float) -> str:
    """Format a duration as e.g. '3d 4h 12m'."""
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)
