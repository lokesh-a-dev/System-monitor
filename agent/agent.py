"""Lightweight metrics agent.

Runs on each monitored server, samples local metrics with the shared
collectors, and POSTs them to the central hub's ``/api/ingest`` endpoint.

Design goals:
  * Minimal dependencies — only ``psutil`` (via monitor.collectors) plus the
    Python standard library. No Flask/rich/requests needed on the servers.
  * Outbound-only — works behind NAT/firewalls; nothing needs to be exposed.
  * Resilient — a hub outage or network blip never crashes the agent; it logs
    and keeps trying on the next interval.
"""
from __future__ import annotations

import json
import socket
import ssl
import time
import urllib.error
import urllib.request

from monitor import collectors


def run(server: str, api_key: str, label: str | None = None,
        interval: float = 5.0, insecure: bool = False,
        timeout: float = 10.0) -> None:
    """Sample and push metrics to *server* forever (until interrupted)."""
    url = server.rstrip("/") + "/api/ingest"
    host = label or socket.gethostname()
    ctx = ssl._create_unverified_context() if insecure else None

    collectors.prime()
    print(f"[agent] {host} -> {url} every {interval}s "
          f"(Ctrl-C to stop)")

    consecutive_failures = 0
    try:
        while True:
            time.sleep(interval)
            snapshot = collectors.collect_all()
            ok, detail = _post(url, api_key, host, snapshot, ctx, timeout)
            if ok:
                if consecutive_failures:
                    print(f"[agent] reconnected after "
                          f"{consecutive_failures} failure(s)")
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                # Log sparsely so a long outage doesn't flood the log.
                if consecutive_failures <= 3 or \
                        consecutive_failures % 12 == 0:
                    print(f"[agent] push failed ({consecutive_failures}): "
                          f"{detail}")
    except KeyboardInterrupt:
        print("\n[agent] stopped.")


def _post(url: str, api_key: str, host: str, snapshot: dict,
          ctx: ssl.SSLContext | None, timeout: float) -> tuple[bool, str]:
    body = json.dumps({"host": host, "label": host,
                       "snapshot": snapshot}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "X-API-Key": api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            resp.read()
        return True, "ok"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code} {exc.reason}"
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return False, str(exc)
