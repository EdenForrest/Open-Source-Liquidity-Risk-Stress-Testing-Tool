"""
tests/test_engine_robustness.py
Engine-hardening tests: empty portfolios, zero NAV, non-finite inputs, and
integer-dtype market values must not crash or corrupt any analytical engine.

Complements tests/test_engine_fixes.py (which covers reverse-stress isolation,
coherence, ray bisection, and waterfall buffer math) — no overlap.
"""
import datetime
import math
import warnings

import pandas as pd
import pytest

from liquidity_risk_tool.config.settings import StressScenario
from liquidity_risk_tool.engines.liquidity_profiler import LiquidityProfiler
from liquidity_risk_tool.engines.redemption_simulator import RedemptionSimulator
from liquidity_risk_tool.engines.stress_engine import StressEngine
from liquidity_risk_tool.engines.waterfall_engine import WaterfallEngine
from liquidity_risk_tool.models.position import Portfolio, Position


def _make_pos(**overrides) -> Position:
    defaults = dict(
        isin="TEST001", name="Test", asset_class="listed_equity",
        market_value=1_000_000.0, currency="EUR", fx_rate=1.0,
        adv_30d=500_000.0, weight=0.05,
    )
    defaults.update(overrides)
    return Position(**defaults)


def _make_portfolio(positions) -> Portfolio:
    return Portfolio(
        fund_name="RobustTest",
        fund_id="ROB",
        base_currency="EUR",
        reporting_date=datetime.datetime(2024, 12, 31),
        positions=positions,
        share_classes=[],
    )


def _mild_scenario(**overrides) -> StressScenario:
    defaults = dict(
        name="RobustnessTest",
        equity_shock=-0.10, credit_spread_shock_bps=100,
        liquidity_haircut_multiplier=1.2, redemption_rate=0.10,
        adv_stress_scalar=0.8, rate_shock_bps=50,
    )
    defaults.update(overrides)
    return StressScenario(**defaults)


# ---------------------------------------------------------------------------
# Empty portfolio / zero NAV
# ---------------------------------------------------------------------------

class TestEmptyPortfolio:
    @pytest.fixture()
    def empty_portfolio(self):
        return _make_portfolio([])

    def test_profiler_runs_on_empty_portfolio(self, empty_portfolio):
        profiler = LiquidityProfiler(empty_portfolio).run()
        df = profiler.position_buckets
        assert df.empty
        for col in ("bucket", "haircut", "realisable_value", "realisable_weight"):
            assert col in df.columns

    def test_profiler_ladder_on_empty_portfolio(self, empty_portfolio):
        profiler = LiquidityProfiler(empty_portfolio).run()
        ladder = profiler.liquidity_ladder()
        assert (ladder["nav_pct"] == 0.0).all()
        assert profiler.liquidity_at_horizon(1) == 0.0
        assert profiler.liquidity_at_horizon(7) == 0.0

    def test_profiler_stress_regime_on_empty_portfolio(self, empty_portfolio):
        profiler = LiquidityProfiler(
            empty_portfolio, stress=True, adv_stress_scalar=0.5
        ).run()
        assert profiler.position_buckets.empty

    def test_waterfall_on_empty_portfolio(self, empty_portfolio):
        profile = LiquidityProfiler(empty_portfolio).run().position_buckets
        result = WaterfallEngine(empty_portfolio, profile).run(1_000_000.0)
        assert result.total_proceeds_eur == 0.0
        assert not result.target_met
        assert math.isfinite(result.nav_impact_pct)

    def test_redemption_simulator_on_empty_portfolio(self, empty_portfolio):
        profile = LiquidityProfiler(empty_portfolio).run().position_buckets
        sim = RedemptionSimulator(empty_portfolio, profile)
        summary = sim.run(scenarios=[0.05, 0.25])
        assert len(summary) == 2
        # Zero NAV ⇒ all ratio columns must be finite (safe_divide defaults)
        assert summary["liquidity_available_pct"].apply(math.isfinite).all()
        assert summary["shortfall_pct"].apply(math.isfinite).all()

    def test_stress_engine_on_empty_portfolio(self, empty_portfolio):
        engine = StressEngine(empty_portfolio, scenarios=[_mild_scenario()])
        results = engine.run()
        assert len(results) == 1
        row = results.iloc[0]
        assert row["nav_before"] == 0.0
        assert math.isfinite(row["nav_impact_pct"])


# ---------------------------------------------------------------------------
# Waterfall target validation
# ---------------------------------------------------------------------------

class TestWaterfallTargetValidation:
    @pytest.fixture()
    def engine(self):
        portfolio = _make_portfolio([_make_pos()])
        profile = LiquidityProfiler(portfolio).run().position_buckets
        return WaterfallEngine(portfolio, profile)

    @pytest.mark.parametrize("bad_target", [float("nan"), float("inf"),
                                            float("-inf"), -1.0])
    def test_run_rejects_bad_target(self, engine, bad_target):
        with pytest.raises(ValueError, match="target_eur"):
            engine.run(bad_target)

    @pytest.mark.parametrize("bad_target", [float("nan"), float("inf"),
                                            float("-inf"), -1.0])
    def test_run_lp_optimised_rejects_bad_target(self, engine, bad_target):
        with pytest.raises(ValueError, match="target_eur"):
            engine.run_lp_optimised(bad_target)

    def test_zero_target_is_allowed(self, engine):
        result = engine.run(0.0)
        assert math.isfinite(result.nav_impact_pct)


# ---------------------------------------------------------------------------
# Redemption scenario validation
# ---------------------------------------------------------------------------

class TestRedemptionScenarioValidation:
    @pytest.fixture()
    def sim(self):
        portfolio = _make_portfolio([_make_pos()])
        profile = LiquidityProfiler(portfolio).run().position_buckets
        return RedemptionSimulator(portfolio, profile)

    @pytest.mark.parametrize("bad_pct", [float("nan"), float("inf"), -0.05])
    def test_bad_scenario_pct_rejected(self, sim, bad_pct):
        with pytest.raises(ValueError, match="scenario"):
            sim.run(scenarios=[0.05, bad_pct])

    def test_valid_scenarios_still_run(self, sim):
        summary = sim.run(scenarios=[0.05, 0.25])
        assert len(summary) == 2


# ---------------------------------------------------------------------------
# Reverse-stress input validation
# ---------------------------------------------------------------------------

class TestReverseStressInputValidation:
    @pytest.fixture()
    def engine(self):
        return StressEngine(_make_portfolio([_make_pos()]),
                            scenarios=[_mild_scenario()])

    def test_unknown_shock_parameter_rejected(self, engine):
        with pytest.raises(ValueError, match="shock_parameter"):
            engine.run_reverse_stress(shock_parameter="not_a_parameter")

    @pytest.mark.parametrize("lo,hi", [
        (float("nan"), 0.6),
        (0.0, float("inf")),
        (0.6, 0.6),     # lo == hi
        (0.8, 0.2),     # lo > hi
    ])
    def test_bad_bounds_rejected(self, engine, lo, hi):
        with pytest.raises(ValueError, match="bounds"):
            engine.run_reverse_stress(lo=lo, hi=hi)

    @pytest.mark.parametrize("bad_tol", [0.0, -0.01, float("nan")])
    def test_bad_tolerance_rejected(self, engine, bad_tol):
        with pytest.raises(ValueError, match="tolerance"):
            engine.run_reverse_stress(tolerance=bad_tol)


# ---------------------------------------------------------------------------
# Integer market values must not truncate or warn in StressEngine
# ---------------------------------------------------------------------------

class TestIntegerMarketValues:
    def test_int_market_values_no_future_warning(self):
        # Integer market values give positions_df an int64 column; without the
        # float cast, assigning shocked (float) values back would truncate and
        # emit a pandas FutureWarning.
        portfolio = _make_portfolio([
            _make_pos(isin="EQ1", market_value=1_000_000),
            _make_pos(isin="BD1", asset_class="ig_corporate_bond",
                      market_value=2_000_000, duration=4.0,
                      credit_spread_bps=120),
        ])
        engine = StressEngine(portfolio, scenarios=[_mild_scenario()])
        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)
            results = engine.run()
        row = results.iloc[0]
        # -10% equity shock on 1m equity must show up (no int truncation to 0
        # impact, no inflated loss)
        assert row["nav_impact_eur"] < 0
        assert math.isfinite(row["nav_impact_pct"])

    def test_shock_preserves_fractional_losses(self):
        portfolio = _make_portfolio([_make_pos(isin="EQ1", market_value=999)])
        scenario = _mild_scenario(equity_shock=-0.105,
                                  credit_spread_shock_bps=0,
                                  rate_shock_bps=0, redemption_rate=0.0)
        engine = StressEngine(portfolio, scenarios=[scenario])
        detail = engine.run_detail()[0]
        # 999 * 10.5% = 104.895 — int64 truncation would round this away
        # (equity_loss_eur is signed: losses are negative)
        assert detail.equity_loss_eur == pytest.approx(-999 * 0.105)


# ---------------------------------------------------------------------------
# Negative market values: cash overdrafts and short positions are LIABILITIES.
# Haircuts must gross UP the cost of closing them, never shrink them.
# ---------------------------------------------------------------------------

class TestNegativeMarketValues:
    def test_profiler_haircut_grosses_up_negative_mv(self):
        # A short HY bond of -1,000,000 with a 5% haircut should cost MORE than
        # face to close (-1,050,000), not LESS. mv*(1-h) would give -950,000,
        # understating the liability and overstating fund liquidity. Spread set
        # to 0 so the haircut equals the pure 5% asset-class haircut.
        portfolio = _make_portfolio([
            _make_pos(isin="HY_SHORT", asset_class="hy_corporate_bond",
                      market_value=-1_000_000.0, adv_30d=0.0,
                      bid_ask_spread_bps=0.0),
        ])
        profile = LiquidityProfiler(portfolio).run().position_buckets
        row = profile.iloc[0]
        realisable = row["realisable_value"]
        mv = row["market_value_eur"]
        haircut = row["haircut"]
        assert haircut == pytest.approx(0.05)
        assert realisable == pytest.approx(mv - abs(mv) * haircut)
        assert realisable == pytest.approx(-1_050_000.0)
        # The liability must not have shrunk toward zero.
        assert realisable < mv

    def test_profiler_short_position_not_treated_as_asset(self):
        # A short equity (-500k) sits alongside a long (+1m). The short's
        # realisable value must remain negative (a cost), not flip positive.
        portfolio = _make_portfolio([
            _make_pos(isin="LONG", market_value=1_000_000.0),
            _make_pos(isin="SHORT", market_value=-500_000.0),
        ])
        profile = LiquidityProfiler(portfolio).run().position_buckets
        short_row = profile[profile["isin"] == "SHORT"].iloc[0]
        assert short_row["realisable_value"] < 0

    def test_waterfall_skips_negative_mv_positions(self):
        # The waterfall must not book phantom proceeds from "selling" a short
        # or overdraft. Only the +1m long can fund a redemption.
        portfolio = _make_portfolio([
            _make_pos(isin="LONG", market_value=1_000_000.0,
                      asset_class="listed_equity", adv_30d=10_000_000.0),
            _make_pos(isin="SHORT", market_value=-500_000.0,
                      asset_class="listed_equity", adv_30d=10_000_000.0),
        ])
        profile = LiquidityProfiler(portfolio).run().position_buckets
        result = WaterfallEngine(portfolio, profile).run(2_000_000.0)
        # Proceeds can come only from the long position; the short cannot add cash.
        assert result.total_proceeds_eur <= 1_000_000.0
        # No line item should be sourced from a negative-MV position.
        for order in result.sell_orders:
            assert order.gross_value >= 0

    def test_waterfall_lp_skips_negative_mv_positions(self):
        portfolio = _make_portfolio([
            _make_pos(isin="LONG", market_value=1_000_000.0,
                      asset_class="listed_equity", adv_30d=10_000_000.0),
            _make_pos(isin="SHORT", market_value=-500_000.0,
                      asset_class="listed_equity", adv_30d=10_000_000.0),
        ])
        profile = LiquidityProfiler(portfolio).run().position_buckets
        result = WaterfallEngine(portfolio, profile).run_lp_optimised(2_000_000.0)
        assert result.total_proceeds_eur <= 1_000_000.0
        for order in result.sell_orders:
            assert order.gross_value >= 0


# ---------------------------------------------------------------------------
# Leveraged derivatives: market_value is margin/MtM, exposure_base is the
# economic notional that actually moves under a shock.
# ---------------------------------------------------------------------------

class TestDerivativeLeverage:
    def test_stress_shocks_derivative_on_exposure_base(self):
        # A future carried at ~zero margin MV but +10m of long equity exposure
        # must lose ~10m * shock under the equity crash, even though its MV is
        # near zero. Without _shock_derivatives this showed ZERO stress P&L.
        portfolio = _make_portfolio([
            _make_pos(isin="FUT_LONG", asset_class="future",
                      market_value=50_000.0, exposure_base=10_000_000.0,
                      adv_30d=0.0),
        ])
        scenario = _mild_scenario(equity_shock=-0.20, credit_spread_shock_bps=0,
                                  rate_shock_bps=0, redemption_rate=0.0,
                                  liquidity_haircut_multiplier=1.0)
        detail = StressEngine(portfolio, scenarios=[scenario]).run_detail()[0]
        # 10m notional * -20% = -2m loss (beta defaults to 1.0).
        assert detail.derivative_loss_eur == pytest.approx(-2_000_000.0)
        # NAV impact must reflect the notional loss, not the tiny margin MV.
        assert detail.nav_impact_eur == pytest.approx(-2_000_000.0)

    def test_stress_short_hedge_gains_in_crash(self):
        # A short index future (negative exposure_base) is a hedge: it GAINS
        # when the market falls, partly offsetting long-book losses.
        portfolio = _make_portfolio([
            _make_pos(isin="EQ", asset_class="listed_equity",
                      market_value=10_000_000.0),
            _make_pos(isin="FUT_SHORT", asset_class="future",
                      market_value=0.0, exposure_base=-4_000_000.0,
                      adv_30d=0.0),
        ])
        scenario = _mild_scenario(equity_shock=-0.20, credit_spread_shock_bps=0,
                                  rate_shock_bps=0, redemption_rate=0.0,
                                  liquidity_haircut_multiplier=1.0)
        detail = StressEngine(portfolio, scenarios=[scenario]).run_detail()[0]
        # Short hedge: -4m * -20% = +0.8m gain.
        assert detail.derivative_loss_eur == pytest.approx(800_000.0)
        # Equity leg loses 2m; net NAV impact = -2m + 0.8m = -1.2m.
        assert detail.nav_impact_eur == pytest.approx(-1_200_000.0)

    def test_leverage_commitment_uses_exposure_base(self):
        from liquidity_risk_tool.engines.leverage_engine import LeverageEngine
        # NAV is the position-MV sum (no share classes). 1m cash + 50k future
        # margin = 1.05m NAV. The future carries 10m of notional via
        # exposure_base, which must drive BOTH leverage measures — not its
        # 50k margin MV. The cash contributes its own 1m to each numerator.
        portfolio = _make_portfolio([
            _make_pos(isin="CASH", asset_class="cash",
                      market_value=1_000_000.0, adv_30d=0.0),
            _make_pos(isin="FUT", asset_class="future",
                      market_value=50_000.0, exposure_base=10_000_000.0,
                      adv_30d=0.0),
        ])
        nav = portfolio.total_nav  # 1_050_000
        result = LeverageEngine(portfolio).run()
        # Numerator = 1m cash + 10m future notional = 11m (NOT 1.05m).
        expected = 11_000_000.0 / nav
        assert result.gross_leverage == pytest.approx(expected)
        assert result.commitment_leverage == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Duplicate ISINs: two lots/tranches of the same instrument must each retain
# their own shocked MV, not collapse to a single value.
# ---------------------------------------------------------------------------

class TestDuplicateIsin:
    def test_shocked_portfolio_preserves_duplicate_isins(self):
        portfolio = _make_portfolio([
            _make_pos(isin="DUP", market_value=1_000_000.0),
            _make_pos(isin="DUP", market_value=3_000_000.0),
        ])
        scenario = _mild_scenario(equity_shock=-0.10, credit_spread_shock_bps=0,
                                  rate_shock_bps=0, redemption_rate=0.0,
                                  liquidity_haircut_multiplier=1.0)
        engine = StressEngine(portfolio, scenarios=[scenario])
        shocked = engine._build_shocked_portfolio(
            engine._shock_equities(portfolio.positions_df.copy(), -0.10)
        )
        mvs = sorted(pos.market_value for pos in shocked.positions)
        # Each lot shocked by -10%: 900k and 2.7m — NOT both collapsed to 2.7m.
        assert mvs == pytest.approx([900_000.0, 2_700_000.0])
