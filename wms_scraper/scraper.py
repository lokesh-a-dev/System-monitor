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
_FIND_IPS_JS = r"""
(domain) => {
  const ipRe = /\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b/g;
  const needle = domain.toLowerCase();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node, start = null;
  while ((node = walker.nextNode())) {
    if (node.textContent.toLowerCase().includes(needle)) { start = node.parentElement; break; }
  }
  if (!start) return null;               // domain not present on this page
  let el = start;
  while (el && el !== document.body) {
    const m = el.textContent.match(ipRe);
    if (m && m.length) return Array.from(new Set(m));
    el = el.parentElement;
  }
  return [];                             // found the domain but no IP near it
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
    """Wait until a domain table (something with an IP in it) is rendered."""
    page.wait_for_function(
        r"""() => /\b(?:\d{1,3}\.){3}\d{1,3}\b/.test(document.body.innerText)""",
        timeout=timeout_ms,
    )


def _ensure_logged_in(page, login_timeout_s: int) -> None:
    """Load the WMS page and block until the operator has finished login.

    We consider login complete once the domains table (with IPs) renders.
    """
    page.goto(BASE_URL + "#domains;de=US3", wait_until="domcontentloaded")
    try:
        _wait_for_domains_table(page, timeout_ms=5000)
        return  # already authenticated (persistent session)
    except Exception:
        pass

    _log("\n" + "=" * 70)
    _log("  Please log in to Zoho in the browser window that just opened.")
    _log("  Complete the OneAuth / TOTP prompt. Waiting for the WMS")
    _log("  Domains page to appear (up to %d s)…" % login_timeout_s)
    _log("=" * 70 + "\n")
    _wait_for_domains_table(page, timeout_ms=login_timeout_s * 1000)
    _log("  Login detected — starting scrape.\n")


def _load_dc(page, dc: str, timeout_ms: int) -> None:
    """Render the domains table for a given data center."""
    target_hash = f"domains;de={dc}"
    if page.url.split("#")[0].rstrip("/") != BASE_URL:
        page.goto(f"{BASE_URL}#{target_hash}", wait_until="domcontentloaded")
    else:
        # Hash-only change won't reload an SPA — set it, then force reload.
        page.evaluate(f"window.location.hash = {target_hash!r}")
        page.reload(wait_until="domcontentloaded")
    _wait_for_domains_table(page, timeout_ms=timeout_ms)
    # Small settle for lazy/async row rendering after the first IP appears.
    page.wait_for_timeout(500)


def scrape(domains, profile_dir, headless=False, login_timeout_s=300,
           table_timeout_s=30, slow_mo_ms=0):
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

    Returns
    -------
    list[DomainResult]
    """
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
                    _load_dc(page, dc, timeout_ms=table_timeout_s * 1000)
                except Exception as exc:
                    for d in dc_domains:
                        results.append(DomainResult(d, dc, error=f"table load failed: {exc}"))
                    continue

                for domain in dc_domains:
                    try:
                        ips = page.evaluate(_FIND_IPS_JS, domain)
                    except Exception as exc:
                        results.append(DomainResult(domain, dc, error=str(exc)))
                        continue
                    if ips is None:
                        results.append(DomainResult(domain, dc, error="not found on page"))
                    else:
                        results.append(DomainResult(domain, dc, ips=list(ips)))
                    tag = ", ".join(results[-1].ips) or f"! {results[-1].error}"
                    _log(f"    {domain:<40} {tag}")
        finally:
            context.close()

    return results
