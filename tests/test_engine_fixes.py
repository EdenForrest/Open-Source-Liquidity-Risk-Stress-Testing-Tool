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
from liquidity_risk_tool.engines.reverse_stress_engine import (
    ReverseStressEngine,
    DEFAULT_AXES,
    COHERENCE_AUTONOMY,
    SHOCK_CORRELATION,
)
from liquidity_risk_tool.config.settings import (
    StressScenario,
    MIN_CASH_BUFFER_PCT,
)

import numpy as np


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


def _cash_heavy_robust_portfolio():
    """60% cash (T+0, zero haircut even under stress) + 40% liquid equity.

    Cash alone (60% of NAV, no haircut, settles T+0) covers the worst-case 50%
    redemption with headroom, so the fund can meet redemptions across the ENTIRE
    plausible shock box — including the severe corner (deep equity crash, ADV
    collapse, 5x haircut, 50% redemptions). There is therefore no Can-Meet=NO
    scenario to find, and reverse stress must report ``found=False``.
    """
    cash = Position(
        isin="CASH01", name="EUR Cash", asset_class="cash",
        market_value=6_000_000.0, currency="EUR", fx_rate=1.0,
        adv_30d=1e12, bid_ask_spread_bps=0.0, weight=0.6,
    )
    equity = Position(
        isin="EQ100", name="Big Liquid Equity", asset_class="listed_equity",
        market_value=4_000_000.0, currency="EUR", fx_rate=1.0,
        adv_30d=100_000_000.0, beta=1.0, bid_ask_spread_bps=0.0, weight=0.4,
    )
    return _make_portfolio([cash, equity])


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


# ---------------------------------------------------------------------------
# Finding #3 — reverse stress is, BY DEFINITION, a Can-Meet = NO scenario
# ---------------------------------------------------------------------------

class TestReverseStressIsRedemptionFailure:
    """A reverse-stress breach must, by definition, be a scenario the fund
    cannot survive: it fails to meet redemptions within the settlement horizon.

    The bug: the optimiser constrained on the T0-T1 liquidity floor alone, so it
    could return a scenario that dipped below the floor yet still raised enough
    cash to meet (small) redemptions — surfacing ``Can Meet = YES`` on the
    scenario-results table. That is not an actual failure. The breach test is now
    ``can_meet_redemption is False``, so every materialised reverse-stress
    scenario is, by construction, ``Can Meet = NO``.
    """

    def _breachable_portfolio(self):
        """700k liquid equity (T+1) + 300k locked illiquid ballast (>T+7).

        Under the severe corner (deep equity crash, ADV collapse, haircut
        blow-out, 50% redemptions) the fund cannot raise the redemption within
        the 7-day horizon — a genuine redemption failure exists in the box, so a
        breach IS findable and must be Can Meet = NO.
        """
        return _equity_plus_illiquid_portfolio()

    def test_breach_scenario_cannot_meet_redemption(self):
        port = self._breachable_portfolio()
        engine = StressEngine(port, scenarios=[
            StressScenario(
                name="dummy", equity_shock=0.0, credit_spread_shock_bps=0,
                liquidity_haircut_multiplier=1.0, redemption_rate=0.0,
            )
        ])
        rev = ReverseStressEngine(engine)

        scenario, scenario_result, reverse_result = rev.run(
            n_starts=4, grid_per_axis=3, max_evaluations=120,
        )

        # A breach must be found in this deliberately-breachable book.
        assert reverse_result.found is True
        assert scenario is not None
        assert scenario_result is not None

        # BY DEFINITION: the materialised reverse-stress scenario is a scenario
        # the fund cannot survive — it must report Can Meet = NO.
        # (use truthiness, not `is False`, to tolerate numpy bool types)
        assert not scenario_result.can_meet_redemption
        # The solver's own record of the breach must agree.
        assert not reverse_result.can_meet_redemption_at_breach

    @pytest.mark.xfail(
        reason="Depends on the waterfall sourcing the T+0 cash bucket. The "
        "profiler now correctly marks cash fully realisable (realisable_value = "
        "full MV, days_to_liquidate=0), but WaterfallEngine.run() still does not "
        "draw the cash bucket, so a 60%-cash fund spuriously fails a 50% "
        "redemption at the severe corner and a breach IS findable. Currently this "
        "test only passes because the 120-evaluation budget runs out before the "
        "search reaches the severe corner — it would flip red under a larger "
        "budget. Marked xfail until the waterfall cash-sourcing fix lands; remove "
        "the marker then.",
        strict=False,
    )
    def test_robust_book_reports_no_breach(self):
        """A fund that can always meet redemptions across the whole plausible box
        must report found=False (no Can-Meet=NO scenario exists) rather than
        materialising a misleading breach row."""
        port = _cash_heavy_robust_portfolio()  # 60% cash covers any 50% redemption
        engine = StressEngine(port, scenarios=[
            StressScenario(
                name="dummy", equity_shock=0.0, credit_spread_shock_bps=0,
                liquidity_haircut_multiplier=1.0, redemption_rate=0.0,
            )
        ])
        rev = ReverseStressEngine(engine)

        scenario, scenario_result, reverse_result = rev.run(
            n_starts=4, grid_per_axis=3, max_evaluations=120,
        )

        assert reverse_result.found is False
        assert scenario is None
        assert scenario_result is None


# ---------------------------------------------------------------------------
# Finding #4 — reverse-stress breaches must be ECONOMICALLY COHERENT
# ---------------------------------------------------------------------------

class TestReverseStressCoherence:
    """A reverse-stress breach must be *severe but plausible* (ESMA Guideline 17 /
    AIFMD II Art.16(1)) — not just individually-bounded on each axis.

    The bug: a diagonal severity norm treated the five drivers as independent, so
    the optimiser could return economically incoherent corners — e.g. a ×3
    liquidity-haircut blow-out with 25% redemptions while equities, spreads and
    rates are all flat and trading volume is normal. Liquidity never dries up on
    its own; it dries up *because* markets fall. The fix is a Mahalanobis severity
    norm (penalising shocks that violate the crisis co-movement structure) plus a
    hard coherence guardrail forbidding liquidity-only / redemption-only breaches
    with no justifying market driver.

    Axis order (matches DEFAULT_AXES):
        0 equity_shock  1 rate_shock_bps  2 adv_stress_scalar
        3 liquidity_haircut_multiplier   4 redemption_rate
    """

    def _engine(self):
        """A ReverseStressEngine wired to its plausibility model only (the helper
        methods under test never reprice the portfolio, so no StressEngine needed)."""
        eng = ReverseStressEngine.__new__(ReverseStressEngine)
        eng.axes = DEFAULT_AXES
        eng._precision = eng._build_precision()
        return eng

    # ---- the precise incoherent corner the user reported --------------------

    def test_user_reported_incoherent_corner_is_rejected(self):
        """Equity 0%, spread 0, rate 0, ADV 1x, haircut ~3x, redemptions 25% — the
        exact incoherent result from the bug report — must fail the guardrail."""
        eng = self._engine()
        # haircut multiplier ~3x is severity ~0.5 (calm 1.0 -> severe 5.0);
        # 25% redemptions is severity 0.5 (calm 0.0 -> severe 0.50). Markets calm.
        s = np.array([0.0, 0.0, 0.0, 0.5, 0.5])
        assert eng._is_coherent(s) is False
        assert eng._coherence_margin(s) < 0

    def test_coherent_combined_shock_is_accepted(self):
        """A liquidity blow-out of the SAME severity, but with markets also stressed
        (the way real crises move), must pass the guardrail."""
        eng = self._engine()
        s = np.array([0.5, 0.3, 0.5, 0.6, 0.5])  # equity/rate/adv stressed too
        assert eng._is_coherent(s) is True
        assert eng._coherence_margin(s) >= 0

    def test_autonomous_allowance_band(self):
        """Liquidity stress may exceed market stress by up to COHERENCE_AUTONOMY
        (idiosyncratic fund pressure), but not beyond."""
        eng = self._engine()
        within = np.array([0.40, 0.0, 0.0, 0.40 + COHERENCE_AUTONOMY - 1e-3, 0.0])
        beyond = np.array([0.40, 0.0, 0.0, 0.40 + COHERENCE_AUTONOMY + 1e-2, 0.0])
        assert eng._is_coherent(within) is True
        assert eng._is_coherent(beyond) is False

    def test_severe_corner_is_coherent(self):
        """The all-severe corner (every driver at 1.0) is coherent — markets and
        liquidity are maximally and jointly stressed — so the feasibility check and
        materialisation fallback remain valid."""
        eng = self._engine()
        assert eng._is_coherent(np.ones(len(DEFAULT_AXES))) is True

    # ---- the Mahalanobis distance itself ------------------------------------

    def test_incoherent_corner_is_farther_than_coherent_of_equal_liquidity(self):
        """Under the Mahalanobis norm, an incoherent liquidity-only corner is more
        *implausible* (larger distance) than a coherent shock with the same
        liquidity severity — so the least-severe-breach search prefers coherence."""
        eng = self._engine()
        incoherent = np.array([0.0, 0.0, 0.0, 0.6, 0.5])
        coherent = np.array([0.5, 0.3, 0.5, 0.6, 0.5])
        assert eng._distance(incoherent) > eng._distance(coherent)

    def test_precision_matrix_is_symmetric_positive_definite(self):
        """Sigma^-1 must be a valid metric: symmetric and positive-definite."""
        eng = self._engine()
        p = eng._precision
        assert np.allclose(p, p.T, atol=1e-9)
        assert float(np.linalg.eigvalsh(p).min()) > 0.0

    def test_distance_gradient_matches_finite_difference(self):
        """The analytic gradient used by SLSQP must match a central finite-diff."""
        eng = self._engine()
        s = np.array([0.3, 0.2, 0.4, 0.5, 0.3])
        g = eng._distance_grad(s)
        h = 1e-6
        fd = np.empty_like(s)
        for i in range(len(s)):
            sp = s.copy(); sp[i] += h
            sm = s.copy(); sm[i] -= h
            fd[i] = (eng._distance(sp) - eng._distance(sm)) / (2 * h)
        assert np.max(np.abs(g - fd)) < 1e-6

    def test_correlation_calibrated_to_forward_scenario_comovement(self):
        """The calibration anchor: SHOCK_CORRELATION must encode POSITIVE crisis
        co-movement (all drivers stress together), matching the firm's own forward
        STRESS_SCENARIOS where liquidity stress always rises with market stress."""
        n = len(DEFAULT_AXES)
        assert SHOCK_CORRELATION.shape == (n, n)
        assert np.allclose(np.diag(SHOCK_CORRELATION), 1.0)
        assert np.allclose(SHOCK_CORRELATION, SHOCK_CORRELATION.T)
        # every off-diagonal co-movement is strictly positive (no driver moves
        # *against* the crisis), and equity is the dominant driver of liquidity.
        off = SHOCK_CORRELATION[~np.eye(n, dtype=bool)]
        assert (off > 0).all()
        eq, _rate, adv, hc, redeem = range(n)
        assert SHOCK_CORRELATION[eq, hc] > 0.5   # equity drawdown drives haircuts
        assert SHOCK_CORRELATION[eq, adv] > 0.5  # equity drawdown drives ADV collapse

    # ---- end-to-end: the full solver only returns coherent breaches ---------

    def test_solver_returns_a_coherent_breach(self):
        """Running the full reverse-stress search on a breachable book must return a
        breach whose severity fractions satisfy the coherence guardrail — i.e. the
        located 'easiest breach' has a genuine market driver, never a liquidity-only
        corner with flat markets (the original bug)."""
        port = _equity_plus_illiquid_portfolio()
        engine = StressEngine(port, scenarios=[
            StressScenario(
                name="dummy", equity_shock=0.0, credit_spread_shock_bps=0,
                liquidity_haircut_multiplier=1.0, redemption_rate=0.0,
            )
        ])
        rev = ReverseStressEngine(engine)

        result = rev.solve(n_starts=6, grid_per_axis=3, max_evaluations=300)

        assert result.found is True
        s = np.array([result.severity_fractions[a.name] for a in rev.axes])
        # the materialised breach is economically coherent ...
        assert rev._is_coherent(s)
        # ... which for this book means a real equity drawdown drives it: the
        # liquidity stress is NOT autonomous of the market.
        assert result.breach_parameters["equity_shock"] < 0.0
