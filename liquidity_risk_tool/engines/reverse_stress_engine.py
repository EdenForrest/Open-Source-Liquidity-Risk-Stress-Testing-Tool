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
from dataclasses import dataclass, field, replace
from itertools import product
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from ..config.settings import LIQUIDITY_BREACH_THRESHOLD, StressScenario
from ._reverse_stress_native import native_solve

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
#   liquidity_haircut_multiplier : 1.0 ->   2.8   (bid/ask & haircut blow-out)
#   redemption_rate              : 0%  ->   30%   (severe run on the fund)
# The redemption ceiling is 30%, not 50%: a single-period 30% outflow is already
# at the severe end of observed open-ended-fund runs (ESMA / AIFMD II reverse-
# stress practice), whereas 50% is a near-liquidation event that swamps every
# other lever and produced implausible "of course it breaches" corners. The
# severity fraction is clamped to [0, 1] on every probe (see ParameterAxis.value
# and _clip_box), so redemption can only range 0% -> +30%, never negative.
DEFAULT_AXES: Tuple[ParameterAxis, ...] = (
    ParameterAxis("equity_shock",                 calm=0.0, severe=-0.60, weight=1.0),
    ParameterAxis("rate_shock_bps",               calm=0.0, severe=400.0, weight=1.0, is_int=True),
    ParameterAxis("adv_stress_scalar",            calm=1.0, severe=0.20,  weight=0.8),
    ParameterAxis("liquidity_haircut_multiplier", calm=1.0, severe=2.8,   weight=0.8),
    ParameterAxis("redemption_rate",              calm=0.0, severe=0.30,  weight=1.2),
)


def axes_with_ceilings(
    overrides: Optional[Dict[str, float]] = None,
) -> Tuple[ParameterAxis, ...]:
    """Return DEFAULT_AXES with the ``severe`` endpoint of named axes overridden.

    ``overrides`` maps an axis name to the value its severity fraction s=1 should
    map to (its "ceiling"). Only ``severe`` is changed; ``calm``, ``weight`` and
    ``is_int`` are preserved so the Mahalanobis severity norm and the calm anchor
    are unchanged — the box the optimiser searches simply grows or shrinks along
    the overridden axes. Unknown names and ``None`` values are ignored. Callers
    are responsible for bounding the values (see ``ReverseStressRequest``); the
    severity fraction is clamped to [0, 1] regardless, so a lever can only ever
    run from ``calm`` to its (possibly overridden) ``severe`` ceiling.
    """
    if not overrides:
        return DEFAULT_AXES
    return tuple(
        replace(axis, severe=float(overrides[axis.name]))
        if overrides.get(axis.name) is not None
        else axis
        for axis in DEFAULT_AXES
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

# Frontier verdict threshold. A located breach whose implausibility distance is at
# least this fraction of the severe-corner distance D(1,…,1) is classified as a
# "frontier" breach: the fund effectively only fails at the maximally-severe corner
# of the plausible box, so it is *practically resilient* and the breach is not a
# realistic scenario to plan around. 0.85 cleanly separates the genuine plausible
# breaches observed in the demo book (D ≈ 0.50·corner) from the corner-hugging
# results (D ≈ 0.85–0.92·corner) that prompted "of course it won't meet redemption".
FRONTIER_DISTANCE_RATIO: float = 0.85


def _classify_plausibility(distance: Optional[float], corner: Optional[float]) -> str:
    """Map (severity_distance, corner_distance) onto a plausibility verdict.

    See :class:`ReverseStressResult.plausibility`. A breach within
    ``FRONTIER_DISTANCE_RATIO`` of the severe corner is "frontier" (practically
    resilient); a closer-to-calm breach is a genuine "plausible" scenario.
    """
    if distance is None or corner is None or corner <= 0:
        return "none"
    return "frontier" if distance >= FRONTIER_DISTANCE_RATIO * corner else "plausible"


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
    # Implausibility distance of the maximally-severe corner s=(1,…,1) under the
    # same Mahalanobis metric — the natural yardstick for severity_distance. A
    # breach whose distance approaches this is, in practice, only reachable at the
    # severe-but-plausible frontier (see ``plausibility``).
    corner_distance: Optional[float] = None
    # Verdict on how realistic the located breach is, derived from the ratio
    # severity_distance / corner_distance:
    #   "plausible"   — a genuine severe-but-plausible breach well inside the box;
    #                   this is an actionable reverse-stress scenario.
    #   "frontier"    — the fund only fails at (or within a whisker of) the severe
    #                   corner. It is *practically resilient*: the breach is the
    #                   implausible extreme, not a realistic scenario, and should be
    #                   surfaced as "robust except at the frontier", NOT as a
    #                   plausible shock the manager should plan around.
    #   "none"        — no breach found / not applicable.
    plausibility: str = "none"

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
            "corner_distance": self.corner_distance,
            "plausibility": self.plausibility,
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
        use_native: bool = True,
    ):
        self.stress_engine = stress_engine
        # Prefer the compiled C++ search core when it is built and importable.
        # Purely an optimisation: when False (or the module is absent) the search
        # runs the identical pure-Python routines below. Set False to force the
        # Python path (e.g. for cross-checking the two against each other).
        self.use_native = use_native
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

    def _evaluate(
        self, s: np.ndarray, force: bool = False, fresh: bool = False
    ) -> Tuple[float, bool]:
        """Return (liquid_pct_after, can_meet_redemption) for severity vector ``s``.

        Cached and clipped to the unit box. This is the single expensive call —
        it reprices the whole portfolio via the host StressEngine.

        ``force=True`` bypasses the evaluation-budget guard. Use it only for the
        final materialisation of the chosen breach point: the result that is
        reported to the user (and drives the ``Can Meet`` cell) must be the real
        repricing, never the budget sentinel — otherwise an exhausted budget could
        mislabel a genuine breach as ``Can Meet = YES``.

        ``fresh=True`` additionally bypasses the 4-decimal cache key and reprices
        the *exact* ``s`` (clipped but un-rounded). The cache quantises severity to
        4 dp so the optimiser's revisits coincide, but the ``can_meet`` boundary
        can be finer than that grid: two points that round to the same key — one
        just inside the breach, one just outside — share a cache slot, so a forced
        reprice of the chosen winner could pick up a neighbour's verdict. The final
        materialisation must reflect the winner's *own* repricing, so it asks for a
        fresh, un-quantised evaluation; the result is not cached (its key would
        otherwise poison later rounded lookups). Everywhere else the 4 dp grid is
        the intended search resolution.
        """
        clipped = np.clip(s, 0.0, 1.0)
        key = tuple(round(float(x), 4) for x in clipped)
        if not fresh and key in self._cache:
            return self._cache[key]
        # Budget guard: once the fresh-evaluation budget is spent, stop repricing.
        # Returning a non-breaching sentinel makes the constraint look unsatisfied,
        # so SLSQP stops exploring and the search settles on the best point already
        # found (or the severe corner). This bounds wall-clock time hard.
        if not force and self._eval_budget is not None and self._n_eval >= self._eval_budget:
            return (1.0, True)
        probe = clipped if fresh else np.asarray(key)
        scenario = self._scenario_from_fractions(probe, name="__reverse_probe__")
        result = self.stress_engine._apply_scenario(scenario)
        self._n_eval += 1
        out = (float(result.liquid_pct_after), bool(result.can_meet_redemption))
        if not fresh:
            self._cache[key] = out
        return out

    def _liquid_after(self, s: np.ndarray) -> float:
        return self._evaluate(s)[0]

    def _is_breach_forced(self, s: np.ndarray) -> bool:
        """Breach test that bypasses the evaluation-budget guard.

        Used inside the boundary polish (:meth:`_refine_along_ray`,
        :meth:`_refine_coordinate`), where a budget sentinel would be poison: the
        polish bisects toward calm and accepts a smaller point only if it still
        breaches, so a sentinel ``(1.0, True)`` (non-breach) for a point the fund
        *cannot* actually survive makes the bisection abandon a genuine, closer
        breach and keep the over-severe seed. The grid + SLSQP phase routinely
        exhausts the budget before the polish runs, so without this the polish
        silently no-ops and returns the severe corner at full strength. The polish
        probes only a small, bounded number of points (≈ ``n_bisect`` per ray,
        ``n_passes·dim·n_bisect`` per coordinate walk), so forcing them is cheap and
        keeps the search faithful — the same reason the final materialisation forces
        its reprice.

        ``fresh=True`` is essential, not an optimisation knob: :meth:`_evaluate`
        caches by a 4-dp quantised key, so the cached boundary and the
        un-quantised redemption test disagree by up to half a grid step right at
        the knife-edge. :meth:`_materialise` re-checks the polished winner with
        ``fresh=True``; if the polish bisected against the *quantised* boundary it
        would accept a point a hair on the wrong side, materialisation would then
        reprice it as Can-Meet=YES, and the whole polish would be discarded for
        the raw corner (the frac=1.0 degeneration). Bisecting on the same
        un-quantised boundary materialisation uses keeps the two in lockstep."""
        return not self._evaluate(s, force=True, fresh=True)[1]

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
        if not self._is_breach_forced(s_breach):
            return self._distance(s_breach), s_breach

        lo, hi = 0.0, 1.0          # lo: known non-breach (calm), hi: known breach
        for _ in range(n_bisect):
            mid = 0.5 * (lo + hi)
            s_mid = mid * s_breach
            # Coherence holds by construction under scaling, but re-check cheaply so
            # a custom-axis configuration (guardrail inactive) can never regress.
            # Forced eval: a budget sentinel here would falsely report no breach and
            # abandon a genuinely closer point (see _is_breach_forced).
            if self._is_coherent(s_mid) and self._is_breach_forced(s_mid):
                hi = mid           # still breaches → push the boundary lower
            else:
                lo = mid           # no longer breaches → boundary is above mid
        s_star = hi * s_breach
        return self._distance(s_star), s_star

    def _refine_coordinate(
        self,
        s_breach: np.ndarray,
        n_passes: int = 2,
        n_bisect: int = 12,
    ) -> Tuple[float, np.ndarray]:
        """Boundary-walk polish: shrink each axis individually toward calm while
        the point keeps breaching and stays coherent.

        The radial ray polish (:meth:`_refine_along_ray`) can only scale *all*
        axes by a common ``t``; it cannot trade severity *between* axes. But the
        least-severe breach rarely sits on the ray from calm to the search winner
        — on the non-convex breach surface a different *mix* of severities at the
        same radius (or less) often also breaches and is strictly closer to calm
        under the Mahalanobis metric. This coordinate descent captures exactly
        those sideways gains: for each axis we bisect its fraction down to the
        smallest value that still breaches (holding the others fixed), then sweep
        again, since relaxing one axis can free another. Axes are visited in
        descending order of their marginal contribution to ``D(s)`` so the most
        implausible levers are relaxed first.

        Every accepted point is re-checked for breach *and* coherence. The walk
        itself is greedy on per-axis severity, not on ``D``: under the correlated
        precision matrix, shrinking one axis of an aligned point can *raise* the
        Mahalanobis norm (the cross terms lose their correlation discount), so
        the walk can wander uphill in ``D`` while chasing smaller axis values.
        The argmin-``D`` accepted state is therefore tracked and returned, which
        makes the polish a pure improvement: it only ever returns a point with
        ``D ≤ D(s_breach)`` that still breaches and stays plausible. Costs at most
        ``n_passes · dim · n_bisect`` cached evaluations. Returns ``(D(s*), s*)``.
        """
        s = np.clip(np.asarray(s_breach, dtype=float), 0.0, 1.0).copy()
        if not (self._is_breach_forced(s) and self._is_coherent(s)):
            return self._distance(s), s

        best_d, best_s = self._distance(s), s.copy()
        dim = len(s)
        for _ in range(n_passes):
            improved = False
            # Relax the axes contributing most to the severity norm first.
            contrib = (self._precision @ s) * s
            order = list(np.argsort(-contrib))
            for i in order:
                if s[i] <= 1e-6:
                    continue
                # Bisect axis i down: lo = smallest value known to still breach,
                # hi = current (breaching) value. Find how far toward 0 we can go.
                lo, hi = 0.0, float(s[i])
                trial = s.copy()
                trial[i] = lo
                # If dropping the axis to 0 still breaches coherently, take it whole.
                # Forced evals throughout: a budget sentinel would falsely clear the
                # breach and freeze the axis at full severity (see _is_breach_forced).
                if self._is_breach_forced(trial) and self._is_coherent(trial):
                    if abs(s[i]) > 1e-9:
                        improved = True
                    s[i] = 0.0
                else:
                    # Otherwise squeeze [lo, hi]: lo non-breach, hi breach.
                    for _ in range(n_bisect):
                        mid = 0.5 * (lo + hi)
                        trial[i] = mid
                        if self._is_breach_forced(trial) and self._is_coherent(trial):
                            hi = mid
                        else:
                            lo = mid
                    if hi < s[i] - 1e-6:
                        s[i] = hi
                        improved = True
                    else:
                        continue
                d_now = self._distance(s)
                if d_now < best_d - 1e-12:
                    best_d, best_s = d_now, s.copy()
            if not improved:
                break
        return best_d, best_s

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
        2. **Coarse grid + boundary refinement** — sample a grid to seed starting
           points, then add a finer *local* sample around every breach/no-breach
           transition (the midpoint of each adjacent feasible/infeasible seed
           pair), so the breach boundary is seeded densely *where it actually is*
           rather than only on the coarse lattice. This is the main accuracy gain:
           it surfaces plausible breaches that fall between coarse grid nodes.
        3. **Multi-start SLSQP** — from the most promising feasible/near-feasible
           seeds (including the boundary midpoints), minimise ``D(s)`` subject to
           ``target - liquid_after(s) ≥ 0``. Keep the best feasible optimum.
        4. **Two-phase polish** — bisect the winner radially toward calm along its
           Mahalanobis ray, *then* run a coordinate boundary-walk that relaxes each
           axis individually. The ray polish cannot trade severity between axes; the
           coordinate walk captures those sideways gains, so the returned breach is
           genuinely the least-severe coherent one on the located boundary, not just
           the closest point on a single ray. Both are pure improvements.
        """
        self._n_eval = 0
        self._cache.clear()
        self._eval_budget = max_evaluations
        dim = len(self.axes)
        s_max = np.ones(dim)

        # ---- Native fast path -------------------------------------------------
        # When the compiled C++ search core is available, run the deterministic
        # search (grid + boundary refinement, ray bisection, coordinate walk) there,
        # using self._evaluate as the breach oracle so caching, the evaluation budget
        # and the 4-dp cache key are byte-for-byte identical to the Python path. The
        # core mirrors the Python routines, so the located breach point matches; we
        # then run the SAME materialisation (step 4) below. Any failure / absence
        # returns None and we fall through to the pure-Python search unchanged.
        native = None
        if self.use_native:
            native = native_solve(
                precision=self._precision,
                axis_names=[a.name for a in self.axes],
                coherence_autonomy=COHERENCE_AUTONOMY,
                target_liquid_pct=self.target_liquid_pct,
                oracle=lambda s: self._evaluate(np.asarray(s, dtype=float)),
                grid_per_axis=grid_per_axis,
                eval_budget=max_evaluations,
            )

        if native is not None:
            status = native.get("status")
            liquid_zero = native.get("baseline_liquid_pct")
            if status == "baseline-breach":
                _, can_meet_zero = self._evaluate(np.zeros(dim), force=True)
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
            if status == "infeasible":
                liquid_max, _ = self._evaluate(s_max, force=True)
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
            if status == "found":
                best = (float(native["distance"]), np.asarray(native["s"], dtype=float))
                method = native.get("method", "grid")
                corner_distance = float(native["corner_distance"])
                return self._materialise(
                    best, method, corner_distance, liquid_zero, s_max
                )
            # Unrecognised status — fall through to the Python search.

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
        corner_distance = self._distance(s_max)  # yardstick for the plausibility verdict
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
        # Keep ~half the budget for the grid + boundary refinement, leaving room for
        # SLSQP and the two-phase polish. Always allow at least a minimal grid.
        max_grid_points = max(32, max_evaluations // 2)
        coords = list(product(grid_vals, repeat=dim))
        if len(coords) > max_grid_points:
            coords = coords[:: max(1, len(coords) // max_grid_points)]
        # Track each sampled point with its breach verdict so we can refine the
        # boundary between breaching and non-breaching neighbours.
        sampled: List[Tuple[np.ndarray, bool]] = []  # (s, breaches_coherently)
        for c in coords:
            s = np.array(c, dtype=float)
            liquid = self._liquid_after(s)
            margin = liquid - self.target_liquid_pct  # smooth guide: ≤ 0 → near breach
            all_seeds.append((margin, s))
            # Feasibility is the *true* breach test (redemption failure), not the
            # liquidity-floor proxy used for ordering — AND the coherence guardrail:
            # an incoherent liquidity-only corner is not a plausible breach, so it
            # must never seed the refinement or become the materialised scenario.
            breaches = self._is_coherent(s) and self._is_breach(s)
            sampled.append((s, breaches))
            if breaches:
                feasible_seeds.append((self._distance(s), s))

        # ---- 2b. Boundary refinement -----------------------------------------
        # The coarse grid only samples severity fractions at the lattice nodes, so a
        # plausible breach that lives *between* nodes is invisible to it. Add a finer
        # local sample at the midpoint of every adjacent (breach, no-breach) seed
        # pair: those midpoints straddle the breach boundary, so they are the most
        # informative new points to probe and the best SLSQP seeds. Budget-capped so
        # this never starves the refinement. Most useful when the coarsest grid
        # (grid_per_axis=3) would otherwise miss a sub-corner breach entirely.
        boundary_seeds: List[Tuple[float, np.ndarray]] = []
        refine_cap = max(8, max_evaluations // 6)
        n_refined = 0
        breachers = [s for s, b in sampled if b]
        non_breachers = [s for s, b in sampled if not b]
        for sb in breachers:
            if n_refined >= refine_cap:
                break
            # Nearest non-breaching seed to this breaching one — they bracket the
            # boundary; their midpoint is the cheapest informative probe.
            if not non_breachers:
                break
            dists = [float(np.sum((sb - sn) ** 2)) for sn in non_breachers]
            sn = non_breachers[int(np.argmin(dists))]
            mid = 0.5 * (sb + sn)
            if self._is_coherent(mid) and self._is_breach(mid):
                d = self._distance(mid)
                boundary_seeds.append((d, mid))
                feasible_seeds.append((d, mid))
            n_refined += 1

        feasible_seeds.sort(key=lambda t: t[0])
        boundary_seeds.sort(key=lambda t: t[0])
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

            # Seed from severe corner + boundary midpoints + most-breaching grid
            # points. The boundary midpoints straddle the breach surface, so they
            # start SLSQP nearest the least-severe coherent breach — exactly where a
            # non-convex book is most likely to hide a more plausible scenario than
            # the lattice nodes reveal. They go right after the corner, ahead of the
            # raw grid seeds, and the start count is widened so they never crowd out
            # the corner/grid diversity that anchors the search.
            n_starts = max(n_starts, n_starts + min(len(boundary_seeds), dim))
            seeds: List[np.ndarray] = [s_max]
            seeds += [s for _, s in boundary_seeds[: max(0, n_starts - 1)]]
            remaining = max(0, n_starts - len(seeds))
            seeds += [s for _, s in feasible_seeds[:remaining]]
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
        if self._is_breach_forced(s_polished) and self._is_coherent(s_polished):
            if d_polished < best[0] - 1e-9:
                best = (d_polished, s_polished)
                method = "ray-bisection" if method == "grid" else f"{method}+ray"
            else:
                best = (d_polished, s_polished)

        # ---- 3c. Coordinate boundary-walk polish ------------------------------
        # The radial ray can only scale every axis by one common factor; it cannot
        # *trade* severity between axes. On a non-convex breach surface the least-
        # severe breach often sits where one axis can still relax further if another
        # holds — a sideways move the ray structurally misses. Walk each axis toward
        # calm individually (descending marginal D contribution) while the point
        # keeps breaching coherently. This is again a pure improvement: it only ever
        # shrinks axes of an already-breaching coherent point, so D never rises and
        # the breach/coherence invariants are preserved. It runs after the ray polish
        # so it refines the genuinely closest point found so far, at a cost of at most
        # a few cached evaluations per axis.
        d_walk, s_walk = self._refine_coordinate(best[1])
        if self._is_breach_forced(s_walk) and self._is_coherent(s_walk) and d_walk < best[0] - 1e-9:
            best = (d_walk, s_walk)
            if not method.endswith("ray") and "coord" not in method:
                method = f"{method}+coord" if method != "grid" else "coordinate-walk"
            else:
                method = f"{method}+coord"

        # ---- 4. Materialise the winning breach point --------------------------
        return self._materialise(best, method, corner_distance, liquid_zero, s_max)

    def _materialise(
        self,
        best: "tuple[float, np.ndarray]",
        method: str,
        corner_distance: float,
        liquid_zero: float,
        s_max: np.ndarray,
    ) -> ReverseStressResult:
        """Force a truthful repricing of the winning point and build the result.

        Shared by both the native-core ("found") path and the pure-Python search
        so the final scenario is materialised identically regardless of which
        engine located the breach.

        Force a real repricing of the winner (bypassing the budget guard): the
        reported result must be truthful, never the budget sentinel. Then enforce
        the invariant — a reverse-stress scenario must, by definition, fail to
        meet redemptions. If the chosen point somehow does not (e.g. budget
        exhaustion let a sentinel-seeded point through), fall back to the severe
        corner, which step 1 proved is a genuine breach.
        """
        s_star = best[1]

        # Final fresh-consistent polish — applied to EVERY breaching winner, not
        # just the corner fallback. The native C++ core runs its own ray/coordinate
        # polish, but its breach oracle is the 4-dp *cached* evaluation, so it
        # settles against the quantised boundary and can stop a fraction short of
        # the true (un-quantised) one. The Python path already polishes with the
        # fresh boundary (_is_breach_forced now forces fresh=True), so without this
        # the two paths diverge: native reports a slightly over-severe breach that
        # Python beats. Re-running the polish here with the fresh boundary pulls the
        # native winner down to the same boundary Python reaches, and is idempotent
        # for an already-polished Python winner (it only ever accepts a *closer*
        # point that still breaches). If the winner does not breach at all we skip
        # straight to the corner-fallback block below, which rebuilds from s_max.
        if not self._evaluate(s_star, force=True, fresh=True)[1]:
            _d_ray, s_ray = self._refine_along_ray(s_star)
            d_coord, s_coord = self._refine_coordinate(s_ray)
            if d_coord < best[0] and not self._evaluate(s_coord, force=True, fresh=True)[1]:
                s_star = s_coord
                best = (d_coord, s_star)
                if "+polish" not in method and "corner" not in method:
                    method = (method or "grid") + "+polish"

        # Reprice the *exact* winner (fresh=True): bypass both the budget guard and
        # the 4-dp cache. The cache quantises severity to 4 dp, but the can_meet
        # boundary can be finer than that grid — a neighbour that rounds to the same
        # key may sit on the other side of the breach line, so a cached verdict can
        # be the neighbour's, not the winner's. The reported Can Meet must be the
        # winner's own repricing.
        liquid_star, can_meet_star = self._evaluate(s_star, force=True, fresh=True)
        if can_meet_star:
            # The winner does not actually breach (e.g. the search settled just
            # outside the boundary, or a cache collision let a non-breaching point
            # through). Fall back to the severe corner, which step 1 proved is a
            # genuine breach — but DO NOT report it raw at full severity. The corner
            # is the most-severe breach, not the least-severe one; returning it as-is
            # is the degeneration that makes the result look static (frac=1.0 on
            # every axis). Re-run the two-phase polish from the corner so the
            # reported scenario is the genuinely least-severe coherent breach on the
            # boundary, exactly as the search would have produced had its own winner
            # actually breached. The polish accepts a closer point only if it *still*
            # fails the real redemption test (_is_breach_forced), so the invariant
            # "a materialised reverse-stress scenario is Can Meet = NO" is preserved.
            _d_ray, s_ray = self._refine_along_ray(s_max)
            d_corner, s_corner = self._refine_coordinate(s_ray)
            s_star = s_corner
            liquid_star, can_meet_star = self._evaluate(s_star, force=True, fresh=True)
            if can_meet_star:
                # Polish landed a hair outside the true boundary (the smooth bisection
                # boundary need not coincide with the fresh, un-quantised redemption
                # test). Retreat to the proven corner so the reported result still
                # genuinely breaches; severity is the only thing lost, never truth.
                s_star = s_max
                liquid_star, can_meet_star = self._evaluate(s_star, force=True, fresh=True)
                best = (self._distance(s_max), s_star)
                method = (method or "grid") + "+corner-fallback"
            else:
                # Recompute the distance for the polished corner so severity_distance
                # and the plausibility verdict reflect the least-severe breach, not
                # the raw corner. best[0] is stale here (it was the discarded winner).
                best = (d_corner, s_star)
                method = (method or "grid") + "+corner-polish"
        breach_params = {
            axis.name: axis.value(float(s_star[i])) for i, axis in enumerate(self.axes)
        }
        fractions = {
            axis.name: round(float(np.clip(s_star[i], 0.0, 1.0)), 4)
            for i, axis in enumerate(self.axes)
        }

        severity_distance = round(best[0], 4)
        return ReverseStressResult(
            found=True,
            target_liquid_pct=self.target_liquid_pct,
            severity_distance=severity_distance,
            severity_fractions=fractions,
            breach_parameters=breach_params,
            liquid_pct_at_breach=liquid_star,
            can_meet_redemption_at_breach=can_meet_star,
            margin_to_breach=liquid_star - self.target_liquid_pct,
            baseline_liquid_pct=liquid_zero,
            n_evaluations=self._n_eval,
            method=method,
            corner_distance=round(corner_distance, 4),
            plausibility=_classify_plausibility(severity_distance, corner_distance),
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

        # A "frontier" breach only materialises at (or within a whisker of) the
        # severe corner — the fund is practically resilient and this is the
        # implausible extreme, not a realistic scenario. Flag it in the name so the
        # row is never read as a plausible shock to plan around.
        is_frontier = result.plausibility == "frontier"
        name = (
            "Reverse stress (resilient — breaches only at severe-but-plausible frontier)"
            if is_frontier
            else "Reverse stress (multi-factor breach)"
        )
        frontier_note = (
            " This breach sits at the implausible extreme of the plausible box "
            f"(distance {result.severity_distance} vs severe-corner {result.corner_distance}): "
            "the fund is practically resilient and does not fail under any genuinely "
            "plausible shock."
            if is_frontier
            else ""
        )

        scenario = StressScenario(
            name=name,
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
                f"{frontier_note}"
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
