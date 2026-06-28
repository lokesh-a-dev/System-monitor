"""Streamlit dashboard for the stock valuation tool.

Run with::

    streamlit run dashboard.py

Features
--------
* Live (Yahoo Finance) or offline (bundled snapshot) data source.
* Per-stock intrinsic value blended from DCF / multiples / DDM / Graham.
* Interactive assumption sliders (discount rate, growth, horizon, margin of
  safety) that re-value the selected stock in real time.
* Entry-point signal with a suggested buy-below price.
* Watchlist comparison table and per-model / DCF-projection charts.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from valuation.config import Config
from valuation.engine import value_stock
from valuation.models import dcf
from valuation.providers import get_provider

st.set_page_config(page_title="Stock Intrinsic Value", page_icon="📈", layout="wide")

_CCY = {"USD": "$", "INR": "₹"}
_RATING_COLOR = {
    "STRONG BUY": "#0a7d0a", "BUY": "#3aa34a", "HOLD": "#c79100",
    "OVERVALUED": "#d4671b", "SELL": "#c0392b", "N/A": "#777",
}


def _sym(currency: str) -> str:
    return _CCY.get(currency, "")


@st.cache_data(show_spinner=False)
def _fetch(symbol: str, provider_name: str) -> dict:
    """Fetch fundamentals (cached). Returns a plain dict for cache-friendliness."""
    f = get_provider(provider_name).fetch(symbol)
    return f.__dict__


def _to_fundamentals(d: dict):
    from valuation.providers.base import Fundamentals

    valid = Fundamentals.__dataclass_fields__.keys()
    return Fundamentals(**{k: v for k, v in d.items() if k in valid})


cfg = Config.load()

st.title("📈 Stock Intrinsic Value & Fair Price")
st.caption(
    "Blends a two-stage DCF with multiples, dividend-discount and Graham models, "
    "then derives a margin-of-safety entry point. Educational — not investment advice."
)

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Data source")
    source = st.radio(
        "Provider", ["Offline snapshot", "Live (Yahoo Finance)"],
        help="Live needs internet + `pip install yfinance`.",
    )
    provider_name = "snapshot" if source.startswith("Offline") else "yahoo"

    watch = cfg.watchlist
    if provider_name == "snapshot":
        try:
            watch = get_provider("snapshot").available()
        except Exception:
            pass

    st.header("Watchlist")
    watch_text = st.text_area(
        "Tickers (one per line)", value="\n".join(watch), height=140,
        help="US: MSFT. Indian: RELIANCE.NS (NSE) or 500325.BO (BSE).",
    )
    symbols = [s.strip().upper() for s in watch_text.splitlines() if s.strip()]

    st.header("Assumption overrides")
    st.caption("Leave at 0 / default to use the model's own estimate.")
    o_discount = st.slider("Discount rate (cost of equity) %", 6.0, 20.0, 0.0, 0.5,
                           help="0 = auto via CAPM from beta.")
    o_growth = st.slider("Stage-1 growth %", 0.0, 30.0, 0.0, 0.5,
                         help="0 = auto from data.")
    o_terminal = st.slider("Terminal growth %", 1.0, 6.0, 0.0, 0.25,
                           help="0 = region default.")
    o_years = st.slider("Projection years", 5, 15, cfg.get("projection_years", 10))
    target_mos = st.slider("Target margin of safety %", 0, 50,
                           int(cfg.get("target_margin_of_safety", 0.25) * 100), 5)

cfg.data["target_margin_of_safety"] = target_mos / 100.0
overrides = dict(
    discount_rate=(o_discount / 100.0) or None,
    growth_stage1=(o_growth / 100.0) or None,
    terminal_growth=(o_terminal / 100.0) or None,
    years=o_years,
)


def _value(symbol: str):
    f = _to_fundamentals(_fetch(symbol, provider_name))
    return f, value_stock(f, cfg, **overrides)


# ---------------------------------------------------------------- watchlist table
st.subheader("Watchlist")
rows = []
valuations = {}
for sym in symbols:
    try:
        f, v = _value(sym)
    except Exception as exc:
        st.warning(f"{sym}: {exc}")
        continue
    valuations[sym] = (f, v)
    sig = v.signal
    rows.append({
        "Ticker": sym,
        "Price": v.price,
        "Fair value": v.intrinsic_value,
        "Upside %": (sig.upside * 100) if sig and sig.upside is not None else None,
        "Margin %": (sig.margin_of_safety * 100) if sig and sig.margin_of_safety is not None else None,
        "Buy below": sig.buy_below if sig else None,
        "Signal": sig.rating if sig else "N/A",
        "Implied growth %": (v.implied_growth * 100) if v.implied_growth is not None else None,
    })

if rows:
    df = pd.DataFrame(rows).set_index("Ticker")
    st.dataframe(
        df.style.format({
            "Price": "{:,.2f}", "Fair value": "{:,.2f}", "Buy below": "{:,.2f}",
            "Upside %": "{:+.1f}", "Margin %": "{:+.1f}", "Implied growth %": "{:.1f}",
        }, na_rep="—").map(
            lambda r: f"color: white; background-color: {_RATING_COLOR.get(r, '#777')}",
            subset=["Signal"],
        ),
        width="stretch",
    )

# ---------------------------------------------------------------- per-stock detail
st.subheader("Stock detail")
if valuations:
    pick = st.selectbox("Select a stock", list(valuations.keys()))
    f, v = valuations[pick]
    ccy = _sym(v.currency)
    sig = v.signal

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Price", f"{ccy}{v.price:,.2f}" if v.price else "—")
    c2.metric("Intrinsic value", f"{ccy}{v.intrinsic_value:,.2f}" if v.intrinsic_value else "—",
              f"{sig.upside*100:+.1f}% upside" if sig and sig.upside is not None else None)
    c3.metric("Buy below", f"{ccy}{sig.buy_below:,.2f}" if sig and sig.buy_below else "—")
    rating = sig.rating if sig else "N/A"
    c4.markdown(
        f"<div style='padding:0.5rem;border-radius:0.5rem;text-align:center;"
        f"background:{_RATING_COLOR.get(rating)};color:white;font-weight:700;"
        f"font-size:1.2rem;margin-top:0.5rem'>{rating}</div>",
        unsafe_allow_html=True,
    )

    st.caption(f"Data: {v.source} as of {v.as_of or 'n/a'} · currency {v.currency}")

    left, right = st.columns(2)
    with left:
        st.markdown("**Per-model estimates**")
        mv = pd.DataFrame(
            [{"Model": k, "Value": val} for k, val in v.model_values.items()
             if val is not None]
        ).set_index("Model")
        if not mv.empty:
            st.bar_chart(mv)
        if v.price:
            st.caption(f"Dashed reference: current price {ccy}{v.price:,.2f}")

    with right:
        st.markdown("**DCF cash-flow projection**")
        if v.dcf_detail and v.dcf_detail.projected_fcf:
            proj = pd.DataFrame({
                "Year": list(range(1, len(v.dcf_detail.projected_fcf) + 1)),
                "Projected FCF": v.dcf_detail.projected_fcf,
                "Discounted FCF": v.dcf_detail.discounted_fcf,
            }).set_index("Year")
            st.line_chart(proj)
        else:
            st.info("DCF unavailable for this stock (missing FCF/shares).")

    if sig:
        st.markdown("**Entry signal**")
        for reason in sig.reasons:
            st.write(f"- {reason}")
        bits = []
        if sig.technical != "n/a":
            bits.append(f"Technical: {sig.technical}")
        if sig.week52_position is not None:
            bits.append(f"52-week position: {sig.week52_position*100:.0f}%")
        if v.implied_growth is not None:
            bits.append(f"Price implies {v.implied_growth*100:.1f}%/yr growth (reverse DCF)")
        for b in bits:
            st.caption(b)

    with st.expander("DCF assumptions used"):
        if v.dcf_detail:
            st.json(v.dcf_detail.assumptions)
else:
    st.info("Add tickers in the sidebar to begin.")
