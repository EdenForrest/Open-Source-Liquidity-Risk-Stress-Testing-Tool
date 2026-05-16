"""
tests/test_report_builder.py
Tests for run_id determinism, ESMA template, and scenario metadata outputs.
"""
import json
import hashlib
import pytest
import pandas as pd
from pathlib import Path

from liquidity_risk_tool.models import build_sample_portfolio
from liquidity_risk_tool.reporting.report_builder import ReportBuilder


@pytest.fixture(scope="module")
def built_report(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("report")
    port = build_sample_portfolio()
    rb = ReportBuilder(port, output_dir=str(tmp))
    rb.build()
    return rb, tmp


class TestRunId:
    def test_run_id_is_64_hex_chars(self, built_report):
        rb, _ = built_report
        assert len(rb._run_id) == 64
        assert all(c in "0123456789abcdef" for c in rb._run_id)

    def test_run_id_deterministic(self):
        port = build_sample_portfolio()
        rb1 = ReportBuilder(port, output_dir="output").build()
        rb2 = ReportBuilder(port, output_dir="output").build()
        assert rb1._run_id == rb2._run_id

    def test_run_id_changes_with_different_portfolio(self, tmp_path):
        port = build_sample_portfolio()
        rb1 = ReportBuilder(port, output_dir=str(tmp_path)).build()
        port.positions[0].market_value = port.positions[0].market_value + 1
        port._refresh_weights()
        rb2 = ReportBuilder(port, output_dir=str(tmp_path)).build()
        assert rb1._run_id != rb2._run_id


class TestExcelOutput:
    def test_excel_has_esma_template_sheet(self, built_report, tmp_path):
        port = build_sample_portfolio()
        rb = ReportBuilder(port, output_dir=str(tmp_path)).build()
        path = rb.to_excel("test_report.xlsx")
        xl = pd.ExcelFile(path)
        assert "ESMA_Template" in xl.sheet_names

    def test_esma_template_has_a1_to_e6(self, built_report, tmp_path):
        port = build_sample_portfolio()
        rb = ReportBuilder(port, output_dir=str(tmp_path)).build()
        path = rb.to_excel("test_esma.xlsx")
        df = pd.read_excel(path, sheet_name="ESMA_Template")
        codes = df["Code"].tolist()
        assert "A.1" in codes
        assert "E.6" in codes
        # Should have at least 22 rows
        assert len(codes) >= 22

    def test_scenario_metadata_sheet_exists(self, built_report, tmp_path):
        port = build_sample_portfolio()
        rb = ReportBuilder(port, output_dir=str(tmp_path)).build()
        path = rb.to_excel("test_meta.xlsx")
        xl = pd.ExcelFile(path)
        assert "Scenario_Metadata" in xl.sheet_names

    def test_scenario_metadata_has_6_rows(self, built_report, tmp_path):
        port = build_sample_portfolio()
        rb = ReportBuilder(port, output_dir=str(tmp_path)).build()
        path = rb.to_excel("test_meta6.xlsx")
        df = pd.read_excel(path, sheet_name="Scenario_Metadata")
        assert len(df) == 6

    def test_scenario_metadata_has_regulatory_basis(self, built_report, tmp_path):
        port = build_sample_portfolio()
        rb = ReportBuilder(port, output_dir=str(tmp_path)).build()
        path = rb.to_excel("test_reg.xlsx")
        df = pd.read_excel(path, sheet_name="Scenario_Metadata")
        assert "regulatory_basis" in df.columns
        # At least one scenario should have a non-empty regulatory_basis
        assert df["regulatory_basis"].notna().any()


class TestJsonOutput:
    def test_json_has_run_id(self, built_report, tmp_path):
        port = build_sample_portfolio()
        rb = ReportBuilder(port, output_dir=str(tmp_path)).build()
        path = rb.to_json("test.json")
        with open(path) as f:
            data = json.load(f)
        assert "run_id" in data
        assert len(data["run_id"]) == 64

    def test_json_has_scenario_metadata(self, built_report, tmp_path):
        port = build_sample_portfolio()
        rb = ReportBuilder(port, output_dir=str(tmp_path)).build()
        path = rb.to_json("test_meta.json")
        with open(path) as f:
            data = json.load(f)
        assert "scenario_metadata" in data
        assert len(data["scenario_metadata"]) == 6

    def test_json_scenario_metadata_fields(self, built_report, tmp_path):
        port = build_sample_portfolio()
        rb = ReportBuilder(port, output_dir=str(tmp_path)).build()
        path = rb.to_json("test_fields.json")
        with open(path) as f:
            data = json.load(f)
        first = data["scenario_metadata"][0]
        for field in ("name", "equity_shock", "credit_spread_shock_bps",
                      "regulatory_basis", "is_worst_case", "version"):
            assert field in first, f"Missing field: {field}"
