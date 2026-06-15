"""
tests/test_models.py
Robustness tests for the core domain models (Position, ShareClass, Portfolio),
the European-format CSV parsing helpers, and the NaN-aware validators.
"""
import math

import pandas as pd
import pytest

from liquidity_risk_tool.engines.validators import (
    ValidationError,
    validate_portfolio,
    validate_position,
)
from liquidity_risk_tool.models import build_sample_portfolio
from liquidity_risk_tool.models.csv_loader import _eu_float, load_portfolio_from_csv
from liquidity_risk_tool.models.position import Portfolio, Position, ShareClass


def _make_pos(**overrides) -> Position:
    defaults = dict(
        isin="TEST001", name="Test", asset_class="listed_equity",
        market_value=1_000_000.0, currency="EUR", fx_rate=1.0,
        adv_30d=500_000.0, weight=0.05,
    )
    defaults.update(overrides)
    return Position(**defaults)


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

class TestPositionNormalisation:
    def test_identifiers_stripped(self):
        pos = _make_pos(isin="  DE0001  ", name=" Bond ", asset_class=" cash ")
        assert pos.isin == "DE0001"
        assert pos.name == "Bond"
        assert pos.asset_class == "cash"

    def test_currency_uppercased(self):
        assert _make_pos(currency=" eur ").currency == "EUR"

    def test_none_currency_defaults_to_eur(self):
        assert _make_pos(currency=None).currency == "EUR"


class TestDaysToLiquidate:
    def test_zero_adv_is_infinite(self):
        assert _make_pos(adv_30d=0.0).days_to_liquidate() == float("inf")

    def test_nan_adv_is_infinite(self):
        assert _make_pos(adv_30d=float("nan")).days_to_liquidate() == float("inf")

    def test_short_position_uses_absolute_value(self):
        long_pos = _make_pos(market_value=1_000_000)
        short_pos = _make_pos(asset_class="future", market_value=-1_000_000)
        days = short_pos.days_to_liquidate()
        assert days == long_pos.days_to_liquidate()
        assert days > 0

    def test_invalid_participation_raises(self):
        with pytest.raises(ValueError):
            _make_pos().days_to_liquidate(adv_participation=0)
        with pytest.raises(ValueError):
            _make_pos().days_to_liquidate(adv_participation=-0.1)

    def test_lock_delay_added(self):
        base = _make_pos().days_to_liquidate()
        locked = _make_pos(is_locked=True, lock_expiry_days=30)
        assert locked.days_to_liquidate() == pytest.approx(base + 30)

    def test_locked_without_expiry_is_infinite(self):
        pos = _make_pos(is_locked=True, lock_expiry_days=None)
        assert pos.days_to_liquidate() == float("inf")


# ---------------------------------------------------------------------------
# ShareClass
# ---------------------------------------------------------------------------

class TestShareClass:
    def test_valid(self):
        sc = ShareClass("A", nav_per_share=100.0, shares_outstanding=1_000.0)
        assert sc.total_nav == 100_000.0

    @pytest.mark.parametrize("bad_nav", [0.0, -1.0, float("nan"), float("inf")])
    def test_bad_nav_per_share_raises(self, bad_nav):
        with pytest.raises(ValueError):
            ShareClass("A", nav_per_share=bad_nav, shares_outstanding=1_000.0)

    @pytest.mark.parametrize("bad_shares", [-1.0, float("nan"), float("inf")])
    def test_bad_shares_outstanding_raises(self, bad_shares):
        with pytest.raises(ValueError):
            ShareClass("A", nav_per_share=100.0, shares_outstanding=bad_shares)

    def test_negative_notice_period_raises(self):
        with pytest.raises(ValueError):
            ShareClass("A", nav_per_share=100.0, shares_outstanding=1_000.0,
                       notice_period_days=-5)


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

def _make_portfolio(**overrides) -> Portfolio:
    defaults = dict(
        fund_name="Test Fund",
        fund_id="TEST",
        reporting_date=pd.Timestamp("2026-06-12"),
        share_classes=[ShareClass("A", 100.0, 10_000.0)],
        positions=[_make_pos()],
        top_10_investor_concentration=0.40,
    )
    defaults.update(overrides)
    return Portfolio(**defaults)


class TestPortfolio:
    def test_reporting_date_string_coerced(self):
        port = _make_portfolio(reporting_date="2026-06-12")
        assert isinstance(port.reporting_date, pd.Timestamp)
        assert port.reporting_date == pd.Timestamp("2026-06-12")

    def test_unparseable_reporting_date_raises(self):
        with pytest.raises(ValueError):
            _make_portfolio(reporting_date="not-a-date")

    def test_nat_reporting_date_raises(self):
        with pytest.raises(ValueError):
            _make_portfolio(reporting_date=pd.NaT)

    @pytest.mark.parametrize("bad_conc", [-0.1, 1.5, float("nan"), float("inf")])
    def test_bad_concentration_raises(self, bad_conc):
        with pytest.raises(ValueError):
            _make_portfolio(top_10_investor_concentration=bad_conc)

    def test_empty_positions_df_keeps_columns(self):
        port = _make_portfolio(positions=[], share_classes=[])
        df = port.positions_df
        assert df.empty
        for col in ("asset_class", "market_value_eur", "adv_30d", "weight"):
            assert col in df.columns

    def test_positions_df_round_trip(self):
        port = _make_portfolio()
        df = port.positions_df
        assert len(df) == 1
        assert df.iloc[0]["isin"] == "TEST001"
        assert df.iloc[0]["market_value_eur"] == 1_000_000.0


# ---------------------------------------------------------------------------
# _eu_float parsing
# ---------------------------------------------------------------------------

class TestEuFloat:
    def test_european_thousands_and_decimal(self):
        assert _eu_float("1.159.375,000000") == 1_159_375.0

    def test_parentheses_negative(self):
        assert _eu_float("(21.016.625,00)") == -21_016_625.0

    def test_empty_string(self):
        assert _eu_float("") == 0.0

    def test_garbage_string(self):
        assert _eu_float("n/a") == 0.0

    def test_nan_float_input(self):
        assert _eu_float(float("nan")) == 0.0

    def test_inf_inputs_rejected(self):
        assert _eu_float(float("inf")) == 0.0
        assert _eu_float("inf") == 0.0

    def test_plain_float_passthrough(self):
        assert _eu_float(42.5) == 42.5

    def test_none_input(self):
        assert _eu_float(None) == 0.0


# ---------------------------------------------------------------------------
# CSV loader column validation
# ---------------------------------------------------------------------------

class TestLoaderColumnChecks:
    def test_missing_required_column_raises_validation_error(self, tmp_path):
        holdings = tmp_path / "HOLDINGS_20260612000000.csv"
        holdings.write_text(
            "ISIN;Security Name;Currency\nDE0001;Bund;EUR\n", encoding="utf-8"
        )
        nav = tmp_path / "NAV_20260612000000.csv"
        nav.write_text(
            'Portfolio Code;Total Assets\nTEST;"1.000.000,00"\n', encoding="utf-8"
        )
        with pytest.raises(ValidationError, match="Portfolio Code"):
            load_portfolio_from_csv(holdings, nav)

    def test_unreadable_nav_file_raises_validation_error(self, tmp_path):
        holdings = tmp_path / "HOLDINGS_20260612000000.csv"
        holdings.write_text("Portfolio Code;Date\n", encoding="utf-8")
        with pytest.raises(ValidationError):
            load_portfolio_from_csv(holdings, tmp_path / "missing_nav.csv")


# ---------------------------------------------------------------------------
# Validators: NaN awareness and short positions
# ---------------------------------------------------------------------------

class TestValidatorRobustness:
    def test_nan_market_value_flagged(self):
        errors = validate_position(_make_pos(market_value=float("nan")))
        assert any("market_value" in e.lower() for e in errors)

    def test_inf_market_value_flagged(self):
        errors = validate_position(_make_pos(market_value=float("inf")))
        assert any("market_value" in e.lower() for e in errors)

    def test_nan_beta_flagged(self):
        errors = validate_position(_make_pos(beta=float("nan")))
        assert any("beta" in e.lower() for e in errors)

    def test_nan_fx_rate_flagged(self):
        errors = validate_position(_make_pos(fx_rate=float("nan")))
        assert any("fx_rate" in e.lower() for e in errors)

    def test_nan_adv_flagged(self):
        errors = validate_position(_make_pos(adv_30d=float("nan")))
        assert any("adv" in e.lower() for e in errors)

    def test_negative_adv_flagged_even_when_locked(self):
        errors = validate_position(_make_pos(adv_30d=-100, is_locked=True))
        assert any("adv" in e.lower() for e in errors)

    def test_short_future_allowed(self):
        pos = _make_pos(asset_class="future", market_value=-500_000.0)
        assert validate_position(pos) == []

    def test_short_option_allowed(self):
        pos = _make_pos(asset_class="option", market_value=-500_000.0)
        assert validate_position(pos) == []

    def test_negative_equity_with_exposure_base_allowed(self):
        pos = _make_pos(market_value=-500_000.0, exposure_base=2_000_000.0)
        assert validate_position(pos) == []

    def test_negative_equity_without_exposure_base_flagged(self):
        errors = validate_position(_make_pos(market_value=-500_000.0))
        assert any("market_value" in e.lower() for e in errors)

    def test_negative_lock_expiry_flagged(self):
        errors = validate_position(_make_pos(is_locked=True, lock_expiry_days=-1))
        assert any("lock_expiry" in e.lower() for e in errors)

    def test_negative_bid_ask_spread_flagged(self):
        errors = validate_position(_make_pos(bid_ask_spread_bps=-5.0))
        assert any("bid_ask" in e.lower() for e in errors)

    def test_duplicate_isin_flagged(self):
        port = build_sample_portfolio()
        port.positions.append(port.positions[0])
        errors = validate_portfolio(port, strict=False)
        assert any("duplicate" in e.lower() for e in errors)

    def test_negative_notice_period_flagged_after_mutation(self):
        port = build_sample_portfolio()
        port.share_classes[0].notice_period_days = -10
        errors = validate_portfolio(port, strict=False)
        assert any("notice_period" in e.lower() for e in errors)

    def test_sample_portfolio_still_clean(self):
        errors = validate_portfolio(build_sample_portfolio(), strict=False)
        assert errors == []
