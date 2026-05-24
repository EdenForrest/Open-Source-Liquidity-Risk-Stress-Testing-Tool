"""
Risk Metrics Aggregator
------------------------
Computes the fund-level risk metrics that would appear in:
  * Monthly UCITS/AIFMD liquidity risk report
  * ManCo risk committee pack
  * CSSF / regulator liquidity reporting (ESMA Q/A guidelines)

Metrics produced
----------------
LiquidityMetrics
  - Liquidity Coverage Ratio (LCR) at T+1 / T+3 / T+7
  - Days to Liquidate 50% / 75% / 90% of portfolio
  - Illiquid concentration (>T+7 as % NAV)
  - Top-10 investor concentration vs. T+1 liquidity
  - Regulatory flags (warning / breach)

StressMetrics
  - Per-scenario: NAV impact, liquid pct change, redemption coverage
  - Worst-case scenario summary

RedemptionMetrics
  - Per redemption rate: coverage, shortfall, days to clear
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd
import numpy as np

from ..engines.liquidity_profiler import LiquidityProfiler
from ..engines.redemption_simulator import RedemptionSimulator
from ..engines.stress_engine import StressEngine
from ..engines.waterfall_engine import WaterfallEngine
from ..models.position import Portfolio
from ..config.settings import REDEMPTION_SCENARIOS, MAX_ADV_PARTICIPATION


# ---------------------------------------------------------------------------
# Metric containers
# ---------------------------------------------------------------------------

@dataclass
class LiquidityMetrics:
    fund_name: str
    reporting_date: str
    total_nav_eur: float

    # Ladder
    bucket_breakdown: pd.DataFrame

    # Coverage
    lcr_t1: float               # liquid (T0+T1) / total NAV
    lcr_t3: float
    lcr_t7: float
    illiquid_pct: float         # >T+7

    # Concentration risk
    top10_concentration: float
    liquidity_vs_concentration: float  # T+1 liquid / top-10 concentration

    # Regulatory
    warning_flag: bool
    breach_flag: bool
    liquid_T0_T1_pct: float

    # Time-to-liquidate percentiles
    days_to_50pct: float
    days_to_75pct: float
    days_to_90pct: float

    # Geographical concentration (AIFMD Annex IV / ESMA34-39-897 Section 4.2)
    top_countries: Dict[str, float] = field(default_factory=dict)
    eu_pct: Optional[float] = None
    non_eu_pct: Optional[float] = None
    geo_top_country: Optional[str] = None
    geo_top_country_pct: Optional[float] = None
    geo_warning_flag: bool = False
    geo_breach_flag: bool = False

    # UCITS 5/10/40 issuer concentration (Art. 52 UCITS Directive)
    ucits_issuer_weights: Dict[str, float] = field(default_factory=dict)
    ucits_breaching_issuers: Dict[str, float] = field(default_factory=dict)
    ucits_aggregate_5_10: float = 0.0
    ucits_single_breach: bool = False
    ucits_aggregate_breach: bool = False
    ucits_compliant: bool = True

    def summary(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k != "bucket_breakdown"}


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

class RiskMetricsBuilder:
    """
    Orchestrates all analytics and packages them into a single report object.
    """

    def __init__(self, portfolio: Portfolio):
        self.portfolio = portfolio

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def build_liquidity_metrics(self) -> LiquidityMetrics:
        profiler = LiquidityProfiler(self.portfolio, stress=False).run()
        # Use NAV file value (portfolio.total_nav) as the authoritative NAV for the report.
        # profiler._nav is the position sum used as the ladder denominator; they should agree
        # within the 0.0001% tolerance validated by the CSV loader.
        nav = self.portfolio.total_nav or profiler._nav
        ladder = profiler.liquidity_ladder()
        flags  = profiler.regulatory_flags()

        # liquidity_at_horizon returns fraction of NAV (0-1)
        lcr_t1 = profiler.liquidity_at_horizon(1)
        lcr_t3 = profiler.liquidity_at_horizon(3)
        lcr_t7 = profiler.liquidity_at_horizon(7)

        # >T+7 illiquid pct
        illiquid = ladder[ladder["bucket"] == ">T+7"]["nav_pct"].sum()

        # Days to liquidate percentiles
        profile_df = profiler.position_buckets
        d50 = self._days_to_liquidate_pct(profile_df, 0.50, nav)
        d75 = self._days_to_liquidate_pct(profile_df, 0.75, nav)
        d90 = self._days_to_liquidate_pct(profile_df, 0.90, nav)

        return LiquidityMetrics(
            fund_name              = self.portfolio.fund_name,
            reporting_date         = str(self.portfolio.reporting_date.date()),
            total_nav_eur          = nav,
            bucket_breakdown       = ladder,
            lcr_t1                 = lcr_t1,
            lcr_t3                 = lcr_t3,
            lcr_t7                 = lcr_t7,
            illiquid_pct           = illiquid,
            top10_concentration    = self.portfolio.top_10_investor_concentration,
            liquidity_vs_concentration = lcr_t1 / self.portfolio.top_10_investor_concentration,
            warning_flag           = flags["warning"] or flags.get("geo_warning_flag", False),
            breach_flag            = flags["breach"]  or flags.get("geo_breach_flag", False),
            liquid_T0_T1_pct       = flags["liquid_T0_T1_pct"],
            days_to_50pct          = d50,
            days_to_75pct          = d75,
            days_to_90pct          = d90,
            top_countries          = flags.get("top_countries", {}),
            eu_pct                 = flags.get("eu_pct"),
            non_eu_pct             = flags.get("non_eu_pct"),
            geo_top_country        = flags.get("geo_top_country"),
            geo_top_country_pct    = flags.get("geo_top_country_pct"),
            geo_warning_flag       = flags.get("geo_warning_flag", False),
            geo_breach_flag        = flags.get("geo_breach_flag", False),
            ucits_issuer_weights   = flags.get("ucits_issuer_weights", {}),
            ucits_breaching_issuers = flags.get("ucits_breaching_issuers", {}),
            ucits_aggregate_5_10   = flags.get("ucits_aggregate_5_10", 0.0),
            ucits_single_breach    = flags.get("ucits_single_breach", False),
            ucits_aggregate_breach = flags.get("ucits_aggregate_breach", False),
            ucits_compliant        = flags.get("ucits_compliant", True),
        )

    def build_stress_summary(self) -> pd.DataFrame:
        engine = StressEngine(self.portfolio)
        results = engine.run()
        results["nav_impact_pct_fmt"] = (results["nav_impact_pct"] * 100).round(2).astype(str) + "%"
        results["liquid_pct_after_fmt"] = (results["liquid_pct_after"] * 100).round(1).astype(str) + "%"
        return results

    def build_redemption_summary(self) -> pd.DataFrame:
        profiler_normal = LiquidityProfiler(self.portfolio, stress=False).run()
        profiler_stress = LiquidityProfiler(self.portfolio, stress=True).run()
        sim = RedemptionSimulator(
            self.portfolio,
            profiler_normal.position_buckets,
            profiler_stress.position_buckets,
        )
        normal_df = sim.run(stress=False)
        stress_df = sim.run(stress=True)
        normal_df["regime"] = "normal"
        stress_df["regime"] = "stress"
        return pd.concat([normal_df, stress_df], ignore_index=True)

    def build_full_report(self) -> dict:
        """Returns all metrics as a dict of DataFrames / objects."""
        return {
            "liquidity_metrics":   self.build_liquidity_metrics(),
            "stress_summary":      self.build_stress_summary(),
            "redemption_summary":  self.build_redemption_summary(),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _days_to_liquidate_pct(
        self, profile: pd.DataFrame, target_pct: float, nav: float
    ) -> float:
        """
        Greedy simulation: sell positions in ADV-capped daily tranches.
        Returns first day by which cumulative proceeds >= target_pct * nav.
        Returns float('inf') only when zero sellable positions exist; otherwise
        returns the maximum days required across all sellable positions even if
        the liquid portion cannot fully cover the target (illiquid tail).
        """
        target_eur = nav * target_pct
        sellable = (
            profile[~profile["is_locked"] & (profile["adv_30d"] > 0)]
            .copy()
            .sort_values("days_to_liquidate")
        )

        if sellable.empty:
            return float("inf")

        cumulative = 0.0
        max_day = 0.0

        for _, pos in sellable.iterrows():
            if cumulative >= target_eur:
                break
            cap = pos["adv_30d"] * MAX_ADV_PARTICIPATION
            days = pos["market_value_eur"] / cap if cap > 0 else 0.0
            max_day = max(max_day, days)
            cumulative += pos["realisable_value"]

        if cumulative >= target_eur:
            return max_day
        # Target unreachable from liquid assets alone — illiquid tail prevents full coverage.
        # Return the max liquidation days of all sellable positions as a lower-bound estimate.
        all_sellable_max = sellable.apply(
            lambda r: r["market_value_eur"] / (r["adv_30d"] * MAX_ADV_PARTICIPATION)
            if r["adv_30d"] * MAX_ADV_PARTICIPATION > 0 else 0.0,
            axis=1,
        ).max()
        return float("inf") if all_sellable_max == 0.0 else all_sellable_max
