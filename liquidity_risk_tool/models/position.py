"""
Core domain model: Position and Portfolio.

A Position represents a single holding; Portfolio aggregates them with
fund-level metadata (NAV, share class details, investor base).
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
import numpy as np


@dataclass
class Position:
    """Single portfolio holding."""
    isin: str
    name: str
    asset_class: str          # key into ASSET_CLASS_LIQUIDITY
    market_value: float       # base currency (EUR), already converted by source system
    weight: float             # fraction of NAV (derived, not input)
    currency: str = "EUR"     # local denomination of the position
    fx_rate: float = 1.0      # FX rate used by source system (informational only)

    # Market microstructure
    adv_30d: float = 0.0      # 30-day average daily volume in EUR
    bid_ask_spread_bps: float = 5.0

    # Override bucket (if None, derived from asset_class)
    liquidity_bucket_override: Optional[str] = None

    # Credit data (bonds)
    duration: Optional[float] = None   # modified duration (years)
    credit_spread_bps: Optional[float] = None
    rating: Optional[str] = None

    # Equity data
    beta: Optional[float] = None       # market beta

    # Encumbrance / lock-up
    is_locked: bool = False
    lock_expiry_days: Optional[int] = None  # days until lock expires

    # Bond price sensitivity
    convexity: Optional[float] = None      # explicit convexity; None → derived from duration
    settlement_days: Optional[int] = None  # actual settlement lag in calendar days
    is_government: bool = False            # True = pure gov bond (rate shock only, no credit spread)

    @property
    def effective_convexity(self) -> float:
        if self.convexity is not None:
            return self.convexity
        if self.duration is not None:
            return (self.duration ** 2) / 2.0
        return 0.0

    @property
    def market_value_eur(self) -> float:
        return self.market_value

    def days_to_liquidate(self, adv_participation: float = 0.20) -> float:
        """Estimate calendar days to fully liquidate using ADV constraint."""
        if self.adv_30d <= 0:
            return float("inf")
        daily_capacity = self.adv_30d * adv_participation
        trading_days = self.market_value_eur / daily_capacity
        if self.is_locked:
            lock_delay = self.lock_expiry_days if self.lock_expiry_days is not None else float("inf")
            return lock_delay + trading_days
        return trading_days


@dataclass
class ShareClass:
    name: str
    nav_per_share: float
    shares_outstanding: float
    notice_period_days: int = 0   # redemption notice period
    redemption_frequency: str = "daily"  # daily, weekly, monthly

    def __post_init__(self):
        if self.nav_per_share <= 0:
            raise ValueError(
                f"ShareClass '{self.name}': nav_per_share must be positive, "
                f"got {self.nav_per_share}"
            )
        if self.shares_outstanding < 0:
            raise ValueError(
                f"ShareClass '{self.name}': shares_outstanding cannot be negative, "
                f"got {self.shares_outstanding}"
            )

    @property
    def total_nav(self) -> float:
        return self.nav_per_share * self.shares_outstanding


@dataclass
class Portfolio:
    """Fund-level container."""
    fund_name: str
    fund_id: str
    reporting_date: pd.Timestamp
    share_classes: list[ShareClass]
    positions: list[Position]
    base_currency: str = "EUR"

    # Investor concentration (top-10 % of AUM)
    top_10_investor_concentration: float = 0.40

    def __post_init__(self):
        self._positions_df_cache: Optional[pd.DataFrame] = None
        self._refresh_weights()
        self._check_nav_drift()

    def _refresh_weights(self):
        self._positions_df_cache = None
        total = self.total_nav
        for pos in self.positions:
            pos.weight = pos.market_value_eur / total if total > 0 else 0.0

    def _check_nav_drift(self):
        """Warn when sum of position market values deviates >5% from share-class NAV."""
        if not self.share_classes or not self.positions:
            return
        sc_nav = sum(sc.total_nav for sc in self.share_classes)
        pos_sum = sum(p.market_value_eur for p in self.positions)
        if sc_nav <= 0 or pos_sum <= 0:
            return
        drift = abs(pos_sum - sc_nav) / sc_nav
        if drift > 0.05:
            warnings.warn(
                f"Portfolio '{self.fund_name}': position sum "
                f"({pos_sum:,.0f}) differs from share-class NAV "
                f"({sc_nav:,.0f}) by {drift*100:.1f}% — "
                f"possible missing positions or stale NAV.",
                UserWarning,
                stacklevel=2,
            )

    @property
    def total_nav(self) -> float:
        if self.share_classes:
            return sum(sc.total_nav for sc in self.share_classes)
        return sum(p.market_value_eur for p in self.positions)

    @property
    def positions_df(self) -> pd.DataFrame:
        """Flat DataFrame view of all positions (cached until weights refresh)."""
        if self._positions_df_cache is not None:
            return self._positions_df_cache
        rows = []
        for p in self.positions:
            rows.append({
                "isin":               p.isin,
                "name":               p.name,
                "asset_class":        p.asset_class,
                "market_value_eur":   p.market_value_eur,
                "weight":             p.weight,
                "currency":           p.currency,
                "adv_30d":            p.adv_30d,
                "bid_ask_spread_bps": p.bid_ask_spread_bps,
                "duration":           p.duration,
                "credit_spread_bps":  p.credit_spread_bps,
                "rating":             p.rating,
                "beta":               p.beta,
                "fx_rate":            p.fx_rate,
                "is_locked":          p.is_locked,
                "lock_expiry_days":   p.lock_expiry_days,
                "bucket_override":    p.liquidity_bucket_override,
                "convexity":          p.convexity,
                "effective_convexity": p.effective_convexity,
                "settlement_days":    p.settlement_days,
                "is_government":      p.is_government,
            })
        self._positions_df_cache = pd.DataFrame(rows)
        return self._positions_df_cache
