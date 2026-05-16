"""
Liquidity Profiler
------------------
Assigns each position to a liquidity bucket and aggregates the portfolio
into a liquidity ladder.  Supports both normal and stress regimes.

Key outputs
-----------
* position_buckets  : per-position bucket assignment + realisable value
* liquidity_ladder  : NAV % per bucket
* cumulative_liquidity : cumulative liquidatable % by day-horizon
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from typing import Optional

from ..config.settings import (
    ASSET_CLASS_LIQUIDITY,
    BUCKET_ORDER,
    CONCENTRATION_FLAG_THRESHOLD,
    LIQUIDITY_BUCKETS,
    MAX_ADV_PARTICIPATION,
    LIQUIDITY_WARNING_THRESHOLD,
    LIQUIDITY_BREACH_THRESHOLD,
)
from ..models.position import Portfolio


_BUCKET_RANK = {"T+0": 0, "T+1": 1, "T+3": 2, "T+7": 3, ">T+7": 4}


class LiquidityProfiler:

    def __init__(self, portfolio: Portfolio, stress: bool = False, adv_stress_scalar: float = 1.0):
        self.portfolio = portfolio
        self.stress = stress
        self.adv_stress_scalar = adv_stress_scalar
        self._result: Optional[pd.DataFrame] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> "LiquidityProfiler":
        df = self.portfolio.positions_df.copy()
        # Use position sum as NAV denominator so that LCR fractions are on the
        # same basis as the realisable values. portfolio.total_nav may come from
        # a separate NAV file whose total differs from the MVHOL position sum,
        # which would cause LCR to exceed 100%.
        nav = df["market_value_eur"].sum() or self.portfolio.total_nav

        df = self._assign_buckets(df)
        df = self._apply_haircuts(df, nav)
        df = self._apply_adv_cap(df)
        df = self._flag_concentration(df, nav)
        self._result = df
        self._nav = nav
        return self

    @property
    def position_buckets(self) -> pd.DataFrame:
        self._check_ran()
        return self._result

    def liquidity_ladder(self) -> pd.DataFrame:
        """Return NAV % per bucket.

        nav_pct = market_value_in_bucket / total_nav (sums to exactly 100%).
        realisable_value_eur is also included for cost/haircut analysis.
        Uses the NAV file value (portfolio.total_nav) as the denominator so that
        the ladder percentages are consistent with regulatory reporting.
        """
        self._check_ran()
        # Use the position sum computed at run() time as the NAV denominator.
        # For a normal portfolio this equals portfolio.total_nav (validated by the loader).
        # For a shocked (stressed) portfolio this is the post-shock position sum,
        # so the percentages are relative to the stressed NAV — as required by ESMA.
        nav = self._nav
        agg = self._result.groupby("bucket").agg(
            realisable_value_eur=("realisable_value", "sum"),
            market_value_eur=("market_value_eur", "sum"),
        ).reindex(BUCKET_ORDER, fill_value=0.0).reset_index()
        agg["nav_pct"] = agg["market_value_eur"] / nav if nav > 0 else 0.0
        agg["cumulative_nav_pct"] = agg["nav_pct"].cumsum()
        return agg

    def liquidity_at_horizon(self, days: int) -> float:
        """Return fraction of NAV realisable within `days` calendar days."""
        ladder = self.liquidity_ladder()
        covered = []
        for _, row in ladder.iterrows():
            lo, hi = LIQUIDITY_BUCKETS[row["bucket"]]
            if lo <= days:
                covered.append(row["nav_pct"])
        return sum(covered)

    def coverage_ratio(self, redemption_pct: float) -> float:
        """Fraction of the redemption amount that can be met in T+0/T+1."""
        immediate = self.liquidity_at_horizon(1)
        return immediate / redemption_pct if redemption_pct > 0 else float("inf")

    def regulatory_flags(self) -> dict:
        liquid_1d = self.liquidity_at_horizon(1)
        flags = {
            "liquid_T0_T1_pct": liquid_1d,
            "warning":  liquid_1d < LIQUIDITY_WARNING_THRESHOLD,
            "breach":   liquid_1d < LIQUIDITY_BREACH_THRESHOLD,
        }
        return flags

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _assign_buckets(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Assign each position to a liquidity bucket.

        The effective bucket is the *worse* of:
          (a) the asset-class settlement bucket (T+0, T+1, etc.), and
          (b) the ADV-implied bucket — how many days it actually takes to
              liquidate the full position at MAX_ADV_PARTICIPATION of ADV.

        A large listed-equity position that needs 10 days to exit fully is
        classified as >T+7 even though equities normally settle T+1.
        This prevents overstatement of short-term liquidity for concentrated
        or illiquid-by-size positions.
        """
        effective_adv = df["adv_30d"] * self.adv_stress_scalar
        daily_capacity = effective_adv * MAX_ADV_PARTICIPATION
        days_to_liq = np.where(
            daily_capacity > 0,
            np.ceil(df["market_value_eur"] / daily_capacity.replace(0, np.nan)),
            np.inf,
        )
        df["_days_to_liq_pre"] = days_to_liq

        def _days_to_bucket(days: float) -> str:
            if days <= 0:
                return "T+0"
            elif days <= 1:
                return "T+1"
            elif days <= 3:
                return "T+3"
            elif days <= 7:
                return "T+7"
            else:
                return ">T+7"

        def get_bucket(row):
            if row["is_locked"]:
                return ">T+7"
            if pd.notna(row["bucket_override"]) and row["bucket_override"]:
                return row["bucket_override"]
            profile = ASSET_CLASS_LIQUIDITY.get(row["asset_class"], {})
            asset_bucket = profile.get("bucket", ">T+7")
            adv_bucket = _days_to_bucket(row["_days_to_liq_pre"])
            # Take the worse (less liquid) of the two
            if _BUCKET_RANK[adv_bucket] > _BUCKET_RANK[asset_bucket]:
                return adv_bucket
            return asset_bucket

        df["bucket"] = df.apply(get_bucket, axis=1)
        df.drop(columns=["_days_to_liq_pre"], inplace=True)
        return df

    def _apply_haircuts(self, df: pd.DataFrame, nav: float) -> pd.DataFrame:
        """
        Compute realisable value as:
            market_value × (1 − haircut − bid_ask_spread)

        haircut        : asset-class regime haircut (normal or stress)
        bid_ask_spread : position-level half-spread (bid_ask_spread_bps / 2 / 10_000)
                         representing the cost of crossing the spread on exit.
        """
        regime = "haircut_stress" if self.stress else "haircut_normal"

        def total_haircut(row):
            profile = ASSET_CLASS_LIQUIDITY.get(row["asset_class"], {})
            base_haircut = profile.get(regime, 0.0)
            # Half-spread cost: we pay the spread to cross from mid to bid on exit
            spread_cost = row["bid_ask_spread_bps"] / 2.0 / 10_000
            return base_haircut + spread_cost

        df["haircut"] = df.apply(total_haircut, axis=1).clip(lower=0.0, upper=0.99)
        df["realisable_value"] = df["market_value_eur"] * (1 - df["haircut"])
        df["realisable_weight"] = df["realisable_value"] / nav
        return df

    def _apply_adv_cap(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Cap daily liquidatable amount at MAX_ADV_PARTICIPATION * effective_ADV.
        effective_ADV = adv_30d * adv_stress_scalar (volume collapse under stress).
        Positions where ADV is 0 (illiquid) remain in their bucket but
        with a flag indicating they cannot be liquidated quickly.
        """
        effective_adv = df["adv_30d"] * self.adv_stress_scalar
        daily_capacity = effective_adv * MAX_ADV_PARTICIPATION
        df["effective_adv"] = effective_adv
        df["adv_capped"] = daily_capacity > 0
        # Days needed to fully exit the position
        df["days_to_liquidate"] = np.where(
            daily_capacity > 0,
            np.ceil(df["market_value_eur"] / daily_capacity.replace(0, np.nan)),
            np.inf,
        )
        return df

    def _flag_concentration(self, df: pd.DataFrame, nav: float) -> pd.DataFrame:
        df["concentration_flag"] = df["weight"] > CONCENTRATION_FLAG_THRESHOLD
        return df

    def _check_ran(self):
        if self._result is None:
            raise RuntimeError("Call .run() before accessing results.")
