"""
Characterization tests for backend.services.pipeline_service.

These tests lock down the CURRENT shape of the React JSON contract
(run_full_pipeline's 18 top-level keys and nested sub-shapes) plus a
byte-identical golden snapshot of the demo dataset, so later refactor
phases (Phase 2-5 of the consolidation plan) can be verified as
non-regressing.

Regenerate the golden snapshot deliberately with:
    REGEN_GOLDEN=1 python -m pytest tests/test_pipeline_service_contract.py -q

Do NOT regenerate casually — a golden diff during a refactor phase means
the refactor changed observable behaviour, which is the thing these tests
exist to catch.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from backend.services.pipeline_service import run_full_pipeline, run_all_portfolios

ROOT = Path(__file__).parent.parent
HOLDINGS_PATH = str(ROOT / "data" / "HOLDINGS_20260515001555.csv")
NAV_PATH = str(ROOT / "data" / "NAV_20260515001555.csv")
MARKET_DATA_PATH = str(ROOT / "data" / "market_data_ALL.csv")
GOLDEN_PATH = Path(__file__).parent / "golden" / "pipeline_demo.json"

TOP_LEVEL_KEYS = {
    "fund_name", "reporting_date", "total_nav_eur", "market_data_loaded",
    "liquidity_metrics", "liquidity_ladder", "stress_ladder", "position_buckets",
    "stress_position_buckets", "top_10_concentration", "stress_results",
    "redemption_results", "redemption_stress_results", "waterfall",
    "waterfall_summary", "waterfall_meta", "scenario_metadata", "aifmd2",
}

WATERFALL_META_KEYS = {
    "target_eur", "total_proceeds_eur", "target_met", "days_to_target",
    "residual_shortfall_eur", "settlement_days", "proceeds_within_horizon_eur",
    "met_eventually", "nav_before", "nav_after", "nav_impact_pct",
}

SCENARIO_METADATA_KEYS = {
    "name", "equity_shock", "credit_spread_shock_bps", "rate_shock_bps",
    "liquidity_haircut_multiplier", "redemption_rate", "adv_stress_scalar",
    "description", "regulatory_basis", "is_worst_case", "version",
}

# LiquidityMetrics.summary() == dataclass __dict__ minus bucket_breakdown.
LIQUIDITY_METRICS_KEYS = {
    "fund_name", "reporting_date", "total_nav_eur",
    "lcr_t1", "lcr_t3", "lcr_t7", "illiquid_pct", "illiquid_realisable",
    "top10_concentration", "liquidity_vs_concentration",
    "warning_flag", "breach_flag", "liquid_T0_T1_pct",
    "days_to_50pct", "days_to_75pct", "days_to_90pct",
    "top_countries", "eu_pct", "non_eu_pct", "geo_top_country",
    "geo_top_country_pct", "geo_warning_flag", "geo_breach_flag",
    "ucits_issuer_weights", "ucits_breaching_issuers", "ucits_aggregate_5_10",
    "ucits_single_breach", "ucits_aggregate_breach", "ucits_compliant",
}


@pytest.fixture(scope="module")
def result():
    return run_full_pipeline(HOLDINGS_PATH, NAV_PATH, MARKET_DATA_PATH)


class TestTopLevelContract:
    def test_exact_top_level_keys(self, result):
        assert set(result.keys()) == TOP_LEVEL_KEYS

    def test_fund_name_is_str(self, result):
        assert isinstance(result["fund_name"], str) and result["fund_name"]

    def test_total_nav_positive(self, result):
        assert result["total_nav_eur"] > 0

    def test_market_data_loaded_bool(self, result):
        assert isinstance(result["market_data_loaded"], bool)


class TestWaterfallMeta:
    def test_exact_keys(self, result):
        assert set(result["waterfall_meta"].keys()) == WATERFALL_META_KEYS

    def test_target_met_is_bool(self, result):
        assert isinstance(result["waterfall_meta"]["target_met"], bool)


class TestScenarioMetadata:
    def test_each_record_has_exact_keys(self, result):
        records = result["scenario_metadata"]
        assert len(records) > 0
        for rec in records:
            assert set(rec.keys()) == SCENARIO_METADATA_KEYS

    def test_exactly_one_worst_case(self, result):
        worst = [r for r in result["scenario_metadata"] if r["is_worst_case"]]
        assert len(worst) == 1


class TestLiquidityMetrics:
    def test_exact_keys(self, result):
        assert set(result["liquidity_metrics"].keys()) == LIQUIDITY_METRICS_KEYS


class TestAifmd2:
    """
    Locks down the CURRENT key set of the aifmd2 block as observed at
    runtime (source of truth = pipeline_service.py, not the refactor plan's
    recap, which cites a different count).
    """
    def test_keys_are_stable(self, result):
        aifmd2 = result["aifmd2"]
        # Snapshot the keys we observed at plan-writing time; if this ever
        # fails because a key was ADDED, update this set deliberately and
        # note it in the phase's commit message. A key going MISSING is a
        # contract break.
        expected = {
            "gross_leverage", "commitment_leverage", "leverage_cap",
            "leverage_breach", "is_loan_origination_aif", "loan_pct_nav",
            "risk_retention_ok", "borrower_breaches", "lmt_preselected",
            "lmt_count", "lmt_compliant", "lmt_config_applied",
            "warnings", "regulatory_basis",
        }
        assert set(aifmd2.keys()) == expected

    def test_regulatory_basis_mentions_aifmd2(self, result):
        assert "AIFMD" in result["aifmd2"]["regulatory_basis"]


class TestRunAllPortfolios:
    def test_wrapper_shape(self):
        out = run_all_portfolios(HOLDINGS_PATH, NAV_PATH, MARKET_DATA_PATH)
        assert set(out.keys()) == {"portfolios", "portfolio_codes"}
        assert isinstance(out["portfolios"], dict)
        assert isinstance(out["portfolio_codes"], list)


class TestGoldenSnapshot:
    """
    Byte-identical (modulo key ordering, via sort_keys) golden snapshot of
    the full demo pipeline output. Regenerate deliberately via REGEN_GOLDEN=1;
    otherwise this test is a tripwire for any behavioural drift during the
    refactor.
    """
    def test_matches_golden(self, result):
        serialised = json.dumps(result, sort_keys=True, default=str, indent=2)

        if os.environ.get("REGEN_GOLDEN") == "1":
            GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN_PATH.write_text(serialised, encoding="utf-8")
            pytest.skip("REGEN_GOLDEN=1 set — golden snapshot (re)written, not compared.")

        assert GOLDEN_PATH.exists(), (
            f"No golden snapshot at {GOLDEN_PATH}. "
            "Generate one with REGEN_GOLDEN=1 python -m pytest tests/test_pipeline_service_contract.py -q"
        )
        expected = GOLDEN_PATH.read_text(encoding="utf-8")
        assert serialised == expected, (
            "Pipeline output diverged from the golden snapshot. If this is an "
            "intentional, reviewed behavioural change, regenerate with "
            "REGEN_GOLDEN=1 and note the change in the commit message."
        )
