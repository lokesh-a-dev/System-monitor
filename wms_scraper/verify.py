#!/usr/bin/env python3
"""Verify scraped public IPs against DNS, adding a ``verified`` column.

Takes the scraper's ``domain,ip`` CSV and, for each row, checks whether the
scraped IP appears in a host's DNS answer — the programmatic equivalent of::

    nslookup wss-interdc.zoho.com | grep <ip>

It writes the same rows back with an extra ``verified`` column: ``verified``
when the row's IP is in the resolved set, blank otherwise.

Two modes:
* default        — resolve one fixed host (``--host``, default
                   ``wss-interdc.zoho.com``) once and check every IP against it;
* ``--per-domain`` — resolve each row's own domain and check its IP against
                   that domain's DNS answer.

Examples
--------
    python -m wms_scraper.verify ips.csv -o ips-verified.csv
    python -m wms_scraper.verify ips.csv --host wss-interdc.zoho.com
    python -m wms_scraper.verify ips.csv --per-domain
    python -m wms_scraper.verify ips.csv --nslookup   # use the nslookup binary
"""
from __future__ import annotations

import argparse
import csv
import socket
import subprocess
import sys

from . import IP_RE, extract_ips

DEFAULT_HOST = "wss-interdc.zoho.com"


def parse_nslookup_addresses(text: str):
    """Extract the *answer* IPs from ``nslookup`` output (not the DNS server).

    nslookup prints the resolver ("Server:/Address:") first, then the answer
    section starting at "Name:". We only collect IPs at/after the first
    ``Name:`` line so the resolver's own address isn't counted.
    """
    ips = []
    in_answer = False
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("name:"):
            in_answer = True
        if not in_answer:
            continue
        # "Address: 1.2.3.4" or "Addresses: 1.2.3.4" (ignore #53 resolver ports)
        if stripped.lower().startswith(("address:", "addresses:")):
            for ip in IP_RE.findall(stripped):
                if ip not in ips:
                    ips.append(ip)
    return ips


def resolve_ips(host: str, use_nslookup: bool = False):
    """Return the set of IPv4 addresses ``host`` resolves to (empty on failure)."""
    if use_nslookup:
        try:
            out = subprocess.run(
                ["nslookup", host], capture_output=True, text=True, timeout=15
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return set()
        return set(parse_nslookup_addresses(out))
    try:
        infos = socket.getaddrinfo(host, None, family=socket.AF_INET)
    except socket.gaierror:
        return set()
    return {info[4][0] for info in infos}


def verify_rows(rows, host, per_domain=False, use_nslookup=False, resolver=resolve_ips,
                log=lambda _msg: None):
    """Yield ``(domain, ip_text, verified)`` for each input ``(domain, ip_text)``.

    ``verified`` is "verified" when every IP in the row resolves within the
    relevant DNS answer (fixed ``host`` or, with ``per_domain``, the row's own
    domain); blank otherwise. Empty-IP rows stay blank. Lookups are cached.
    """
    cache = {}

    def _resolved(name):
        if name not in cache:
            cache[name] = resolver(name, use_nslookup)
            log(f"  resolved {name} -> {len(cache[name])} IP(s)")
        return cache[name]

    for domain, ip_text in rows:
        ips = extract_ips(ip_text)
        if not ips:
            yield domain, ip_text, ""
            continue
        target = domain if per_domain else host
        resolved = _resolved(target)
        verified = "verified" if resolved and all(ip in resolved for ip in ips) else ""
        yield domain, ip_text, verified


def _read_rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        # Tolerate a header row ("domain,ip") or raw data with no header.
        if header and header[:2] != ["domain", "ip"]:
            first = (header[0], header[1] if len(header) > 1 else "")
            yield first
        for row in reader:
            if not row:
                continue
            yield row[0], row[1] if len(row) > 1 else ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="wms_scraper.verify",
        description="Add a 'verified' column by checking scraped IPs against DNS.",
    )
    parser.add_argument("input", help="CSV from the scraper (domain,ip).")
    parser.add_argument("-o", "--output", help="Write to a file instead of stdout.")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help=f"Host to resolve and match IPs against (default: {DEFAULT_HOST}).")
    parser.add_argument("--per-domain", action="store_true",
                        help="Resolve each row's own domain instead of --host.")
    parser.add_argument("--nslookup", action="store_true",
                        help="Use the nslookup binary instead of the system resolver.")
    args = parser.parse_args(argv)

    rows = list(_read_rows(args.input))
    out_rows = list(verify_rows(
        rows, host=args.host, per_domain=args.per_domain,
        use_nslookup=args.nslookup, log=lambda m: print(m, file=sys.stderr),
    ))

    stream = open(args.output, "w", newline="", encoding="utf-8") if args.output else sys.stdout
    try:
        writer = csv.writer(stream)
        writer.writerow(["domain", "ip", "verified"])
        writer.writerows(out_rows)
    finally:
        if args.output:
            stream.close()

    verified = sum(1 for _, _, v in out_rows if v)
    print(f"\n{verified}/{len(out_rows)} row(s) verified.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
