#!/usr/bin/env python3
"""Command-line interface for the Zoho WMS domain → public-IP scraper.

Examples
--------
    # First run (visible browser so you can log in + approve OneAuth once):
    python -m wms_scraper.cli --domains domains.txt

    # Later runs can reuse the saved session (still needs a window if the
    # session expired and Zoho asks for TOTP again):
    python -m wms_scraper.cli --domains domains.txt --format csv --output ips.csv

    # Ad-hoc domains on the command line:
    python -m wms_scraper.cli us4-swss.zoho.com in2-swss.zoho.in
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

from .scraper import scrape

DEFAULT_PROFILE = os.path.join(
    os.path.expanduser("~"), ".cache", "zoho-wms-scraper", "profile"
)


def _read_domains(args) -> list:
    domains: list = list(args.domains or [])
    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                # Skip blanks, comments, and an optional "Domains" header line.
                if not line or line.startswith("#") or line.lower() == "domains":
                    continue
                domains.append(line)
    return domains


def _write_output(results, fmt: str, output) -> None:
    stream = open(output, "w", encoding="utf-8", newline="") if output else sys.stdout
    try:
        if fmt == "json":
            json.dump(
                [
                    {"domain": r.domain, "dc": r.dc, "ips": r.ips, "error": r.error}
                    for r in results
                ],
                stream,
                indent=2,
            )
            stream.write("\n")
        elif fmt == "csv":
            writer = csv.writer(stream)
            writer.writerow(["domain", "dc", "ips", "error"])
            for r in results:
                writer.writerow([r.domain, r.dc, " ".join(r.ips), r.error])
        else:  # table
            width = max((len(r.domain) for r in results), default=10)
            for r in results:
                value = ", ".join(r.ips) if r.ips else f"(!) {r.error or 'no IP found'}"
                stream.write(f"{r.domain:<{width}}  {r.dc:<6}  {value}\n")
    finally:
        if output:
            stream.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="wms_scraper",
        description="Scrape public IPs for Zoho domains from the WMS Domains page.",
    )
    parser.add_argument("domains", nargs="*", help="Domains to look up.")
    parser.add_argument("-f", "--file", dest="file",
                        help="File with one domain per line (a 'Domains' header, "
                             "blank lines and '#' comments are ignored).")
    parser.add_argument("--profile", default=DEFAULT_PROFILE,
                        help=f"Persistent browser profile dir (default: {DEFAULT_PROFILE}).")
    parser.add_argument("--headless", action="store_true",
                        help="Run without a visible window (only after a session "
                             "is already saved in --profile).")
    parser.add_argument("--login-timeout", type=int, default=300,
                        help="Seconds to wait for you to finish OneAuth login (default 300).")
    parser.add_argument("--table-timeout", type=int, default=30,
                        help="Seconds to wait for each DC's table to render (default 30).")
    parser.add_argument("--slow-mo", type=int, default=0,
                        help="Milliseconds to slow each browser action (debugging).")
    parser.add_argument("--format", choices=["table", "csv", "json"], default="table",
                        help="Output format (default: table).")
    parser.add_argument("-o", "--output", help="Write output to a file instead of stdout.")
    args = parser.parse_args(argv)

    domains = _read_domains(args)
    if not domains:
        parser.error("no domains given — pass them as arguments or via --file.")

    os.makedirs(args.profile, exist_ok=True)
    results = scrape(
        domains,
        profile_dir=args.profile,
        headless=args.headless,
        login_timeout_s=args.login_timeout,
        table_timeout_s=args.table_timeout,
        slow_mo_ms=args.slow_mo,
    )
    _write_output(results, args.format, args.output)

    missing = sum(1 for r in results if not r.found)
    if missing:
        print(f"\n{missing}/{len(results)} domain(s) had no IP scraped.", file=sys.stderr)
    return 1 if missing == len(results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
