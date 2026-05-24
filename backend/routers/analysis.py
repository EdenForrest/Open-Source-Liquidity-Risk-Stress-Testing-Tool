"""
GET /api/run/{run_id}/status       — poll run completion
GET /api/run/{run_id}/portfolios   — list portfolio codes in a completed run
GET /api/run/{run_id}/liquidity    — liquidity metrics + ladder + positions
GET /api/run/{run_id}/stress       — stress scenario results
GET /api/run/{run_id}/redemption   — redemption coverage matrix
GET /api/run/{run_id}/waterfall    — day-by-day sell schedule
GET /api/run/{run_id}/report       — full results as JSON download
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from backend import store

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
def export_excel(run_id: str, portfolio: Optional[str] = Query(default=None)):
    """Return a structured Excel (.xlsx) workbook for a single portfolio."""
    from backend.services.export_service import build_excel

    r = _portfolio_results(run_id, portfolio)
    code = portfolio or "portfolio"
    xlsx_bytes = build_excel(r)
    filename = f"liquidity_report_{code}_{run_id[:8]}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
