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
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd
import numpy as np

from ..config.settings import (
    STRESS_SCENARIOS,
    ASSET_CLASS_LIQUIDITY,
    BUCKET_ORDER,
    DURATION_BY_ASSET_CLASS,
    EQUITY_SHOCK_MAX_LOSS,
    LIQUIDITY_BREACH_THRESHOLD,
    LIQUIDITY_BUCKETS,
    StressScenario,
)
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
    liquid_pct_before: float    # % liquid in T0-T1 pre-stress
    liquid_pct_after: float     # % liquid in T0-T1 post-stress
    time_to_liquidate_days: float
    redemption_pct: float       # redemption rate in scenario
    can_meet_redemption: bool
    liquidity_loss_eur: float = 0.0   # loss attributable to haircut uplift
    rate_loss_eur: float = 0.0        # loss attributable to parallel rate shock on gov bonds
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

    def __init__(
        self,
        portfolio: Portfolio,
        scenarios: Optional[List[StressScenario]] = None,
    ):
        self.portfolio = portfolio
        self.scenarios = scenarios or STRESS_SCENARIOS

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

        equity_loss = (
            df.loc[df["asset_class"].isin(self.EQUITY_ASSET_CLASSES), "shocked_mv"].sum()
            - df.loc[df["asset_class"].isin(self.EQUITY_ASSET_CLASSES), "market_value_eur"].sum()
        )

        nav_after = df["shocked_mv"].sum()
        nav_impact = nav_after - nav_before

        # 2. Re-run liquidity profile on shocked portfolio
        shocked_portfolio = self._build_shocked_portfolio(df)
        profiler_normal = LiquidityProfiler(
            shocked_portfolio, stress=False, adv_stress_scalar=scenario.adv_stress_scalar
        ).run()
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

        # liquidity_at_horizon returns a fraction of NAV (0-1), not EUR
        liquid_before = profiler_normal.liquidity_at_horizon(1)
        liquid_after  = self._liquidity_at_horizon_df(stressed_profile, 1, nav_after)

        # 3. Waterfall to meet redemption
        redemption_eur = nav_after * scenario.redemption_rate
        waterfall = WaterfallEngine(shocked_portfolio, stressed_profile, stress=True)
        wf_result = waterfall.run(redemption_eur)

        return ScenarioResult(
            scenario_name          = scenario.name,
            nav_before             = nav_before,
            nav_after_shock        = nav_after,
            nav_impact_eur         = nav_impact,
            nav_impact_pct         = nav_impact / nav_before,
            equity_loss_eur        = equity_loss,
            credit_loss_eur        = credit_loss,
            liquid_pct_before      = liquid_before,   # already a fraction from liquidity_at_horizon
            liquid_pct_after       = liquid_after,
            time_to_liquidate_days = wf_result.days_to_target,
            redemption_pct         = scenario.redemption_rate,
            can_meet_redemption    = wf_result.target_met,
            liquidity_loss_eur     = liquidity_loss,
            rate_loss_eur          = rate_loss,
            position_detail        = stressed_profile,
        )

    # ------------------------------------------------------------------
    # Shock helpers
    # ------------------------------------------------------------------

    def _shock_equities(self, df: pd.DataFrame, shock: float) -> pd.DataFrame:
        df["shocked_mv"] = df["market_value_eur"].copy()
        mask = df["asset_class"].isin(self.EQUITY_ASSET_CLASSES)
        if mask.any():
            beta = df.loc[mask, "beta"].fillna(1.0)
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
            df["shocked_mv"] = df["market_value_eur"].copy()

        rate_dy = rate_shock_bps / 10_000
        spread_dy = spread_shock_bps / 10_000

        total_credit_loss = 0.0
        total_rate_loss = 0.0

        # Government bonds: rate shock only
        for ac in self.GOVERNMENT_BOND_CLASSES:
            mask = df["asset_class"] == ac
            if not mask.any():
                continue
            dur = df.loc[mask, "duration"].fillna(DURATION_BY_ASSET_CLASS.get(ac, 3.0))
            cvx = df.loc[mask, "effective_convexity"].fillna(0.0)
            dy = rate_dy
            price_change_pct = -dur * dy + 0.5 * cvx * (dy ** 2)
            mv_before = df.loc[mask, "shocked_mv"].copy()
            df.loc[mask, "shocked_mv"] = mv_before * (1 + price_change_pct)
            total_rate_loss += (df.loc[mask, "shocked_mv"] - mv_before).sum()

        # Credit bonds: rate shock + spread shock
        for ac in self.CREDIT_BOND_CLASSES:
            mask = df["asset_class"] == ac
            if not mask.any():
                continue
            dur = df.loc[mask, "duration"].fillna(DURATION_BY_ASSET_CLASS.get(ac, 3.0))
            cvx = df.loc[mask, "effective_convexity"].fillna(0.0)
            dy = rate_dy + spread_dy
            price_change_pct = -dur * dy + 0.5 * cvx * (dy ** 2)
            mv_before = df.loc[mask, "shocked_mv"].copy()
            df.loc[mask, "shocked_mv"] = mv_before * (1 + price_change_pct)
            total_credit_loss += (df.loc[mask, "shocked_mv"] - mv_before).sum()

        return df, total_credit_loss, total_rate_loss

    def _apply_haircut_multiplier(
        self, profile: pd.DataFrame, multiplier: float
    ) -> pd.DataFrame:
        profile = profile.copy()
        profile["haircut"] = (profile["haircut"] * multiplier).clip(upper=0.99)
        profile["realisable_value"] = profile["market_value_eur"] * (1 - profile["haircut"])
        nav = profile["market_value_eur"].sum()
        profile["realisable_weight"] = profile["realisable_value"] / nav if nav > 0 else 0
        return profile

    def _build_shocked_portfolio(self, df: pd.DataFrame) -> Portfolio:
        """Shallow copy of portfolio with shocked market values."""
        shocked = copy.deepcopy(self.portfolio)
        mv_map = df.set_index("isin")["shocked_mv"].to_dict()
        for pos in shocked.positions:
            if pos.isin in mv_map:
                pos.market_value = mv_map[pos.isin] / pos.fx_rate
        shocked._refresh_weights()
        return shocked

    def _liquidity_at_horizon_df(
        self, profile: pd.DataFrame, days: int, nav: float
    ) -> float:
        total = 0.0
        for bucket in BUCKET_ORDER:
            lo, _ = LIQUIDITY_BUCKETS[bucket]
            if lo <= days:
                total += profile[profile["bucket"] == bucket]["realisable_value"].sum()
        return total / nav if nav > 0 else 0.0

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

        base_scenario = copy.deepcopy(self.scenarios[-1])  # start from worst-case shape

        found = False
        breach_shock = None
        breach_liquid = None
        n_iter = 0

        for n_iter in range(1, max_iterations + 1):
            mid = (lo + hi) / 2.0
            trial = copy.deepcopy(base_scenario)
            if shock_parameter == "equity_shock":
                trial.equity_shock = -mid
            elif shock_parameter == "credit_spread_shock_bps":
                trial.credit_spread_shock_bps = int(mid * 10_000)
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
