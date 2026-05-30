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
