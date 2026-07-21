# Zoho WMS domain → public-IP scraper

Given a list of domains, this tool scrapes the **Public IP** listed for each on
the WMS Domains page (`https://zohodcm.com/zservice/wms#domains;de=<DC>`).

It figures out which **data center** (`de=` value) each domain belongs to from
the domain name itself, opens each DC's Domains table in a real browser you log
into once, and reads back the IPs.

```
us4-swss-accl.zoho.com  ->  de=US4
in2-swss.zoho.in        ->  de=IN2
uae1-swss.zoho.ae       ->  de=UAE1
ca1-swss.zohocloud.ca   ->  de=CA1
```

## How login / OneAuth works

Zoho asks for **TOTP via OneAuth on every fresh login**, and only you can
approve that. So the tool does **not** handle credentials or OTPs at all.
Instead it launches a **visible browser** with a **persistent profile**: you
log in and approve OneAuth once, and the saved session is reused on later runs.
The tool just waits until the Domains table appears, then drives the page.

## Install

```bash
pip install -r wms_scraper/requirements.txt
python -m playwright install chromium
```

## Usage

Run from the repository root.

```bash
# First run — a browser window opens; log in + approve OneAuth once.
python -m wms_scraper.cli --file wms_scraper/domains.txt

# Ad-hoc domains, CSV to a file (reuses the saved session):
python -m wms_scraper.cli us4-swss.zoho.com in2-swss.zoho.in \
    --format csv --output ips.csv

# JSON output:
python -m wms_scraper.cli --file wms_scraper/domains.txt --format json -o ips.json
```

`domains.txt` is one domain per line; blank lines, `#` comments and a leading
`Domains` header line are ignored (so you can paste the list straight from WMS).

### Options

| Flag | Meaning |
|------|---------|
| `domains...` | Domains as positional arguments. |
| `-f, --file` | Read domains from a file (one per line). |
| `--profile DIR` | Persistent browser profile dir (default: `~/.cache/zoho-wms-scraper/profile`). Keeps you logged in between runs. |
| `--headless` | Run with no window — only works once a session is already saved in `--profile`. |
| `--login-timeout N` | Seconds to wait for you to finish OneAuth login (default 300). |
| `--table-timeout N` | Seconds to wait for each DC's table to render (default 30). |
| `--slow-mo N` | Slow each browser action by N ms (debugging). |
| `--format` | `table` (default), `csv`, or `json`. |
| `-o, --output` | Write to a file instead of stdout. |

## How it scrapes (DOM-agnostic)

Rather than depending on WMS's exact HTML classes (which can change), for each
domain the tool finds the on-page text for that domain and climbs to the
nearest ancestor element that also contains an IPv4 address — i.e. that
domain's table row — then extracts the IP(s) from just that row. The IP regex
validates octet ranges, so ports (`9443`) and years aren't mistaken for IPs.

## Notes & limitations

- Needs a machine where you can see the browser and approve OneAuth (i.e. your
  own laptop, not a headless CI box) at least for the first login.
- If WMS lazy-loads / paginates a very long domain list, a domain scrolled out
  of the DOM may report "not found on page". If you hit that, tell me and I'll
  add a per-domain search/scroll step using the page's search box.
- The tool only reads the page; it never changes WMS data.
