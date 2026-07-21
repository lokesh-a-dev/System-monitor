"""Tests for the pure logic of the WMS scraper (no browser needed)."""
from wms_scraper import (
    build_ip_map,
    dc_for_domain,
    domain_from_onclick,
    extract_ips,
    group_by_dc,
    normalise_domain,
)


def test_dc_for_domain_basic():
    assert dc_for_domain("us4-swss-accl.zoho.com") == "US4"
    assert dc_for_domain("us3-swss.zoho.com") == "US3"
    assert dc_for_domain("in2-swss.zoho.in") == "IN2"
    assert dc_for_domain("eu1-swss.zoho.eu") == "EU1"


def test_dc_for_domain_region_variants():
    assert dc_for_domain("uae1-swss.zoho.ae") == "UAE1"
    assert dc_for_domain("ca1-swss.zohocloud.ca") == "CA1"
    assert dc_for_domain("au2-swss.zoho.com.au") == "AU2"
    assert dc_for_domain("cn3-swss.zoho.com.cn") == "CN3"


def test_dc_for_domain_is_case_insensitive_and_trimmed():
    assert dc_for_domain("  US4-swss.zoho.com  ") == "US4"


def test_group_by_dc_dedupes_and_preserves_order():
    grouped = group_by_dc([
        "us4-swss.zoho.com",
        "us3-swss.zoho.com",
        "us4-swss.zoho.com",   # duplicate
        "",                      # blank
        "in2-swss.zoho.in",
    ])
    assert list(grouped.keys()) == ["US4", "US3", "IN2"]
    assert grouped["US4"] == ["us4-swss.zoho.com"]
    assert grouped["US3"] == ["us3-swss.zoho.com"]


def test_extract_ips_from_row_text():
    text = ("preinternalzvprtmp-ro.zoho.com "
            "136.143.180.151 - TCP/80 -> 80 "
            "136.143.185.151 - TCP/80 -> 80")
    assert extract_ips(text) == ["136.143.180.151", "136.143.185.151"]


def test_extract_ips_dedupes_preserving_order():
    text = "10.0.0.1 foo 10.0.0.2 bar 10.0.0.1"
    assert extract_ips(text) == ["10.0.0.1", "10.0.0.2"]


def test_extract_ips_rejects_out_of_range_octets():
    # Port numbers / years must not be mistaken for IPs.
    assert extract_ips("port 9443 -> 80 in 2026") == []
    assert extract_ips("999.1.1.1 is not valid") == []


def test_extract_ips_empty():
    assert extract_ips("") == []
    assert extract_ips(None) == []


def test_normalise_domain():
    assert normalise_domain("  US4-SWSS.Zoho.COM \n") == "us4-swss.zoho.com"


def test_domain_from_onclick():
    assert domain_from_onclick(
        "showAllPublicIpDetailsForDomain('cn2-dss.zoho.com.cn',1)"
    ) == "cn2-dss.zoho.com.cn"
    # Double quotes and stray whitespace are tolerated.
    assert domain_from_onclick(
        'showAllPublicIpDetailsForDomain( "US3-SWSS.zoho.com" , 2 )'
    ) == "us3-swss.zoho.com"
    assert domain_from_onclick("someOtherHandler('x')") is None
    assert domain_from_onclick("") is None


def test_build_ip_map_single_and_multi_ip():
    cells = [
        # cn2-dss has one IP.
        ("showAllPublicIpDetailsForDomain('cn2-dss.zoho.com.cn',1)",
         "163.53.93.10 - TCP/443 -> 8443"),
        # us3-swss has two IPs across two cells.
        ("showAllPublicIpDetailsForDomain('us3-swss.zoho.com',1)",
         "136.143.180.151 - TCP/80 -> 80"),
        ("showAllPublicIpDetailsForDomain('us3-swss.zoho.com',2)",
         "136.143.185.151 - TCP/80 -> 80"),
    ]
    result = build_ip_map(cells)
    assert result == {
        "cn2-dss.zoho.com.cn": ["163.53.93.10"],
        "us3-swss.zoho.com": ["136.143.180.151", "136.143.185.151"],
    }


def test_build_ip_map_ignores_cells_without_handler():
    cells = [
        ("noHandlerHere()", "1.2.3.4"),
        ("showAllPublicIpDetailsForDomain('a.zoho.com',1)", "5.6.7.8"),
    ]
    assert build_ip_map(cells) == {"a.zoho.com": ["5.6.7.8"]}
