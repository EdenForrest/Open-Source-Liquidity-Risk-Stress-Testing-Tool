"""
Geographical concentration evaluation (AIFMD Annex IV / ESMA34-39-897 §4.2).
"""
from __future__ import annotations

import pandas as pd

from ..config.settings import (
    EU_COUNTRIES,
    GEO_CONCENTRATION_BREACH_NON_EU,
    GEO_CONCENTRATION_WARNING_SINGLE,
)


def evaluate_geo_concentration(position_buckets: pd.DataFrame, nav: float) -> dict:
    """
    Country-exposure concentration flags for a profiled position DataFrame.

    ``position_buckets`` needs ``country`` and ``market_value_eur`` columns;
    ``nav`` is the total market value the weights are expressed against.
    Returns an empty dict when there is no country data or NAV is non-positive.
    """
    if "country" not in position_buckets.columns:
        return {}
    geo_df = position_buckets.dropna(subset=["country"])
    if geo_df.empty or nav <= 0:
        return {}

    geo_groups = geo_df.groupby("country")["market_value_eur"].sum() / nav
    top_countries = geo_groups.sort_values(ascending=False).head(10).to_dict()
    non_eu_pct = float(geo_groups[~geo_groups.index.isin(EU_COUNTRIES)].sum())
    max_single = float(geo_groups.max())
    geo_top_country = str(geo_groups.idxmax())
    return {
        "top_countries":      top_countries,
        "eu_pct":             1.0 - non_eu_pct,
        "non_eu_pct":         non_eu_pct,
        "geo_top_country":    geo_top_country,
        "geo_top_country_pct": max_single,
        "geo_warning_flag":   max_single > GEO_CONCENTRATION_WARNING_SINGLE,
        "geo_breach_flag":    non_eu_pct > GEO_CONCENTRATION_BREACH_NON_EU,
    }
