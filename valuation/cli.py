"""Command-line interface for the valuation tool.

Examples
--------
    python -m valuation                     # value the configured watchlist
    python -m valuation MSFT NVDA RELIANCE.NS
    python -m valuation --offline           # force the bundled snapshot
    python -m valuation MSFT --detail       # full per-model breakdown
    python -m valuation --json              # machine-readable output
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List

from . import report
from .config import Config
from .engine import Valuation, value_stock
from .providers import get_provider


def _run(symbols: List[str], provider_name: str, cfg: Config) -> List[Valuation]:
    provider = get_provider(provider_name)
    results: List[Valuation] = []
    for sym in symbols:
        try:
            fundamentals = provider.fetch(sym)
        except Exception as exc:
            print(f"! {sym}: {exc}", file=sys.stderr)
            continue
        results.append(value_stock(fundamentals, cfg))
    return results


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="valuation",
        description="Estimate intrinsic value & entry points for stocks.",
    )
    parser.add_argument("symbols", nargs="*",
                        help="Tickers to value (default: watchlist). Indian: .NS/.BO")
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--live", action="store_const", dest="provider", const="yahoo",
                     help="Force live Yahoo Finance data.")
    src.add_argument("--offline", action="store_const", dest="provider",
                     const="snapshot", help="Force the bundled offline snapshot.")
    parser.add_argument("--config", help="Path to watchlist.yaml")
    parser.add_argument("--detail", action="store_true",
                        help="Show a full per-model breakdown for each stock.")
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON instead of tables.")
    parser.set_defaults(provider="auto")
    args = parser.parse_args(argv)

    cfg = Config.load(args.config)
    symbols = [s.upper() for s in args.symbols] or cfg.watchlist

    results = _run(symbols, args.provider, cfg)
    if not results:
        print("No results.", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([v.to_dict() for v in results], indent=2, default=str))
        return 0

    report.summary_table(results)
    if args.detail:
        for v in results:
            report.detail(v)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
