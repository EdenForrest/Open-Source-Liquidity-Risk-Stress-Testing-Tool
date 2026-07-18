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
    MAX_HAIRCUT,
    LIQUIDITY_WARNING_THRESHOLD,
    LIQUIDITY_BREACH_THRESHOLD,
    GEO_CONCENTRATION_WARNING_SINGLE,
    GEO_CONCENTRATION_BREACH_NON_EU,
    EU_COUNTRIES,
    UCITS_SINGLE_ISSUER_LIMIT,
    UCITS_AGGREGATE_BUCKET_LIMIT,
    UCITS_AGGREGATE_BUCKET_SINGLE_CAP,
)
from ..models.position import Portfolio
from .liquidity_utils import safe_divide


_BUCKET_RANK = {"T+0": 0, "T+1": 1, "T+3": 2, "T+7": 3, ">T+7": 4}


def _is_settled_not_traded(asset_class: str) -> bool:
    """True for assets that are *not* liquidated by trading volume and so are
    immune to ADV-participation caps — i.e. they settle same-day (T+0) by their
    asset-class profile. Cash is the canonical case: it is already money, it does
    not have to be *sold* into a market, so an ADV of 0 means "does not trade",
    NOT "cannot be liquidated".

    Without this carve-out, cash (adv_30d == 0) would get days_to_liquidate = inf
    and be bucketed >T+7, making even a cash-rich fund appear unable to meet
    redemptions under stress — a false breach.
    """
    profile = ASSET_CLASS_LIQUIDITY.get(asset_class, {})
    return profile.get("bucket") == "T+0"


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
        if self._nav <= 0:
            return 0.0
        covered = []
        for _, row in ladder.iterrows():
            _, hi = LIQUIDITY_BUCKETS[row["bucket"]]
            if hi <= days:
                # Realisable (post-haircut) value, not raw market value — this
                # feeds coverage ratios, which must be net of liquidation costs.
                covered.append(row["realisable_value_eur"] / self._nav)
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

        # Geographical concentration (AIFMD Annex IV / ESMA34-39-897 Section 4.2)
        if "country" in self._result.columns:
            geo_df = self._result.dropna(subset=["country"])
            if not geo_df.empty:
                total_nav = self._result["market_value_eur"].sum()
                if total_nav > 0:
                    geo_groups = geo_df.groupby("country")["market_value_eur"].sum() / total_nav
                    top_countries = geo_groups.sort_values(ascending=False).head(10).to_dict()
                    non_eu_pct = float(geo_groups[~geo_groups.index.isin(EU_COUNTRIES)].sum())
                    max_single = float(geo_groups.max())
                    geo_top_country = str(geo_groups.idxmax())
                    flags.update({
                        "top_countries":      top_countries,
                        "eu_pct":             1.0 - non_eu_pct,
                        "non_eu_pct":         non_eu_pct,
                        "geo_top_country":    geo_top_country,
                        "geo_top_country_pct": max_single,
                        "geo_warning_flag":   max_single > GEO_CONCENTRATION_WARNING_SINGLE,
                        "geo_breach_flag":    non_eu_pct > GEO_CONCENTRATION_BREACH_NON_EU,
                    })

        # UCITS 5/10/40 issuer concentration rule (Art. 52 UCITS Directive)
        # Cash positions (ISIN starting with "CASH") are excluded — cash is not
        # a transferable security and falls outside the Art. 52 issuer limits.
        total_nav = self._result["market_value_eur"].sum()
        if total_nav > 0:
            non_cash = self._result[~self._result["isin"].str.startswith("CASH", na=False)]
            issuer_weights = (
                non_cash.groupby("isin")["market_value_eur"].sum() / total_nav
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

            flags.update({
                "ucits_issuer_weights":       top_issuers,
                "ucits_breaching_issuers":    breaching.to_dict(),
                "ucits_aggregate_5_10":       aggregate_5_10,
                "ucits_single_breach":        bool(len(breaching) > 0),
                "ucits_aggregate_breach":     aggregate_5_10 > UCITS_AGGREGATE_BUCKET_LIMIT,
                "ucits_compliant":            len(breaching) == 0 and aggregate_5_10 <= UCITS_AGGREGATE_BUCKET_LIMIT,
            })

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
        if df.empty:
            # df.apply(..., axis=1) on an empty frame returns an empty DataFrame
            # rather than a Series, so the bucket assignment below would break.
            df["bucket"] = pd.Series(dtype=object)
            return df

        effective_adv = df["adv_30d"] * self.adv_stress_scalar
        daily_capacity = effective_adv * MAX_ADV_PARTICIPATION
        # Cash-like positions settle same-day regardless of trading volume, so the
        # ADV-implied bucket must not drag them below T+0 (see _is_settled_not_traded).
        settled = df["asset_class"].map(_is_settled_not_traded)
        # abs() so short positions (negative MV) are bucketed by the time it
        # takes to buy them back, not treated as instantly liquid.
        days_to_liq = np.where(
            settled,
            0.0,
            np.where(
                daily_capacity > 0,
                np.ceil(df["market_value_eur"].abs() / daily_capacity.replace(0, np.nan)),
                np.inf,
            ),
        )
        # Vectorised bucketing — equivalent to the previous row-wise get_bucket,
        # but expressed as column ops so it runs once over the frame rather than
        # once per row (this method is on the reverse-stress hot path).
        #
        # ADV-implied bucket from days_to_liq: thresholds 0 / 1 / 3 / 7.
        adv_bucket = np.select(
            [days_to_liq <= 0, days_to_liq <= 1, days_to_liq <= 3, days_to_liq <= 7],
            ["T+0", "T+1", "T+3", "T+7"],
            default=">T+7",
        )
        # Asset-class settlement bucket: pure dict lookup per class.
        asset_bucket = df["asset_class"].map(
            lambda ac: ASSET_CLASS_LIQUIDITY.get(ac, {}).get("bucket", ">T+7")
        ).to_numpy()
        # Take the worse (less liquid) of the asset and ADV buckets by rank.
        rank = np.vectorize(_BUCKET_RANK.get)
        worst = np.where(rank(adv_bucket) > rank(asset_bucket), adv_bucket, asset_bucket)

        # Precedence: locked → >T+7; else a valid override wins; else the worst bucket.
        override = df["bucket_override"]
        has_override = override.notna().to_numpy() & override.astype(bool).to_numpy()
        bucket = np.where(
            df["is_locked"].to_numpy(),
            ">T+7",
            np.where(has_override, override.to_numpy(), worst),
        )
        df["bucket"] = bucket
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

        if df.empty:
            # Same empty-frame apply() pitfall as in _assign_buckets.
            df["haircut"] = pd.Series(dtype=float)
            df["realisable_value"] = pd.Series(dtype=float)
            df["realisable_weight"] = pd.Series(dtype=float)
            return df

        # Vectorised: the per-asset-class base haircut is a pure dict lookup, so
        # map the column instead of looping rows. Half-spread cost is arithmetic.
        # (Equivalent to the previous df.apply(total_haircut, axis=1).)
        base_haircut = df["asset_class"].map(
            lambda ac: ASSET_CLASS_LIQUIDITY.get(ac, {}).get(regime, 0.0)
        )
        spread_cost = df["bid_ask_spread_bps"] / 2.0 / 10_000
        df["haircut"] = (base_haircut + spread_cost).clip(lower=0.0, upper=MAX_HAIRCUT)
        # Haircut is a realisation COST: it reduces what a long position fetches
        # AND increases what closing a short/overdraft (negative MV) costs.
        # mv * (1 - h) on a negative MV would shrink the liability and overstate
        # liquidity; mv - |mv|*h is conservative for both signs.
        df["realisable_value"] = (
            df["market_value_eur"] - df["market_value_eur"].abs() * df["haircut"]
        )
        df["realisable_weight"] = safe_divide(df["realisable_value"], nav)
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
        # Cash-like, settled-not-traded positions are never ADV-capped: they do
        # not have to be sold into a market, so adv_30d == 0 must NOT mean
        # "cannot liquidate". They are fully realisable same-day.
        settled = df["asset_class"].map(_is_settled_not_traded)
        # Days needed to fully exit the position (0 for cash-like positions).
        # abs() so short positions get a meaningful horizon: closing a short
        # means buying back through the same ADV-capped market.
        df["days_to_liquidate"] = np.where(
            settled,
            0.0,
            np.where(
                daily_capacity > 0,
                np.ceil(df["market_value_eur"].abs() / daily_capacity.replace(0, np.nan)),
                np.inf,
            ),
        )
        # adv_capped flags positions where the cap BINDS: the ADV-implied exit
        # horizon exceeds the asset class's own settlement bucket, i.e. the
        # participation cap — not settlement mechanics — is what slows the
        # exit. Zero-ADV non-cash positions (days = inf) are capped by
        # definition; positions that clear within their settlement window are
        # not, even though a cap nominally exists.
        def _asset_bucket_horizon(ac: str) -> float:
            bucket = ASSET_CLASS_LIQUIDITY.get(ac, {}).get("bucket", ">T+7")
            return float(LIQUIDITY_BUCKETS[bucket][1])

        horizon = df["asset_class"].map(_asset_bucket_horizon)
        df["adv_capped"] = ~settled & (df["days_to_liquidate"] > horizon)
        return df

    def _flag_concentration(self, df: pd.DataFrame, nav: float) -> pd.DataFrame:
        df["concentration_flag"] = df["weight"] > CONCENTRATION_FLAG_THRESHOLD
        return df

    def _check_ran(self):
        if self._result is None:
            raise RuntimeError("Call .run() before accessing results.")
