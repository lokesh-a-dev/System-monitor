"""Tests for the stock valuation toolkit."""
from __future__ import annotations

import math

import pytest

from valuation.config import Config
from valuation.engine import value_stock
from valuation.models import dcf, dividend, graham, multiples
from valuation.providers import get_provider
from valuation.providers.base import Fundamentals
from valuation.signals import evaluate, rsi


# --------------------------------------------------------------------- DCF
def test_two_stage_fcfe_known_value():
    # Flat growth == terminal growth -> growing perpetuity closed form.
    # FCF0=100, g=2%, r=10%, infinite horizon -> 100*1.02/(0.10-0.02)=1275.
    r = dcf.two_stage_fcfe(
        fcf0=100, shares=1, discount_rate=0.10,
        growth_stage1=0.02, terminal_growth=0.02, years=200, add_net_cash=False,
    )
    assert r.ok
    assert r.value_per_share == pytest.approx(1275, rel=0.01)


def test_dcf_rejects_discount_below_terminal():
    r = dcf.two_stage_fcfe(100, 1, 0.03, 0.05, 0.05, 10)
    assert not r.ok
    assert "terminal" in r.note


def test_dcf_net_cash_addback():
    base = dcf.two_stage_fcfe(100, 10, 0.10, 0.05, 0.025, 10, net_cash=0, add_net_cash=True)
    plus = dcf.two_stage_fcfe(100, 10, 0.10, 0.05, 0.025, 10, net_cash=500, add_net_cash=True)
    assert plus.value_per_share == pytest.approx(base.value_per_share + 50, rel=1e-6)


def test_cost_of_equity_floor():
    assert dcf.cost_of_equity(0.0, 0.01, 0.01, floor=0.075) == 0.075
    assert dcf.cost_of_equity(1.0, 0.04, 0.05) == pytest.approx(0.09)


def test_reverse_dcf_recovers_growth():
    f = Fundamentals(
        symbol="X", price=None, free_cash_flow=100, shares_outstanding=10,
        beta=1.0, net_cash=0, region="US",
    )
    # Value at a known growth, then check reverse_dcf recovers it from that price.
    v = dcf.value(f, growth_stage1=0.12, discount_rate=0.10, terminal_growth=0.025)
    f.price = v.value_per_share
    implied = dcf.reverse_dcf(f, discount_rate=0.10, terminal_growth=0.025)
    assert implied == pytest.approx(0.12, abs=0.01)


# ----------------------------------------------------------------- models
def test_graham_number():
    f = Fundamentals(symbol="X", eps=10, book_value_per_share=20)
    g = graham.value(f)
    assert g.graham_number == pytest.approx(math.sqrt(22.5 * 10 * 20))


def test_multiples_uses_eps():
    f = Fundamentals(symbol="X", eps=5, growth_rate=0.10)
    m = multiples.value(f, fair_pe=20)
    assert m.value_per_share == pytest.approx(100)


def test_dividend_skipped_for_low_yield():
    f = Fundamentals(symbol="X", price=400, dividend_per_share=1.0, beta=1.0)
    assert dividend.value(f).value_per_share is None  # 0.25% yield


def test_dividend_values_real_payer():
    f = Fundamentals(symbol="X", price=100, dividend_per_share=4.0, beta=1.0,
                     growth_rate=0.04)
    assert dividend.value(f).ok


# ---------------------------------------------------------------- signals
def test_signal_strong_buy():
    s = evaluate(price=50, intrinsic=100, target_mos=0.25)
    assert s.rating == "STRONG BUY"
    assert s.buy_below == pytest.approx(75)
    assert s.upside == pytest.approx(1.0)


def test_signal_sell():
    s = evaluate(price=200, intrinsic=100, target_mos=0.25)
    assert s.rating == "SELL"


def test_rsi_all_gains_is_100():
    assert rsi(list(range(1, 30))) == 100.0


# ------------------------------------------------------------- integration
def test_snapshot_provider_and_engine():
    f = get_provider("offline").fetch("MSFT")
    assert f.price and f.free_cash_flow and f.shares_outstanding
    v = value_stock(f, Config.load())
    assert v.intrinsic_value and v.intrinsic_value > 0
    assert v.signal is not None
    # DCF and multiples should both contribute for a profitable large cap.
    assert v.weights_used.get("dcf", 0) > 0


def test_indian_ticker_region_inference():
    from valuation.providers.yahoo import _region_for

    assert _region_for("RELIANCE.NS") == ("IN", "INR")
    assert _region_for("MSFT") == ("US", "USD")


def test_all_snapshot_stocks_value():
    prov = get_provider("offline")
    cfg = Config.load()
    for sym in prov.available():
        v = value_stock(prov.fetch(sym), cfg)
        assert v.intrinsic_value is not None and v.intrinsic_value > 0, sym
