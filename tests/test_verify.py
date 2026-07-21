"""Tests for the DNS-verification logic (no real network needed)."""
from wms_scraper.verify import parse_nslookup_addresses, verify_rows

SAMPLE_NSLOOKUP = """\
Server:\t192.168.1.1
Address:\t192.168.1.1#53

Non-authoritative answer:
Name:\twss-interdc.zoho.com
Address: 136.143.191.55
Address: 136.143.183.55
"""


def test_parse_nslookup_ignores_resolver_and_keeps_answers():
    ips = parse_nslookup_addresses(SAMPLE_NSLOOKUP)
    # The resolver's own 192.168.1.1 (before "Name:") must not be included.
    assert ips == ["136.143.191.55", "136.143.183.55"]


def test_parse_nslookup_empty():
    assert parse_nslookup_addresses("") == []
    assert parse_nslookup_addresses("Server: 8.8.8.8\nAddress: 8.8.8.8#53") == []


def _fake_resolver(resolved_map):
    def _resolve(name, use_nslookup=False):
        return set(resolved_map.get(name, set()))
    return _resolve


def test_verify_rows_fixed_host():
    rows = [
        ("us4-swss.zoho.com", "136.143.191.55"),
        ("us3-swss.zoho.com", "136.143.183.55"),
        ("ca1-swss.zohocloud.ca", ""),          # no IP -> blank
        ("uk1-swss.zoho.uk", "10.0.0.9"),        # not in DNS -> blank
    ]
    resolver = _fake_resolver({
        "wss-interdc.zoho.com": {"136.143.191.55", "136.143.183.55"},
    })
    out = list(verify_rows(rows, host="wss-interdc.zoho.com", resolver=resolver))
    assert out == [
        ("us4-swss.zoho.com", "136.143.191.55", "verified"),
        ("us3-swss.zoho.com", "136.143.183.55", "verified"),
        ("ca1-swss.zohocloud.ca", "", ""),
        ("uk1-swss.zoho.uk", "10.0.0.9", ""),
    ]


def test_verify_rows_multi_ip_requires_all_present():
    rows = [
        ("a.zoho.com", "1.1.1.1; 2.2.2.2"),   # both present -> verified
        ("b.zoho.com", "1.1.1.1; 9.9.9.9"),   # one missing  -> blank
    ]
    resolver = _fake_resolver({"h": {"1.1.1.1", "2.2.2.2"}})
    out = list(verify_rows(rows, host="h", resolver=resolver))
    assert out[0][2] == "verified"
    assert out[1][2] == ""


def test_verify_rows_per_domain():
    rows = [
        ("us4-swss.zoho.com", "136.143.191.55"),
        ("us3-swss.zoho.com", "136.143.183.55"),
    ]
    resolver = _fake_resolver({
        "us4-swss.zoho.com": {"136.143.191.55"},   # matches its own DNS
        "us3-swss.zoho.com": {"9.9.9.9"},          # DNS differs -> blank
    })
    out = list(verify_rows(rows, host="ignored", per_domain=True, resolver=resolver))
    assert out[0][2] == "verified"
    assert out[1][2] == ""
