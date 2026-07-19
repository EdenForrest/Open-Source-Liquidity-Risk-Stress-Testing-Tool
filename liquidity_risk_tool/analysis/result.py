"""``AnalysisResult`` — the single DTO produced by a pipeline run.

Carries every artifact the engines produced during one ``compute_analysis``
call, so downstream consumers (the FastAPI serializer, ``RiskMetricsBuilder``,
``ReportBuilder``, the CLI) can reuse them instead of re-running engines.

``to_client_dict()`` is the pipeline_service.py serialization block moved
verbatim: same 18 top-level keys, same nested shapes, byte-identical output
for the same inputs. Opt-in slots (``reverse_stress``, ``waterfall_lp``,
``validation``) are NOT serialized here — the React contract stays exactly
18 keys; reverse stress remains available only via the on-demand
POST /api/run/{run_id}/reverse-stress endpoint.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

from ..config.settings import AIFMD2_PRESELECTED_LMTS, AIFMD2_MIN_LMT_COUNT
from ..engines.liquidity_profiler import LiquidityProfiler
from ..engines.leverage_engine import LeverageResult
from ..engines.stress_engine import ScenarioResult
from ..engines.waterfall_engine import WaterfallResult
from ..models.position import Portfolio
from ..reporting.risk_metrics import LiquidityMetrics


# ---------------------------------------------------------------------------
# JSON-safety helpers (moved verbatim from backend/services/pipeline_service.py)
# ---------------------------------------------------------------------------

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


@dataclass
class AnalysisResult:
    """Every artifact produced by one ``compute_analysis`` run."""

    portfolio: Portfolio
    normal_profiler: LiquidityProfiler
    stress_profiler: LiquidityProfiler
    redemption_normal: Any   # pd.DataFrame
    redemption_stress: Any   # pd.DataFrame
    stress_detail: list[ScenarioResult]
    worst: ScenarioResult
    waterfall: WaterfallResult
    leverage: LeverageResult
    metrics: LiquidityMetrics
    scenario_metadata: list[dict]
    market_data_loaded: bool
    lmt_config: Optional[dict] = None

    # Opt-in slots — populated only when the corresponding compute_analysis
    # kwarg requests them; never serialized by to_client_dict().
    reverse_stress: Optional[Any] = None
    waterfall_lp: Optional[Any] = None
    validation: Optional[Any] = None

    # Internal artifacts needed to build stress_ladder without recomputation.
    stress_ladder_df: Any = None  # pd.DataFrame, set by compute_analysis

    def to_client_dict(self) -> dict:
        """Serialize to the 18-key dict the React frontend consumes.

        Verbatim move of pipeline_service.py:153-211 — byte-identical output
        for the same inputs (golden-snapshot gated).
        """
        portfolio = self.portfolio
        normal_profiler = self.normal_profiler
        normal_buckets = normal_profiler.position_buckets
        stress_buckets = self.stress_profiler.position_buckets
        stress_detail = self.stress_detail
        waterfall = self.waterfall
        leverage = self.leverage
        metrics = self.metrics
        lmt_config = self.lmt_config

        return {
            "fund_name": portfolio.fund_name,
            "reporting_date": str(portfolio.reporting_date.date()),
            "total_nav_eur": portfolio.total_nav,
            "market_data_loaded": self.market_data_loaded,
            "liquidity_metrics": _clean_dict(metrics.summary()),
            "liquidity_ladder": _clean_records(
                normal_profiler.liquidity_ladder().to_dict(orient="records")
            ),
            "stress_ladder": _clean_records(
                self.stress_ladder_df.to_dict(orient="records")
            ),
            "position_buckets": _clean_records(normal_buckets.to_dict(orient="records")),
            "stress_position_buckets": _clean_records(stress_buckets.to_dict(orient="records")),
            "top_10_concentration": getattr(portfolio, "top_10_investor_concentration", 0.30),
            "stress_results": [_clean_dict(s.to_dict()) for s in stress_detail],
            "redemption_results": _clean_records(
                self.redemption_normal.to_dict(orient="records")
            ),
            "redemption_stress_results": _clean_records(
                self.redemption_stress.to_dict(orient="records")
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
            "scenario_metadata": [_clean_dict(m) for m in self.scenario_metadata],
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
