"""
POST /api/upload      — accept holdings + NAV CSV files, kick off pipeline async
GET  /api/portfolios  — list portfolio codes available in the data/ folder
GET  /api/scenarios   — return STRESS_SCENARIOS metadata from settings
GET  /api/sample-data — download all bundled synthetic demo files as a zip
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
import tempfile
import traceback
import uuid
import zipfile
from pathlib import Path

import json as _json

from fastapi import APIRouter, Form, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, Response

from backend import store
from backend.services.pipeline_service import run_all_portfolios
from liquidity_risk_tool.config.settings import STRESS_SCENARIOS, REVOLUTION_SCENARIOS

router = APIRouter(tags=["portfolio"])
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "sample"

# Cached demo run — invalidated when any input file (holdings, NAV, market data)
# changes. Keying on the full input set rather than just the holdings mtime means
# regenerating the synthetic data always busts the cache, even when the holdings
# file alone is byte-identical to a prior run.
_DEMO_RUN_ID: str | None = None
_DEMO_INPUT_KEY: tuple[float, ...] | None = None


def _safe_filename(raw: str | None, fallback: str) -> str:
    """Strip path components and illegal characters; return safe basename."""
    if not raw:
        return fallback
    # Take only the last path component (browser may send full path on Windows)
    name = Path(raw).name
    # Replace any characters that are illegal in Windows filenames
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    return name or fallback


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------

async def _run_pipeline_bg(
    run_id: str,
    holdings_path: Path,
    nav_path: Path,
    market_data_path: Path | None,
    scenario_library: str = "esma",
    lmt_config: dict | None = None,
) -> None:
    store.update(run_id, status="running")
    # Persist the source paths so on-demand re-runs (e.g. a user-defined custom
    # stress scenario) can re-load the *exact* same portfolio positions. The
    # StressEngine reprices real positions, so a stub cannot stand in for the
    # portfolio — we must be able to re-load it from these CSVs.
    store.update(
        run_id,
        holdings_path=str(holdings_path),
        nav_path=str(nav_path),
        market_data_path=str(market_data_path) if market_data_path else None,
    )
    try:
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None,
            lambda: run_all_portfolios(holdings_path, nav_path, market_data_path, scenario_library=scenario_library, lmt_config=lmt_config),
        )
        store.update(run_id, status="complete", results=results)
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("Pipeline failed for run %s\n%s", run_id, tb)
        store.update(run_id, status="error", error=f"{type(exc).__name__}: {exc}")
        # Only failed runs clean up their uploaded temp files immediately — there
        # is no successful run to re-load from. Files in the bundled data dir are
        # never deleted. Successful uploaded runs retain their temp files for the
        # process lifetime so custom-scenario re-runs can re-load the portfolio.
        for p in [holdings_path, nav_path, market_data_path]:
            if p and p.exists() and DATA_DIR not in p.parents:
                p.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/upload")
async def upload_portfolio(
    holdings_file: UploadFile = File(...),
    nav_file: UploadFile = File(...),
    market_data_file: UploadFile | None = File(default=None),
    scenario_library: str = Form(default="esma"),
    lmt_config_json: str = Form(default="{}"),
    annex_iv_meta_json: str = Form(default=""),
):
    """Upload MVHOL + NAV CSV files and trigger the full pipeline run.

    Optional ``annex_iv_meta_json`` carries AIFM/AIF/share-class identification
    used to enable Annex IV regulatory export (JSON: aifm_lei, aifm_national_code,
    aifm_name, reporting_member_state, aif_lei, aif_national_code, share_classes).
    When omitted, Annex IV preview still works but XML/Excel export is blocked.
    """
    try:
        lmt_config = _json.loads(lmt_config_json) if lmt_config_json else {}
    except _json.JSONDecodeError:
        lmt_config = {}
    try:
        annex_iv_meta = _json.loads(annex_iv_meta_json) if annex_iv_meta_json else None
        if not isinstance(annex_iv_meta, dict):
            annex_iv_meta = None
    except _json.JSONDecodeError:
        annex_iv_meta = None
    try:
        tmp_dir = Path(tempfile.mkdtemp())

        holdings_path = tmp_dir / _safe_filename(holdings_file.filename, "holdings.csv")
        holdings_path.write_bytes(await holdings_file.read())
        logger.info("Saved holdings to %s", holdings_path)

        nav_path = tmp_dir / _safe_filename(nav_file.filename, "nav.csv")
        nav_path.write_bytes(await nav_file.read())
        logger.info("Saved NAV to %s", nav_path)

        market_data_path: Path | None = None
        if market_data_file and market_data_file.filename:
            market_data_path = tmp_dir / _safe_filename(market_data_file.filename, "market_data.csv")
            market_data_path.write_bytes(await market_data_file.read())
            logger.info("Saved market data to %s", market_data_path)

        run_id = str(uuid.uuid4())
        store.create(run_id)
        if annex_iv_meta is not None:
            store.update(run_id, annex_iv_meta=annex_iv_meta)

        asyncio.create_task(
            _run_pipeline_bg(run_id, holdings_path, nav_path, market_data_path, scenario_library=scenario_library, lmt_config=lmt_config)
        )

        return {"run_id": run_id, "status": "pending"}

    except Exception as exc:
        logger.exception("Upload failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/portfolios")
def list_portfolios():
    """List portfolio codes inferred from HOLDINGS_*.csv files in data/."""
    if not DATA_DIR.exists():
        return {"portfolios": []}
    files = sorted(DATA_DIR.glob("HOLDINGS_*.csv"))
    codes: list[str] = []
    for f in files:
        # Try reading the PortfolioCode column header from first data row
        try:
            import csv
            with open(f, newline="", encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    code = row.get("PortfolioCode") or row.get("Portfolio Code") or ""
                    if code and code not in codes:
                        codes.append(code)
                    break
        except Exception:
            codes.append(f.stem)
    return {"portfolios": codes, "files": [f.name for f in files]}


@router.post("/demo")
async def run_demo():
    """Run the pipeline on bundled synthetic data and return the run_id.
    Result is cached — subsequent calls return the same run_id instantly.
    Pairs HOLDINGS and NAV files by matching timestamp prefix to prevent mismatches.
    """
    global _DEMO_RUN_ID, _DEMO_INPUT_KEY

    # Find best matched HOLDINGS+NAV pair by shared timestamp prefix
    holdings_files = sorted(DATA_DIR.glob("HOLDINGS_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    market_data = DATA_DIR / "market_data_ALL.csv"

    if not holdings_files:
        raise HTTPException(status_code=404, detail="No synthetic demo data found in data/ directory")

    # Match NAV file to the newest HOLDINGS by shared timestamp suffix
    holdings_file = holdings_files[0]
    timestamp = holdings_file.stem.replace("HOLDINGS_", "")
    nav_file = DATA_DIR / f"NAV_{timestamp}.csv"
    if not nav_file.exists():
        # Fallback: pick newest NAV file
        nav_files = sorted(DATA_DIR.glob("NAV_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not nav_files:
            raise HTTPException(status_code=404, detail="No NAV demo data found in data/ directory")
        nav_file = nav_files[0]

    # Cache key: mtimes of every input that feeds the pipeline. If any changes
    # (e.g. the synthetic data is regenerated), the key differs and we recompute.
    current_key = tuple(
        f.stat().st_mtime
        for f in (holdings_file, nav_file, market_data)
        if f.exists()
    )
    if _DEMO_RUN_ID is not None and _DEMO_INPUT_KEY == current_key:
        record = store.get(_DEMO_RUN_ID)
        if record and record.status in ("complete", "running", "pending"):
            return {"run_id": _DEMO_RUN_ID, "status": record.status}

    run_id = str(uuid.uuid4())
    _DEMO_RUN_ID = run_id
    _DEMO_INPUT_KEY = current_key
    store.create(run_id)

    asyncio.create_task(
        _run_pipeline_bg(
            run_id,
            holdings_file,
            nav_file,
            market_data if market_data.exists() else None,
        )
    )

    return {"run_id": run_id, "status": "pending"}


@router.get("/scenarios")
def list_scenarios(library: str = "esma"):
    """Return stress scenario definitions. library: esma | revolution | all"""
    from fastapi import Query as _Q
    if library == "revolution":
        source = REVOLUTION_SCENARIOS
    elif library == "all":
        source = STRESS_SCENARIOS + REVOLUTION_SCENARIOS
    else:
        source = STRESS_SCENARIOS
    return {
        "library": library,
        "scenarios": [
            {
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
            }
            for sc in source
        ]
    }


@router.get("/sample-data")
def download_sample_data():
    """Bundle the synthetic demo dataset into a single zip download.

    Includes the latest Holdings + matching NAV pair, the consolidated market
    data, and a synthetic Annex IV metadata file. All files are synthetic —
    safe to share publicly.
    """
    if not DATA_DIR.exists():
        raise HTTPException(status_code=404, detail="No synthetic demo data found")

    # Latest HOLDINGS file, then the NAV that shares its timestamp suffix
    holdings_files = sorted(
        DATA_DIR.glob("HOLDINGS_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not holdings_files:
        raise HTTPException(status_code=404, detail="No synthetic holdings data found")

    holdings_file = holdings_files[0]
    timestamp = holdings_file.stem.replace("HOLDINGS_", "")
    nav_file = DATA_DIR / f"NAV_{timestamp}.csv"
    if not nav_file.exists():
        nav_files = sorted(
            DATA_DIR.glob("NAV_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        nav_file = nav_files[0] if nav_files else None

    # (source path, name inside the zip) — skip any that are missing
    candidates = [
        (holdings_file, holdings_file.name),
        (nav_file, nav_file.name if nav_file else None),
        (DATA_DIR / "market_data_ALL.csv", "market_data_ALL.csv"),
        (DATA_DIR / "annex_iv_meta.json", "annex_iv_meta.json"),
    ]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for src, arcname in candidates:
            if src is None or arcname is None or not src.exists():
                continue
            zf.writestr(arcname, src.read_bytes())

    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="sample_data.zip"'},
    )
