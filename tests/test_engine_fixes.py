"""
tests/test_engine_fixes.py
Regression tests for two audit findings:

  #1  run_reverse_stress() must isolate the swept shock_parameter by starting
      from a NEUTRAL base scenario. Previously it deep-copied self.scenarios[-1]
      (the worst-case scenario), which contaminated the breach shock level with
      baked-in equity/credit/haircut/ADV/redemption shocks and coupled the answer
      to the contents/order of self.scenarios.

  #2  WaterfallEngine.run() and run_lp_optimised() must raise enough to meet the
      redemption AND retain the MIN_CASH_BUFFER_PCT cash buffer
      (effective_target = target_eur + nav * MIN_CASH_BUFFER_PCT). Previously the
      buffer was computed but ignored, so the engine under-liquidated.
"""
import datetime

import pytest

from liquidity_risk_tool.models.position import Position, Portfolio
from liquidity_risk_tool.engines.stress_engine import StressEngine
from liquidity_risk_tool.engines.liquidity_profiler import LiquidityProfiler
from liquidity_risk_tool.engines.waterfall_engine import WaterfallEngine
from liquidity_risk_tool.config.settings import (
    StressScenario,
    MIN_CASH_BUFFER_PCT,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_portfolio(positions):
    return Portfolio(
        fund_name="FixTest", fund_id="FIX", base_currency="EUR",
        reporting_date=datetime.datetime(2024, 12, 31),
        positions=positions, share_classes=[],
    )


def _equity_plus_illiquid_portfolio():
    """700k liquid equity (T+1) + 300k locked illiquid ballast (>T+7).

    The equity ADV (3.5M) keeps it in T+1 at adv_stress_scalar=1.0 but pushes it
    to T+3 at scalar=0.5, so a contaminated base (which carried the worst-case
    ADV collapse) would have produced a materially different breach level.
    Because the liquid fraction = equity/(equity+ballast) shrinks as the equity
    is shocked down, sweeping equity_shock alone genuinely drives liquidity down.
    """
    equity = Position(
        isin="EQ001", name="Equity A", asset_class="listed_equity",
        market_value=700_000.0, currency="EUR", fx_rate=1.0,
        adv_30d=3_500_000.0, beta=1.0, bid_ask_spread_bps=0.0, weight=0.7,
    )
    ballast = Position(
        isin="RE001", name="Locked RE", asset_class="real_estate",
        market_value=300_000.0, currency="EUR", fx_rate=1.0,
        adv_30d=0.0, is_locked=True, bid_ask_spread_bps=0.0, weight=0.3,
    )
    return _make_portfolio([equity, ballast])


def _single_liquid_portfolio():
    """One large, highly-liquid position whose ADV cap never binds, so the
    waterfall can always raise exactly the (buffered) target."""
    equity = Position(
        isin="EQ100", name="Big Liquid Equity", asset_class="listed_equity",
        market_value=10_000_000.0, currency="EUR", fx_rate=1.0,
        adv_30d=100_000_000.0, beta=1.0, bid_ask_spread_bps=0.0, weight=1.0,
    )
    return _make_portfolio([equity])


# ---------------------------------------------------------------------------
# Finding #1 — reverse-stress contamination
# ---------------------------------------------------------------------------

class TestReverseStressIsolation:

    TARGET = 0.55  # between the unshocked (~0.62) and max-shock (~0.47) liquid pct

    def test_result_independent_of_scenarios_last_element(self):
        """The breach result must NOT depend on self.scenarios[-1].

        Two engines over the SAME portfolio but with different last scenarios
        must return identical reverse-stress results, because the search now
        starts from a neutral base rather than self.scenarios[-1].
        """
        port = _equity_plus_illiquid_portfolio()

        mild = StressScenario(
            name="Mild", equity_shock=0.0, credit_spread_shock_bps=0,
            liquidity_haircut_multiplier=1.0, redemption_rate=0.0,
            adv_stress_scalar=1.0, rate_shock_bps=0,
        )
        # A drastically different worst-case last scenario. Under the old bug this
        # was deep-copied as the search base and would have changed the answer.
        severe = StressScenario(
            name="Severe", equity_shock=-0.20, credit_spread_shock_bps=300,
            liquidity_haircut_multiplier=2.0, redemption_rate=0.30,
            adv_stress_scalar=0.50, rate_shock_bps=100, is_worst_case=True,
        )

        engine_a = StressEngine(port, scenarios=[mild])
        engine_b = StressEngine(port, scenarios=[mild, severe])

        result_a = engine_a.run_reverse_stress(target_liquid_pct=self.TARGET)
        result_b = engine_b.run_reverse_stress(target_liquid_pct=self.TARGET)

        assert result_a == result_b

    def test_breach_found_and_scenario_label_is_neutral(self):
        port = _equity_plus_illiquid_portfolio()
        engine = StressEngine(port, scenarios=[
            StressScenario(
                name="Worst", equity_shock=-0.20, credit_spread_shock_bps=300,
                liquidity_haircut_multiplier=2.0, redemption_rate=0.30,
                adv_stress_scalar=0.50, rate_shock_bps=100, is_worst_case=True,
            )
        ])

        result = engine.run_reverse_stress(
            target_liquid_pct=self.TARGET, shock_parameter="equity_shock",
        )

        assert result["found"] is True
        assert 0.0 < result["breach_shock_level"] < 0.60
        # liquidity at the located breach is at or below the requested threshold
        assert result["liquid_pct_at_breach"] <= self.TARGET + 1e-6
        # the breach is attributed to the neutral isolation scenario, never a
        # worst-case scenario name from self.scenarios
        assert result["scenario_at_breach"] == "Reverse stress (equity_shock)"


# ---------------------------------------------------------------------------
# Finding #2 — MIN_CASH_BUFFER_PCT honoured by the waterfall
# ---------------------------------------------------------------------------

class TestWaterfallBuffer:

    TARGET = 1_000_000.0

    def _profiled(self):
        port = _single_liquid_portfolio()
        profile = LiquidityProfiler(port).run().position_buckets
        return port, profile

    def test_run_raises_target_plus_buffer(self):
        port, profile = self._profiled()
        engine = WaterfallEngine(port, profile)

        result = engine.run(self.TARGET)

        buffer = port.total_nav * MIN_CASH_BUFFER_PCT
        expected = self.TARGET + buffer

        assert buffer > 0  # sanity: there IS a buffer to retain
        # proceeds cover the redemption AND the retained cash buffer
        assert result.total_proceeds_eur == pytest.approx(expected, rel=1e-6)
        # and strictly more than the bare redemption (the old bug raised only target)
        assert result.total_proceeds_eur > self.TARGET + buffer * 0.5
        assert result.target_met is True
        assert result.residual_shortfall_eur == pytest.approx(0.0, abs=0.01)

    def test_run_lp_optimised_raises_target_plus_buffer(self):
        pytest.importorskip("scipy")
        port, profile = self._profiled()
        engine = WaterfallEngine(port, profile)

        result = engine.run_lp_optimised(self.TARGET)

        buffer = port.total_nav * MIN_CASH_BUFFER_PCT
        expected = self.TARGET + buffer

        assert result.total_proceeds_eur == pytest.approx(expected, rel=1e-6)
        assert result.total_proceeds_eur > self.TARGET + buffer * 0.5
        assert result.target_met is True
        assert result.residual_shortfall_eur == pytest.approx(0.0, abs=0.01)
