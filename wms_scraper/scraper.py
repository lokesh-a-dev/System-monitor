"""Browser automation that scrapes public IPs from the Zoho WMS Domains page.

Design notes
------------
* The WMS page is a **hash-routed single-page app**; the data center is chosen
  via the URL fragment ``#domains;de=<DC>``. Changing only the hash does not
  reload an SPA, so we set the hash and ``reload()`` to force a fresh render.
* Login requires **TOTP via OneAuth on every fresh login**, which only a human
  can complete. So the browser runs **headed** with a **persistent profile**
  (``--profile``): you log in (and approve OneAuth) once, and the session
  cookies are reused on later runs — no code ever touches your credentials or
  OTP.
* IP extraction is **DOM-agnostic**: for each domain we locate the text on the
  page and climb to the nearest ancestor element that also contains an IP
  address (i.e. that domain's row), then pull the IPs from just that element.
  This survives class-name / markup changes on the WMS side.

Requires Playwright::

    pip install playwright
    python -m playwright install chromium
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field

from . import extract_ips, group_by_dc

BASE_URL = "https://zohodcm.com/zservice/wms"

# JS run in the page to find one domain's IPs without depending on markup.
# Starts at the text node containing the domain and climbs to the smallest
# ancestor whose text also contains an IPv4 address (that domain's row).
# Harvest a full {domain: [ip, ...]} map for the currently-rendered DC table.
#
# The WMS public-IP cells look like:
#   <div class="grid-content ..." data-divid="publicDomainsTableTable">
#     <span>136.143.180.151 - TCP/80 -> 80
#       <span class="info-icon"
#             onclick="showAllPublicIpDetailsForDomain('us3-swss.zoho.com',1)">
#       </span>
#     </span>
#   </div>
# The exact domain lives in the info-icon's onclick, so we key off that (no
# fuzzy text matching) and pull the IP from the enclosing cell's text. A domain
# with multiple public IPs simply has multiple such cells, all carrying the
# same domain in their onclick — they accumulate into the list.
_HARVEST_JS = r"""
() => {
  const ipRe = /\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b/g;
  const domRe = /showAllPublicIpDetailsForDomain\(\s*['"]([^'"]+)['"]/;
  const map = {};
  const icons = document.querySelectorAll('[onclick*="showAllPublicIpDetailsForDomain"]');
  icons.forEach((icon) => {
    const m = domRe.exec(icon.getAttribute('onclick') || '');
    if (!m) return;
    const domain = m[1].trim().toLowerCase();
    if (!(domain in map)) map[domain] = [];
    const cell = icon.closest('div') || icon.parentElement;
    const text = cell ? cell.textContent : '';
    const ips = text.match(ipRe) || [];
    for (const ip of ips) if (!map[domain].includes(ip)) map[domain].push(ip);
  });
  return map;
}
"""

# Locate the scrollable container that holds the IP grid and reset it (and the
# window) to the top, so incremental scrolling starts from row 0.
_SCROLL_TOP_JS = r"""
() => {
  let el = document.querySelector('[onclick*="showAllPublicIpDetailsForDomain"]');
  while (el && el !== document.body) {
    if (el.scrollHeight > el.clientHeight + 4) { el.scrollTop = 0; break; }
    el = el.parentElement;
  }
  window.scrollTo(0, 0);
}
"""

# Scroll the IP grid's scroll container down by ~one page. Returns whether the
# bottom has been reached. Stepping (rather than jumping to the bottom) forces
# a virtualised grid to render every row's window in turn, so no middle rows
# are skipped.
_SCROLL_STEP_JS = r"""
() => {
  let cell = document.querySelector('[onclick*="showAllPublicIpDetailsForDomain"]');
  let container = null, el = cell;
  while (el && el !== document.body) {
    if (el.scrollHeight > el.clientHeight + 4) { container = el; break; }
    el = el.parentElement;
  }
  const t = container || document.scrollingElement || document.body;
  const step = Math.max(120, t.clientHeight * 0.8);
  const before = t.scrollTop;
  t.scrollTop = Math.min(t.scrollTop + step, t.scrollHeight);
  const atBottom = t.scrollTop + t.clientHeight >= t.scrollHeight - 4;
  return { moved: t.scrollTop - before, atBottom };
}
"""


@dataclass
class DomainResult:
    domain: str
    dc: str
    ips: list = field(default_factory=list)
    error: str = ""

    @property
    def found(self) -> bool:
        return bool(self.ips) and not self.error


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _wait_for_domains_table(page, timeout_ms: int) -> None:
    """Wait until the public-domains table has rendered its IP cells.

    Prefers the specific signal (an info-icon whose onclick names a domain);
    falls back to any IP in the body text. Guards against a null body during
    login redirects / SPA transitions so it just polls again instead of
    aborting with a TypeError.
    """
    page.wait_for_function(
        r"""() => {
            const b = document.body;
            if (!b) return false;
            if (document.querySelector('[onclick*="showAllPublicIpDetailsForDomain"]')) return true;
            return /\b(?:\d{1,3}\.){3}\d{1,3}\b/.test(b.innerText || "");
        }""",
        timeout=timeout_ms,
    )


def _harvest_dc(page, table_timeout_ms: int):
    """Return a ``{domain: [ip, ...]}`` map for the current DC's table.

    Scrolls the grid incrementally from top to bottom, harvesting at each step,
    so a virtualised grid (which only keeps visible rows in the DOM) renders
    every row's window in turn and no middle rows are skipped. Accumulates into
    ``best`` so rows recycled out of the DOM after being seen are kept.
    """
    _wait_for_domains_table(page, timeout_ms=table_timeout_ms)
    page.wait_for_timeout(400)  # let the initial rows settle

    best = {}

    def _absorb():
        current = page.evaluate(_HARVEST_JS) or {}
        for domain, ips in current.items():
            slot = best.setdefault(domain, [])
            for ip in ips:
                if ip not in slot:
                    slot.append(ip)

    page.evaluate(_SCROLL_TOP_JS)
    page.wait_for_timeout(250)
    _absorb()

    prev_total, stable = -1, 0
    for _ in range(400):  # cap for very long DC tables
        info = page.evaluate(_SCROLL_STEP_JS) or {}
        page.wait_for_timeout(250)
        _absorb()
        total = sum(len(v) for v in best.values())
        stable = stable + 1 if total == prev_total else 0
        prev_total = total
        # Stop only once we've reached the bottom and a couple of extra steps
        # add nothing new (handles slow row rendering near the end).
        if info.get("atBottom") and stable >= 2:
            break
    return best


def _wait_for_app_shell(page, timeout_ms: int) -> None:
    """Wait until the WMS app shell (its nav) is loaded on the zohodcm host.

    This is the login-complete signal — it does NOT require the domains table,
    which may be blank until we navigate to a clean ``de`` hash. We key off the
    WMS-only nav labels ("Firewall Outgoing Rules" / "Provisioning").
    """
    page.wait_for_function(
        r"""() => location.hostname.indexOf('zohodcm.com') !== -1
                 && !!document.body
                 && /Firewall Outgoing Rules|Provisioning/.test(document.body.innerText)""",
        timeout=timeout_ms,
    )


def _ensure_logged_in(page, login_timeout_s: int) -> None:
    """Load the WMS page and block until the operator has finished login.

    Login is complete once the WMS app shell is present (see
    :func:`_wait_for_app_shell`) — not once the table renders, because the
    table can be blank until we set a clean ``de`` hash.
    """
    page.goto(BASE_URL + "#domains;de=US3", wait_until="domcontentloaded")
    try:
        _wait_for_app_shell(page, timeout_ms=8000)
        return  # already authenticated (persistent session)
    except Exception:
        pass

    _log("\n" + "=" * 70)
    _log("  Please log in to Zoho in the browser window that just opened.")
    _log("  Complete the OneAuth / TOTP prompt. Waiting for the WMS")
    _log("  console to load (up to %d s)…" % login_timeout_s)
    _log("=" * 70 + "\n")
    _wait_for_app_shell(page, timeout_ms=login_timeout_s * 1000)
    _log("  Login detected — starting scrape.\n")


def _load_dc(page, dc: str) -> None:
    """Navigate to a given data center's domains table.

    Forces a *clean* single-fragment hash (Zoho's login redirect can leave a
    doubled ``#domains;de=US3#domains;de=US3`` fragment that renders a blank
    page) and reloads so the SPA re-initialises with the requested ``de``.
    Waiting for / harvesting the table is done by :func:`_harvest_dc`.
    """
    # Setting location.hash replaces the whole fragment, so any doubled/stale
    # hash is discarded. Reload re-inits the SPA with the clean de value.
    page.evaluate("(dc) => { window.location.hash = 'domains;de=' + dc; }", dc)
    page.reload(wait_until="domcontentloaded")


def scrape(domains, profile_dir, headless=False, login_timeout_s=300,
           table_timeout_s=30, slow_mo_ms=0, debug_dir=None):
    """Scrape public IPs for ``domains`` from the WMS page.

    Parameters
    ----------
    domains : iterable of str
        Domains to look up (order preserved in output).
    profile_dir : str
        Directory for the persistent browser profile (keeps you logged in).
    headless : bool
        Run without a visible window. Only works once a session already
        exists in ``profile_dir``; the first login needs ``headless=False``.
    login_timeout_s : int
        How long to wait for the operator to finish OneAuth login.
    table_timeout_s : int
        How long to wait for each DC's table to render.
    debug_dir : str or None
        If set, write per-DC diagnostics there: ``<DC>-found.txt`` (every
        domain the table actually contained) and ``<DC>.png`` (a screenshot).
        Use this to tell genuine absence from a wrong/empty data-center load.

    Returns
    -------
    list[DomainResult]
    """
    import os

    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - env dependent
        raise SystemExit(
            "Playwright is required. Install it with:\n"
            "  pip install playwright\n"
            "  python -m playwright install chromium"
        ) from exc

    grouped = group_by_dc(domains)
    results: "list[DomainResult]" = []

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=headless,
            slow_mo=slow_mo_ms,
            viewport={"width": 1440, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            _ensure_logged_in(page, login_timeout_s=login_timeout_s)

            for dc, dc_domains in grouped.items():
                _log(f"[{dc}] loading {len(dc_domains)} domain(s)…")
                try:
                    _load_dc(page, dc)
                    dc_map = _harvest_dc(page, table_timeout_ms=table_timeout_s * 1000)
                except Exception as exc:
                    for d in dc_domains:
                        results.append(DomainResult(d, dc, error=f"table load failed: {exc}"))
                    continue

                _log(f"    ({len(dc_map)} domains found in {dc}'s table)")
                if debug_dir:
                    found_path = os.path.join(debug_dir, f"{dc}-found.txt")
                    with open(found_path, "w", encoding="utf-8") as fh:
                        for d in sorted(dc_map):
                            fh.write(f"{d}\t{'; '.join(dc_map[d])}\n")
                    try:
                        page.screenshot(path=os.path.join(debug_dir, f"{dc}.png"),
                                        full_page=True)
                    except Exception:
                        pass
                    _log(f"      (wrote {dc}-found.txt + {dc}.png to {debug_dir})")
                for domain in dc_domains:
                    ips = dc_map.get(domain, [])
                    error = "" if ips else "not found on page"
                    results.append(DomainResult(domain, dc, ips=list(ips), error=error))
                    tag = ", ".join(ips) if ips else "(blank — not on page)"
                    _log(f"    {domain:<42} {tag}")
        finally:
            context.close()

    return results
