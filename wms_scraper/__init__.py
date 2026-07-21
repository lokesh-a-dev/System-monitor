"""Zoho WMS domain → public-IP scraper.

Automates the WMS "Domains" page (``https://zohodcm.com/zservice/wms#domains;de=<DC>``):
given a list of domains, it groups them by data center (the ``de`` URL
parameter), loads each DC's domain table in a real browser you log into once
(OneAuth / TOTP), and scrapes the public IP(s) listed for each domain.

The pure helpers (domain → DC routing, IP extraction) live here and are unit
tested; the browser driving lives in :mod:`wms_scraper.scraper`.
"""
from __future__ import annotations

import re
from collections import OrderedDict

__all__ = [
    "IP_RE",
    "DOMAIN_ONCLICK_RE",
    "dc_for_domain",
    "group_by_dc",
    "extract_ips",
    "normalise_domain",
    "domain_from_onclick",
    "build_ip_map",
]

# Matches an IPv4 address anywhere in a blob of text.
IP_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
                   r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b")

# The WMS info-icon carries the exact domain in its onclick handler, e.g.
#   onclick="showAllPublicIpDetailsForDomain('us3-swss.zoho.com',1)"
DOMAIN_ONCLICK_RE = re.compile(
    r"""showAllPublicIpDetailsForDomain\(\s*['"]([^'"]+)['"]"""
)


def normalise_domain(domain: str) -> str:
    """Trim whitespace and lowercase a domain for consistent matching."""
    return domain.strip().lower()


def dc_for_domain(domain: str) -> str:
    """Return the data-center code (``de`` value) for a domain.

    The DC is the domain's leading DNS label up to the first hyphen, upper
    cased. Examples::

        us4-swss-accl.zoho.com  -> US4
        in2-swss.zoho.in        -> IN2
        uae1-swss.zoho.ae       -> UAE1
        ca1-swss.zohocloud.ca   -> CA1
    """
    label = normalise_domain(domain).split(".")[0]
    return label.split("-")[0].upper()


def group_by_dc(domains):
    """Group domains by their DC code, preserving first-seen order.

    Returns an ``OrderedDict`` of ``{dc: [domain, ...]}`` with blank lines and
    duplicates removed.
    """
    grouped: "OrderedDict[str, list]" = OrderedDict()
    seen = set()
    for raw in domains:
        domain = normalise_domain(raw)
        if not domain or domain in seen:
            continue
        seen.add(domain)
        grouped.setdefault(dc_for_domain(domain), []).append(domain)
    return grouped


def extract_ips(text: str):
    """Extract unique IPv4 addresses from a blob of text, in order seen."""
    out = []
    for ip in IP_RE.findall(text or ""):
        if ip not in out:
            out.append(ip)
    return out


def domain_from_onclick(onclick: str):
    """Pull the domain out of a ``showAllPublicIpDetailsForDomain(...)`` handler.

    Returns the lowercased domain, or ``None`` if the handler isn't present.
    """
    m = DOMAIN_ONCLICK_RE.search(onclick or "")
    return m.group(1).strip().lower() if m else None


def build_ip_map(cells):
    """Build a ``{domain: [ip, ...]}`` map from WMS public-IP cells.

    ``cells`` is an iterable of ``(onclick_attr, cell_text)`` pairs — one per
    rendered IP cell. This mirrors the in-page harvesting done by the browser
    scraper, kept here in pure Python so the parsing contract is unit tested.
    Domains with several IP cells accumulate all their IPs (order preserved).
    """
    out = {}
    for onclick, text in cells:
        domain = domain_from_onclick(onclick)
        if not domain:
            continue
        slot = out.setdefault(domain, [])
        for ip in extract_ips(text):
            if ip not in slot:
                slot.append(ip)
    return out
