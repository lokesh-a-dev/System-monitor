# System Health Monitor

A Python tool that **analyses system health**, **monitors live**, and learns a
**statistical baseline** of normal behaviour for your machine — then flags
deviations from that normal as anomalies.

It covers everything from CPU to the network: CPU (usage, per-core, load,
frequency, temperature), memory & swap, disk (per-partition usage + I/O),
network (throughput, errors, connections), processes (top consumers, states),
and system info (uptime, users, OS).

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
| `main.py`               | CLI entry point. |

The collectors and analysis are UI-agnostic, so a **web dashboard can be added
later** by feeding the same snapshots to a different presenter.

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
- Web dashboard (FastAPI + charts) reusing the existing collectors.
- Email / webhook alert delivery.
