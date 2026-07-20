"""
UCITS 5/10/40 issuer concentration rule (Art. 52 UCITS Directive).
"""
from __future__ import annotations

import pandas as pd

from ..config.settings import (
    UCITS_AGGREGATE_BUCKET_LIMIT,
    UCITS_AGGREGATE_BUCKET_SINGLE_CAP,
    UCITS_SINGLE_ISSUER_LIMIT,
)


def evaluate_ucits_5_10_40(position_buckets: pd.DataFrame, nav: float) -> dict:
    """
    Issuer-concentration flags for a profiled position DataFrame.

    Cash positions (ISIN starting with "CASH") are excluded — cash is not
    a transferable security and falls outside the Art. 52 issuer limits.
    Returns an empty dict when NAV is non-positive.
    """
    if nav <= 0:
        return {}

    non_cash = position_buckets[~position_buckets["isin"].str.startswith("CASH", na=False)]
    issuer_weights = (
        non_cash.groupby("isin")["market_value_eur"].sum() / nav
    ).sort_values(ascending=False)

    # Hard breach is >10% (the single-issuer cap); 5-10% holdings are
    # permitted under Art. 52 subject to the 40% aggregate limit.
    breaching = issuer_weights[issuer_weights > UCITS_AGGREGATE_BUCKET_SINGLE_CAP]
    bucket_5_10 = issuer_weights[
        (issuer_weights > UCITS_SINGLE_ISSUER_LIMIT) &
        (issuer_weights <= UCITS_AGGREGATE_BUCKET_SINGLE_CAP)
    ]
    aggregate_5_10 = float(bucket_5_10.sum())
    top_issuers = issuer_weights.head(10).to_dict()

    return {
        "ucits_issuer_weights":       top_issuers,
        "ucits_breaching_issuers":    breaching.to_dict(),
        "ucits_aggregate_5_10":       aggregate_5_10,
        "ucits_single_breach":        bool(len(breaching) > 0),
        "ucits_aggregate_breach":     aggregate_5_10 > UCITS_AGGREGATE_BUCKET_LIMIT,
        "ucits_compliant":            len(breaching) == 0 and aggregate_5_10 <= UCITS_AGGREGATE_BUCKET_LIMIT,
    }
