#!/usr/bin/env python3
"""Resolve a list of domains to their IP addresses using ``nslookup``.

Reads a text file containing one domain per line (default: ``domains.txt``),
runs ``nslookup`` on each domain, extracts every resolved IP address and
writes the results to a CSV file with two columns: ``domain,ip``.

If a domain resolves to multiple addresses, one row is written per IP so the
CSV stays flat and easy to filter. Domains that fail to resolve are still
recorded with an empty ``ip`` column so nothing is silently dropped.

Usage
-----
    python domain_ip_lookup.py                       # domains.txt -> domain_ips.csv
    python domain_ip_lookup.py hosts.txt out.csv     # custom input/output
    python domain_ip_lookup.py --help
"""
from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Matches IPv4 and IPv6 addresses reported by nslookup on the "Address:" lines.
_ADDRESS_RE = re.compile(r"^Address(?:\s+\d+)?:\s*(\S+)", re.MULTILINE)


def read_domains(path: Path) -> list[str]:
    """Return the list of domains from *path*, skipping blanks and comments."""
    domains: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        domains.append(line)
    return domains


def lookup_ips(domain: str, timeout: int = 10) -> list[str]:
    """Run ``nslookup`` for *domain* and return the resolved IP addresses.

    Returns an empty list if the lookup fails or no address is found.
    """
    try:
        result = subprocess.run(
            ["nslookup", domain],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []

    ips: list[str] = []
    seen: set[str] = set()
    # The first "Address:" line is usually the DNS server itself (paired with a
    # "Server:" line), so we only collect addresses that appear after the
    # "Name:" line which introduces the answer section.
    output = result.stdout
    answer_section = output.split("Name:", 1)
    text = answer_section[1] if len(answer_section) > 1 else output

    for match in _ADDRESS_RE.finditer(text):
        ip = match.group(1)
        # Strip any "#port" suffix (e.g. "8.8.8.8#53") just in case.
        ip = ip.split("#", 1)[0]
        if ip and ip not in seen:
            seen.add(ip)
            ips.append(ip)
    return ips


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve domains from a file to IPs and write a domain,ip CSV.",
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="domains.txt",
        help="Input file with one domain per line (default: domains.txt).",
    )
    parser.add_argument(
        "output",
        nargs="?",
        default="domain_ips.csv",
        help="Output CSV file (default: domain_ips.csv).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Per-domain nslookup timeout in seconds (default: 10).",
    )
    args = parser.parse_args(argv)

    if shutil.which("nslookup") is None:
        print("error: 'nslookup' was not found on PATH.", file=sys.stderr)
        return 1

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"error: input file not found: {input_path}", file=sys.stderr)
        return 1

    domains = read_domains(input_path)
    if not domains:
        print(f"error: no domains found in {input_path}", file=sys.stderr)
        return 1

    output_path = Path(args.output)
    rows_written = 0
    resolved = 0
    failed = 0

    with output_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["domain", "ip"])
        for domain in domains:
            ips = lookup_ips(domain, timeout=args.timeout)
            if ips:
                resolved += 1
                for ip in ips:
                    writer.writerow([domain, ip])
                    rows_written += 1
                print(f"{domain} -> {', '.join(ips)}")
            else:
                failed += 1
                writer.writerow([domain, ""])
                rows_written += 1
                print(f"{domain} -> (no address found)")

    print(
        f"\nDone. {resolved} resolved, {failed} failed, "
        f"{rows_written} rows written to {output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
