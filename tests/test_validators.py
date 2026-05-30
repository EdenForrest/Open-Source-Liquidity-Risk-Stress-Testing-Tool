"""
tests/test_validators.py
Tests for the input validation module.
"""
import pytest
from liquidity_risk_tool.engines.validators import (
    validate_position,
    validate_portfolio,
    ValidationError,
)
from liquidity_risk_tool.models import build_sample_portfolio
from liquidity_risk_tool.models.position import Position


def _make_pos(**overrides) -> Position:
    defaults = dict(
        isin="TEST001", name="Test", asset_class="listed_equity",
        market_value=1_000_000.0, currency="EUR", fx_rate=1.0,
        adv_30d=500_000.0, weight=0.05,
    )
    defaults.update(overrides)
    return Position(**defaults)


class TestValidatePosition:
    def test_valid_position_no_errors(self):
        assert validate_position(_make_pos()) == []

    def test_negative_market_value(self):
        errors = validate_position(_make_pos(market_value=-1))
        assert any("market_value" in e.lower() for e in errors)

    def test_zero_market_value(self):
        errors = validate_position(_make_pos(market_value=0))
        assert any("market_value" in e.lower() for e in errors)

    def test_duration_too_high(self):
        errors = validate_position(_make_pos(duration=35.0))
        assert any("duration" in e.lower() for e in errors)

    def test_duration_negative(self):
        errors = validate_position(_make_pos(duration=-1.0))
        assert any("duration" in e.lower() for e in errors)

    def test_negative_adv(self):
        errors = validate_position(_make_pos(adv_30d=-100))
        assert any("adv" in e.lower() for e in errors)

    def test_credit_spread_too_high(self):
        errors = validate_position(_make_pos(credit_spread_bps=6000))
        assert any("credit_spread" in e.lower() for e in errors)

    def test_beta_too_high(self):
        errors = validate_position(_make_pos(beta=5.0))
        assert any("beta" in e.lower() for e in errors)

    def test_negative_beta(self):
        errors = validate_position(_make_pos(beta=-0.5))
        assert any("beta" in e.lower() for e in errors)

    def test_negative_convexity(self):
        errors = validate_position(_make_pos(convexity=-1.0))
        assert any("convexity" in e.lower() for e in errors)

    def test_negative_fx_rate(self):
        errors = validate_position(_make_pos(fx_rate=-1.0))
        assert any("fx_rate" in e.lower() for e in errors)

    def test_negative_settlement_days(self):
        errors = validate_position(_make_pos(settlement_days=-1))
        assert any("settlement_days" in e.lower() for e in errors)

    def test_valid_settlement_days(self):
        assert validate_position(_make_pos(settlement_days=2)) == []

    def test_valid_bond_position(self):
        pos = _make_pos(asset_class="ig_corporate_bond", duration=4.5,
                        credit_spread_bps=120, convexity=0.5)
        assert validate_position(pos) == []


class TestValidatePortfolio:
    def test_sample_portfolio_passes(self):
        port = build_sample_portfolio()
        errors = validate_portfolio(port, strict=False)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_strict_raises_on_error(self):
        port = build_sample_portfolio()
        # Corrupt one position
        port.positions[0].market_value = -1
        with pytest.raises(ValidationError):
            validate_portfolio(port, strict=True)

    def test_non_strict_returns_list(self):
        port = build_sample_portfolio()
        port.positions[0].market_value = -1
        errors = validate_portfolio(port, strict=False)
        assert len(errors) >= 1

    def test_empty_positions_passes(self):
        port = build_sample_portfolio()
        port.positions = []
        errors = validate_portfolio(port, strict=False)
        assert errors == []

    def test_invalid_redemption_frequency(self):
        port = build_sample_portfolio()
        port.share_classes[0].redemption_frequency = "hourly"
        errors = validate_portfolio(port, strict=False)
        assert any("redemption_frequency" in e for e in errors)

    def test_valid_redemption_frequency(self):
        port = build_sample_portfolio()
        port.share_classes[0].redemption_frequency = "weekly"
        errors = validate_portfolio(port, strict=False)
        assert errors == []
