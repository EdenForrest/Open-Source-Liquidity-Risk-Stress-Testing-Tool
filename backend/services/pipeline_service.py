"""
Thin orchestrator — delegates to ``liquidity_risk_tool.analysis.compute_analysis``
for the actual engine orchestration, and serialises the result via
``AnalysisResult.to_client_dict()`` into the dict the API routes hand back
to the client.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from liquidity_risk_tool.models.csv_loader import available_portfolio_codes
from liquidity_risk_tool.analysis import compute_analysis


def run_full_pipeline(
    holdings_path: str | Path,
    nav_path: str | Path,
    market_data_path: Optional[str | Path] = None,
    portfolio_code: Optional[str] = None,
    scenario_library: str = "esma",
    lmt_config: Optional[dict] = None,
) -> dict:
    """Run the full analytics pipeline and return a serialisable results dict."""
    result = compute_analysis(
        holdings_path,
        nav_path,
        market_data_path,
        portfolio_code=portfolio_code,
        scenario_library=scenario_library,
        lmt_config=lmt_config,
    )
    return result.to_client_dict()


def run_all_portfolios(
    holdings_path: str | Path,
    nav_path: str | Path,
    market_data_path: Optional[str | Path] = None,
    scenario_library: str = "esma",
    lmt_config: Optional[dict] = None,
) -> dict:
    """Run the full pipeline for every portfolio code found in the holdings file."""
    codes = available_portfolio_codes(holdings_path)
    portfolios: dict[str, dict] = {}
    for code in codes:
        portfolios[code] = run_full_pipeline(
            holdings_path, nav_path, market_data_path,
            portfolio_code=code, scenario_library=scenario_library, lmt_config=lmt_config,
        )
    return {"portfolios": portfolios, "portfolio_codes": codes}


def build_report_files(results: dict, output_dir: str = "output") -> dict:
    """Re-run ReportBuilder to generate Excel + JSON files and return their paths."""
    import json
    from pathlib import Path as P

    out = P(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / "liquidity_risk_report.json"
    json_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    return {
        "json_path": str(json_path),
    }
