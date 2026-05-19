"""
Redemption Scenario Simulator
------------------------------
Models investor redemption flows across multiple scenarios (5%, 10%, 20%, 30%
of NAV) and determines whether the fund can meet redemptions within the
notice period from liquid assets alone.

Incorporates:
* share-class-specific notice periods and redemption frequency
* investor concentration risk (top-10 concentration assumption)
* gate and suspension thresholds (UCITS/AIFMD style)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pandas as pd
import numpy as np

from ..config.settings import (
    REDEMPTION_SCENARIOS, BUCKET_ORDER, LIQUIDITY_BUCKETS, MAX_ADV_PARTICIPATION,
    MAX_LIQUIDATION_DAYS, MIN_CASH_BUFFER_PCT,
)
from .liquidity_utils import liquidity_at_horizon
from ..models.position import Portfolio


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class RedemptionResult:
    scenario_pct: float       # redemption as % of total NAV
    redemption_eur: float
    liquidity_available_eur: float
    liquidity_available_pct: float
    shortfall_eur: float
    shortfall_pct: float      # shortfall as % of total NAV
    can_meet_t1: bool
    can_meet_t3: bool
    can_meet_t7: bool
    gate_triggered: bool
    suspension_triggered: bool
    concentration_driven: bool  # redemption dominated by single top investor
    days_to_clear: float        # estimated days to fully liquidate for payment

    def to_dict(self) -> dict:
        return self.__dict__


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

class RedemptionSimulator:
    """
    Parameters
    ----------
    portfolio      : Portfolio instance
    liquid_profile : DataFrame from LiquidityProfiler.position_buckets (normal regime)
    stress_profile : DataFrame from LiquidityProfiler.position_buckets (stress regime)
    gate_threshold : fraction of NAV above which a liquidity gate is applied
    suspension_threshold : fraction above which full suspension is assumed
    """

    GATE_THRESHOLD       = 0.10   # UCITS common practice
    SUSPENSION_THRESHOLD = 0.25

    def __init__(
        self,
        portfolio: Portfolio,
        liquid_profile: pd.DataFrame,
        stress_profile: pd.DataFrame | None = None,
    ):
        self.portfolio      = portfolio
        self.liquid_profile = liquid_profile
        self.stress_profile = stress_profile if stress_profile is not None else liquid_profile

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, scenarios: List[float] | None = None, stress: bool = False) -> pd.DataFrame:
        """Run all redemption scenarios; return a summary DataFrame."""
        if scenarios is None:
            scenarios = REDEMPTION_SCENARIOS
        profile = self.stress_profile if stress else self.liquid_profile
        results = [self._evaluate_scenario(pct, profile) for pct in scenarios]
        return pd.DataFrame([r.to_dict() for r in results])

    def concentration_shock(self, top_investor_pct: float | None = None) -> RedemptionResult:
        """Model a single large investor redeeming their entire position."""
        conc = top_investor_pct or self.portfolio.top_10_investor_concentration
        largest_single = conc * 0.30   # approximate largest single investor
        return self._evaluate_scenario(largest_single, self.liquid_profile, concentration_driven=True)

    # ------------------------------------------------------------------
    # Core evaluation
    # ------------------------------------------------------------------

    def _evaluate_scenario(
        self,
        redemption_pct: float,
        profile: pd.DataFrame,
        concentration_driven: bool = False,
    ) -> RedemptionResult:
        nav = profile["market_value_eur"].sum() or self.portfolio.total_nav
        redemption_eur = nav * redemption_pct

        # Liquidity available at each horizon
        liq_t1 = self._liquidity_at_horizon(profile, 1)
        liq_t3 = self._liquidity_at_horizon(profile, 3)
        liq_t7 = self._liquidity_at_horizon(profile, 7)

        buffer = nav * MIN_CASH_BUFFER_PCT
        usable_t1 = max(0.0, liq_t1 - buffer)
        usable_t3 = max(0.0, liq_t3 - buffer)
        usable_t7 = max(0.0, liq_t7 - buffer)

        shortfall_eur = max(0.0, redemption_eur - usable_t7)

        # Estimate days to fully cover redemption via waterfall
        days_to_clear = self._estimate_days_to_cover(redemption_eur, profile)

        return RedemptionResult(
            scenario_pct              = redemption_pct,
            redemption_eur            = redemption_eur,
            liquidity_available_eur   = usable_t7,
            liquidity_available_pct   = usable_t7 / nav,
            shortfall_eur             = shortfall_eur,
            shortfall_pct             = shortfall_eur / nav,
            can_meet_t1               = usable_t1 >= redemption_eur,
            can_meet_t3               = usable_t3 >= redemption_eur,
            can_meet_t7               = usable_t7 >= redemption_eur,
            gate_triggered            = redemption_pct >= self.GATE_THRESHOLD,
            suspension_triggered      = redemption_pct >= self.SUSPENSION_THRESHOLD,
            concentration_driven      = concentration_driven,
            days_to_clear             = days_to_clear,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _liquidity_at_horizon(self, profile: pd.DataFrame, days: int) -> float:
        return liquidity_at_horizon(profile, days)

    def _estimate_days_to_cover(self, target_eur: float, profile: pd.DataFrame) -> float:
        """
        Parallel daily simulation: each day every unlocked position contributes
        up to min(effective_adv * MAX_ADV_PARTICIPATION, remaining_realisable_value).
        Returns fractional calendar days until the cash target is reached.

        Stressed profiles have lower effective_adv (ADV scalar) AND lower
        realisable_value (higher haircuts), so stressed days >= normal days —
        the previous max(day, days_needed) approach inverted this when stress
        haircuts reduced realisable_value proportionally more than the ADV scalar.
        """
        if target_eur <= 0:
            return 0.0

        sellable = profile[~profile["is_locked"]].copy()
        adv_col = "effective_adv" if "effective_adv" in sellable.columns else "adv_30d"
        caps = (sellable[adv_col] * MAX_ADV_PARTICIPATION).clip(lower=0).values
        values = sellable["realisable_value"].clip(lower=0).values

        liquid = caps > 0
        caps, values = caps[liquid], values[liquid]
        if len(caps) == 0:
            return float("inf")

        remaining = float(target_eur)
        day = 0
        while remaining > 0 and day < MAX_LIQUIDATION_DAYS:
            daily = float(np.minimum(caps, values).sum())
            if daily <= 0:
                return float("inf")
            if daily >= remaining:
                return day + remaining / daily
            remaining -= daily
            values = np.maximum(values - caps, 0.0)
            day += 1

        return float(day) if remaining <= 0 else float("inf")
