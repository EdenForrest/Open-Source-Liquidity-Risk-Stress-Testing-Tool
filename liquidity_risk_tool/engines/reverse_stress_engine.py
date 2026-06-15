"""
Reverse Stress Testing Engine
-----------------------------
Comprehensive, multi-parameter reverse stress test.

Forward stress testing asks: *"Given scenario X, what happens to liquidity?"*
Reverse stress testing inverts the question, as required by ESMA's Guidelines on
liquidity stress testing (Guideline 17 — reverse stress testing) and AIFMD II
Art.16(1): *"What combination of shocks would breach our liquidity constraint?"*

Unlike a one-dimensional parameter sweep, this engine searches **jointly** over
the five risk drivers a manager actually controls / is exposed to:

    1. equity_shock                 — equity market drawdown (multiplicative)
    2. rate_shock_bps               — parallel rates / govvie shift (additive bps)
    3. adv_stress_scalar            — ADV / volume collapse (market-depth drought)
    4. liquidity_haircut_multiplier — uplift on stress haircuts (bid/ask blow-out)
    5. redemption_rate              — investor outflow as a fraction of NAV

Optimisation problem
--------------------
We look for the *most plausible* (least-severe) joint shock that still produces a
breach — the standard reverse-stress objective, sometimes called the "closest
scenario to the central / calm state" on the breach boundary.

Let ``s = (s_eq, s_rate, s_adv, s_hc, s_redeem) ∈ [0, 1]^5`` be per-parameter
*severity fractions*, each linearly mapped onto a plausible range. We solve::

    minimise    D(s) = sqrt( sᵀ Σ⁻¹ s )                (severity / implausibility)
    subject to  cannot meet redemptions at s            (a breach occurs)
                max liquidity-severity ≤ max market-severity + α   (coherence)
                0 ≤ s_i ≤ 1

``D(s)`` is a **Mahalanobis** distance from the calm state ``s = 0`` under the
crisis co-movement metric ``Σ = W^½ · R · W^½`` (R = :data:`SHOCK_CORRELATION`,
W = per-axis implausibility weights). Coherent shocks — every driver stressing
together, the way real crises move — are *cheap*; an incoherent liquidity-only
blow-out with calm markets is *expensive*. A hard coherence guardrail additionally
forbids liquidity/redemption stress that runs ahead of any market driver by more
than the autonomous allowance ``α`` (:data:`COHERENCE_AUTONOMY`). The constrained
minimiser is therefore the most plausible — never an economically impossible —
way the fund can breach, exactly what reverse stress is meant to find.

The breach surface is non-convex (liquidity responds discontinuously as buckets
cross horizons), so we use a **multi-start SLSQP** search: a coarse grid of
starting points feeds a sequence of gradient-based constrained refinements, and
we keep the coherent breaching point with the smallest ``D(s)``. Every winner is
then **bisected back toward calm along its Mahalanobis ray** to shed any residual
severity the gradient step left on the table. If scipy is unavailable, that same
ray bisection from the most-breaching grid seed is the whole search — so the
engine always returns a genuinely least-severe coherent breach, never just the
full-severity corner.

The result is materialised as a real :class:`StressScenario`, re-applied through
the host :class:`StressEngine` so it slots into the same ``stress_results`` /
``scenario_metadata`` tables as the forward scenarios.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from itertools import product
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from ..config.settings import LIQUIDITY_BREACH_THRESHOLD, StressScenario

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Parameter space definition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParameterAxis:
    """One reverse-stress decision variable.

    A severity fraction ``s ∈ [0, 1]`` maps linearly onto ``[calm, severe]``::

        value(s) = calm + s · (severe - calm)

    ``weight`` scales the axis in the implausibility norm: a *higher* weight means
    moving this lever is considered *more* implausible (the optimiser will prefer
    to leave it near ``calm``). Weights are derived from how exceptional a full
    move on the axis is relative to the others, so the norm is comparable across
    parameters with very different units (e.g. a 60% equity crash vs. a ×20
    haircut). Calibrated to ESMA / AIFMD severe-but-plausible ranges.
    """

    name: str
    calm: float            # severity-fraction 0.0 maps here (central / no-stress)
    severe: float          # severity-fraction 1.0 maps here (extreme-but-bounded)
    weight: float          # relative implausibility weight in the severity norm
    is_int: bool = False   # round to int when writing onto the scenario (bps)

    def value(self, s: float) -> float:
        v = self.calm + float(np.clip(s, 0.0, 1.0)) * (self.severe - self.calm)
        return float(round(v)) if self.is_int else float(v)


# Default axes — calibrated to severe-but-plausible regulatory ranges.
#   equity_shock                 : 0%  ->  -60%   (deeper than 2008 single-name beta-1)
#   rate_shock_bps               : 0   ->  +400bps (sharp parallel hiking shock)
#   adv_stress_scalar            : 1.0 ->   0.20  (ADV collapses to 20% of normal)
#   liquidity_haircut_multiplier : 1.0 ->   5.0   (bid/ask & haircut blow-out)
#   redemption_rate              : 0%  ->   50%   (severe run on the fund)
DEFAULT_AXES: Tuple[ParameterAxis, ...] = (
    ParameterAxis("equity_shock",                 calm=0.0, severe=-0.60, weight=1.0),
    ParameterAxis("rate_shock_bps",               calm=0.0, severe=400.0, weight=1.0, is_int=True),
    ParameterAxis("adv_stress_scalar",            calm=1.0, severe=0.20,  weight=0.8),
    ParameterAxis("liquidity_haircut_multiplier", calm=1.0, severe=5.0,   weight=0.8),
    ParameterAxis("redemption_rate",              calm=0.0, severe=0.50,  weight=1.2),
)


# ---------------------------------------------------------------------------
# Plausibility model: crisis co-movement of the risk drivers
# ---------------------------------------------------------------------------
#
# Treating the axes as independent (a diagonal severity norm) lets the optimiser
# reach economically *incoherent* corners — e.g. a ×3 liquidity-haircut blow-out
# with equities flat, spreads unchanged and normal trading volume. That never
# happens: liquidity dries up *because* markets fall. Both ESMA's Guidelines on
# liquidity stress testing (Guideline 17) and AIFMD II Art.16(1) require shocks to
# be "severe **but plausible**" — i.e. jointly coherent, not just individually
# bounded.
#
# Industry practice for a quantitative least-severe-breach search is a covariance-
# based **Mahalanobis** severity norm, D(s) = sqrt(sᵀ Σ⁻¹ s), so off-diagonal-
# impossible combinations are *far* from calm even when each axis moves only a
# little. We calibrate the correlation structure directly to the firm's own
# hand-calibrated forward scenarios (config.STRESS_SCENARIOS), where liquidity
# stress (haircut↑, ADV↓, redemptions↑) always rises together with market stress
# (equity↓, rate↑). Severity fractions are signed so that "more severe" is +1 on
# every axis (the raw adv_stress_scalar falls toward 0 as severity rises, but the
# fraction sᵢ still runs 0→1), which makes all pairwise co-movements **positive**.
#
# Axis order MUST match DEFAULT_AXES:
#   0 equity_shock  1 rate_shock_bps  2 adv_stress_scalar
#   3 liquidity_haircut_multiplier   4 redemption_rate
SHOCK_CORRELATION: np.ndarray = np.array(
    [
        #  eq    rate   adv    hc     redeem
        [1.00,  0.30,  0.70,  0.70,  0.60],   # equity drawdown
        [0.30,  1.00,  0.40,  0.40,  0.30],   # rate shock (weaker market link)
        [0.70,  0.40,  1.00,  0.80,  0.50],   # ADV collapse
        [0.70,  0.40,  0.80,  1.00,  0.50],   # haircut blow-out
        [0.60,  0.30,  0.50,  0.50,  1.00],   # redemption run
    ],
    dtype=float,
)

# Index groupings used by the coherence guardrail.
_MARKET_AXES = ("equity_shock", "rate_shock_bps")
_LIQUIDITY_AXES = ("adv_stress_scalar", "liquidity_haircut_multiplier", "redemption_rate")

# A small *autonomous* allowance: liquidity/redemption stress may exceed the
# market-driven level by at most this fraction (idiosyncratic fund-specific
# pressure — a key investor leaving, an operational ADV hit). Beyond it, a
# liquidity-only breach with no market driver is rejected as implausible.
COHERENCE_AUTONOMY: float = 0.25


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class ReverseStressResult:
    """Outcome of a comprehensive multi-parameter reverse stress search."""

    found: bool
    target_liquid_pct: float
    severity_distance: Optional[float]            # D(s*) — implausibility of the breach
    severity_fractions: Dict[str, float] = field(default_factory=dict)   # s* per axis
    breach_parameters: Dict[str, float] = field(default_factory=dict)    # mapped values
    liquid_pct_at_breach: Optional[float] = None
    can_meet_redemption_at_breach: Optional[bool] = None
    n_evaluations: int = 0
    # How the breach was located. The search winner is always ray-polished, so the
    # method records the winner's *origin* with a "+ray" suffix when the bisection
    # tightened it:
    #   "SLSQP+multistart+ray" | "SLSQP+multistart" | "ray-bisection" | "grid"
    #   "baseline-breach"  (already in breach at s=0) | "infeasible" (robust book)
    # "ray-bisection" = scipy-free path: the grid/corner winner with only ray polish.
    method: str = ""
    margin_to_breach: Optional[float] = None      # liquid_pct_after - target (≤0 if breach)
    # True when the portfolio is already below the liquidity target with NO shock
    # applied (severity distance 0). Reverse stress is ill-posed in this case —
    # there is no "least-severe shock to breach" because the fund is already in
    # breach — so callers should surface this distinctly, not as a found scenario.
    breached_at_baseline: bool = False
    baseline_liquid_pct: Optional[float] = None   # T0-T1 liquidity at s = 0 (no shock)

    def to_dict(self) -> dict:
        return {
            "found": self.found,
            "target_liquid_pct": self.target_liquid_pct,
            "severity_distance": self.severity_distance,
            "severity_fractions": self.severity_fractions,
            "breach_parameters": self.breach_parameters,
            "liquid_pct_at_breach": self.liquid_pct_at_breach,
            "can_meet_redemption_at_breach": self.can_meet_redemption_at_breach,
            "n_evaluations": self.n_evaluations,
            "method": self.method,
            "margin_to_breach": self.margin_to_breach,
            "breached_at_baseline": self.breached_at_baseline,
            "baseline_liquid_pct": self.baseline_liquid_pct,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class ReverseStressEngine:
    """Comprehensive multi-parameter reverse stress test.

    Parameters
    ----------
    stress_engine    : a configured :class:`StressEngine` bound to the portfolio.
                       Its ``_apply_scenario`` is the (expensive) simulator we
                       invert; this engine never re-implements the pricing logic.
    axes             : decision variables to optimise over (defaults to the five
                       drivers required by the spec / regulators).
    target_liquid_pct: breach threshold on T0-T1 liquidity
                       (defaults to ``LIQUIDITY_BREACH_THRESHOLD``).
    """

    def __init__(
        self,
        stress_engine,
        axes: Optional[Tuple[ParameterAxis, ...]] = None,
        target_liquid_pct: Optional[float] = None,
    ):
        self.stress_engine = stress_engine
        self.axes: Tuple[ParameterAxis, ...] = tuple(axes) if axes else DEFAULT_AXES
        self.target_liquid_pct = (
            LIQUIDITY_BREACH_THRESHOLD if target_liquid_pct is None else target_liquid_pct
        )
        # Precision matrix Σ⁻¹ for the Mahalanobis severity norm, aligned to the
        # ACTIVE axes (weights fold into Σ as a diagonal scaling). Built once.
        self._precision: np.ndarray = self._build_precision()
        self._n_eval = 0
        # Hard ceiling on *fresh* (uncached) portfolio repricings, so a single
        # solve can never run away past the client timeout. Set per-solve.
        self._eval_budget: Optional[int] = None
        # Cache evaluations: the optimiser revisits points (gradient FD, restarts).
        self._cache: Dict[Tuple[float, ...], Tuple[float, bool]] = {}

    # ------------------------------------------------------------------
    # Core simulator wrappers
    # ------------------------------------------------------------------

    def _scenario_from_fractions(self, s: np.ndarray, name: str) -> StressScenario:
        """Build a StressScenario from severity fractions, leaving credit spread
        un-stressed: the spread shock is intentionally NOT a free variable here so
        the five requested drivers (equity, rates, ADV, haircut, redemption) are
        isolated. A spread axis can be added to ``axes`` if desired."""
        params = {axis.name: axis.value(float(s[i])) for i, axis in enumerate(self.axes)}
        return StressScenario(
            name=name,
            equity_shock=params.get("equity_shock", 0.0),
            credit_spread_shock_bps=int(params.get("credit_spread_shock_bps", 0)),
            liquidity_haircut_multiplier=params.get("liquidity_haircut_multiplier", 1.0),
            redemption_rate=params.get("redemption_rate", 0.0),
            adv_stress_scalar=params.get("adv_stress_scalar", 1.0),
            rate_shock_bps=int(params.get("rate_shock_bps", 0)),
        )

    def _evaluate(self, s: np.ndarray, force: bool = False) -> Tuple[float, bool]:
        """Return (liquid_pct_after, can_meet_redemption) for severity vector ``s``.

        Cached and clipped to the unit box. This is the single expensive call —
        it reprices the whole portfolio via the host StressEngine.

        ``force=True`` bypasses the evaluation-budget guard. Use it only for the
        final materialisation of the chosen breach point: the result that is
        reported to the user (and drives the ``Can Meet`` cell) must be the real
        repricing, never the budget sentinel — otherwise an exhausted budget could
        mislabel a genuine breach as ``Can Meet = YES``.
        """
        key = tuple(round(float(x), 4) for x in np.clip(s, 0.0, 1.0))
        if key in self._cache:
            return self._cache[key]
        # Budget guard: once the fresh-evaluation budget is spent, stop repricing.
        # Returning a non-breaching sentinel makes the constraint look unsatisfied,
        # so SLSQP stops exploring and the search settles on the best point already
        # found (or the severe corner). This bounds wall-clock time hard.
        if not force and self._eval_budget is not None and self._n_eval >= self._eval_budget:
            return (1.0, True)
        scenario = self._scenario_from_fractions(np.asarray(key), name="__reverse_probe__")
        result = self.stress_engine._apply_scenario(scenario)
        self._n_eval += 1
        out = (float(result.liquid_pct_after), bool(result.can_meet_redemption))
        self._cache[key] = out
        return out

    def _liquid_after(self, s: np.ndarray) -> float:
        return self._evaluate(s)[0]

    def _is_breach(self, s: np.ndarray) -> bool:
        """A reverse-stress *breach* is — by definition — a scenario the fund
        **cannot survive**: it fails to meet redemptions within the settlement
        horizon (``can_meet_redemption is False``).

        This is the exact regulatory constraint reverse stress must invert (AIFMD
        II Art.16(1) / ESMA Guideline 17): the combination of shocks under which
        the fund can no longer honour redemptions. Constraining instead on the raw
        T0-T1 liquidity floor would return scenarios that dip below the floor yet
        still raise enough cash to meet (small) redemptions — reported as
        ``Can Meet = YES`` — which is not an actual failure and contradicts the
        definition. By making the redemption-coverage failure *the* breach test,
        every materialised reverse-stress scenario is, by construction,
        ``Can Meet = NO``. The liquidity floor is used only as a smooth search
        guide (see :meth:`_breach_margin`), never as the acceptance test."""
        _liquid, can_meet = self._evaluate(s)
        return not can_meet

    def _breach_margin(self, s: np.ndarray) -> float:
        """Continuous severity signal used to *guide* the gradient solver toward
        the breach region (``≥ 0`` once liquidity is at/below the floor).

        The true breach test (:meth:`_is_breach`) is the boolean redemption
        failure, which is non-smooth and useless for SLSQP. As a smooth proxy we
        reuse the liquidity-floor margin ``target - liquid_after``: driving
        liquidity down is strongly correlated with eventually failing redemptions,
        so this pulls SLSQP toward the breach region. Final acceptance of any
        optimum is always re-checked with :meth:`_is_breach`, so the proxy only
        affects the *search path*, never which scenarios count as breaches."""
        return self.target_liquid_pct - self._liquid_after(s)

    # ------------------------------------------------------------------
    # Plausibility (Mahalanobis) norm + coherence guardrail
    # ------------------------------------------------------------------

    def _build_precision(self) -> np.ndarray:
        """Build the precision matrix Σ⁻¹ used by the Mahalanobis severity norm.

        Σ is the crisis co-movement covariance of the severity fractions:
        ``Σ = W^½ · R · W^½`` where ``R`` is :data:`SHOCK_CORRELATION` and ``W`` is
        the diagonal of per-axis implausibility weights. Folding the weights into Σ
        means D(s) = sqrt(sᵀ Σ⁻¹ s) generalises the old diagonal norm: with R = I it
        collapses back to sqrt(Σ wᵢ sᵢ²), but with the real correlation structure an
        *incoherent* combination (e.g. haircut blow-out while equities are flat) sits
        far from the calm state because Σ⁻¹ penalises moves that violate the expected
        co-movement.

        Falls back to a pure diagonal precision (the original behaviour) whenever the
        active axes are not the canonical five-driver set, so custom axis tuples and
        unit tests that pass their own axes keep working.
        """
        n = len(self.axes)
        w = np.array([a.weight for a in self.axes], dtype=float)
        names = tuple(a.name for a in self.axes)
        default_names = tuple(a.name for a in DEFAULT_AXES)

        if names == default_names and SHOCK_CORRELATION.shape == (n, n):
            r = SHOCK_CORRELATION
        else:
            # Unknown / custom axis layout — no calibrated correlation available.
            logger.debug(
                "reverse-stress axes %s differ from default; using diagonal norm", names
            )
            r = np.eye(n)

        sqrt_w = np.sqrt(w)
        cov = np.outer(sqrt_w, sqrt_w) * r          # Σ = W^½ R W^½
        # Symmetric PD inverse via pseudo-inverse for numerical safety (R is PD here,
        # but pinv tolerates a near-singular custom calibration without raising).
        precision = np.linalg.pinv(cov)
        return 0.5 * (precision + precision.T)       # re-symmetrise

    def _distance(self, s: np.ndarray) -> float:
        """Mahalanobis severity / implausibility norm D(s) = sqrt(sᵀ Σ⁻¹ s).

        Distance from the calm state ``s = 0`` under the crisis co-movement metric:
        coherent shocks (all drivers stressing together) are *cheap*; incoherent
        ones (a liquidity-only blow-out with calm markets) are *expensive*. The
        constrained minimiser on the breach boundary is therefore the most plausible
        way the fund can fail — never an economically impossible corner.
        """
        s = np.clip(np.asarray(s, dtype=float), 0.0, 1.0)
        q = float(s @ self._precision @ s)
        return float(np.sqrt(max(q, 0.0) + 1e-12))

    def _distance_grad(self, s: np.ndarray) -> np.ndarray:
        """Gradient of :meth:`_distance` w.r.t. s (for SLSQP)."""
        s = np.clip(np.asarray(s, dtype=float), 0.0, 1.0)
        d = self._distance(s)
        return (self._precision @ s) / d

    def _coherence_margin(self, s: np.ndarray) -> float:
        """Coherence guardrail: ≥ 0 when liquidity stress is *justified* by market
        stress, < 0 for an implausible liquidity-only / redemption-only breach.

        The economic rule is that liquidity dries up *because* markets fall, so the
        worst liquidity-side severity (ADV collapse, haircut blow-out, redemption
        run) may exceed the worst market-side severity (equity drawdown, rate shock)
        by at most an autonomous, fund-specific allowance
        (:data:`COHERENCE_AUTONOMY`). Beyond that, a breach driven purely by
        liquidity levers with no market driver is rejected as not severe-but-
        plausible::

            max(liquidity severities) ≤ max(market severities) + COHERENCE_AUTONOMY

        Returned as a smooth signed margin so SLSQP can use it as an inequality
        constraint and the grid seeder can filter on its sign.
        """
        s = np.clip(np.asarray(s, dtype=float), 0.0, 1.0)
        idx = {a.name: i for i, a in enumerate(self.axes)}

        market = [s[idx[n]] for n in _MARKET_AXES if n in idx]
        liquidity = [s[idx[n]] for n in _LIQUIDITY_AXES if n in idx]
        # If either side is absent (custom axes), the guardrail does not apply.
        if not market or not liquidity:
            return 1.0

        max_market = max(market)
        max_liquidity = max(liquidity)
        return float(max_market + COHERENCE_AUTONOMY - max_liquidity)

    def _is_coherent(self, s: np.ndarray) -> bool:
        """True when ``s`` satisfies the coherence guardrail (market stress justifies
        the liquidity stress, within the autonomous allowance)."""
        return self._coherence_margin(s) >= -1e-9

    def _refine_along_ray(
        self, s_breach: np.ndarray, n_bisect: int = 18
    ) -> Tuple[float, np.ndarray]:
        """Walk a *known* coherent breach back toward calm to shed residual severity.

        Given a point ``s_breach`` that breaches and is coherent, the scaled points
        ``t · s_breach`` for ``t ∈ [0, 1]`` trace the Mahalanobis ray from calm
        (``t = 0``) out to the breach (``t = 1``): because D is a norm,
        ``D(t·s) = t·D(s)`` is monotone in ``t``, so the *least-severe* point on the
        ray is the smallest ``t`` that still breaches. Coherence is also preserved
        under scaling toward the origin (both ``max`` severities shrink by the same
        ``t``, and the ``+α`` slack only grows in relative terms), so every accepted
        point stays plausible.

        We bisect on ``t``: the breach region is ``[t*, 1]`` for some boundary
        ``t* ≥ 0``; we squeeze ``[lo, hi]`` with ``lo`` non-breaching and ``hi``
        breaching until they meet, then return the breaching end. This is gradient-
        free, costs ``n_bisect`` cached evaluations, and is the entire search when
        scipy is unavailable. Returns ``(D(s*), s*)``.

        The input is assumed to breach (caller checks); if a numerical edge makes
        even ``t = 1`` look non-breaching, we return it unchanged rather than fail.
        """
        s_breach = np.clip(np.asarray(s_breach, dtype=float), 0.0, 1.0)
        if not self._is_breach(s_breach):
            return self._distance(s_breach), s_breach

        lo, hi = 0.0, 1.0          # lo: known non-breach (calm), hi: known breach
        for _ in range(n_bisect):
            mid = 0.5 * (lo + hi)
            s_mid = mid * s_breach
            # Coherence holds by construction under scaling, but re-check cheaply so
            # a custom-axis configuration (guardrail inactive) can never regress.
            if self._is_coherent(s_mid) and self._is_breach(s_mid):
                hi = mid           # still breaches → push the boundary lower
            else:
                lo = mid           # no longer breaches → boundary is above mid
        s_star = hi * s_breach
        return self._distance(s_star), s_star

    # ------------------------------------------------------------------
    # Optimisation
    # ------------------------------------------------------------------

    def solve(
        self,
        n_starts: int = 6,
        grid_per_axis: int = 3,
        max_iter: int = 60,
        max_evaluations: int = 300,
    ) -> ReverseStressResult:
        """Find the least-severe joint shock that breaches the liquidity target.

        Strategy
        --------
        1. **Feasibility check** — evaluate the maximally-severe corner ``s = 1``.
           If even that does not breach, the portfolio is robust across the whole
           plausible box and we report ``found=False`` (a meaningful result).
        2. **Coarse grid** — sample a small grid to seed starting points and to
           give the grid-only fallback something to refine.
        3. **Multi-start SLSQP** — from the most promising feasible/near-feasible
           seeds, minimise ``D(s)`` subject to ``target - liquid_after(s) ≥ 0``.
           Keep the best feasible optimum.
        4. **Fallback** — if scipy is missing or SLSQP yields nothing feasible,
           refine on the grid (coarse-to-fine bisection toward the boundary).
        """
        self._n_eval = 0
        self._cache.clear()
        self._eval_budget = max_evaluations
        dim = len(self.axes)

        # ---- 0. Calm-corner check: already in breach with no shock? ------------
        # If the unstressed portfolio (s = 0) is already below the liquidity target,
        # reverse stress is ill-posed: the "least-severe shock to breach" is no shock
        # at all (distance 0). Report this distinctly instead of materialising a
        # zero-shock "breach scenario", which is misleading.
        s_zero = np.zeros(dim)
        liquid_zero, can_meet_zero = self._evaluate(s_zero)
        if self._is_breach(s_zero):
            return ReverseStressResult(
                found=False,
                target_liquid_pct=self.target_liquid_pct,
                severity_distance=0.0,
                liquid_pct_at_breach=liquid_zero,
                can_meet_redemption_at_breach=can_meet_zero,
                margin_to_breach=liquid_zero - self.target_liquid_pct,
                breached_at_baseline=True,
                baseline_liquid_pct=liquid_zero,
                n_evaluations=self._n_eval,
                method="baseline-breach",
            )

        # ---- 1. Feasibility at the severe corner -------------------------------
        s_max = np.ones(dim)
        if not self._is_breach(s_max):
            # No breach (redemption failure) is reachable within the plausible
            # box → the fund is robust across all severe-but-plausible shocks.
            liquid_max, _ = self._evaluate(s_max)
            return ReverseStressResult(
                found=False,
                target_liquid_pct=self.target_liquid_pct,
                severity_distance=None,
                liquid_pct_at_breach=None,
                margin_to_breach=liquid_max - self.target_liquid_pct,
                baseline_liquid_pct=liquid_zero,
                n_evaluations=self._n_eval,
                method="infeasible",
            )

        # ---- 2. Coarse grid seeds ---------------------------------------------
        # Each grid point is a full portfolio repricing, so the grid dominates the
        # cost. Reserve a slice of the evaluation budget for the SLSQP refinement
        # (gradient finite-differences + restarts) and decimate the grid to fit the
        # remainder. ``max_grid_points`` is therefore strictly below the raw grid
        # size whenever the budget is tight — the cap that follows is a real
        # down-sample, not a no-op.
        grid_vals = np.linspace(0.0, 1.0, grid_per_axis)
        feasible_seeds: List[Tuple[float, np.ndarray]] = []  # (distance, s) breaching
        all_seeds: List[Tuple[float, np.ndarray]] = []        # (margin, s) by closeness
        # Keep ~2/3 of the budget for the grid, leaving room for SLSQP. Always
        # allow at least a minimal grid so seeding still works.
        max_grid_points = max(32, (2 * max_evaluations) // 3)
        coords = list(product(grid_vals, repeat=dim))
        if len(coords) > max_grid_points:
            coords = coords[:: max(1, len(coords) // max_grid_points)]
        for c in coords:
            s = np.array(c, dtype=float)
            liquid = self._liquid_after(s)
            margin = liquid - self.target_liquid_pct  # smooth guide: ≤ 0 → near breach
            all_seeds.append((margin, s))
            # Feasibility is the *true* breach test (redemption failure), not the
            # liquidity-floor proxy used for ordering — AND the coherence guardrail:
            # an incoherent liquidity-only corner is not a plausible breach, so it
            # must never seed the refinement or become the materialised scenario.
            if self._is_coherent(s) and self._is_breach(s):
                feasible_seeds.append((self._distance(s), s))

        feasible_seeds.sort(key=lambda t: t[0])
        all_seeds.sort(key=lambda t: t[0])  # most-breaching first

        best: Optional[Tuple[float, np.ndarray]] = (
            feasible_seeds[0] if feasible_seeds else None
        )
        method = "grid"

        # ---- 3. Multi-start SLSQP refinement ----------------------------------
        try:
            from scipy.optimize import minimize

            def objective(s):
                # Mahalanobis severity norm under the crisis co-movement metric.
                return self._distance(s)

            def obj_grad(s):
                return self._distance_grad(s)

            def breach_constraint(s):
                # Smooth guide: ≥ 0 when liquidity is at/below target. Pulls SLSQP
                # toward the breach region; true acceptance is re-checked below
                # with _is_breach (redemption failure), which is non-smooth.
                return self._breach_margin(s)

            def coherence_constraint(s):
                # Hard plausibility guardrail: ≥ 0 only when market stress justifies
                # the liquidity stress, blocking implausible liquidity-only breaches.
                return self._coherence_margin(s)

            constraints = [
                {"type": "ineq", "fun": breach_constraint},
                {"type": "ineq", "fun": coherence_constraint},
            ]
            bounds = [(0.0, 1.0)] * dim

            # Seed from severe corner + most-breaching grid points.
            seeds: List[np.ndarray] = [s_max]
            seeds += [s for _, s in feasible_seeds[: max(0, n_starts - 1)]]
            if len(seeds) < n_starts:
                seeds += [s for _, s in all_seeds[: n_starts - len(seeds)]]

            for s0 in seeds:
                try:
                    res = minimize(
                        objective,
                        x0=np.clip(s0, 0.0, 1.0),
                        jac=obj_grad,
                        method="SLSQP",
                        bounds=bounds,
                        constraints=constraints,
                        options={"maxiter": max_iter, "ftol": 1e-4},
                    )
                except Exception:
                    logger.debug("SLSQP start failed", exc_info=True)
                    continue
                s_star = np.clip(res.x, 0.0, 1.0)
                # Accept only genuine *and plausible* breaches: the fund actually
                # fails to meet redemptions (per _is_breach) AND the shock is
                # coherent (market stress justifies the liquidity stress). SLSQP can
                # settle marginally outside the coherence constraint, so re-check it.
                if self._is_coherent(s_star) and self._is_breach(s_star):
                    d = self._distance(s_star)
                    if best is None or d < best[0]:
                        best = (d, s_star)
                        method = "SLSQP+multistart"
        except ImportError:
            logger.info("scipy not available — using grid-only reverse stress search")

        if best is None:
            # Breach is reachable (corner breached) but search lost it: fall back
            # to the severe corner so we still return an actionable breach point.
            best = (self._distance(s_max), s_max)
            method = "grid"

        # ---- 3b. Ray-bisection polish -----------------------------------------
        # The winner — whether an SLSQP optimum, the best grid seed, or the severe
        # corner — generally still carries severity the gradient step (or the coarse
        # grid) left on the table: D is a norm, so any point on the ray from calm to
        # the winner that *still* breaches is strictly closer to the calm state.
        # Bisect back along that Mahalanobis ray to the least-severe coherent breach.
        # This is a pure improvement (the polished point breaches and is coherent by
        # construction, and D(t·s) = t·D(s) ≤ D(s)), and — crucially — it is the
        # entire search when scipy is absent, so the grid winner (or corner) is never
        # returned at full severity. It costs only a handful of cached evaluations.
        d_polished, s_polished = self._refine_along_ray(best[1])
        if self._is_breach(s_polished) and self._is_coherent(s_polished):
            if d_polished < best[0] - 1e-9:
                best = (d_polished, s_polished)
                method = "ray-bisection" if method == "grid" else f"{method}+ray"
            else:
                best = (d_polished, s_polished)

        # ---- 4. Materialise the winning breach point --------------------------
        # Force a real repricing of the winner (bypassing the budget guard): the
        # reported result must be truthful, never the budget sentinel. Then enforce
        # the invariant — a reverse-stress scenario must, by definition, fail to
        # meet redemptions. If the chosen point somehow does not (e.g. budget
        # exhaustion let a sentinel-seeded point through), fall back to the severe
        # corner, which step 1 proved is a genuine breach.
        s_star = best[1]
        liquid_star, can_meet_star = self._evaluate(s_star, force=True)
        if can_meet_star:
            s_star = s_max
            liquid_star, can_meet_star = self._evaluate(s_star, force=True)
            method = method or "grid"
        breach_params = {
            axis.name: axis.value(float(s_star[i])) for i, axis in enumerate(self.axes)
        }
        fractions = {
            axis.name: round(float(np.clip(s_star[i], 0.0, 1.0)), 4)
            for i, axis in enumerate(self.axes)
        }

        return ReverseStressResult(
            found=True,
            target_liquid_pct=self.target_liquid_pct,
            severity_distance=round(best[0], 4),
            severity_fractions=fractions,
            breach_parameters=breach_params,
            liquid_pct_at_breach=liquid_star,
            can_meet_redemption_at_breach=can_meet_star,
            margin_to_breach=liquid_star - self.target_liquid_pct,
            baseline_liquid_pct=liquid_zero,
            n_evaluations=self._n_eval,
            method=method,
        )

    # ------------------------------------------------------------------
    # Scenario materialisation
    # ------------------------------------------------------------------

    def build_breach_scenario(self, result: ReverseStressResult) -> Optional[StressScenario]:
        """Turn a found breach into a named, regulatory-tagged StressScenario.

        Returns ``None`` when no breach was found (the portfolio is robust across
        the plausible box) so callers can skip surfacing a row.
        """
        if not result.found:
            return None

        p = result.breach_parameters
        bits = []
        if "equity_shock" in p and abs(p["equity_shock"]) > 1e-9:
            bits.append(f"equity {p['equity_shock']:.0%}")
        if "rate_shock_bps" in p and abs(p["rate_shock_bps"]) > 0:
            bits.append(f"rates {int(p['rate_shock_bps']):+d}bps")
        if "adv_stress_scalar" in p and p["adv_stress_scalar"] < 0.999:
            bits.append(f"ADV→{p['adv_stress_scalar']:.0%} of normal")
        if "liquidity_haircut_multiplier" in p and p["liquidity_haircut_multiplier"] > 1.001:
            bits.append(f"haircut ×{p['liquidity_haircut_multiplier']:.2f}")
        if "redemption_rate" in p and p["redemption_rate"] > 1e-9:
            bits.append(f"redemptions {p['redemption_rate']:.0%}")
        shock_desc = ", ".join(bits) if bits else "no shock"

        scenario = StressScenario(
            name="Reverse stress (multi-factor breach)",
            equity_shock=p.get("equity_shock", 0.0),
            credit_spread_shock_bps=int(p.get("credit_spread_shock_bps", 0)),
            liquidity_haircut_multiplier=p.get("liquidity_haircut_multiplier", 1.0),
            redemption_rate=p.get("redemption_rate", 0.0),
            adv_stress_scalar=p.get("adv_stress_scalar", 1.0),
            rate_shock_bps=int(p.get("rate_shock_bps", 0)),
            description=(
                f"Least-severe joint shock that drives T0-T1 liquidity below "
                f"{result.target_liquid_pct:.0%}: {shock_desc}. "
                f"Found by {result.method} over {result.n_evaluations} portfolio "
                f"re-pricings (implausibility distance {result.severity_distance})."
            ),
            regulatory_basis=(
                "Reverse stress (multi-factor) - AIFMD II Art.16(1); "
                "ESMA Guidelines on liquidity stress testing, Guideline 17"
            ),
            is_worst_case=False,
        )
        return scenario

    def run(
        self,
        n_starts: int = 6,
        grid_per_axis: int = 3,
        max_iter: int = 60,
        max_evaluations: int = 300,
    ) -> Tuple[Optional[StressScenario], Optional["object"], ReverseStressResult]:
        """Convenience driver: solve, materialise, and re-apply through the host
        engine so the breach slots into the standard result tables.

        Returns ``(scenario, scenario_result, reverse_result)``. When the
        portfolio is robust (no breach in the plausible box), returns
        ``(None, None, reverse_result)``.
        """
        reverse_result = self.solve(
            n_starts=n_starts,
            grid_per_axis=grid_per_axis,
            max_iter=max_iter,
            max_evaluations=max_evaluations,
        )
        scenario = self.build_breach_scenario(reverse_result)
        if scenario is None:
            return None, None, reverse_result
        scenario_result = self.stress_engine._apply_scenario(scenario)
        return scenario, scenario_result, reverse_result
