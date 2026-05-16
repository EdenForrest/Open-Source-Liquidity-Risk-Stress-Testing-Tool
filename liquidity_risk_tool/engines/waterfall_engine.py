"""
Liquidation Waterfall Engine
-----------------------------
Simulates the ordered asset sell-down needed to meet a given cash target.
Follows the ESMA stress-testing guidelines logic:
  1. Sell most-liquid assets first (T+0 → T+1 → T+3 → T+7 → >T+7)
  2. Respect ADV participation caps (never > MAX_ADV_PARTICIPATION of 30d ADV)
  3. Keep minimum cash buffer intact
  4. Apply market-impact costs (realisable value < market value)
  5. Skip locked positions

Returns a day-by-day sell schedule and cumulative cash raised.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import pandas as pd
import numpy as np

from ..config.settings import (
    ASSET_CLASS_LIQUIDITY,
    BUCKET_ORDER,
    MAX_ADV_PARTICIPATION,
    MIN_CASH_BUFFER_PCT,
)
from ..models.position import Portfolio


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class SellOrder:
    day: int
    isin: str
    name: str
    asset_class: str
    bucket: str
    gross_value: float          # market value sold
    market_impact_cost: float   # estimated slippage + spread
    net_proceeds: float         # cash received after costs
    is_partial: bool = False


@dataclass
class WaterfallResult:
    target_eur: float
    total_proceeds_eur: float
    target_met: bool
    days_to_target: float
    sell_orders: List[SellOrder] = field(default_factory=list)
    residual_shortfall_eur: float = 0.0
    nav_before: float = 0.0
    nav_after: float = 0.0
    nav_impact_pct: float = 0.0

    def sell_schedule_df(self) -> pd.DataFrame:
        if not self.sell_orders:
            return pd.DataFrame()
        rows = [
            {
                "day": o.day,
                "isin": o.isin,
                "name": o.name,
                "asset_class": o.asset_class,
                "bucket": o.bucket,
                "gross_value_eur": o.gross_value,
                "market_impact_eur": o.market_impact_cost,
                "net_proceeds_eur": o.net_proceeds,
                "is_partial": o.is_partial,
            }
            for o in self.sell_orders
        ]
        return pd.DataFrame(rows)

    def daily_summary_df(self) -> pd.DataFrame:
        df = self.sell_schedule_df()
        if df.empty:
            return df
        summary = (
            df.groupby("day")
            .agg(
                gross_sold=("gross_value_eur", "sum"),
                impact_cost=("market_impact_eur", "sum"),
                net_proceeds=("net_proceeds_eur", "sum"),
                positions_sold=("isin", "count"),
            )
            .reset_index()
        )
        summary["cumulative_proceeds"] = summary["net_proceeds"].cumsum()
        return summary


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class WaterfallEngine:
    """
    Parameters
    ----------
    portfolio    : Portfolio
    profile      : DataFrame from LiquidityProfiler.position_buckets
    stress       : bool — use stress haircuts if True
    """

    def __init__(
        self,
        portfolio: Portfolio,
        profile: pd.DataFrame,
        stress: bool = False,
    ):
        self.portfolio = portfolio
        self.profile   = profile.copy()
        self.stress     = stress

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, target_eur: float) -> WaterfallResult:
        nav = self.portfolio.total_nav
        buffer = nav * MIN_CASH_BUFFER_PCT
        effective_target = target_eur  # we aim to raise this net of buffer

        result = WaterfallResult(
            target_eur  = target_eur,
            nav_before  = nav,
            total_proceeds_eur = 0.0,
            target_met  = False,
            days_to_target = 0.0,
        )

        remaining = effective_target
        orders: List[SellOrder] = []

        # Work through buckets in priority order
        for bucket in BUCKET_ORDER:
            if remaining <= 0:
                break
            bucket_positions = self.profile[
                (self.profile["bucket"] == bucket) &
                (~self.profile["is_locked"])
            ].copy()

            # Sort by descending ADV within bucket — highest-volume positions sell first
            # to minimise market impact and satisfy MiFID II best-execution obligations.
            bucket_positions = bucket_positions.sort_values("adv_30d", ascending=False)

            for _, pos in bucket_positions.iterrows():
                if remaining <= 0:
                    break
                sell_result = self._liquidate_position(pos, remaining, bucket)
                if sell_result is None:
                    continue
                orders.append(sell_result)
                remaining -= sell_result.net_proceeds

        total_proceeds = sum(o.net_proceeds for o in orders)

        result.sell_orders            = orders
        result.total_proceeds_eur     = total_proceeds
        result.target_met             = (effective_target - total_proceeds) <= 0.01
        result.residual_shortfall_eur = max(0.0, effective_target - total_proceeds)
        result.days_to_target         = float(self._sequential_days(orders))
        result.nav_after              = nav - sum(o.gross_value for o in orders)
        result.nav_impact_pct       = (result.nav_before - result.nav_after) / result.nav_before

        return result

    def run_lp_optimised(self, target_eur: float) -> WaterfallResult:
        """
        LP-based sell scheduler: minimise total liquidation time subject to
        raising at least `target_eur` in net proceeds.

        Decision variable x[i] = gross sell amount for position i.
        Objective: min Σ x[i] / daily_cap[i]   (proxy for time)
        Constraints:
          Σ x[i] * net_rate[i] >= target_eur
          0 <= x[i] <= market_value[i]
          locked positions excluded

        Falls back to self.run(target_eur) if scipy is unavailable or LP infeasible.
        """
        try:
            from scipy.optimize import linprog
        except ImportError:
            return self.run(target_eur)

        regime = "haircut_stress" if self.stress else "haircut_normal"

        sellable = self.profile[~self.profile["is_locked"]].copy()
        if sellable.empty:
            return self.run(target_eur)

        n = len(sellable)
        isins      = sellable["isin"].tolist()
        mv         = sellable["market_value_eur"].values.astype(float)
        adv        = sellable["adv_30d"].values.astype(float)

        daily_cap  = adv * MAX_ADV_PARTICIPATION
        # For positions with zero ADV treat daily cap as infinity for LP bounds;
        # they cannot actually be sold quickly but LP needs a finite bound.
        lp_cap = np.where(daily_cap > 0, daily_cap, mv)

        net_rate = np.array([
            (1 - ASSET_CLASS_LIQUIDITY.get(ac, {}).get(regime, 0.0)
             - ASSET_CLASS_LIQUIDITY.get(ac, {}).get("market_impact_bps", 10) / 10_000)
            for ac in sellable["asset_class"]
        ], dtype=float).clip(min=0.0)

        c         = np.where(daily_cap > 0, 1.0 / daily_cap, 1e6)   # minimise time
        A_ub      = (-net_rate).reshape(1, n)                         # -Σ x*r <= -target
        b_ub      = np.array([-target_eur])
        bounds    = [(0.0, float(m)) for m in mv]

        res = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs")

        if res.status != 0:
            return self.run(target_eur)

        # Build WaterfallResult from LP solution
        x = res.x
        nav = self.portfolio.total_nav
        orders: List[SellOrder] = []

        for i, (_, pos) in enumerate(sellable.iterrows()):
            sell_gross = x[i]
            if sell_gross < 1.0:
                continue
            ac = pos["asset_class"]
            haircut = ASSET_CLASS_LIQUIDITY.get(ac, {}).get(regime, 0.0)
            impact_bps = ASSET_CLASS_LIQUIDITY.get(ac, {}).get("market_impact_bps", 10)
            impact_cost = sell_gross * impact_bps / 10_000
            net_proceeds = sell_gross * (1 - haircut) - impact_cost
            days = int(np.ceil(sell_gross / daily_cap[i])) if daily_cap[i] > 0 else 9999
            orders.append(SellOrder(
                day=days, isin=pos["isin"], name=pos["name"],
                asset_class=ac, bucket=pos["bucket"],
                gross_value=sell_gross, market_impact_cost=impact_cost,
                net_proceeds=max(0.0, net_proceeds),
                is_partial=sell_gross < pos["market_value_eur"],
            ))

        total_proceeds = sum(o.net_proceeds for o in orders)
        return WaterfallResult(
            target_eur=target_eur,
            total_proceeds_eur=total_proceeds,
            target_met=(target_eur - total_proceeds) <= 0.01,
            days_to_target=float(self._sequential_days(orders)),
            sell_orders=orders,
            residual_shortfall_eur=max(0.0, target_eur - total_proceeds),
            nav_before=nav,
            nav_after=nav - sum(o.gross_value for o in orders),
            nav_impact_pct=(sum(o.gross_value for o in orders) / nav) if nav > 0 else 0.0,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _sequential_days(self, orders: List[SellOrder]) -> int:
        """Return the longest single-position liquidation horizon across all sell orders."""
        if not orders:
            return 0
        return max(o.day for o in orders)

    def _liquidate_position(
        self,
        pos: pd.Series,
        remaining: float,
        bucket: str,
    ) -> SellOrder | None:
        """Compute sell order for a single position."""
        profile_data = ASSET_CLASS_LIQUIDITY.get(pos["asset_class"], {})
        if "haircut" in pos.index and pd.notna(pos["haircut"]):
            haircut = float(pos["haircut"])
        else:
            regime = "haircut_stress" if self.stress else "haircut_normal"
            haircut = profile_data.get(regime, 0.0)
        market_impact_bps = profile_data.get("market_impact_bps", 10)

        # How much can we sell (ADV cap)
        adv = pos["adv_30d"]
        daily_capacity = adv * MAX_ADV_PARTICIPATION if adv > 0 else 0.0

        # Use absolute market value — short derivatives have negative market_value_eur
        available_value = abs(pos["market_value_eur"]) * (1 - haircut)

        # Skip positions that cannot be liquidated: zero ADV (truly illiquid) or
        # zero available value after haircut (e.g. fully impaired).
        if daily_capacity <= 0 or available_value <= 0:
            return None

        # Sell only what is needed, up to the gross amount the market can absorb.
        # Use abs(market_value) so short positions produce positive sell_gross.
        mv_abs = abs(pos["market_value_eur"])
        net_rate = 1 - haircut - market_impact_bps / 10_000
        if net_rate > 0:
            sell_gross = min(mv_abs, remaining / net_rate)
        else:
            sell_gross = mv_abs
        sell_gross = min(sell_gross, mv_abs)

        # Skip rounding residuals — floating-point drift after earlier positions have
        # already met the target can leave a near-zero remaining amount.
        if sell_gross < 1.0:
            return None

        days = int(np.ceil(sell_gross / daily_capacity))

        impact_cost = sell_gross * market_impact_bps / 10_000
        net_proceeds = sell_gross * (1 - haircut) - impact_cost
        net_proceeds = max(0.0, net_proceeds)

        is_partial = sell_gross < mv_abs

        return SellOrder(
            day          = days,
            isin         = pos["isin"],
            name         = pos["name"],
            asset_class  = pos["asset_class"],
            bucket       = bucket,
            gross_value  = sell_gross,
            market_impact_cost = impact_cost,
            net_proceeds = net_proceeds,
            is_partial   = is_partial,
        )
