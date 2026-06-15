"""
Input validation for Position and Portfolio objects.
Runs lightweight domain-constraint checks before any analysis.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, List

from ..config.settings import (
    CREDIT_SPREAD_BPS_RANGE,
    EQUITY_BETA_RANGE,
    REDEMPTION_FREQUENCIES,
    SHORTABLE_ASSET_CLASSES,
)

if TYPE_CHECKING:
    from ..models.position import Position, Portfolio


class ValidationError(ValueError):
    pass


def _is_bad(value: float) -> bool:
    """True for NaN/inf — values that silently pass naive range comparisons."""
    return not math.isfinite(value)


def validate_position(pos: "Position") -> List[str]:
    """Return a list of error strings for a single position. Empty = valid."""
    errors: List[str] = []

    mv = pos.market_value_eur
    if _is_bad(mv):
        errors.append(f"{pos.isin}: market_value_eur must be finite (got {mv})")
    elif mv == 0:
        errors.append(f"{pos.isin}: market_value_eur must be non-zero (got {mv})")
    elif mv < 0:
        # Negative MV is legitimate only for short derivatives / overdrawn cash
        # (the CSV loader preserves the sign) or when an explicit economic
        # exposure base is supplied.
        if pos.asset_class not in SHORTABLE_ASSET_CLASSES and pos.exposure_base is None:
            errors.append(
                f"{pos.isin}: market_value_eur must be > 0 for asset_class "
                f"'{pos.asset_class}' (got {mv}; negative values are only allowed "
                f"for {sorted(SHORTABLE_ASSET_CLASSES)} or positions with exposure_base)"
            )

    if pos.duration is not None:
        if _is_bad(pos.duration) or not (0 <= pos.duration <= 30):
            errors.append(f"{pos.isin}: duration {pos.duration} out of range [0, 30]")

    if _is_bad(pos.adv_30d) or pos.adv_30d < 0:
        errors.append(f"{pos.isin}: adv_30d must be a finite value >= 0 (got {pos.adv_30d})")

    if _is_bad(pos.bid_ask_spread_bps) or pos.bid_ask_spread_bps < 0:
        errors.append(
            f"{pos.isin}: bid_ask_spread_bps must be a finite value >= 0 "
            f"(got {pos.bid_ask_spread_bps})"
        )

    if pos.credit_spread_bps is not None:
        lo, hi = CREDIT_SPREAD_BPS_RANGE
        if _is_bad(pos.credit_spread_bps) or not (lo <= pos.credit_spread_bps <= hi):
            errors.append(f"{pos.isin}: credit_spread_bps {pos.credit_spread_bps} out of range {CREDIT_SPREAD_BPS_RANGE}")

    if pos.beta is not None:
        lo, hi = EQUITY_BETA_RANGE
        if _is_bad(pos.beta) or not (lo <= pos.beta <= hi):
            errors.append(f"{pos.isin}: beta {pos.beta} out of range {EQUITY_BETA_RANGE}")

    if pos.convexity is not None and (_is_bad(pos.convexity) or pos.convexity < 0):
        errors.append(f"{pos.isin}: convexity {pos.convexity} must be finite and >= 0")

    if _is_bad(pos.fx_rate) or pos.fx_rate <= 0:
        errors.append(f"{pos.isin}: fx_rate must be a finite value > 0 (got {pos.fx_rate})")

    if pos.settlement_days is not None and pos.settlement_days < 0:
        errors.append(f"{pos.isin}: settlement_days must be >= 0 (got {pos.settlement_days})")

    if pos.is_locked and pos.lock_expiry_days is not None and pos.lock_expiry_days < 0:
        errors.append(
            f"{pos.isin}: lock_expiry_days must be >= 0 for a locked position "
            f"(got {pos.lock_expiry_days})"
        )

    if pos.exposure_base is not None and _is_bad(pos.exposure_base):
        errors.append(f"{pos.isin}: exposure_base must be finite (got {pos.exposure_base})")

    return errors


def validate_portfolio(portfolio: "Portfolio", strict: bool = True) -> List[str]:
    """
    Validate all positions in the portfolio.
    If strict=True, raises ValidationError on any failure.
    Returns list of all error strings.
    """
    all_errors: List[str] = []
    seen_isins: set = set()
    for pos in portfolio.positions:
        all_errors.extend(validate_position(pos))
        if pos.isin:
            if pos.isin in seen_isins:
                all_errors.append(
                    f"{pos.isin}: duplicate isin — position appears more than once"
                )
            seen_isins.add(pos.isin)

    for sc in getattr(portfolio, "share_classes", []) or []:
        freq = getattr(sc, "redemption_frequency", None)
        if freq is not None and freq not in REDEMPTION_FREQUENCIES:
            all_errors.append(
                f"ShareClass '{getattr(sc, 'name', '?')}': redemption_frequency "
                f"'{freq}' not in {REDEMPTION_FREQUENCIES}"
            )
        notice = getattr(sc, "notice_period_days", 0)
        if notice is not None and notice < 0:
            all_errors.append(
                f"ShareClass '{getattr(sc, 'name', '?')}': notice_period_days "
                f"must be >= 0 (got {notice})"
            )

    if strict and all_errors:
        raise ValidationError(
            f"Portfolio validation failed with {len(all_errors)} error(s):\n"
            + "\n".join(f"  - {e}" for e in all_errors)
        )
    return all_errors
