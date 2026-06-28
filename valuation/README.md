# Stock Intrinsic Value & Fair Price Tool

A personal-use toolkit that estimates the **intrinsic value** and **fair entry
price** of a stock by blending several valuation models, then turns the result
into a margin-of-safety **buy / hold / sell** signal. Works for **US** tickers
(`MSFT`, `NVDA`) and **Indian** tickers via Yahoo suffixes (`RELIANCE.NS` for
NSE, `500325.BO` for BSE).

> ⚠️ Educational tool, **not investment advice**. Valuations are only as good
> as their assumptions — always sanity-check the inputs.

## What it does

For each stock it runs four models and blends them into one fair value:

| Model | What it captures | Best for |
|-------|------------------|----------|
| **Two-stage DCF (FCFE)** | PV of future free cash flow, growth fading to a terminal rate | Cash-generative businesses |
| **Multiples** | Fair P/E × EPS (PEG-anchored) | Profitable companies; captures earnings the DCF's FCF misses during heavy-capex phases |
| **Dividend Discount (Gordon)** | PV of a growing dividend | Real dividend payers (auto-skipped below ~1.5% yield) |
| **Graham** | Conservative earnings/asset floor + revised growth formula | A downside sanity check |

It also computes:

- **Margin of safety** and a **buy-below price** for your target discount.
- A **reverse DCF** — the growth rate today's price implies ("is the market
  expecting more than the company can deliver?").
- A **technical context** (50/200-day trend, RSI) and 52-week range position.

## Install

```bash
pip install -r requirements.txt
# Minimum for offline use: PyYAML + rich. Live data also needs yfinance;
# the dashboard needs streamlit + pandas.
```

## Usage

### Command line

```bash
python -m valuation                       # value the configured watchlist (live, falls back to snapshot)
python -m valuation MSFT NVDA RELIANCE.NS # specific tickers
python -m valuation --offline             # force the bundled snapshot (no network)
python -m valuation MSFT --detail         # full per-model breakdown
python -m valuation --json                # machine-readable output
```

### Dashboard

```bash
streamlit run dashboard.py
```

Interactive: pick the data source, edit the watchlist, drag the assumption
sliders (discount rate, growth, horizon, margin of safety) and watch the fair
value and entry signal update live, with per-model and DCF-projection charts.

## Configuration

Everything lives in **`watchlist.yaml`** (override path with `$VALUATION_CONFIG`):

- `watchlist` — the tickers to value.
- `target_margin_of_safety` — how far below fair value you want to buy.
- `model_weights` — how the four models blend (missing models drop out and the
  rest re-normalise).
- `regions` — risk-free rate, equity risk premium and terminal growth for `US`
  vs `IN` (drives the CAPM discount rate).
- `overrides` — per-ticker assumption overrides, e.g. cap NVDA's stage-1 growth.

## Data sources

- **Live:** Yahoo Finance via `yfinance` (`--live`).
- **Offline:** `data/fundamentals.yaml`, an approximate ~June-2026 snapshot of
  the watchlist so the tool (and tests) run with no network. Refresh with live
  mode before making real decisions.

## How the DCF works (and its limits)

Levered free cash flow is projected for `projection_years`, with growth fading
linearly from the stage-1 rate to the terminal rate, discounted at the CAPM
cost of equity. A Gordon-growth terminal value is added, then net cash, then
divided by shares.

Because it keys off **free cash flow**, the DCF reads conservatively for firms
in a heavy-investment phase (e.g. hyperscalers building AI capacity) whose FCF
is temporarily depressed — that's exactly why the **multiples** model is blended
in, and why the **reverse DCF** is shown to reveal the market's implied growth.

## Tests

```bash
python -m pytest tests/test_valuation.py -q
```
