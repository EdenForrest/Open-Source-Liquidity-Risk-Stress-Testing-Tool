"""Shared utilities for liquidity engine calculations."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config.settings import BUCKET_ORDER, LIQUIDITY_BUCKETS, MAX_ADV_PARTICIPATION


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Divide with zero-safety."""
    return numerator / denominator if denominator > 0 else default


def liquidity_at_horizon(profile: pd.DataFrame, days: int) -> float:
    """Sum realisable_value for all buckets whose settlement day <= days."""
    total = 0.0
    for bucket in BUCKET_ORDER:
        _, hi = LIQUIDITY_BUCKETS[bucket]
        if hi <= days:
            total += profile[profile["bucket"] == bucket]["realisable_value"].sum()
    return total


def realisable_value(market_value: pd.Series, haircut: pd.Series) -> pd.Series:
    """Realisable value net of haircut: market_value - |market_value| * haircut.

    Deliberately NOT market_value * (1 - haircut): a haircut is a realisation
    COST, so it must reduce what a long position fetches AND increase what
    closing a short/overdraft (negative market_value) costs. mv * (1 - h) on
    a negative mv would shrink the liability and overstate liquidity;
    mv - |mv| * h is conservative for both signs.
    """
    return market_value - market_value.abs() * haircut


def realisable_value_np(market_value: np.ndarray, haircut: np.ndarray) -> np.ndarray:
    """NumPy-array twin of :func:`realisable_value`.

    Used on hot paths (stress engine reverse-stress search) where pandas
    Series construction/alignment overhead is measurable across hundreds of
    repricings per search. Numerically identical to the pandas version.
    """
    return market_value - np.abs(market_value) * haircut


def adv_capped_days(
    market_value_eur: pd.Series,
    adv_30d: pd.Series,
    settled: pd.Series,
    adv_stress_scalar: float = 1.0,
) -> np.ndarray:
    """Days needed to fully exit each position under an ADV-participation cap.

    effective_adv = adv_30d * adv_stress_scalar
    daily_capacity = effective_adv * MAX_ADV_PARTICIPATION
    days = 0 for settled (cash-like, T+0-regardless-of-volume) positions;
           ceil(|market_value_eur| / daily_capacity) if daily_capacity > 0;
           inf otherwise (zero-ADV, non-cash-like positions).

    abs() so short positions (negative market value) are timed by how long it
    takes to buy them back, not treated as instantly liquid.

    This is the single formula shared by LiquidityProfiler._assign_buckets
    (transient bucket-assignment days) and LiquidityProfiler._apply_adv_cap
    (persisted days_to_liquidate column) — both call sites were byte-identical
    duplicates of this computation.
    """
    effective_adv = adv_30d * adv_stress_scalar
    daily_capacity = effective_adv * MAX_ADV_PARTICIPATION
    return np.where(
        settled,
        0.0,
        np.where(
            daily_capacity > 0,
            np.ceil(market_value_eur.abs() / daily_capacity.replace(0, np.nan)),
            np.inf,
        ),
    )


def days_to_liquidate_pct(profile: pd.DataFrame, target_pct: float, nav: float) -> float:
    """Greedy simulation: sell positions in ADV-capped daily tranches.

    Returns the first day by which cumulative proceeds >= target_pct * nav.
    Returns float('inf') only when zero sellable positions exist; otherwise
    returns the maximum days required across all sellable positions even if
    the liquid portion cannot fully cover the target (illiquid tail).

    Sellable positions are sorted by their precomputed `days_to_liquidate`
    column, but the per-position day figure used for accumulation is
    recomputed inline here as market_value_eur / (adv_30d * MAX_ADV_PARTICIPATION)
    — deliberately simpler than the adv_capped_days formula: no
    adv_stress_scalar and no settled-not-traded floor-to-zero. This mirrors
    the original risk_metrics.py behaviour exactly and must not be "fixed"
    to match adv_capped_days.
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
