# System Health Monitor

A Python tool that **analyses system health**, **monitors live**, and learns a
**statistical baseline** of normal behaviour for your machine — then flags
deviations from that normal as anomalies.

It covers everything from CPU to the network: CPU (usage, per-core, load,
frequency, temperature), memory & swap, disk (per-partition usage + I/O),
network (throughput, errors, connections), processes (top consumers, states),
and system info (uptime, users, OS).

> 📈 **Also in this repo:** a separate **Stock Intrinsic Value & Fair Price
> tool** (DCF + multiples + dividend + Graham, with a Streamlit dashboard and
> margin-of-safety entry signals for US & Indian stocks). See
> [`valuation/README.md`](valuation/README.md) — run `python -m valuation` or
> `streamlit run dashboard.py`.

---

## Why this exists

Raw numbers don't tell you much on their own — `CPU 80%` is fine on one box and
alarming on another. This tool turns numbers into judgement in three layers:

1. **Metrics** — collect the vital signs of the machine.
2. **Health analysis** — compare each metric to thresholds → `HEALTHY` /
   `WARNING` / `CRITICAL`, and compute a 0–100 health score.
3. **Baseline & anomaly detection** — learn what's *normal for this host*
   (mean & standard deviation per metric over time), then flag readings that
   are several standard deviations away (z-score). This adapts to your machine
   instead of relying on one-size-fits-all limits.

## Architecture

```
collect ──► storage (SQLite time-series) ──► baseline (stats) ─┐
                                                               ├─► health + anomalies ──► dashboard / report / alerts
                          live snapshot ───────────────────────┘
```

| Module | Responsibility |
|--------|----------------|
| `monitor/collectors.py` | Read each subsystem via `psutil` (no judgement). |
| `monitor/storage.py`    | SQLite time-series + raw snapshot store, pruning. |
| `monitor/health.py`     | Thresholds → status levels + health score. |
| `monitor/baseline.py`   | Learn mean/std per metric; z-score anomaly detection. |
| `monitor/alerts.py`     | Fire & deduplicate alerts (cooldown), log to file. |
| `monitor/config.py`     | Defaults + `config.yaml` deep-merge. |
| `ui/dashboard.py`       | Live colour-coded terminal dashboard (`rich`). |
| `ui/report.py`          | Text / HTML health reports. |
| `web/sampler.py`        | Background thread: samples, stores, keeps latest state. |
| `web/app.py`            | Flask app + JSON API (local single-host dashboard). |
| `web/templates`, `web/static` | Browser dashboard (HTML/CSS/JS), reused by the hub. |
| `agent/agent.py`        | Push agent: collect locally, POST to the hub (stdlib only). |
| `server/store.py`       | Host-aware SQLite store for many hosts. |
| `server/app.py`         | Central hub: ingest + fleet overview + per-host detail. |
| `main.py`               | CLI entry point. |

The collectors and analysis are UI-agnostic: the terminal dashboard, the HTML
report, the local web dashboard, **and the remote fleet hub** all consume the
**same snapshots** and reuse the **same** health/baseline logic.

## Monitoring remote servers (EC2 / cloud) from anywhere

For watching cloud servers, the tool uses an **agent → central hub** push model
(like Datadog/Grafana Cloud):

```
EC2 #1 ─┐  agent: collect locally + POST (outbound HTTPS, API-key auth)
EC2 #2 ─┼───────────────────────────────────────────────►  HUB (central collector)
EC2 #N ─┘                                                    ├─ stores per-host history
                                                             └─ fleet dashboard (view anywhere)
```

Why push (not pull): agents make **outbound** connections only, so they work
behind NAT/firewalls/security-groups with **no inbound ports** opened on the
monitored servers. It scales to a fleet and you get one dashboard for all hosts.

### 1. Generate a shared API key

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 2. Run the hub (on a box reachable by the agents)

```bash
export MONITOR_API_KEY="<the key>"
python main.py hub --port 8000 --db hub.db
# fleet overview at http://<hub-host>:8000/
```

### 3. Run an agent on each server you want to monitor

```bash
export MONITOR_API_KEY="<the same key>"
python main.py agent --server https://your-hub.example.com --label web-1
# --interval N   seconds between pushes (default: config value)
# --insecure     skip TLS verification (self-signed certs only)
```

The agent depends only on `psutil` + the Python standard library — no Flask,
rich, or extra packages needed on the monitored servers.

### Securing the hub (important)

The built-in Flask server is for development. For a public hub:

- **Put it behind a reverse proxy with HTTPS** (Caddy or nginx) so the API key
  and metrics travel encrypted. Example Caddyfile:
  ```
  monitor.example.com {
      reverse_proxy 127.0.0.1:8000
  }
  ```
- Run the app under a production WSGI server, e.g.
  `gunicorn "server.app:create_app(...)"` (or keep it bound to localhost and
  let Caddy terminate TLS).
- Keep the **API key secret** and rotate it if leaked. Treat the ingest
  endpoint as authenticated-only.
- Open only the hub's port (in the EC2 security group); agents need **no**
  inbound rules.

### Run agents as a service (systemd)

```ini
# /etc/systemd/system/sysmon-agent.service
[Unit]
Description=System Health Monitor agent
After=network-online.target

[Service]
Environment=MONITOR_API_KEY=your-key-here
ExecStart=/usr/bin/python3 /opt/system-monitor/main.py agent \
    --server https://monitor.example.com --label %H
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable --now sysmon-agent
```

Hub endpoints: `POST /api/ingest` (auth), `GET /api/hosts`,
`/api/snapshot?host=`, `/api/history?host=&metric=&minutes=`,
`/api/baseline?host=`, `/api/metrics`.

## Web dashboard

```bash
python main.py web                      # http://127.0.0.1:8000
python main.py web --host 0.0.0.0 --port 8080
```

A background thread samples metrics on the configured interval (writing
history to SQLite and rebuilding the baseline periodically); the browser polls
a small JSON API and renders:

- live resource gauges (CPU, memory, disk, network) colour-coded by status,
- a health score + overall status badge,
- a **history line chart** (self-contained canvas — no external/CDN
  dependency, works fully offline) with selectable metric and time range,
- per-partition disk usage and top processes,
- health checks, baseline **anomalies**, and recent **alerts**.

JSON API: `/api/snapshot`, `/api/history?metric=&minutes=`, `/api/baseline`,
`/api/alerts`, `/api/metrics`.

## Install

```bash
pip install -r requirements.txt
```

## Usage

```bash
# One JSON snapshot of everything (good for piping/inspection)
python main.py snapshot

# Live colour-coded dashboard (Ctrl-C to quit)
python main.py live

# Browser dashboard with live charts (this machine)
python main.py web

# Central hub for many remote servers (see "Monitoring remote servers")
python main.py hub
python main.py agent --server https://your-hub --label web-1

# Build history so the baseline becomes trustworthy
python main.py collect            # forever (Ctrl-C to stop)
python main.py collect --samples 100

# Show the learned baseline (mean / std / min / max per metric)
python main.py baseline

# Generate a health report
python main.py report                       # text to stdout
python main.py report --format html --output report.html
```

All commands accept `--config path/to/config.yaml`.

## Configuration

Thresholds, sampling interval, retention, anomaly sensitivity, and alert
cooldown live in `config.yaml` (see that file for the documented defaults).

## How the baseline works

1. `collect` samples metrics every `interval` seconds into SQLite.
2. `baseline` computes, per metric, the mean and standard deviation over all
   stored samples. Once at least `anomaly.min_samples` samples exist, the
   baseline is marked **trustworthy**.
3. During `live`/`report`, each current reading gets a z-score
   `z = (value − mean) / std`. If `|z|` exceeds `z_warning` / `z_critical`
   it's reported as an anomaly. The live dashboard refreshes the baseline
   periodically as new history accumulates.

> Tip: let `collect` run for a while (ideally across normal daily activity)
> before trusting anomaly detection — a baseline is only as good as the
> "normal" it has observed.

## Testing

```bash
python -m pytest -q
```

The suite uses synthetic snapshots so it runs deterministically anywhere.

## Roadmap ideas

- Per-hour-of-day baselines (normal at 3am ≠ normal at 3pm).
- EWMA / rolling baselines that age out stale history.
- Email / webhook alert delivery (and a per-host alert log on the hub).
- WebSocket push instead of polling for the dashboards.
- Agent-side buffering so metrics survive a hub outage.
- Per-host config / thresholds and grouping/tagging in the fleet view.
