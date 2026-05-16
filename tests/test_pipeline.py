"""
Smoke-test suite — verifies the complete pipeline produces coherent outputs.
Run with: python -m pytest tests/ -v
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pandas as pd
import numpy as np

from liquidity_risk_tool.models          import build_sample_portfolio
from liquidity_risk_tool.engines         import (
    LiquidityProfiler, RedemptionSimulator, WaterfallEngine, StressEngine,
)
from liquidity_risk_tool.reporting       import RiskMetricsBuilder
from liquidity_risk_tool.config          import STRESS_SCENARIOS, REDEMPTION_SCENARIOS, BUCKET_ORDER

_NAV_PCT_TOL = 1e-6   # tolerance for "sums to 100%" assertions


@pytest.fixture(scope="module")
def portfolio():
    return build_sample_portfolio()


@pytest.fixture(scope="module")
def profiler_normal(portfolio):
    return LiquidityProfiler(portfolio, stress=False).run()


@pytest.fixture(scope="module")
def profiler_stress(portfolio):
    return LiquidityProfiler(portfolio, stress=True).run()


# ── Portfolio ──────────────────────────────────────────────────────────────

class TestPortfolio:
    def test_nav_positive(self, portfolio):
        assert portfolio.total_nav > 0

    def test_positions_non_empty(self, portfolio):
        assert len(portfolio.positions) > 0

    def test_weights_sum_to_one(self, portfolio):
        total_weight = sum(p.weight for p in portfolio.positions)
        assert abs(total_weight - 1.0) < 1e-6

    def test_positions_df_shape(self, portfolio):
        df = portfolio.positions_df
        assert len(df) == len(portfolio.positions)
        assert "market_value_eur" in df.columns


# ── Liquidity Profiler ────────────────────────────────────────────────────

class TestLiquidityProfiler:
    def test_all_positions_have_bucket(self, profiler_normal):
        df = profiler_normal.position_buckets
        assert df["bucket"].notna().all()

    def test_realisable_lte_market_value(self, profiler_normal):
        df = profiler_normal.position_buckets
        assert (df["realisable_value"] <= df["market_value_eur"] + 1).all()

    def test_ladder_buckets_complete(self, profiler_normal):
        from liquidity_risk_tool.config import BUCKET_ORDER
        ladder = profiler_normal.liquidity_ladder()
        assert set(ladder["bucket"]) == set(BUCKET_ORDER)

    def test_cumulative_pct_monotone(self, profiler_normal):
        ladder = profiler_normal.liquidity_ladder()
        cumul = ladder["cumulative_nav_pct"].values
        assert all(cumul[i] <= cumul[i+1] for i in range(len(cumul)-1))

    def test_stress_lte_normal_liquid(self, portfolio, profiler_normal, profiler_stress):
        nav = portfolio.total_nav
        normal_liq = profiler_normal.liquidity_at_horizon(1)
        stress_liq = profiler_stress.liquidity_at_horizon(1)
        assert stress_liq <= normal_liq + 1  # stress should be <= normal

    def test_liquidity_at_horizon_0(self, profiler_normal, portfolio):
        liq = profiler_normal.liquidity_at_horizon(0)
        assert 0 <= liq <= portfolio.total_nav

    def test_liquidity_at_horizon_increases_with_days(self, profiler_normal):
        liq_1 = profiler_normal.liquidity_at_horizon(1)
        liq_7 = profiler_normal.liquidity_at_horizon(7)
        assert liq_7 >= liq_1

    def test_ladder_normal_nav_pct_sums_to_100(self, profiler_normal):
        ladder = profiler_normal.liquidity_ladder()
        assert abs(ladder["nav_pct"].sum() - 1.0) < _NAV_PCT_TOL, (
            f"Normal ladder nav_pct sums to {ladder['nav_pct'].sum():.8f}, expected 1.0"
        )

    def test_ladder_stress_nav_pct_sums_to_100(self, profiler_stress):
        ladder = profiler_stress.liquidity_ladder()
        assert abs(ladder["nav_pct"].sum() - 1.0) < _NAV_PCT_TOL, (
            f"Stress ladder nav_pct sums to {ladder['nav_pct'].sum():.8f}, expected 1.0"
        )

    def test_ladder_normal_cumulative_ends_at_100(self, profiler_normal):
        ladder = profiler_normal.liquidity_ladder()
        assert abs(ladder["cumulative_nav_pct"].iloc[-1] - 1.0) < _NAV_PCT_TOL

    def test_ladder_stress_cumulative_ends_at_100(self, profiler_stress):
        ladder = profiler_stress.liquidity_ladder()
        assert abs(ladder["cumulative_nav_pct"].iloc[-1] - 1.0) < _NAV_PCT_TOL

    def test_ladder_nav_pct_non_negative(self, profiler_normal, profiler_stress):
        for label, profiler in [("normal", profiler_normal), ("stress", profiler_stress)]:
            ladder = profiler.liquidity_ladder()
            assert (ladder["nav_pct"] >= 0).all(), f"{label} ladder has negative nav_pct"


# ── Stressed Ladder (GUI aggregation) ────────────────────────────────────

class TestStressedLadder:
    """
    Covers the stressed_agg DataFrame built in the GUI's _compute_engines()
    — same logic, tested without any Tkinter dependency.
    """

    @pytest.fixture(scope="class")
    def stressed_agg(self, portfolio):
        engine = StressEngine(portfolio, STRESS_SCENARIOS)
        results = engine.run_detail()
        worst = next(
            (s for s in results if "Severe" in s.scenario_name),
            results[-1],
        )
        stressed_nav = worst.position_detail["market_value_eur"].sum()
        agg = (
            worst.position_detail
            .groupby("bucket")
            .agg(
                realisable_value_eur=("realisable_value", "sum"),
                market_value_eur=("market_value_eur", "sum"),
            )
            .reindex(BUCKET_ORDER, fill_value=0.0)
            .reset_index()
        )
        agg["nav_pct"] = agg["market_value_eur"] / stressed_nav if stressed_nav > 0 else 0.0
        agg["cumulative_nav_pct"] = agg["nav_pct"].cumsum()
        return agg

    def test_stressed_agg_nav_pct_sums_to_100(self, stressed_agg):
        assert abs(stressed_agg["nav_pct"].sum() - 1.0) < _NAV_PCT_TOL, (
            f"Stressed agg nav_pct sums to {stressed_agg['nav_pct'].sum():.8f}, expected 1.0"
        )

    def test_stressed_agg_cumulative_ends_at_100(self, stressed_agg):
        assert abs(stressed_agg["cumulative_nav_pct"].iloc[-1] - 1.0) < _NAV_PCT_TOL

    def test_stressed_agg_all_buckets_present(self, stressed_agg):
        assert list(stressed_agg["bucket"]) == list(BUCKET_ORDER)

    def test_stressed_agg_nav_pct_non_negative(self, stressed_agg):
        assert (stressed_agg["nav_pct"] >= 0).all()


# ── Redemption Simulator ──────────────────────────────────────────────────

class TestRedemptionSimulator:
    def test_returns_all_scenarios(self, portfolio, profiler_normal):
        sim = RedemptionSimulator(portfolio, profiler_normal.position_buckets)
        df = sim.run()
        assert len(df) == len(REDEMPTION_SCENARIOS)

    def test_larger_redemption_harder_to_meet(self, portfolio, profiler_normal):
        sim = RedemptionSimulator(portfolio, profiler_normal.position_buckets)
        df = sim.run().sort_values("scenario_pct")
        # Can-meet-t1 should be non-increasing as scenario_pct grows
        t1_series = df["can_meet_t1"].astype(int).values
        for i in range(len(t1_series) - 1):
            assert t1_series[i] >= t1_series[i+1]

    def test_gate_triggered_at_10pct(self, portfolio, profiler_normal):
        sim = RedemptionSimulator(portfolio, profiler_normal.position_buckets)
        df = sim.run()
        row_10 = df[df["scenario_pct"] == 0.10].iloc[0]
        assert row_10["gate_triggered"] is True or row_10["gate_triggered"] == True

    def test_shortfall_non_negative(self, portfolio, profiler_normal):
        sim = RedemptionSimulator(portfolio, profiler_normal.position_buckets)
        df = sim.run()
        assert (df["shortfall_eur"] >= 0).all()


# ── Waterfall Engine ───────────────────────────────────────────────────────

class TestWaterfallEngine:
    def test_proceeds_non_negative(self, portfolio, profiler_normal):
        wf = WaterfallEngine(portfolio, profiler_normal.position_buckets)
        result = wf.run(portfolio.total_nav * 0.10)
        assert result.total_proceeds_eur >= 0

    def test_small_redemption_met(self, portfolio, profiler_normal):
        wf = WaterfallEngine(portfolio, profiler_normal.position_buckets)
        result = wf.run(portfolio.total_nav * 0.02)
        assert result.target_met

    def test_sell_schedule_df_columns(self, portfolio, profiler_normal):
        wf = WaterfallEngine(portfolio, profiler_normal.position_buckets)
        result = wf.run(portfolio.total_nav * 0.10)
        df = result.sell_schedule_df()
        assert "net_proceeds_eur" in df.columns
        assert "bucket" in df.columns

    def test_nav_impact_between_0_and_1(self, portfolio, profiler_normal):
        wf = WaterfallEngine(portfolio, profiler_normal.position_buckets)
        result = wf.run(portfolio.total_nav * 0.20)
        assert 0 <= result.nav_impact_pct <= 1.0


# ── Stress Engine ─────────────────────────────────────────────────────────

class TestStressEngine:
    def test_all_scenarios_run(self, portfolio):
        engine = StressEngine(portfolio)
        results = engine.run()
        assert len(results) == len(STRESS_SCENARIOS)

    def test_nav_decreases_under_shock(self, portfolio):
        engine = StressEngine(portfolio)
        results = engine.run_detail()
        equity_scenario = next(r for r in results if "Equity-Led Stress -20" in r.scenario_name)
        assert equity_scenario.nav_after_shock < equity_scenario.nav_before

    def test_liquid_pct_between_0_and_1(self, portfolio):
        engine = StressEngine(portfolio)
        results = engine.run()
        assert (results["liquid_pct_after"] >= 0).all()
        assert (results["liquid_pct_after"] <= 1.0).all()

    def test_base_scenario_minimal_impact(self, portfolio):
        engine = StressEngine(portfolio)
        results = engine.run_detail()
        base = next(r for r in results if r.scenario_name == "Base")
        assert abs(base.nav_impact_pct) < 0.001  # effectively zero


# ── Risk Metrics Builder ──────────────────────────────────────────────────

class TestRiskMetricsBuilder:
    def test_lcr_ordering(self, portfolio):
        builder = RiskMetricsBuilder(portfolio)
        lm = builder.build_liquidity_metrics()
        assert lm.lcr_t1 <= lm.lcr_t3 <= lm.lcr_t7

    def test_illiquid_plus_liquid_le_1(self, portfolio):
        builder = RiskMetricsBuilder(portfolio)
        lm = builder.build_liquidity_metrics()
        assert lm.lcr_t7 + lm.illiquid_pct <= 1.01  # allow rounding

    def test_stress_summary_shape(self, portfolio):
        builder = RiskMetricsBuilder(portfolio)
        df = builder.build_stress_summary()
        assert len(df) == len(STRESS_SCENARIOS)
        assert "nav_impact_pct" in df.columns

    def test_redemption_summary_has_both_regimes(self, portfolio):
        builder = RiskMetricsBuilder(portfolio)
        df = builder.build_redemption_summary()
        assert set(df["regime"]) == {"normal", "stress"}
