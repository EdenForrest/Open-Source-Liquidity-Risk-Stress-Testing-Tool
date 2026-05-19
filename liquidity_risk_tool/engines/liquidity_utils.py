"""Shared utilities for liquidity engine calculations."""
from __future__ import annotations

import pandas as pd

from ..config.settings import BUCKET_ORDER, LIQUIDITY_BUCKETS


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Divide with zero-safety."""
    return numerator / denominator if denominator > 0 else default


def liquidity_at_horizon(profile: pd.DataFrame, days: int) -> float:
    """Sum realisable_value for all buckets whose settlement day <= days."""
    total = 0.0
    for bucket in BUCKET_ORDER:
        lo, _ = LIQUIDITY_BUCKETS[bucket]
        if lo <= days:
            total += profile[profile["bucket"] == bucket]["realisable_value"].sum()
    return total
