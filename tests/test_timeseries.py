"""
Round-trip tests for the historical time-series generator + ingestion path.

Verifies that ``data.generate_timeseries`` produces a coherent series that
``csv_loader.load_portfolio_history`` ingests, that security identity is
preserved across dates, that NAV files agree with holdings position sums, and
that an embedded stress window produces a drawdown.
"""
from __future__ import annotations

import warnings

import pytest

from data.generate_timeseries import generate_timeseries
from liquidity_risk_tool.models.csv_loader import (
    load_portfolio_history,
    load_portfolio_from_csv,
)


@pytest.fixture(scope="module")
def series_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("history")
    generate_timeseries(
        output_dir=out,
        start_date="05.01.2026",
        end_date="20.02.2026",
        freq="daily",
        seed=7,
        n_portfolios=7,
        stress_window=("02.02.2026", "13.02.2026"),
    )
    return out


def test_files_written(series_dir):
    assert (series_dir / "NAV.csv").exists()
    assert (series_dir / "manifest.json").exists()
    holdings = list(series_dir.glob("HOLDINGS_*.csv"))
    market = list(series_dir.glob("market_data_ALL_*.csv"))
    assert len(holdings) == len(market) > 10
    # no temp bootstrap files left behind
    assert not list(series_dir.glob("_base_*"))


def test_history_loads_in_order(series_dir):
    series = load_portfolio_history(series_dir, portfolio_code="SYN-EQUITY")
    assert len(series) > 10
    dates = [d for d, _ in series]
    assert dates == sorted(dates), "snapshots must be chronological"


def test_security_identity_persists(series_dir):
    series = load_portfolio_history(series_dir, portfolio_code="SYN-EQUITY")
    first = {p.isin for p in series[0][1].positions}
    last = {p.isin for p in series[-1][1].positions}
    assert first == last, "the same book must persist across the series"


def test_nav_matches_position_sum(series_dir):
    # as_of_date pins each snapshot; loader warns if NAV disagrees with holdings.
    series = load_portfolio_history(series_dir, portfolio_code="SYN-GOVBOND")
    for d, pf in series:
        pos_sum = sum(p.market_value_eur for p in pf.positions)
        assert pf.total_nav > 0
        assert abs(pos_sum - pf.total_nav) / pf.total_nav < 1e-4


def test_prices_actually_move(series_dir):
    series = load_portfolio_history(series_dir, portfolio_code="SYN-EQUITY")
    nav_first = sum(p.market_value_eur for p in series[0][1].positions)
    nav_last = sum(p.market_value_eur for p in series[-1][1].positions)
    assert nav_first != nav_last, "a static series would defeat the purpose"


def test_stress_window_causes_drawdown(series_dir):
    series = load_portfolio_history(series_dir, portfolio_code="SYN-EQUITY")
    navs = {d.strftime("%Y-%m-%d"): sum(p.market_value_eur for p in pf.positions)
            for d, pf in series}
    pre = navs.get("2026-01-30") or list(navs.values())[0]
    post = navs.get("2026-02-13") or list(navs.values())[-1]
    assert post < pre, "equity NAV should fall through the stress window"


def test_illiq_breach_preserved_across_series(series_dir):
    # The regulatory scenario baked into the base generator must survive
    # repricing on every date, not just the base snapshot.
    series = load_portfolio_history(series_dir, portfolio_code="SYN-ILLIQ")
    from liquidity_risk_tool.reporting.risk_metrics import RiskMetricsBuilder
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for d, pf in series[:: max(1, len(series) // 5)]:
            m = RiskMetricsBuilder(pf).build_liquidity_metrics()
            assert m.breach_flag, f"SYN-ILLIQ should breach on {d.date()}"


def test_as_of_date_backward_compatible(series_dir):
    # Loading a single dated holdings file without as_of_date still works.
    holdings = sorted(series_dir.glob("HOLDINGS_*.csv"))[0]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pf = load_portfolio_from_csv(holdings, series_dir / "NAV.csv",
                                     portfolio_code="SYN-EQUITY")
    assert pf.total_nav > 0
