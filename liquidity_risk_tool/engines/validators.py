"""
Input validation for Position and Portfolio objects.
Runs lightweight domain-constraint checks before any analysis.
"""
from __future__ import annotations
from typing import TYPE_CHECKING, List

from ..config.settings import (
    CREDIT_SPREAD_BPS_RANGE,
    EQUITY_BETA_RANGE,
    REDEMPTION_FREQUENCIES,
)

if TYPE_CHECKING:
    from ..models.position import Position, Portfolio


class ValidationError(ValueError):
    pass


def validate_position(pos: "Position") -> List[str]:
    """Return a list of error strings for a single position. Empty = valid."""
    errors: List[str] = []

    if pos.market_value_eur <= 0:
        errors.append(f"{pos.isin}: market_value_eur must be > 0 (got {pos.market_value_eur})")

    if pos.duration is not None:
        if not (0 <= pos.duration <= 30):
            errors.append(f"{pos.isin}: duration {pos.duration} out of range [0, 30]")

    if not pos.is_locked and pos.adv_30d < 0:
        errors.append(f"{pos.isin}: adv_30d must be >= 0 (got {pos.adv_30d})")

    if pos.credit_spread_bps is not None:
        lo, hi = CREDIT_SPREAD_BPS_RANGE
        if not (lo <= pos.credit_spread_bps <= hi):
            errors.append(f"{pos.isin}: credit_spread_bps {pos.credit_spread_bps} out of range {CREDIT_SPREAD_BPS_RANGE}")

    if pos.beta is not None:
        lo, hi = EQUITY_BETA_RANGE
        if not (lo <= pos.beta <= hi):
            errors.append(f"{pos.isin}: beta {pos.beta} out of range {EQUITY_BETA_RANGE}")

    if pos.convexity is not None and pos.convexity < 0:
        errors.append(f"{pos.isin}: convexity {pos.convexity} must be >= 0")

    if pos.fx_rate <= 0:
        errors.append(f"{pos.isin}: fx_rate must be > 0 (got {pos.fx_rate})")

    if pos.settlement_days is not None and pos.settlement_days < 0:
        errors.append(f"{pos.isin}: settlement_days must be >= 0 (got {pos.settlement_days})")

    return errors


def validate_portfolio(portfolio: "Portfolio", strict: bool = True) -> List[str]:
    """
    Validate all positions in the portfolio.
    If strict=True, raises ValidationError on any failure.
    Returns list of all error strings.
    """
    all_errors: List[str] = []
    for pos in portfolio.positions:
        all_errors.extend(validate_position(pos))

    for sc in getattr(portfolio, "share_classes", []) or []:
        freq = getattr(sc, "redemption_frequency", None)
        if freq is not None and freq not in REDEMPTION_FREQUENCIES:
            all_errors.append(
                f"ShareClass '{getattr(sc, 'name', '?')}': redemption_frequency "
                f"'{freq}' not in {REDEMPTION_FREQUENCIES}"
            )

    if strict and all_errors:
        raise ValidationError(
            f"Portfolio validation failed with {len(all_errors)} error(s):\n"
            + "\n".join(f"  - {e}" for e in all_errors)
        )
    return all_errors
