#!/usr/bin/env python3
"""System Health Monitor — command-line entry point.

Subcommands
-----------
  live      Live colour-coded terminal dashboard.
  web       Local browser dashboard (this machine).
  hub       Central collector dashboard for many remote hosts.
  agent     Push this machine's metrics to a hub (run on each server).
  collect   Sample metrics into the database (build history / baseline).
  baseline  Print the learned statistical baseline.
  report    Generate a health report (text or HTML).
  snapshot  Print a single JSON snapshot and exit.

Run ``python main.py <command> --help`` for per-command options.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from monitor import baseline as baseline_mod
from monitor import collectors
from monitor.alerts import AlertManager
from monitor.config import Config
from monitor.health import evaluate
from monitor.storage import Storage


def _load_config(args: argparse.Namespace) -> Config:
    return Config.load(args.config)


def cmd_snapshot(args: argparse.Namespace) -> int:
    collectors.prime()
    time.sleep(0.3)  # let interval counters accumulate a real reading
    snapshot = collectors.collect_all()
    print(json.dumps(snapshot, indent=2, default=str))
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    config = _load_config(args)
    collectors.prime()
    with Storage(config["database"]) as storage:
        print(f"Collecting every {config['interval']}s into "
              f"{config['database']} (Ctrl-C to stop)...")
        count = 0
        try:
            while args.samples == 0 or count < args.samples:
                time.sleep(config["interval"])
                snapshot = collectors.collect_all()
                storage.record(snapshot)
                count += 1
                print(f"\r  recorded {count} sample(s)  "
                      f"(total in db: {storage.sample_count()})",
                      end="", flush=True)
        except KeyboardInterrupt:
            print("\n  stopped.")
        if config["retention_days"]:
            removed = storage.prune(config["retention_days"])
            if removed:
                print(f"  pruned {removed} old metric rows.")
    return 0


def cmd_baseline(args: argparse.Namespace) -> int:
    config = _load_config(args)
    with Storage(config["database"]) as storage:
        if storage.sample_count() == 0:
            print("No history yet. Run 'collect' first to build a baseline.")
            return 1
        baselines = baseline_mod.build_baseline(storage, config)
    print(f"Baseline from {storage_sample_note(config)}:\n")
    print(f"{'metric':<16}{'mean':>12}{'std':>12}{'min':>10}"
          f"{'max':>10}{'n':>7}  trusted")
    print("-" * 75)
    for metric, b in baselines.items():
        if b.count == 0:
            continue
        print(f"{metric:<16}{b.mean:12.2f}{b.std:12.2f}{b.minimum:10.2f}"
              f"{b.maximum:10.2f}{b.count:7d}  "
              f"{'yes' if b.trustworthy else 'no'}")
    return 0


def storage_sample_note(config: Config) -> str:
    with Storage(config["database"]) as storage:
        return f"{storage.sample_count()} stored snapshots"


def cmd_report(args: argparse.Namespace) -> int:
    from ui import report as report_ui

    config = _load_config(args)
    with Storage(config["database"]) as storage:
        baselines = baseline_mod.build_baseline(storage, config)
        # Take a fresh live snapshot for the report's "current" section.
        collectors.prime()
        time.sleep(0.3)
        snapshot = collectors.collect_all()
        storage.record(snapshot)
        health = evaluate(snapshot, config)
        anomalies = baseline_mod.detect_anomalies(snapshot, baselines, config)

    if args.format == "html":
        content = report_ui.html_report(snapshot, health, baselines, anomalies)
    else:
        content = report_ui.text_report(snapshot, health, baselines, anomalies)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(content)
        print(f"Report written to {args.output}")
    else:
        print(content)
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    from web.app import run as run_web

    config = _load_config(args)
    print(f"Starting web dashboard at http://{args.host}:{args.port}")
    print("Sampling in the background; press Ctrl-C to stop.")
    try:
        run_web(config, host=args.host, port=args.port, debug=args.debug)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


def _resolve_api_key(args: argparse.Namespace) -> str:
    import os
    key = args.api_key or os.environ.get("MONITOR_API_KEY", "")
    if not key:
        print("ERROR: an API key is required. Pass --api-key or set the "
              "MONITOR_API_KEY environment variable.", file=sys.stderr)
        print("Generate one with: python -c \"import secrets; "
              "print(secrets.token_urlsafe(32))\"", file=sys.stderr)
        sys.exit(2)
    return key


def cmd_hub(args: argparse.Namespace) -> int:
    from server.app import run as run_hub

    config = _load_config(args)
    api_key = _resolve_api_key(args)
    db = args.db or "hub.db"
    print(f"Starting collector hub on http://{args.host}:{args.port}")
    print(f"  database   : {db}")
    print(f"  ingest at  : POST /api/ingest  (X-API-Key required)")
    print(f"  host stale after {args.stale_after:.0f}s without data")
    print("Press Ctrl-C to stop.")
    try:
        run_hub(config, api_key=api_key, db_path=db, host=args.host,
                port=args.port, stale_after=args.stale_after,
                debug=args.debug)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


def cmd_agent(args: argparse.Namespace) -> int:
    from agent.agent import run as run_agent

    api_key = _resolve_api_key(args)
    interval = args.interval if args.interval is not None \
        else _load_config(args)["interval"]
    run_agent(server=args.server, api_key=api_key, label=args.label,
              interval=interval, insecure=args.insecure)
    return 0


def cmd_live(args: argparse.Namespace) -> int:
    from rich.live import Live

    from ui import dashboard

    config = _load_config(args)
    collectors.prime()
    alert_mgr = AlertManager(config)

    with Storage(config["database"]) as storage:
        baselines = baseline_mod.build_baseline(storage, config)
        last_rebuild = time.time()
        try:
            with Live(auto_refresh=False, screen=True) as live:
                while True:
                    time.sleep(config["interval"])
                    snapshot = collectors.collect_all()
                    storage.record(snapshot)
                    health = evaluate(snapshot, config)
                    anomalies = baseline_mod.detect_anomalies(
                        snapshot, baselines, config)
                    alert_mgr.process(health, anomalies)
                    live.update(dashboard.render(snapshot, health, anomalies),
                                refresh=True)
                    # Periodically refresh the baseline with new history.
                    if time.time() - last_rebuild > 60:
                        baselines = baseline_mod.build_baseline(storage, config)
                        last_rebuild = time.time()
        except KeyboardInterrupt:
            print("Stopped.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="system-monitor",
        description="Analyse system health, monitor live, and learn a "
                    "baseline of normal behaviour.",
    )
    parser.add_argument("--config", default="config.yaml",
                        help="path to YAML config (default: config.yaml)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("live", help="live terminal dashboard").set_defaults(
        func=cmd_live)

    p_web = sub.add_parser("web", help="browser dashboard (Flask)")
    p_web.add_argument("--host", default="127.0.0.1")
    p_web.add_argument("--port", type=int, default=8000)
    p_web.add_argument("--debug", action="store_true")
    p_web.set_defaults(func=cmd_web)

    # Central collector hub (receives pushed metrics from agents).
    p_hub = sub.add_parser("hub", help="central collector for many hosts")
    p_hub.add_argument("--host", default="0.0.0.0",
                       help="bind address (default: 0.0.0.0)")
    p_hub.add_argument("--port", type=int, default=8000)
    p_hub.add_argument("--db", help="hub database file (default: hub.db)")
    p_hub.add_argument("--api-key", help="ingest API key "
                       "(or set MONITOR_API_KEY)")
    p_hub.add_argument("--stale-after", type=float, default=45.0,
                       help="seconds without data before a host is offline")
    p_hub.add_argument("--debug", action="store_true")
    p_hub.set_defaults(func=cmd_hub)

    # Push agent (runs on each monitored server).
    p_agent = sub.add_parser("agent", help="push local metrics to a hub")
    p_agent.add_argument("--server", required=True,
                         help="hub base URL, e.g. https://monitor.example.com")
    p_agent.add_argument("--api-key", help="ingest API key "
                         "(or set MONITOR_API_KEY)")
    p_agent.add_argument("--label", help="host label (default: hostname)")
    p_agent.add_argument("--interval", type=float,
                         help="seconds between pushes (default: config value)")
    p_agent.add_argument("--insecure", action="store_true",
                         help="skip TLS certificate verification")
    p_agent.set_defaults(func=cmd_agent)

    p_collect = sub.add_parser("collect", help="record metrics to history")
    p_collect.add_argument("--samples", type=int, default=0,
                           help="number of samples to collect (0 = forever)")
    p_collect.set_defaults(func=cmd_collect)

    sub.add_parser("baseline", help="show learned baseline").set_defaults(
        func=cmd_baseline)

    p_report = sub.add_parser("report", help="generate a health report")
    p_report.add_argument("--format", choices=["text", "html"],
                          default="text")
    p_report.add_argument("--output", help="write to file instead of stdout")
    p_report.set_defaults(func=cmd_report)

    sub.add_parser("snapshot", help="print one JSON snapshot").set_defaults(
        func=cmd_snapshot)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
