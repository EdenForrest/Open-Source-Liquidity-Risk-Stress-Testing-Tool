"""
Stress Testing Engine
----------------------
Applies ESMA-style stress scenarios to the portfolio and computes:
  * Shocked NAV under each scenario
  * Liquidity profile under stress
  * NAV impact in EUR and %
  * % of portfolio liquid under stress
  * Time-to-liquidate under stress assumptions

Shock types modelled
--------------------
1. Equity shocks      : price multiplier on equity / ETF positions
2. Credit spread shocks : bond repricing via DV01 (duration × spread change)
3. Liquidity haircut multiplier : stress haircuts scaled up
4. Combined severe scenario
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field, replace
from typing import List, Optional

import pandas as pd
import numpy as np

from ..config.settings import (
    STRESS_SCENARIOS,
    REVOLUTION_SCENARIOS,
    ASSET_CLASS_LIQUIDITY,
    BUCKET_ORDER,
    DURATION_BY_ASSET_CLASS,
    EQUITY_SHOCK_MAX_LOSS,
    LIQUIDITY_BREACH_THRESHOLD,
    LIQUIDITY_BUCKETS,
    MAX_HAIRCUT,
    StressScenario,
)
from .liquidity_utils import liquidity_at_horizon, safe_divide
from ..models.position import Portfolio
from .liquidity_profiler import LiquidityProfiler
from .waterfall_engine import WaterfallEngine


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class ScenarioResult:
    scenario_name: str
    nav_before: float
    nav_after_shock: float
    nav_impact_eur: float
    nav_impact_pct: float
    equity_loss_eur: float
    credit_loss_eur: float
    liquid_pct_before: float    # % liquid in T0-T1 pre-stress  (÷ nav_before)
    liquid_pct_after: float     # % liquid in T0-T1 post-stress (÷ nav_after — ESMA basis)
    time_to_liquidate_days: float
    redemption_pct: float       # redemption rate in scenario
    can_meet_redemption: bool
    liquidity_loss_eur: float = 0.0   # loss attributable to haircut uplift
    rate_loss_eur: float = 0.0        # loss attributable to parallel rate shock on gov bonds
    derivative_loss_eur: float = 0.0  # loss on leveraged derivatives (options/futures) under the equity shock
    # Absolute realisable EUR in the T0-T1 horizon, before and after the shock.
    # liquid_pct_after divides by the (shrunken) post-shock NAV, which is the
    # ESMA reporting basis but is NOT comparable to liquid_pct_before: a NAV
    # crash inflates the share of any unshocked liquidity (e.g. cash), so the
    # stressed % can RISE even as the fund's real liquidity falls. These EUR
    # figures and liquid_pct_after_vs_before are the like-for-like comparison.
    liquid_eur_before: float = 0.0
    liquid_eur_after: float = 0.0
    # liquid_after measured against the SAME denominator as liquid_before
    # (nav_before), so the two are directly comparable.
    liquid_pct_after_vs_before: float = 0.0
    # Carried from the source StressScenario so downstream consumers (Annex IV
    # validation, reporting) can identify the regulator-mandated worst case
    # without re-deriving it from nav_impact. ESMA's "Severe Combined" sets this.
    is_worst_case: bool = False
    position_detail: pd.DataFrame = field(default_factory=pd.DataFrame)

    def to_dict(self) -> dict:
        return {
            k: v for k, v in self.__dict__.items()
            if k != "position_detail"
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class StressEngine:
    """
    Parameters
    ----------
    portfolio   : Portfolio
    scenarios   : list of StressScenario (defaults to config STRESS_SCENARIOS)
    """

    EQUITY_ASSET_CLASSES    = {"listed_equity", "etf"}
    GOVERNMENT_BOND_CLASSES = {"government_bond"}
    CREDIT_BOND_CLASSES     = {"ig_corporate_bond", "hy_corporate_bond", "structured_credit", "money_market"}
    BOND_ASSET_CLASSES      = GOVERNMENT_BOND_CLASSES | CREDIT_BOND_CLASSES
    # Linear derivatives repriced off the equity shock on their economic
    # exposure (exposure_base), not their (near-zero / margin) market value.
    DERIVATIVE_ASSET_CLASSES = {"option", "future"}

    def __init__(
        self,
        portfolio: Portfolio,
        scenarios: Optional[List[StressScenario]] = None,
        scenario_library: str = "esma",
    ):
        self.portfolio = portfolio
        if scenarios is not None:
            self.scenarios = scenarios
        elif scenario_library == "revolution":
            self.scenarios = REVOLUTION_SCENARIOS
        elif scenario_library == "all":
            self.scenarios = STRESS_SCENARIOS + REVOLUTION_SCENARIOS
        else:
            self.scenarios = STRESS_SCENARIOS

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> pd.DataFrame:
        results = [self._apply_scenario(s) for s in self.scenarios]
        return pd.DataFrame([r.to_dict() for r in results])

    def run_detail(self) -> List[ScenarioResult]:
        return [self._apply_scenario(s) for s in self.scenarios]

    # ------------------------------------------------------------------
    # Scenario application
    # ------------------------------------------------------------------

    def _apply_scenario(self, scenario: StressScenario) -> ScenarioResult:
        df = self.portfolio.positions_df.copy()
        # Use position sum as the baseline so nav_before and nav_after are on
        # the same basis. portfolio.total_nav can come from a separate NAV file
        # whose total may differ from the MVHOL position sum, causing spurious
        # positive returns when the gap exceeds the shock loss.
        nav_before = df["market_value_eur"].sum()

        # 1. Compute shocked market values
        df = self._shock_equities(df, scenario.equity_shock)
        df, credit_loss, rate_loss = self._shock_credit(
            df,
            spread_shock_bps=scenario.credit_spread_shock_bps,
            rate_shock_bps=scenario.rate_shock_bps,
        )
        df, derivative_loss = self._shock_derivatives(df, scenario.equity_shock)

        equity_loss = (
            df.loc[df["asset_class"].isin(self.EQUITY_ASSET_CLASSES), "shocked_mv"].sum()
            - df.loc[df["asset_class"].isin(self.EQUITY_ASSET_CLASSES), "market_value_eur"].sum()
        )

        nav_after = df["shocked_mv"].sum()
        nav_impact = nav_after - nav_before

        # 2. Re-run liquidity profile on shocked portfolio
        shocked_portfolio = self._build_shocked_portfolio(df)
        profiler_stress = LiquidityProfiler(
            shocked_portfolio, stress=True, adv_stress_scalar=scenario.adv_stress_scalar
        ).run()

        # Apply liquidity haircut multiplier
        mv_before_haircut = profiler_stress.position_buckets["realisable_value"].sum()
        stressed_profile = self._apply_haircut_multiplier(
            profiler_stress.position_buckets,
            scenario.liquidity_haircut_multiplier,
        )
        liquidity_loss = stressed_profile["realisable_value"].sum() - mv_before_haircut

        # liquid_before: original portfolio under normal conditions (pre-shock, normal ADV)
        profiler_pre = LiquidityProfiler(
            self.portfolio, stress=False, adv_stress_scalar=1.0
        ).run()
        # Absolute realisable EUR in the T0-T1 horizon — the like-for-like basis.
        liquid_eur_before = liquidity_at_horizon(profiler_pre.position_buckets, 1)
        liquid_eur_after  = liquidity_at_horizon(stressed_profile, 1)
        liquid_before = safe_divide(liquid_eur_before, nav_before)
        # liquid_after: shocked portfolio under stressed conditions (post-shock, compressed ADV + multiplied haircuts).
        # Divided by nav_after — the ESMA reporting basis (stressed liquidity vs stressed NAV).
        liquid_after  = safe_divide(liquid_eur_after, nav_after)
        # Same numerator measured against nav_before, so it can be compared
        # directly to liquid_before without the shrinking-denominator artefact.
        liquid_after_vs_before = safe_divide(liquid_eur_after, nav_before)

        # 3. Waterfall to meet redemption.
        # Under an extreme shock a *leveraged* book can have its NAV wiped out
        # entirely (shocked_mv sums to ≤ 0). A redemption is a claim on positive
        # net assets, so a non-positive NAV means the fund is already insolvent —
        # it cannot honour any redemption. Clamp the target to 0 (the waterfall
        # rejects a negative target) and let target_met decide: with no positive
        # NAV to redeem against, a non-trivial redemption_rate is unmeetable, which
        # is exactly the breach a reverse stress search must be able to locate
        # rather than crash on.
        redemption_eur = max(nav_after, 0.0) * scenario.redemption_rate
        waterfall = WaterfallEngine(shocked_portfolio, stressed_profile, stress=True)
        wf_result = waterfall.run(redemption_eur)
        # An insolvent book that owes a redemption cannot meet it regardless of how
        # the (degenerate) waterfall scores a near-zero target.
        if nav_after <= 0.0 and scenario.redemption_rate > 0.0:
            wf_result = replace(wf_result, target_met=False)

        return ScenarioResult(
            scenario_name          = scenario.name,
            nav_before             = nav_before,
            nav_after_shock        = nav_after,
            nav_impact_eur         = nav_impact,
            nav_impact_pct         = safe_divide(nav_impact, nav_before),
            equity_loss_eur        = equity_loss,
            credit_loss_eur        = credit_loss,
            liquid_pct_before      = liquid_before,   # already a fraction from liquidity_at_horizon
            liquid_pct_after       = liquid_after,
            time_to_liquidate_days = wf_result.days_to_target,
            redemption_pct         = scenario.redemption_rate,
            can_meet_redemption    = wf_result.target_met,
            liquidity_loss_eur     = liquidity_loss,
            rate_loss_eur          = rate_loss,
            derivative_loss_eur    = derivative_loss,
            liquid_eur_before      = liquid_eur_before,
            liquid_eur_after       = liquid_eur_after,
            liquid_pct_after_vs_before = liquid_after_vs_before,
            is_worst_case          = getattr(scenario, "is_worst_case", False),
            position_detail        = stressed_profile,
        )

    # ------------------------------------------------------------------
    # Shock helpers
    # ------------------------------------------------------------------

    def _shock_equities(self, df: pd.DataFrame, shock: float) -> pd.DataFrame:
        # Cast to float: integer market values would give shocked_mv an int64
        # dtype, and assigning float shocks into an int column truncates (and
        # is deprecated by pandas).
        df["shocked_mv"] = df["market_value_eur"].astype(float)
        mask = df["asset_class"].isin(self.EQUITY_ASSET_CLASSES)
        if mask.any():
            # to_numeric first: beta defaults to None, so the column can be
            # object-dtype, where fillna would emit a downcasting FutureWarning.
            beta = pd.to_numeric(df.loc[mask, "beta"], errors="coerce").fillna(1.0)
            price_return = (shock * beta).clip(lower=-EQUITY_SHOCK_MAX_LOSS)
            df.loc[mask, "shocked_mv"] = df.loc[mask, "market_value_eur"] * (1 + price_return)
        return df

    def _shock_credit(
        self,
        df: pd.DataFrame,
        spread_shock_bps: int,
        rate_shock_bps: int = 0,
    ) -> tuple[pd.DataFrame, float, float]:
        """
        Reprice bonds using duration + convexity: ΔP/P ≈ -MD·Δy + 0.5·convexity·Δy²

        Government bonds receive the rate shock only.
        Credit bonds receive rate shock + spread shock.
        Returns (df, total_credit_loss_eur, total_rate_loss_eur).
        """
        if "shocked_mv" not in df.columns:
            df["shocked_mv"] = df["market_value_eur"].astype(float)

        rate_dy = rate_shock_bps / 10_000
        spread_dy = spread_shock_bps / 10_000

        total_credit_loss = 0.0
        total_rate_loss = 0.0

        # Government bonds: rate shock only
        for ac in self.GOVERNMENT_BOND_CLASSES:
            mask = df["asset_class"] == ac
            if not mask.any():
                continue
            dur = pd.to_numeric(df.loc[mask, "duration"], errors="coerce").fillna(
                DURATION_BY_ASSET_CLASS.get(ac, 3.0))
            cvx = pd.to_numeric(df.loc[mask, "effective_convexity"],
                                errors="coerce").fillna(0.0)
            dy = rate_dy
            price_change_pct = -dur * dy + 0.5 * cvx * (dy ** 2)
            mv_before = df.loc[mask, "shocked_mv"].copy()
            df.loc[mask, "shocked_mv"] = mv_before * (1 + price_change_pct)
            total_rate_loss += (df.loc[mask, "shocked_mv"] - mv_before).sum()

        # Credit bonds: rate shock + spread shock. The MV reprices on the
        # combined move; for attribution, the rate-only repricing books to
        # rate loss and the incremental spread effect (including the
        # rate×spread convexity cross-term) books to credit loss, so the two
        # components sum exactly to the total ΔMV.
        for ac in self.CREDIT_BOND_CLASSES:
            mask = df["asset_class"] == ac
            if not mask.any():
                continue
            dur = pd.to_numeric(df.loc[mask, "duration"], errors="coerce").fillna(
                DURATION_BY_ASSET_CLASS.get(ac, 3.0))
            cvx = pd.to_numeric(df.loc[mask, "effective_convexity"],
                                errors="coerce").fillna(0.0)
            dy = rate_dy + spread_dy
            price_change_pct = -dur * dy + 0.5 * cvx * (dy ** 2)
            rate_only_pct = -dur * rate_dy + 0.5 * cvx * (rate_dy ** 2)
            mv_before = df.loc[mask, "shocked_mv"].copy()
            df.loc[mask, "shocked_mv"] = mv_before * (1 + price_change_pct)
            total_rate_loss += (mv_before * rate_only_pct).sum()
            total_credit_loss += (mv_before * (price_change_pct - rate_only_pct)).sum()

        return df, total_credit_loss, total_rate_loss

    def _shock_derivatives(
        self, df: pd.DataFrame, equity_shock: float
    ) -> tuple[pd.DataFrame, float]:
        """Reprice linear derivatives (options/futures) under the equity shock.

        A derivative's market_value_eur is its mark-to-market / margin balance,
        which is near zero at inception and does NOT reflect the economic
        exposure being shocked. The P&L of an index future or delta-one option
        is driven by its notional (exposure_base), so:

            loss = equity_shock * beta * exposure
            shocked_mv = market_value_eur + loss

        exposure_base falls back to market_value_eur where it is missing/zero
        (a derivative carried at full notional). A negative exposure_base is a
        short hedge: it GAINS when the market falls, correctly offsetting long
        book losses. Without this, leveraged derivatives showed zero stress P&L.
        """
        if "shocked_mv" not in df.columns:
            df["shocked_mv"] = df["market_value_eur"].astype(float)

        mask = df["asset_class"].isin(self.DERIVATIVE_ASSET_CLASSES)
        if not mask.any():
            return df, 0.0

        exp = pd.to_numeric(df.loc[mask, "exposure_base"], errors="coerce")
        mv = df.loc[mask, "market_value_eur"].astype(float)
        # Economic notional: exposure_base where populated and non-zero, else MV.
        exposure = exp.where(exp.notna() & (exp.abs() > 0), mv)
        beta = pd.to_numeric(df.loc[mask, "beta"], errors="coerce").fillna(1.0)
        price_return = (equity_shock * beta).clip(lower=-EQUITY_SHOCK_MAX_LOSS)
        loss = exposure * price_return
        df.loc[mask, "shocked_mv"] = mv + loss
        return df, float(loss.sum())

    def _apply_haircut_multiplier(
        self, profile: pd.DataFrame, multiplier: float
    ) -> pd.DataFrame:
        profile = profile.copy()
        # The multiplier is calibrated against regime (stress) haircuts — see
        # StressScenario.liquidity_haircut_multiplier ("applied on top of
        # stress haircuts"). The bid-ask half-spread component is an observed
        # transaction cost, not a regime haircut, so it passes through
        # unscaled.
        if "bid_ask_spread_bps" in profile.columns:
            spread_cost = (profile["bid_ask_spread_bps"] / 2.0 / 10_000).clip(lower=0.0)
        else:
            spread_cost = 0.0
        base = (profile["haircut"] - spread_cost).clip(lower=0.0)
        profile["haircut"] = (base * multiplier + spread_cost).clip(lower=0.0, upper=MAX_HAIRCUT)
        # mv - |mv|*h, not mv*(1-h): haircuts must gross UP the cost of closing
        # negative-MV positions (shorts, overdrafts), mirroring the profiler.
        profile["realisable_value"] = (
            profile["market_value_eur"]
            - profile["market_value_eur"].abs() * profile["haircut"]
        )
        nav = profile["market_value_eur"].sum()
        profile["realisable_weight"] = safe_divide(profile["realisable_value"], nav)
        return profile

    def _build_shocked_portfolio(self, df: pd.DataFrame) -> Portfolio:
        """Shallow copy of portfolio with shocked market values."""
        shocked = copy.deepcopy(self.portfolio)
        # positions_df builds rows in self.positions order and the shock helpers
        # never reorder df, so the shocked_mv column aligns positionally with
        # shocked.positions. Mapping by ISIN instead would collapse duplicate
        # ISINs (e.g. two tranches / two lots of the same instrument) to a single
        # value, mis-stating the shocked NAV of every position sharing that ISIN.
        if len(df) != len(shocked.positions):
            # Defensive: fall back to ISIN mapping if the 1:1 row alignment ever
            # breaks (it should not), accepting the duplicate-collapse risk over
            # a silent positional mismatch.
            mv_map = df.set_index("isin")["shocked_mv"].to_dict()
            for pos in shocked.positions:
                if pos.isin in mv_map:
                    pos.market_value = float(mv_map[pos.isin])
        else:
            # market_value is already EUR (converted at load); fx_rate is
            # informational only, so no re-conversion here.
            for pos, shocked_mv in zip(shocked.positions, df["shocked_mv"]):
                pos.market_value = float(shocked_mv)
        shocked._refresh_weights()
        return shocked

    def _liquidity_at_horizon_df(
        self, profile: pd.DataFrame, days: int, nav: float
    ) -> float:
        return safe_divide(liquidity_at_horizon(profile, days), nav)

    # ------------------------------------------------------------------
    # Reverse stress testing
    # ------------------------------------------------------------------

    def run_reverse_stress(
        self,
        target_liquid_pct: float = None,
        shock_parameter: str = "equity_shock",
        lo: float = 0.0,
        hi: float = 0.60,
        tolerance: float = 0.005,
        max_iterations: int = 40,
    ) -> dict:
        """
        Binary search for the minimum shock magnitude that drives
        T0-T1 liquidity below `target_liquid_pct`.

        Parameters
        ----------
        target_liquid_pct : breach threshold (defaults to LIQUIDITY_BREACH_THRESHOLD)
        shock_parameter   : field of StressScenario to vary; currently "equity_shock"
        lo / hi           : search bounds for shock magnitude (absolute value)
        tolerance         : acceptable precision on the breach shock level
        max_iterations    : safety cap

        Returns
        -------
        dict with keys: found, breach_shock_level, iterations,
                        liquid_pct_at_breach, scenario_at_breach
        """
        if target_liquid_pct is None:
            target_liquid_pct = LIQUIDITY_BREACH_THRESHOLD

        valid_parameters = frozenset({
            "equity_shock",
            "credit_spread_shock_bps",
            "adv_stress_scalar",
            "liquidity_haircut_multiplier",
            "rate_shock_bps",
            "redemption_rate",
        })
        if shock_parameter not in valid_parameters:
            raise ValueError(
                f"Unknown shock_parameter '{shock_parameter}'; "
                f"expected one of {sorted(valid_parameters)}"
            )
        if not (math.isfinite(lo) and math.isfinite(hi) and lo < hi):
            raise ValueError(
                f"Search bounds must be finite with lo < hi (got lo={lo}, hi={hi})"
            )
        if not (math.isfinite(tolerance) and tolerance > 0):
            raise ValueError(f"tolerance must be a finite value > 0 (got {tolerance})")

        # Start the search from a NEUTRAL (all-zero) scenario so the swept
        # `shock_parameter` is the ONLY shock applied. Previously this deep-copied
        # self.scenarios[-1] (the worst-case scenario), which contaminated the
        # result: every trial already carried the worst-case equity crash, credit
        # blow-out, haircut multiplier, redemption and ADV collapse, so the reported
        # "breach shock level" was confounded by those baked-in shocks rather than
        # isolating the single parameter being varied. It also coupled the answer to
        # the ordering/contents of self.scenarios via the [-1] index.
        base_scenario = StressScenario(
            name=f"Reverse stress ({shock_parameter})",
            equity_shock=0.0,
            credit_spread_shock_bps=0,
            liquidity_haircut_multiplier=1.0,
            redemption_rate=0.0,
            adv_stress_scalar=1.0,
            rate_shock_bps=0,
            description=(
                f"Neutral base used to isolate the swept parameter "
                f"'{shock_parameter}' during reverse stress."
            ),
        )

        found = False
        breach_shock = None
        breach_liquid = None
        n_iter = 0

        for n_iter in range(1, max_iterations + 1):
            mid = (lo + hi) / 2.0
            trial = copy.deepcopy(base_scenario)
            # The bisection assumes severity is increasing in `mid`, so each
            # parameter needs an explicit mapping onto its stress direction.
            if shock_parameter == "equity_shock":
                trial.equity_shock = -mid
            elif shock_parameter == "credit_spread_shock_bps":
                trial.credit_spread_shock_bps = int(mid * 10_000)
            elif shock_parameter == "adv_stress_scalar":
                # Smaller scalar = less volume = more stress.
                trial.adv_stress_scalar = 1.0 - mid
            elif shock_parameter == "liquidity_haircut_multiplier":
                # Multiplier > 1 widens haircuts; values below 1 would be anti-stress.
                trial.liquidity_haircut_multiplier = 1.0 + mid
            else:
                setattr(trial, shock_parameter, mid)

            result = self._apply_scenario(trial)
            liquid = result.liquid_pct_after

            if liquid <= target_liquid_pct:
                breach_shock = mid
                breach_liquid = liquid
                found = True
                hi = mid
            else:
                lo = mid

            if hi - lo < tolerance:
                break

        return {
            "found": found,
            "breach_shock_level": breach_shock,
            "iterations": n_iter,
            "liquid_pct_at_breach": breach_liquid,
            "scenario_at_breach": base_scenario.name if found else None,
        }

    def reverse_stress_scenario(
        self,
        target_liquid_pct: float = None,
        shock_parameter: str = "equity_shock",
        lo: float = 0.0,
        hi: float = 0.60,
        tolerance: float = 0.005,
        max_iterations: int = 40,
    ):
        """Run reverse stress and materialise the breach as a forward scenario.

        Returns ``(StressScenario, ScenarioResult, search)`` where ``search`` is the
        raw dict from :meth:`run_reverse_stress`. When no breach is found within the
        search bounds, returns ``(None, None, search)`` so callers can skip it.

        This lets the reverse-stress outcome slot into the same ``stress_results`` /
        ``scenario_metadata`` tables as the forward scenarios: the breach scenario is
        a real, single-parameter shock re-applied through ``_apply_scenario``.
        """
        if target_liquid_pct is None:
            target_liquid_pct = LIQUIDITY_BREACH_THRESHOLD

        search = self.run_reverse_stress(
            target_liquid_pct=target_liquid_pct,
            shock_parameter=shock_parameter,
            lo=lo,
            hi=hi,
            tolerance=tolerance,
            max_iterations=max_iterations,
        )
        if not search.get("found") or search.get("breach_shock_level") is None:
            return None, None, search

        mag = search["breach_shock_level"]
        if shock_parameter == "equity_shock":
            shock_desc = f"equity {-mag:.1%}"
        elif shock_parameter == "credit_spread_shock_bps":
            shock_desc = f"credit spread +{int(mag * 10_000)}bps"
        elif shock_parameter == "liquidity_haircut_multiplier":
            shock_desc = f"liquidity haircut ×{mag:.2f}"
        elif shock_parameter == "adv_stress_scalar":
            shock_desc = f"ADV collapse to {mag:.0%} of normal"
        else:
            shock_desc = f"{shock_parameter} {mag:.3g}"

        breach_scenario = StressScenario(
            name=f"Reverse stress ({shock_parameter})",
            equity_shock=0.0,
            credit_spread_shock_bps=0,
            liquidity_haircut_multiplier=1.0,
            redemption_rate=0.0,
            adv_stress_scalar=1.0,
            rate_shock_bps=0,
            description=(
                f"Minimum single-parameter shock that drives T0-T1 liquidity below "
                f"{target_liquid_pct:.0%}: {shock_desc}."
            ),
            regulatory_basis="Reverse stress - AIFMD II Art.16(1); ESMA Guidelines on stress testing",
            is_worst_case=False,
        )
        if shock_parameter == "equity_shock":
            breach_scenario.equity_shock = -mag
        elif shock_parameter == "credit_spread_shock_bps":
            breach_scenario.credit_spread_shock_bps = int(mag * 10_000)
        else:
            setattr(breach_scenario, shock_parameter, mag)

        result = self._apply_scenario(breach_scenario)
        return breach_scenario, result, search
