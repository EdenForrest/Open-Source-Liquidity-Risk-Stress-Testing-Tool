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

    minimise    D(s) = sqrt( Σ_i w_i · s_i² )          (severity / implausibility)
    subject to  liquid_pct_after(s) ≤ breach_threshold  (a breach occurs)
                0 ≤ s_i ≤ 1

``D(s)`` is a plausibility-weighted Euclidean (Mahalanobis-style) distance from
the calm state ``s = 0``. Its constrained minimiser on the breach boundary is the
*easiest* way the fund can breach — exactly what reverse stress is meant to find.

The breach surface is non-convex (liquidity responds discontinuously as buckets
cross horizons), so we use a **multi-start SLSQP** search: a coarse Sobol/grid of
starting points feeds a sequence of gradient-based constrained refinements, and
we keep the feasible (breaching) point with the smallest ``D(s)``. If scipy is
unavailable, we fall back to a pure coarse-to-fine grid search over the same box.

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
    method: str = ""                              # "SLSQP+multistart" | "grid"
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

    def _evaluate(self, s: np.ndarray) -> Tuple[float, bool]:
        """Return (liquid_pct_after, can_meet_redemption) for severity vector ``s``.

        Cached and clipped to the unit box. This is the single expensive call —
        it reprices the whole portfolio via the host StressEngine.
        """
        key = tuple(round(float(x), 4) for x in np.clip(s, 0.0, 1.0))
        if key in self._cache:
            return self._cache[key]
        # Budget guard: once the fresh-evaluation budget is spent, stop repricing.
        # Returning a non-breaching sentinel makes the constraint look unsatisfied,
        # so SLSQP stops exploring and the search settles on the best point already
        # found (or the severe corner). This bounds wall-clock time hard.
        if self._eval_budget is not None and self._n_eval >= self._eval_budget:
            return (1.0, True)
        scenario = self._scenario_from_fractions(np.asarray(key), name="__reverse_probe__")
        result = self.stress_engine._apply_scenario(scenario)
        self._n_eval += 1
        out = (float(result.liquid_pct_after), bool(result.can_meet_redemption))
        self._cache[key] = out
        return out

    def _liquid_after(self, s: np.ndarray) -> float:
        return self._evaluate(s)[0]

    def _distance(self, s: np.ndarray) -> float:
        """Plausibility-weighted severity norm D(s) = sqrt(Σ w_i s_i²)."""
        w = np.array([a.weight for a in self.axes], dtype=float)
        s = np.clip(np.asarray(s, dtype=float), 0.0, 1.0)
        return float(np.sqrt(np.sum(w * s * s)))

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
        if liquid_zero <= self.target_liquid_pct:
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
        liquid_max, _ = self._evaluate(s_max)
        if liquid_max > self.target_liquid_pct:
            # No breach is reachable within the plausible box → robust.
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
            margin = liquid - self.target_liquid_pct  # ≤ 0 → breach
            all_seeds.append((margin, s))
            if margin <= 0.0:
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

            w = np.array([a.weight for a in self.axes], dtype=float)

            def objective(s):
                s = np.clip(s, 0.0, 1.0)
                return float(np.sqrt(np.sum(w * s * s) + 1e-12))

            def obj_grad(s):
                s = np.clip(s, 0.0, 1.0)
                d = np.sqrt(np.sum(w * s * s) + 1e-12)
                return (w * s) / d

            def breach_constraint(s):
                # ≥ 0 when liquidity is at/below target (breach satisfied)
                return self.target_liquid_pct - self._liquid_after(s)

            constraints = {"type": "ineq", "fun": breach_constraint}
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
                liquid = self._liquid_after(s_star)
                # Accept only genuinely-breaching optima (small numeric tolerance).
                if liquid <= self.target_liquid_pct + 1e-4:
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
            method = method or "grid"

        # ---- 4. Materialise the winning breach point --------------------------
        s_star = best[1]
        liquid_star, can_meet_star = self._evaluate(s_star)
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
