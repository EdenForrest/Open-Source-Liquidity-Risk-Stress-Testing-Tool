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
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from backend import store
from backend.schemas.analysis import (
    CustomScenarioRequest,
    LMTSimRequest,
    LmtConfig,  # noqa: F401  (kept importable from this module for back-compat)
    ReverseStressRequest,
    WaterfallOptimiseRequest,
)
from backend.services import stress_service

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
    checks = run_checks(r, annex_iv_meta=_annex_iv_meta(run_id))
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

@router.post("/run/{run_id}/lmt-simulate")
def lmt_simulate(run_id: str, body: LMTSimRequest):
    """
    Re-run the RedemptionSimulator against stored position_buckets using a
    caller-supplied lmt_config.  No full pipeline re-run — instant response.

    The lmt_config is validated by the typed ``LmtConfig`` schema, which
    enforces the AIFMD II §20.4 compliance rules (≥2 selectable LMTs active;
    swing_pricing / dual_pricing mutually exclusive) and range-checks every
    fraction param. Violations return HTTP 422.
    """
    r = _portfolio_results(run_id, body.portfolio)
    return stress_service.run_lmt_simulation(r, body.lmt_config, scenarios=body.scenarios)


# ---------------------------------------------------------------------------
# Custom stress scenario
# ---------------------------------------------------------------------------

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
    # Validate the run exists & is complete, and resolve the portfolio code.
    _portfolio_results(run_id, body.portfolio)
    codes: list[str] = _require_complete(run_id).get("portfolio_codes", [])
    code = body.portfolio or (codes[0] if codes else None)
    record = store.get(run_id)

    try:
        return stress_service.run_custom_scenario(record, code, body)
    except stress_service.PortfolioUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (stress_service.PortfolioLoadError, stress_service.StressRunError,
            stress_service.EmptyStressResult) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Reverse stress (multi-parameter breach search) — on demand only
# ---------------------------------------------------------------------------

@router.post("/run/{run_id}/reverse-stress")
def reverse_stress(run_id: str, body: ReverseStressRequest):
    """
    Run the multi-parameter reverse stress search on demand and return the
    least-severe joint shock that breaches the liquidity constraint, materialised
    as a StressScenario plus its ScenarioResult (same shape as the standard
    ``stress_results`` / ``scenario_metadata`` rows) and the raw search summary.

    This is deliberately NOT part of the main pipeline: it is an expensive,
    multi-start optimisation that reprices the whole portfolio hundreds of times.
    It is exposed only behind an explicit user action (button), and is internally
    capped (evaluation budget) so it cannot run past the client timeout.

    When the portfolio is robust across the whole plausible box (no breach is
    reachable), ``found`` is False and ``stress_result`` / ``scenario_metadata``
    are null — a meaningful resilience result, not an error.
    """
    # Validate the run exists & is complete, and resolve the portfolio code.
    _portfolio_results(run_id, body.portfolio)
    codes: list[str] = _require_complete(run_id).get("portfolio_codes", [])
    code = body.portfolio or (codes[0] if codes else None)
    record = store.get(run_id)

    try:
        return stress_service.run_reverse_stress(record, code)
    except stress_service.PortfolioUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (stress_service.PortfolioLoadError, stress_service.StressRunError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
    r = _portfolio_results(run_id, body.portfolio)

    try:
        return stress_service.run_waterfall_optimise(r)
    except stress_service.MissingWaterfallTarget as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
