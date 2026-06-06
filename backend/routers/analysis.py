"""
GET  /api/run/{run_id}/status       — poll run completion
GET  /api/run/{run_id}/portfolios   — list portfolio codes in a completed run
GET  /api/run/{run_id}/liquidity    — liquidity metrics + ladder + positions
GET  /api/run/{run_id}/stress       — stress scenario results
GET  /api/run/{run_id}/redemption   — redemption coverage matrix
GET  /api/run/{run_id}/waterfall    — day-by-day sell schedule
GET  /api/run/{run_id}/report       — full results as JSON download
GET  /api/run/{run_id}/export/all   — zip of all portfolio reports in chosen format
POST /api/run/{run_id}/lmt-simulate — re-run RedemptionSimulator with custom LMT config
POST /api/run/{run_id}/waterfall-optimise — re-run the waterfall via LP optimiser
"""
from __future__ import annotations

import io
import zipfile
from typing import List, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, model_validator

from backend import store
from liquidity_risk_tool.config.settings import (
    AIFMD2_MIN_LMT_COUNT,
    SELECTABLE_TOOLS,
)

router = APIRouter(tags=["analysis"])


def _require_complete(run_id: str) -> dict:
    record = store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if record.status == "error":
        raise HTTPException(status_code=500, detail=record.error or "Pipeline error")
    if record.status != "complete":
        raise HTTPException(status_code=202, detail=f"Run status: {record.status}")
    return record.results  # type: ignore[return-value]


def _portfolio_results(run_id: str, portfolio: Optional[str]) -> dict:
    """Return the single-portfolio sub-dict for a completed run."""
    r = _require_complete(run_id)
    codes: list[str] = r.get("portfolio_codes", [])
    code = portfolio or (codes[0] if codes else None)
    if code is None:
        raise HTTPException(status_code=404, detail="No portfolios found in this run")
    if code not in r.get("portfolios", {}):
        raise HTTPException(status_code=404, detail=f"Portfolio '{code}' not in this run. Available: {codes}")
    return r["portfolios"][code]


def _annex_iv_meta(run_id: str) -> Optional[dict]:
    """Return the AIFM/AIF/share-class metadata uploaded for this run (or None)."""
    record = store.get(run_id)
    return record.annex_iv_meta if record is not None else None


def _require_annex_iv_ready(run_id: str) -> dict:
    """Return the run's Annex IV metadata, or raise 409 if export is not enabled.

    Annex IV no longer auto-activates: a defaults-filled ESMA filing must never
    leave the tool. Regulatory export is blocked until a dedicated AIFM/AIF +
    share-class metadata upload satisfies ``annex_iv_ready``.
    """
    from liquidity_risk_tool.reporting.annex_iv_mapper import annex_iv_ready

    meta = _annex_iv_meta(run_id)
    if not annex_iv_ready(meta):
        raise HTTPException(
            status_code=409,
            detail="Annex IV metadata not uploaded — provide AIFM/AIF "
            "identification and share-class data to enable regulatory export",
        )
    return meta


@router.get("/run/{run_id}/status")
def get_status(run_id: str):
    record = store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return {"run_id": run_id, "status": record.status, "error": record.error}


@router.get("/run/{run_id}/debug")
def get_debug(run_id: str):
    """Return raw run record for diagnosing failures."""
    record = store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return {
        "run_id": run_id,
        "status": record.status,
        "error": record.error,
        "has_results": record.results is not None,
        "result_keys": list(record.results.keys()) if record.results else None,
    }


@router.get("/run/{run_id}/portfolios")
def get_portfolios(run_id: str):
    """Return the list of portfolio codes available in this run."""
    r = _require_complete(run_id)
    return {"portfolio_codes": r.get("portfolio_codes", [])}


@router.get("/run/{run_id}/liquidity")
def get_liquidity(run_id: str, portfolio: Optional[str] = Query(default=None)):
    r = _portfolio_results(run_id, portfolio)
    return {
        "fund_name": r["fund_name"],
        "reporting_date": r["reporting_date"],
        "total_nav_eur": r["total_nav_eur"],
        "liquidity_metrics": r["liquidity_metrics"],
        "liquidity_ladder": r["liquidity_ladder"],
        "stress_ladder": r["stress_ladder"],
        "position_buckets": r["position_buckets"],
    }


@router.get("/run/{run_id}/stress")
def get_stress(run_id: str, portfolio: Optional[str] = Query(default=None)):
    r = _portfolio_results(run_id, portfolio)
    return {
        "scenario_metadata": r["scenario_metadata"],
        "stress_results": r["stress_results"],
    }


@router.get("/run/{run_id}/redemption")
def get_redemption(run_id: str, portfolio: Optional[str] = Query(default=None)):
    r = _portfolio_results(run_id, portfolio)
    return {
        "redemption_results": r["redemption_results"],
        "redemption_stress_results": r["redemption_stress_results"],
    }


@router.get("/run/{run_id}/waterfall")
def get_waterfall(run_id: str, portfolio: Optional[str] = Query(default=None)):
    r = _portfolio_results(run_id, portfolio)
    return {
        "waterfall_meta": r["waterfall_meta"],
        "waterfall": r["waterfall"],
        "waterfall_summary": r["waterfall_summary"],
    }


@router.get("/run/{run_id}/leverage")
def get_leverage(run_id: str, portfolio: Optional[str] = Query(default=None)):
    r = _portfolio_results(run_id, portfolio)
    return r.get("aifmd2", {})


@router.get("/run/{run_id}/validation")
def get_validation(run_id: str, portfolio: Optional[str] = Query(default=None)):
    """Run business-logic validation checks against a completed pipeline run."""
    from backend.services.validation_service import run_checks
    r = _portfolio_results(run_id, portfolio)
    checks = run_checks(r)
    passed = sum(1 for c in checks if c["passed"])
    return {
        "total": len(checks),
        "passed": passed,
        "failed": len(checks) - passed,
        "checks": checks,
    }


@router.get("/run/{run_id}/report")
def get_report(run_id: str):
    """Return the full results dict (all portfolios) as a downloadable JSON response."""
    r = _require_complete(run_id)
    return JSONResponse(
        content=r,
        headers={"Content-Disposition": f'attachment; filename="liquidity_report_{run_id[:8]}.json"'},
    )


@router.get("/run/{run_id}/export/excel")
def export_excel(run_id: str, portfolio: Optional[str] = Query(default=None), period: Optional[str] = Query(default=None)):
    """Return a structured Excel (.xlsx) workbook for a single portfolio."""
    from backend.services.export_service import build_excel

    r = _portfolio_results(run_id, portfolio)
    code = portfolio or "portfolio"
    xlsx_bytes = build_excel(r, period=period)
    filename = f"liquidity_report_{code}_{run_id[:8]}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/run/{run_id}/export/pdf")
def export_pdf(run_id: str, portfolio: Optional[str] = Query(default=None)):
    """Return a PDF liquidity risk report for a single portfolio."""
    from backend.services.export_service import build_pdf

    r = _portfolio_results(run_id, portfolio)
    code = portfolio or "portfolio"
    pdf_bytes = build_pdf(r)
    filename = f"liquidity_report_{code}_{run_id[:8]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/run/{run_id}/export/annex-iv-excel")
def export_annex_iv_excel(run_id: str, portfolio: Optional[str] = Query(default=None), period: Optional[str] = Query(default=None)):
    """Return a single-sheet Annex IV Excel workbook (regulatory filing only)."""
    from backend.services.export_service import build_excel_annex_iv

    r = _portfolio_results(run_id, portfolio)
    meta = _require_annex_iv_ready(run_id)
    code = portfolio or "portfolio"
    period_label = (period or "2026Q1").replace("/", "-")
    xlsx_bytes = build_excel_annex_iv(r, period=period, aifm_metadata=meta)
    filename = f"annex_iv_{code}_{period_label}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/run/{run_id}/export/xml")
def export_xml(run_id: str, portfolio: Optional[str] = Query(default=None), period: Optional[str] = Query(default=None)):
    """Return an ESMA AIFMD Annex IV XML report for a single portfolio."""
    from backend.services.export_service import build_xml

    r = _portfolio_results(run_id, portfolio)
    meta = _require_annex_iv_ready(run_id)
    code = portfolio or "portfolio"
    xml_bytes = build_xml(r, period=period, aifm_metadata=meta)
    filename = f"annex_iv_{code}_{run_id[:8]}.xml"
    return Response(
        content=xml_bytes,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/run/{run_id}/annex-iv")
def get_annex_iv(run_id: str, portfolio: Optional[str] = Query(default=None), period: Optional[str] = Query(default=None)):
    """Return the mapped ESMA AIFMD Annex IV data dict for UI preview."""
    from liquidity_risk_tool.reporting.annex_iv_mapper import build_annex_iv

    r = _portfolio_results(run_id, portfolio)
    return build_annex_iv(r, period_code=period or "2026Q1", aifm_metadata=_annex_iv_meta(run_id))


@router.get("/run/{run_id}/export/all")
def export_all(run_id: str, format: str = Query(default="excel")):
    """Return a zip archive containing one report per portfolio in the chosen format."""
    from backend.services.export_service import build_excel, build_pdf, build_xml

    r = _require_complete(run_id)
    portfolios: dict = r.get("portfolios", {})
    if not portfolios:
        raise HTTPException(status_code=404, detail="No portfolios found in this run")

    fmt = format.lower()
    if fmt not in ("excel", "pdf", "xml"):
        raise HTTPException(status_code=400, detail=f"Unsupported format '{format}'. Use excel, pdf, or xml.")

    # XML is the ESMA Annex IV regulatory filing — gate it on the metadata upload.
    meta = _require_annex_iv_ready(run_id) if fmt == "xml" else None

    builders = {"excel": (build_excel, "xlsx"), "pdf": (build_pdf, "pdf"), "xml": (build_xml, "xml")}
    build_fn, ext = builders[fmt]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for code, portfolio_data in portfolios.items():
            file_bytes = build_xml(portfolio_data, aifm_metadata=meta) if fmt == "xml" else build_fn(portfolio_data)
            zf.writestr(f"liquidity_report_{code}_{run_id[:8]}.{ext}", file_bytes)

    zip_bytes = buf.getvalue()
    archive_name = f"liquidity_reports_{run_id[:8]}.zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{archive_name}"'},
    )


# ---------------------------------------------------------------------------
# AIFMD II LMT Impact Simulator
# ---------------------------------------------------------------------------

class LmtConfig(BaseModel):
    """
    Typed AIFMD II LMT configuration with server-side compliance enforcement.

    All cost params are fractions in [0, 1]; day params are >= 0. The
    ``model_validator`` enforces the two MODEL.md §20.4 rules:
      1. at least ``AIFMD2_MIN_LMT_COUNT`` selectable LMTs active (suspension /
         side_pockets are always-available and do not count — only
         ``SELECTABLE_TOOLS`` are counted), and
      2. swing_pricing and dual_pricing are mutually exclusive.
    Violations raise a ``ValueError`` → FastAPI returns HTTP 422.

    ``dual_spread_frac`` is the canonical bid-spread key; ``dual_spread_bps`` is
    still accepted as a backward-compatible alias (also a fraction on the wire).
    """

    model_config = {"extra": "allow"}

    active_tools: List[str] = Field(default_factory=list)
    gate_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    suspension_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    swing_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    swing_factor_max: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    adl_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    fee_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    notice_extension_days: Optional[int] = Field(default=None, ge=0)
    in_kind_pct: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    dual_spread_frac: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    dual_spread_bps: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _enforce_aifmd2_rules(self) -> "LmtConfig":
        # Rule 1: at least AIFMD2_MIN_LMT_COUNT *selectable* LMTs must be active.
        selectable = {t for t in self.active_tools if t in SELECTABLE_TOOLS}
        if len(selectable) < AIFMD2_MIN_LMT_COUNT:
            raise ValueError(
                f"AIFMD II requires at least {AIFMD2_MIN_LMT_COUNT} selectable LMTs "
                f"active (suspension and side_pockets are always-available and do "
                f"not count); got {sorted(selectable)} from {self.active_tools}."
            )
        # Rule 2: swing_pricing and dual_pricing are mutually exclusive.
        if "swing_pricing" in self.active_tools and "dual_pricing" in self.active_tools:
            raise ValueError(
                "swing_pricing and dual_pricing are mutually exclusive anti-dilution "
                "tools — activate at most one."
            )
        return self


class LMTSimRequest(BaseModel):
    lmt_config: LmtConfig = Field(default_factory=LmtConfig)
    scenarios: Optional[List[float]] = None
    portfolio: Optional[str] = None


@router.post("/run/{run_id}/lmt-simulate")
def lmt_simulate(run_id: str, body: LMTSimRequest):
    """
    Re-run the RedemptionSimulator against stored position_buckets using a
    caller-supplied lmt_config.  No full pipeline re-run — instant response.

    The lmt_config is validated by the typed ``LmtConfig`` schema, which
    enforces the AIFMD II §20.4 compliance rules (≥2 selectable LMTs active;
    swing_pricing / dual_pricing mutually exclusive) and range-checks every
    fraction param. Violations return HTTP 422.

    lmt_config keys (all optional):
      active_tools          list[str]  — tool names to activate
      gate_threshold        float      — fraction of NAV (default 0.10)
      suspension_threshold  float      — fraction of NAV (default 0.25)
      swing_threshold       float      — fraction of NAV that triggers swing/ADL
      swing_factor_max      float      — max swing factor (fraction)
      adl_rate              float      — ADL as fraction of NAV (e.g. 0.005)
      fee_rate              float      — redemption fee as fraction (e.g. 0.002)
      notice_extension_days int        — extra days before cash due
      in_kind_pct           float      — fraction met via asset transfer (0–1)
      dual_spread_frac      float      — bid spread applied to redemption price
                                         (alias: dual_spread_bps, also a fraction)
    """
    from liquidity_risk_tool.engines.redemption_simulator import RedemptionSimulator
    from liquidity_risk_tool.models.position import Portfolio

    r = _portfolio_results(run_id, body.portfolio)

    normal_buckets = pd.DataFrame(r["position_buckets"])
    stress_buckets_raw = r.get("stress_position_buckets") or r.get("position_buckets")
    stress_buckets = pd.DataFrame(stress_buckets_raw)

    # Reconstruct minimal Portfolio stub — simulator only needs total_nav + concentration
    class _PortfolioStub:
        total_nav = r["total_nav_eur"]
        top_10_investor_concentration = r.get("top_10_concentration", 0.30)

    lmt_config_dict = body.lmt_config.model_dump(exclude_none=True)

    sim = RedemptionSimulator(
        portfolio=_PortfolioStub(),  # type: ignore[arg-type]
        liquid_profile=normal_buckets,
        stress_profile=stress_buckets,
        lmt_config=lmt_config_dict,
    )

    from backend.services.pipeline_service import _clean_records

    normal_df = sim.run(scenarios=body.scenarios, stress=False)
    stress_df  = sim.run(scenarios=body.scenarios, stress=True)

    return {
        "normal":            _clean_records(normal_df.to_dict(orient="records")),
        "stress":            _clean_records(stress_df.to_dict(orient="records")),
        "lmt_config_applied": lmt_config_dict,
    }


# ---------------------------------------------------------------------------
# Custom stress scenario
# ---------------------------------------------------------------------------

class CustomScenarioRequest(BaseModel):
    """
    A user-defined stress scenario. Field semantics mirror ``StressScenario``:

      equity_shock                multiplicative price shock on equities/ETFs,
                                  e.g. -0.10 == -10% (range [-1, 1]).
      credit_spread_shock_bps     additive credit-spread widening in basis points.
      rate_shock_bps              parallel rate shift applied to government bonds.
      liquidity_haircut_multiplier  uplift on stress haircuts (1.0 == no uplift).
      redemption_rate             fraction of NAV redeemed in the scenario (0–1).
      adv_stress_scalar           ADV collapse: 0.5 == 50% of normal volume.

    The scenario is run via the StressEngine against a freshly re-loaded
    portfolio (the engine reprices real positions, so a results-only stub will
    not do), and the resulting ScenarioResult + parameter metadata are returned
    in the same shape as the pipeline's ``stress_results`` / ``scenario_metadata``
    so the UI can append them to the existing tables.
    """

    name: str = Field(default="Custom Scenario", min_length=1, max_length=80)
    equity_shock: float = Field(default=0.0, ge=-1.0, le=1.0)
    credit_spread_shock_bps: int = Field(default=0, ge=0, le=10000)
    rate_shock_bps: int = Field(default=0, ge=-10000, le=10000)
    liquidity_haircut_multiplier: float = Field(default=1.0, ge=1.0, le=20.0)
    redemption_rate: float = Field(default=0.05, ge=0.0, le=1.0)
    adv_stress_scalar: float = Field(default=1.0, gt=0.0, le=5.0)
    portfolio: Optional[str] = None


@router.post("/run/{run_id}/custom-scenario")
def custom_scenario(run_id: str, body: CustomScenarioRequest):
    """
    Run a single user-defined stress scenario against the run's portfolio and
    return its ScenarioResult plus the scenario parameters, ready to append to
    the Scenario Results / Scenario Parameters tables.

    Unlike ``/lmt-simulate`` and ``/waterfall-optimise`` (which re-use stored
    aggregate buckets), the StressEngine reprices *real* positions, so this
    endpoint re-loads the exact same portfolio from the source CSVs that were
    persisted on the originating run. Requires those source paths to still
    exist on disk (they are retained for the process lifetime).
    """
    from pathlib import Path

    from liquidity_risk_tool.config.settings import StressScenario
    from liquidity_risk_tool.engines.stress_engine import StressEngine
    from liquidity_risk_tool.models.csv_loader import (
        load_portfolio_from_csv,
        enrich_portfolio_from_market_data,
    )
    from backend.services.pipeline_service import _clean_dict

    # Validate the run exists & is complete, and resolve the portfolio code.
    r = _portfolio_results(run_id, body.portfolio)
    codes: list[str] = _require_complete(run_id).get("portfolio_codes", [])
    code = body.portfolio or (codes[0] if codes else None)

    record = store.get(run_id)
    holdings_path = getattr(record, "holdings_path", None) if record else None
    nav_path = getattr(record, "nav_path", None) if record else None
    market_data_path = getattr(record, "market_data_path", None) if record else None

    if not holdings_path or not nav_path or not Path(holdings_path).exists() or not Path(nav_path).exists():
        raise HTTPException(
            status_code=409,
            detail="Source portfolio files for this run are no longer available. "
            "Re-run the pipeline (upload or demo) before creating a custom scenario.",
        )

    try:
        portfolio = load_portfolio_from_csv(holdings_path, nav_path, portfolio_code=code)
        if market_data_path and Path(market_data_path).exists():
            enrich_portfolio_from_market_data(portfolio, Path(market_data_path))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to re-load portfolio: {exc}") from exc

    scenario = StressScenario(
        name=body.name,
        equity_shock=body.equity_shock,
        credit_spread_shock_bps=body.credit_spread_shock_bps,
        liquidity_haircut_multiplier=body.liquidity_haircut_multiplier,
        redemption_rate=body.redemption_rate,
        adv_stress_scalar=body.adv_stress_scalar,
        rate_shock_bps=body.rate_shock_bps,
        description="User-defined custom stress scenario.",
        regulatory_basis="User-defined - not a prescribed regulatory scenario",
    )

    try:
        results = StressEngine(portfolio, scenarios=[scenario]).run_detail()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Stress run failed: {exc}") from exc

    if not results:
        raise HTTPException(status_code=500, detail="Stress run produced no result")

    result = results[0]

    scenario_meta = {
        "name": scenario.name,
        "equity_shock": scenario.equity_shock,
        "credit_spread_shock_bps": scenario.credit_spread_shock_bps,
        "rate_shock_bps": scenario.rate_shock_bps,
        "liquidity_haircut_multiplier": scenario.liquidity_haircut_multiplier,
        "redemption_rate": scenario.redemption_rate,
        "adv_stress_scalar": scenario.adv_stress_scalar,
        "description": scenario.description,
        "regulatory_basis": scenario.regulatory_basis,
        "is_worst_case": scenario.is_worst_case,
        "version": scenario.version,
    }

    return {
        "stress_result": _clean_dict(result.to_dict()),
        "scenario_metadata": _clean_dict(scenario_meta),
    }


class WaterfallOptimiseRequest(BaseModel):
    portfolio: Optional[str] = None


@router.post("/run/{run_id}/waterfall-optimise")
def waterfall_optimise(run_id: str, body: WaterfallOptimiseRequest):
    """
    Re-run the liquidation waterfall against stored stress position buckets
    using the LP optimiser (``WaterfallEngine.run_lp_optimised``) instead of the
    greedy bucket-priority sell-down. No full pipeline re-run — instant response.

    The LP minimises total liquidation time subject to raising at least the
    stored target (plus the minimum cash buffer). Falls back to the greedy
    schedule inside the engine if scipy is unavailable or the LP is infeasible.

    Returns the same shape as ``GET /run/{run_id}/waterfall``
    (``waterfall_meta``, ``waterfall``, ``waterfall_summary``) plus
    ``optimiser: "lp"`` so the caller can label the active schedule.
    """
    from liquidity_risk_tool.engines.waterfall_engine import WaterfallEngine
    from backend.services.pipeline_service import _clean_records, _clean_dict

    r = _portfolio_results(run_id, body.portfolio)

    stress_buckets_raw = r.get("stress_position_buckets") or r.get("position_buckets")
    stress_buckets = pd.DataFrame(stress_buckets_raw)

    target_eur = (r.get("waterfall_meta") or {}).get("target_eur")
    if target_eur is None:
        raise HTTPException(
            status_code=404,
            detail="No stored waterfall target for this run — run the pipeline first.",
        )

    # Reconstruct minimal Portfolio stub — the engine only reads total_nav.
    class _PortfolioStub:
        total_nav = r["total_nav_eur"]

    engine = WaterfallEngine(
        portfolio=_PortfolioStub(),  # type: ignore[arg-type]
        profile=stress_buckets,
        stress=True,
    )
    result = engine.run_lp_optimised(float(target_eur))

    return {
        "optimiser": "lp",
        "waterfall_meta": _clean_dict({
            "target_eur": result.target_eur,
            "total_proceeds_eur": result.total_proceeds_eur,
            "target_met": result.target_met,
            "days_to_target": result.days_to_target,
            "residual_shortfall_eur": result.residual_shortfall_eur,
            "settlement_days": result.settlement_days,
            "proceeds_within_horizon_eur": result.proceeds_within_horizon_eur,
            "met_eventually": result.met_eventually,
            "nav_before": result.nav_before,
            "nav_after": result.nav_after,
            "nav_impact_pct": result.nav_impact_pct,
        }),
        "waterfall": _clean_records(
            result.sell_schedule_df().to_dict(orient="records")
        ),
        "waterfall_summary": _clean_records(
            result.daily_summary_df().to_dict(orient="records")
        ),
    }
