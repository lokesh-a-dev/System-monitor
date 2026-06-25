#!/usr/bin/env python3
"""System Health Monitor — command-line entry point.

Subcommands
-----------
  live      Live colour-coded terminal dashboard.
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
