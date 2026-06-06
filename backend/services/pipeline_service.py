"""
Thin orchestrator — calls the existing engine classes in the same order as gui.py,
and returns a single serialisable dict that the API routes hand back to the client.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from liquidity_risk_tool.models.csv_loader import (
    load_portfolio_from_csv,
    enrich_portfolio_from_market_data,
    available_portfolio_codes,
)
from liquidity_risk_tool.engines.liquidity_profiler import LiquidityProfiler
from liquidity_risk_tool.engines.stress_engine import StressEngine
from liquidity_risk_tool.engines.redemption_simulator import RedemptionSimulator
from liquidity_risk_tool.engines.waterfall_engine import WaterfallEngine
from liquidity_risk_tool.engines.leverage_engine import LeverageEngine
from liquidity_risk_tool.reporting.risk_metrics import RiskMetricsBuilder
from liquidity_risk_tool.reporting.report_builder import ReportBuilder
from liquidity_risk_tool.config.settings import (
    STRESS_SCENARIOS, REVOLUTION_SCENARIOS, AIFMD2_PRESELECTED_LMTS, AIFMD2_MIN_LMT_COUNT,
)


def _safe(v):
    """Convert numpy scalars and NaN/Inf floats to JSON-native Python types."""
    import numpy as np
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return None if (np.isnan(v) or np.isinf(v)) else float(v)
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _clean_records(records: list[dict]) -> list[dict]:
    return [{k: _safe(val) for k, val in row.items()} for row in records]


def _clean_dict(d: dict) -> dict:
    """Recursively apply _safe() to all scalar values in a dict."""
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = _clean_dict(v)
        elif isinstance(v, list):
            out[k] = [_safe(i) if not isinstance(i, dict) else _clean_dict(i) for i in v]
        else:
            out[k] = _safe(v)
    return out


def run_full_pipeline(
    holdings_path: str | Path,
    nav_path: str | Path,
    market_data_path: Optional[str | Path] = None,
    portfolio_code: Optional[str] = None,
    scenario_library: str = "esma",
    lmt_config: Optional[dict] = None,
) -> dict:
    """Run the full analytics pipeline and return a serialisable results dict."""

    portfolio = load_portfolio_from_csv(holdings_path, nav_path, portfolio_code=portfolio_code)

    if market_data_path and Path(market_data_path).exists():
        enrich_portfolio_from_market_data(portfolio, Path(market_data_path))

    normal_profiler = LiquidityProfiler(portfolio, stress=False).run()
    stress_profiler = LiquidityProfiler(portfolio, stress=True).run()

    normal_buckets = normal_profiler.position_buckets
    stress_buckets = stress_profiler.position_buckets

    # The pipeline's redemption tables serve as the "Without LMT" baseline that the
    # Redemption tab compares against the on-demand /lmt-simulate ("With LMT") results.
    # That baseline MUST be genuinely tool-free: if we passed lmt_config=None here the
    # simulator would fall back to AIFMD2_PRESELECTED_LMTS (gate + suspension + swing
    # pricing), so swing pricing would silently reduce the baseline's effective cash
    # demand. A user who then applies a config WITHOUT swing pricing would see a higher
    # effective demand than the contaminated baseline, making the T+1/T+3/T+7 horizons
    # flip from met→failed — i.e. LMTs would appear to WORSEN liquidity. Forcing an empty
    # active-tools set (only when no explicit config is supplied) keeps the baseline clean
    # while still honouring a caller-provided lmt_config when one is passed.
    baseline_lmt_config = lmt_config if lmt_config else {"active_tools": []}
    redemption_sim = RedemptionSimulator(portfolio, normal_buckets, stress_buckets, lmt_config=baseline_lmt_config)
    redemption_normal = redemption_sim.run(stress=False)
    redemption_stress = redemption_sim.run(stress=True)

    stress_engine = StressEngine(portfolio, scenario_library=scenario_library)
    stress_detail = stress_engine.run_detail()

    # NOTE: reverse stress testing is intentionally NOT run here. It is an
    # expensive, multi-start optimisation that reprices the whole portfolio many
    # times, so running it on every pipeline call (upload / demo) made the /run
    # request hang past the client timeout. It is now invoked on demand only,
    # behind an explicit button, via POST /run/{run_id}/reverse-stress.

    worst = max(stress_detail, key=lambda s: abs(s.nav_impact_pct))
    waterfall_target = portfolio.total_nav * worst.redemption_pct
    waterfall = WaterfallEngine(portfolio, stress_buckets, stress=True).run(waterfall_target)

    metrics = RiskMetricsBuilder(portfolio).build_liquidity_metrics()

    leverage = LeverageEngine(portfolio).run()

    # Build stressed ladder from the worst scenario's post-shock position detail
    # so that bucket migrations from equity/credit shocks are reflected — matching
    # the legacy GUI behaviour (gui.py:1655-1671).
    from liquidity_risk_tool.config.settings import BUCKET_ORDER as _BUCKET_ORDER
    _stressed_nav = worst.position_detail["market_value_eur"].sum() if not worst.position_detail.empty else 1.0
    _stressed_agg = (
        worst.position_detail
        .groupby("bucket")
        .agg(
            realisable_value_eur=("realisable_value", "sum"),
            market_value_eur=("market_value_eur", "sum"),
        )
        .reindex(_BUCKET_ORDER, fill_value=0.0)
        .reset_index()
    )
    _stressed_agg["nav_pct"] = _stressed_agg["market_value_eur"] / _stressed_nav if _stressed_nav > 0 else 0.0
    _stressed_agg["cumulative_nav_pct"] = _stressed_agg["nav_pct"].cumsum()

    # Scenario metadata (name + governance fields) from the active scenario list.
    # The reverse-stress breach scenario, when requested, is appended client-side
    # from the on-demand /run/{run_id}/reverse-stress endpoint.
    _active_scenarios = list(stress_engine.scenarios)
    scenario_meta = []
    for sc in _active_scenarios:
        scenario_meta.append({
            "name": sc.name,
            "equity_shock": sc.equity_shock,
            "credit_spread_shock_bps": sc.credit_spread_shock_bps,
            "rate_shock_bps": sc.rate_shock_bps,
            "liquidity_haircut_multiplier": sc.liquidity_haircut_multiplier,
            "redemption_rate": sc.redemption_rate,
            "adv_stress_scalar": sc.adv_stress_scalar,
            "description": getattr(sc, "description", ""),
            "regulatory_basis": getattr(sc, "regulatory_basis", ""),
            "is_worst_case": getattr(sc, "is_worst_case", False),
            "version": getattr(sc, "version", ""),
        })

    return {
        "fund_name": portfolio.fund_name,
        "reporting_date": str(portfolio.reporting_date.date()),
        "total_nav_eur": portfolio.total_nav,
        "market_data_loaded": bool(market_data_path and Path(market_data_path).exists()),
        "liquidity_metrics": _clean_dict(metrics.summary()),
        "liquidity_ladder": _clean_records(
            normal_profiler.liquidity_ladder().to_dict(orient="records")
        ),
        "stress_ladder": _clean_records(
            _stressed_agg.to_dict(orient="records")
        ),
        "position_buckets": _clean_records(normal_buckets.to_dict(orient="records")),
        "stress_position_buckets": _clean_records(stress_buckets.to_dict(orient="records")),
        "top_10_concentration": getattr(portfolio, "top_10_investor_concentration", 0.30),
        "stress_results": [_clean_dict(s.to_dict()) for s in stress_detail],
        "redemption_results": _clean_records(
            redemption_normal.to_dict(orient="records")
        ),
        "redemption_stress_results": _clean_records(
            redemption_stress.to_dict(orient="records")
        ),
        "waterfall": _clean_records(
            waterfall.sell_schedule_df().to_dict(orient="records")
        ),
        "waterfall_summary": _clean_records(
            waterfall.daily_summary_df().to_dict(orient="records")
        ),
        "waterfall_meta": _clean_dict({
            "target_eur": waterfall.target_eur,
            "total_proceeds_eur": waterfall.total_proceeds_eur,
            "target_met": waterfall.target_met,
            "days_to_target": waterfall.days_to_target,
            "residual_shortfall_eur": waterfall.residual_shortfall_eur,
            "settlement_days": waterfall.settlement_days,
            "proceeds_within_horizon_eur": waterfall.proceeds_within_horizon_eur,
            "met_eventually": waterfall.met_eventually,
            "nav_before": waterfall.nav_before,
            "nav_after": waterfall.nav_after,
            "nav_impact_pct": waterfall.nav_impact_pct,
        }),
        "scenario_metadata": [_clean_dict(m) for m in scenario_meta],
        "aifmd2": _clean_dict({
            "gross_leverage": leverage.gross_leverage,
            "commitment_leverage": leverage.commitment_leverage,
            "leverage_cap": leverage.leverage_cap,
            "leverage_breach": leverage.leverage_breach,
            "is_loan_origination_aif": leverage.is_loan_origination_aif,
            "loan_pct_nav": leverage.loan_pct_nav,
            "risk_retention_ok": leverage.risk_retention_ok,
            "borrower_breaches": ", ".join(leverage.borrower_breaches),
            "lmt_preselected": AIFMD2_PRESELECTED_LMTS,
            "lmt_count": len(AIFMD2_PRESELECTED_LMTS),
            "lmt_compliant": len(AIFMD2_PRESELECTED_LMTS) >= AIFMD2_MIN_LMT_COUNT,
            "lmt_config_applied": lmt_config or {},
            "warnings": "; ".join(leverage.warnings),
            "regulatory_basis": "AIFMD II (Directive (EU) 2024/927), effective 16 April 2026",
        }),
    }


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
    import json, tempfile
    from pathlib import Path as P

    out = P(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / "liquidity_risk_report.json"
    json_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    return {
        "json_path": str(json_path),
    }
