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
# Harvest a {domain: {ips: [...], count: N}} map for the rendered DC table.
#
# The WMS public-IP column is a flat sequence of one cell per IP line:
#   <div class="grid-content" data-divid="publicDomainsTableTable">
#     <span>136.143.180.151 - TCP/80 -> 80</span></div>
#   <div class="grid-content" data-divid="publicDomainsTableTable">
#     <span>136.143.185.151 - TCP/80 -> 80
#       <span class="info-icon"
#             onclick="showAllPublicIpDetailsForDomain('us3-swss.zoho.com',2)">
#       </span></span></div>
# A domain with several public IPs spans several consecutive cells, but ONLY the
# last cell carries the info-icon that names the domain. So we walk the cells in
# order, accumulating IPs, and flush the accumulated block to the domain each
# time we hit an info-icon. The onclick's 2nd argument is the domain's public-IP
# count, kept as `count` so the caller can detect an under-capture.
_HARVEST_JS = r"""
() => {
  const ipRe = /\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b/g;
  const domRe = /showAllPublicIpDetailsForDomain\(\s*['"]([^'"]+)['"]\s*(?:,\s*(\d+))?/;
  const map = {};
  const cells = document.querySelectorAll('div[data-divid="publicDomainsTableTable"]');
  let pending = [];
  cells.forEach((cell) => {
    const found = cell.textContent.match(ipRe) || [];
    for (const ip of found) pending.push(ip);
    let icon = cell.querySelector('[onclick*="showAllPublicIpDetailsForDomain"]');
    const selfOc = cell.getAttribute && (cell.getAttribute('onclick') || '');
    if (!icon && selfOc && selfOc.indexOf('showAllPublicIpDetailsForDomain') !== -1) {
      icon = cell;
    }
    if (icon) {
      const m = domRe.exec(icon.getAttribute('onclick') || '');
      if (m) {
        const domain = m[1].trim().toLowerCase();
        const count = m[2] ? parseInt(m[2], 10) : null;
        if (!(domain in map)) map[domain] = { ips: [], count: count };
        if (count != null) {
          map[domain].count = Math.max(map[domain].count || 0, count);
        }
        for (const ip of pending) {
          if (!map[domain].ips.includes(ip)) map[domain].ips.push(ip);
        }
      }
      pending = [];  // start a fresh block for the next domain
    }
  });
  return map;
}
"""

# Open the "all public IPs" dialog for a domain by invoking the same global
# handler the info-icon uses. Works without the row being scrolled into view.
_OPEN_DIALOG_JS = r"""
(args) => {
  const [domain, count] = args;
  if (typeof showAllPublicIpDetailsForDomain === 'function') {
    showAllPublicIpDetailsForDomain(domain, count || 1);
    return true;
  }
  return false;
}
"""

# The dialog's table is headed "Public IP ... Port Forwarding ..."; find it by
# that header text rather than a brittle nth-child / div-index path.
_DIALOG_READY_JS = r"""
() => {
  const t = [...document.querySelectorAll('table')].find(
    (tb) => /Public IP/i.test(tb.textContent) && /Port Forwarding/i.test(tb.textContent));
  if (!t) return false;
  return /\b(?:\d{1,3}\.){3}\d{1,3}\b/.test(t.textContent);
}
"""

# The public IPs are the first-column cells (each a <td rowspan> in a
# .cluster row). Read those; fall back to the first <td> of every row.
_DIALOG_IPS_JS = r"""
() => {
  const ipRe = /\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b/g;
  const t = [...document.querySelectorAll('table')].find(
    (tb) => /Public IP/i.test(tb.textContent) && /Port Forwarding/i.test(tb.textContent));
  if (!t) return [];
  const ips = [];
  const push = (txt) => (txt.match(ipRe) || []).forEach(
    (ip) => { if (!ips.includes(ip)) ips.push(ip); });
  const spanned = t.querySelectorAll('td[rowspan]');
  if (spanned.length) {
    spanned.forEach((td) => push(td.textContent));
  } else {
    t.querySelectorAll('tr').forEach((tr) => {
      const td = tr.querySelector('td');
      if (td) push(td.textContent);
    });
  }
  return ips;
}
"""

# Best-effort close of the dialog so the next domain's popup is clean: click a
# close control if present, else remove the dialog's table container.
_CLOSE_DIALOG_JS = r"""
() => {
  const t = [...document.querySelectorAll('table')].find(
    (tb) => /Public IP/i.test(tb.textContent) && /Port Forwarding/i.test(tb.textContent));
  if (!t) return;
  let root = t;
  for (let i = 0; i < 8 && root.parentElement && root.parentElement !== document.body; i++) {
    root = root.parentElement;
  }
  const closer = root.querySelector(
    '.close, .dialogClose, .zdialogClose, [title="Close" i], [aria-label="Close" i]');
  if (closer) { closer.click(); return; }
  root.remove();
}
"""

# Finds the scrollable container that holds the IP grid (an ancestor of an IP
# cell whose content overflows) and reports its scroll metrics. Used to decide
# how many page-steps are needed to walk the whole (possibly virtualised) list.
_SCROLL_METRICS_JS = r"""
() => {
  let cell = document.querySelector('[onclick*="showAllPublicIpDetailsForDomain"]');
  let el = cell;
  while (el && el !== document.body) {
    if (el.scrollHeight > el.clientHeight + 4) {
      return { scrollHeight: el.scrollHeight, clientHeight: el.clientHeight, container: true };
    }
    el = el.parentElement;
  }
  const t = document.scrollingElement || document.body;
  return { scrollHeight: t.scrollHeight, clientHeight: t.clientHeight, container: false };
}
"""

# Scroll the IP grid's container (and the window) to a fraction [0..1] of its
# scrollable height. Jumping to fixed fractions — rather than looping on a
# flaky "at bottom?" check — keeps the walk bounded so it can never hang.
_SCROLL_TO_JS = r"""
(frac) => {
  let cell = document.querySelector('[onclick*="showAllPublicIpDetailsForDomain"]');
  let container = null, el = cell;
  while (el && el !== document.body) {
    if (el.scrollHeight > el.clientHeight + 4) { container = el; break; }
    el = el.parentElement;
  }
  const t = container || document.scrollingElement || document.body;
  t.scrollTop = (t.scrollHeight - t.clientHeight) * frac;
  window.scrollTo(0, (document.body.scrollHeight - window.innerHeight) * frac);
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
    """Harvest the current DC's table.

    Returns ``(ips, counts)`` where ``ips`` is ``{domain: [ip, ...]}`` and
    ``counts`` is ``{domain: expected_public_ip_count}`` (from the onclick).

    Scrolls the grid incrementally from top to bottom, harvesting at each step,
    so a virtualised grid (which only keeps visible rows in the DOM) renders
    every row's window in turn and no middle rows are skipped. Accumulates so
    rows recycled out of the DOM after being seen are kept.
    """
    _wait_for_domains_table(page, timeout_ms=table_timeout_ms)
    page.wait_for_timeout(400)  # let the initial rows settle

    ips = {}
    counts = {}

    def _absorb():
        current = page.evaluate(_HARVEST_JS) or {}
        for domain, info in current.items():
            slot = ips.setdefault(domain, [])
            for ip in info.get("ips", []):
                if ip not in slot:
                    slot.append(ip)
            count = info.get("count")
            if count is not None:
                counts[domain] = max(counts.get(domain, 0), count)

    # Harvest what's visible at the top, then walk the list in a *bounded*
    # number of page-sized steps (one screenful of overlap each) so a
    # virtualised grid renders every row window. Steps are derived from the
    # container height and hard-capped, so this can never spin.
    _absorb()
    metrics = page.evaluate(_SCROLL_METRICS_JS) or {}
    client_h = metrics.get("clientHeight") or 1
    scroll_h = metrics.get("scrollHeight") or 1
    steps = max(1, min(40, int(scroll_h / client_h) + 1))
    for i in range(1, steps + 1):
        page.evaluate(_SCROLL_TO_JS, i / steps)
        page.wait_for_timeout(300)
        _absorb()
    return ips, counts


def _dialog_ips(page, domain: str, count, dialog_timeout_ms: int = 8000):
    """Open a domain's public-IP dialog and return every IP it lists.

    Invokes the page's own ``showAllPublicIpDetailsForDomain`` handler, waits
    for the dialog table, reads the first (Public IP) column, then closes it.
    Returns ``[]`` if the dialog never appears (best-effort — the caller keeps
    the inline IPs in that case).
    """
    try:
        opened = page.evaluate(_OPEN_DIALOG_JS, [domain, count or 1])
    except Exception:
        opened = False
    if not opened:
        return []
    try:
        page.wait_for_function(_DIALOG_READY_JS, timeout=dialog_timeout_ms)
        found = page.evaluate(_DIALOG_IPS_JS) or []
    except Exception:
        found = []
    finally:
        try:
            page.evaluate(_CLOSE_DIALOG_JS)
            page.keyboard.press("Escape")
            page.wait_for_timeout(150)
        except Exception:
            pass
    return list(found)


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
                    dc_map, dc_counts = _harvest_dc(page, table_timeout_ms=table_timeout_s * 1000)
                except Exception as exc:
                    for d in dc_domains:
                        results.append(DomainResult(d, dc, error=f"table load failed: {exc}"))
                    continue

                _log(f"    ({len(dc_map)} domains found in {dc}'s table)")
                if debug_dir:
                    found_path = os.path.join(debug_dir, f"{dc}-found.txt")
                    with open(found_path, "w", encoding="utf-8") as fh:
                        for d in sorted(dc_map):
                            expected = dc_counts.get(d)
                            note = f"\t(expected {expected})" if expected and expected != len(dc_map[d]) else ""
                            fh.write(f"{d}\t{'; '.join(dc_map[d])}{note}\n")
                    try:
                        page.screenshot(path=os.path.join(debug_dir, f"{dc}.png"))
                    except Exception:
                        pass
                    _log(f"      (wrote {dc}-found.txt + {dc}.png to {debug_dir})")
                for domain in dc_domains:
                    inline = dc_map.get(domain, [])
                    expected = dc_counts.get(domain)
                    if not inline and expected is None:
                        # Domain isn't in this DC's table at all.
                        results.append(DomainResult(domain, dc, error="not found on page"))
                        _log(f"    {domain:<42} (blank — not on page)")
                        continue

                    # The dialog is the authoritative full list of public IPs;
                    # fall back to the inline IP(s) if it doesn't open.
                    ips = _dialog_ips(page, domain, expected) or inline
                    error = ""
                    if not ips:
                        error = "not found on page"
                    elif expected and len(ips) < expected:
                        error = f"captured {len(ips)}/{expected} IPs"
                    results.append(DomainResult(domain, dc, ips=list(ips), error=error))
                    tag = "; ".join(ips) if ips else "(blank — not on page)"
                    if error and ips:
                        tag += f"  [! {error}]"
                    _log(f"    {domain:<42} {tag}")
        finally:
            context.close()

    return results
