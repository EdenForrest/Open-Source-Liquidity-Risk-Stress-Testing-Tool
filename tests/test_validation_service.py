"""
Characterization tests for backend.services.validation_service.

Locks down the current shape of run_checks() output and, critically, the
EXACT message text of the §20.4 LMT-count check (AIFMD II Art. 16). Phase 6
of the consolidation plan extracts this check into
liquidity_risk_tool/regulatory/aifmd.py::check_lmt_count so that both this
validator and the pydantic model validator (backend/schemas/analysis.py)
share one source of truth — these tests are the regression lock that proves
the extraction preserved message text byte-for-byte.
"""
from pathlib import Path

import pytest

from backend.services.pipeline_service import run_full_pipeline
from backend.services.validation_service import run_checks

ROOT = Path(__file__).parent.parent
HOLDINGS_PATH = str(ROOT / "data" / "HOLDINGS_20260515001555.csv")
NAV_PATH = str(ROOT / "data" / "NAV_20260515001555.csv")
MARKET_DATA_PATH = str(ROOT / "data" / "market_data_ALL.csv")

CHECK_DICT_KEYS = {"name", "category", "passed", "message"}

EXPECTED_CATEGORIES = {
    "Portfolio", "Liquidity Metrics", "Liquidity Ladder", "Redemption",
    "Stress", "Market Data", "Waterfall", "Reconciliation", "Annex IV",
}

LMT_CHECK_NAME = "LMT configuration declared (≥2 tools, AIFMD II Art. 16)"


@pytest.fixture(scope="module")
def demo_result():
    return run_full_pipeline(HOLDINGS_PATH, NAV_PATH, MARKET_DATA_PATH)


@pytest.fixture(scope="module")
def checks(demo_result):
    return run_checks(demo_result)


class TestRunChecksShape:
    def test_returns_list_of_check_dicts(self, checks):
        assert isinstance(checks, list)
        assert len(checks) > 0
        for c in checks:
            assert set(c.keys()) == CHECK_DICT_KEYS
            assert isinstance(c["passed"], bool)
            assert isinstance(c["name"], str) and c["name"]
            assert isinstance(c["category"], str) and c["category"]
            assert isinstance(c["message"], str)

    def test_categories_are_known(self, checks):
        seen = {c["category"] for c in checks}
        assert seen <= EXPECTED_CATEGORIES

    def test_annex_iv_category_present(self, checks):
        assert any(c["category"] == "Annex IV" for c in checks)


class TestLmtCountCheck:
    """
    §20.4 — AIFMD II Art. 16 minimum pre-selected LMT count.
    This is the exact-text regression lock referenced by the Phase 6 plan:
    liquidity_risk_tool/regulatory/aifmd.py::check_lmt_count must reproduce
    these two message forms verbatim.
    """

    def _lmt_check(self, checks):
        matches = [c for c in checks if c["name"] == LMT_CHECK_NAME]
        assert len(matches) == 1, f"Expected exactly one LMT-count check, found {len(matches)}"
        return matches[0]

    def test_check_exists_with_exact_name(self, checks):
        check = self._lmt_check(checks)
        assert check["category"] == "Annex IV"

    def test_message_matches_pass_or_fail_form(self, demo_result, checks):
        check = self._lmt_check(checks)
        lmts = demo_result["aifmd2"].get("lmt_preselected") or []
        if check["passed"]:
            expected = f"{len(lmts)} LMT(s) preselected: {lmts}"
        else:
            expected = "FAIL — no LMTs declared; AIFMD II requires ≥2 pre-selected tools"
        assert check["message"] == expected

    def test_non_compliant_message_exact_text(self):
        """
        Directly locks the non-compliant message string (independent of the
        demo dataset's actual LMT config) so Phase 6's extraction has a
        literal string to match against regardless of which branch the demo
        data happens to hit.
        """
        expected_fail_message = "FAIL — no LMTs declared; AIFMD II requires ≥2 pre-selected tools"
        # Sanity: this literal must appear verbatim in the validator source.
        import inspect
        from backend.services import validation_service
        src = inspect.getsource(validation_service)
        assert expected_fail_message in src
