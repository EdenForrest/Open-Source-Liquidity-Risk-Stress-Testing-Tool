"""
Stress / LMT / waterfall on-demand orchestration, extracted from
``backend.routers.analysis``.

The router used to inline engine orchestration, portfolio CSV re-loading,
throw-away ``_PortfolioStub`` adapters and hand-built metadata dicts directly in
its POST handlers. That logic lives here now, as stateless module-level functions
(matching ``pipeline_service`` / ``export_service`` / ``validation_service``):
dicts in, JSON-safe dicts out.

This module is deliberately **HTTP-agnostic** — it knows nothing about FastAPI.
Failure modes are surfaced as the domain exceptions below; the router maps them
to the appropriate HTTP status codes:

    PortfolioUnavailable    -> 409  (source CSVs gone)
    PortfolioLoadError      -> 500  (re-load failed)
    StressRunError          -> 500  (engine raised)
    EmptyStressResult       -> 500  (engine produced nothing)
    MissingWaterfallTarget  -> 404  (no stored waterfall target)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from liquidity_risk_tool.config.settings import StressScenario
from liquidity_risk_tool.engines.stress_engine import StressEngine
from liquidity_risk_tool.engines.reverse_stress_engine import ReverseStressEngine
from liquidity_risk_tool.engines.waterfall_engine import WaterfallEngine
from liquidity_risk_tool.engines.redemption_simulator import RedemptionSimulator
from liquidity_risk_tool.models.csv_loader import (
    load_portfolio_from_csv,
    enrich_portfolio_from_market_data,
)
from backend.services.pipeline_service import _clean_dict, _clean_records


# ---------------------------------------------------------------------------
# Domain exceptions (HTTP-agnostic; the router owns the status-code mapping)
# ---------------------------------------------------------------------------

class PortfolioUnavailable(Exception):
    """Source portfolio CSVs for the run are no longer on disk (-> 409)."""


class PortfolioLoadError(Exception):
    """Re-loading the portfolio from its source CSVs failed (-> 500)."""


class StressRunError(Exception):
    """A stress / reverse-stress engine run raised (-> 500)."""


class EmptyStressResult(Exception):
    """A stress run completed but produced no ScenarioResult (-> 500)."""


class MissingWaterfallTarget(Exception):
    """No stored waterfall target for the run — pipeline must run first (-> 404)."""


# ---------------------------------------------------------------------------
# Shared private helpers
# ---------------------------------------------------------------------------

def _reload_portfolio(record, portfolio_code):
    """
    Resolve the source CSV paths off the run ``record``, verify they still exist,
    and load + market-data-enrich the ``Portfolio``.

    Both ``run_custom_scenario`` and ``run_reverse_stress`` need the *real*
    positions (the StressEngine reprices them), so a results-only stub will not
    do — they must re-load from the exact CSVs persisted on the originating run.

    Raises ``PortfolioUnavailable`` if the source files are gone, or
    ``PortfolioLoadError`` if loading them fails.
    """
    holdings_path = getattr(record, "holdings_path", None) if record else None
    nav_path = getattr(record, "nav_path", None) if record else None
    market_data_path = getattr(record, "market_data_path", None) if record else None

    if not holdings_path or not nav_path or not Path(holdings_path).exists() or not Path(nav_path).exists():
        raise PortfolioUnavailable(
            "Source portfolio files for this run are no longer available. "
            "Re-run the pipeline (upload or demo) before this action."
        )

    try:
        portfolio = load_portfolio_from_csv(holdings_path, nav_path, portfolio_code=portfolio_code)
        if market_data_path and Path(market_data_path).exists():
            enrich_portfolio_from_market_data(portfolio, Path(market_data_path))
    except Exception as exc:
        raise PortfolioLoadError(f"Failed to re-load portfolio: {exc}") from exc

    return portfolio


def _scenario_meta(scenario) -> dict:
    """
    Project a ``StressScenario`` to the 11-field metadata dict that the UI
    appends to its Scenario Parameters table. Shared by the custom-scenario and
    reverse-stress paths; ``version`` uses ``getattr(..., "")`` so it serves a
    scenario synthesised by the reverse-stress search (which may omit it).
    """
    return {
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
        "version": getattr(scenario, "version", ""),
    }


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

def run_custom_scenario(record, portfolio_code, params) -> dict:
    """
    Run a single user-defined stress scenario against a freshly re-loaded
    portfolio and return its ScenarioResult plus the scenario parameters.

    ``params`` is a ``CustomScenarioRequest``. Returns the same shape the
    endpoint returns: ``{"stress_result": ..., "scenario_metadata": ...}``.
    """
    portfolio = _reload_portfolio(record, portfolio_code)

    scenario = StressScenario(
        name=params.name,
        equity_shock=params.equity_shock,
        credit_spread_shock_bps=params.credit_spread_shock_bps,
        liquidity_haircut_multiplier=params.liquidity_haircut_multiplier,
        redemption_rate=params.redemption_rate,
        adv_stress_scalar=params.adv_stress_scalar,
        rate_shock_bps=params.rate_shock_bps,
        description="User-defined custom stress scenario.",
        regulatory_basis="User-defined - not a prescribed regulatory scenario",
    )

    try:
        results = StressEngine(portfolio, scenarios=[scenario]).run_detail()
    except Exception as exc:
        raise StressRunError(f"Stress run failed: {exc}") from exc

    if not results:
        raise EmptyStressResult("Stress run produced no result")

    result = results[0]

    return {
        "stress_result": _clean_dict(result.to_dict()),
        "scenario_metadata": _clean_dict(_scenario_meta(scenario)),
    }


def run_reverse_stress(
    record,
    portfolio_code,
    use_native: bool = True,
    ceilings: dict | None = None,
) -> dict:
    """
    Run the multi-parameter reverse stress search and return the least-severe
    joint shock that breaches the liquidity constraint, materialised as a
    StressScenario plus its ScenarioResult (same shape as ``stress_results`` /
    ``scenario_metadata``) and the raw search summary.

    When the portfolio is robust across the whole plausible box (no breach is
    reachable), ``found`` is False and ``stress_result`` / ``scenario_metadata``
    are null — a meaningful resilience result, not an error.

    ``use_native`` selects the compiled C++ search core when it is available;
    the native and Python paths are numerically identical, so this is purely a
    performance choice. The returned ``engine_used`` reports which one actually
    ran ("native" only when the caller asked for it *and* the core is built).

    ``ceilings`` optionally overrides the severe endpoint of one or more axes
    (keys are axis names, e.g. ``equity_shock``); omitted axes keep their
    calibrated defaults. The values are assumed already bounded by the request
    schema. When supplied, the Python search path is forced — the compiled core
    is built against the fixed DEFAULT_AXES box and does not honour overrides.
    """
    from liquidity_risk_tool.engines._reverse_stress_native import native_available
    from liquidity_risk_tool.engines.reverse_stress_engine import axes_with_ceilings

    portfolio = _reload_portfolio(record, portfolio_code)

    overrides = {k: v for k, v in (ceilings or {}).items() if v is not None}
    axes = axes_with_ceilings(overrides) if overrides else None
    # The native core hardcodes the default box; only the Python path can search
    # a user-resized box, so a ceiling override forces Python.
    if overrides:
        use_native = False

    try:
        stress_engine = StressEngine(portfolio)
        engine = ReverseStressEngine(stress_engine, axes=axes, use_native=use_native)
        scenario, scenario_result, reverse_result = engine.run()
    except Exception as exc:
        raise StressRunError(f"Reverse stress run failed: {exc}") from exc

    engine_used = "native" if (use_native and native_available()) else "python"

    if scenario is None or scenario_result is None:
        # Robust across the plausible box — no breach found.
        return {
            "found": False,
            "engine_used": engine_used,
            "stress_result": None,
            "scenario_metadata": None,
            "reverse_result": _clean_dict(reverse_result.to_dict()),
        }

    # A "frontier" breach only materialises at (or within a whisker of) the
    # severe corner of the plausible box — its worst lever being the maximal
    # liquidity_haircut_multiplier of 2.8. The fund is practically resilient and
    # this is the implausible extreme, not a realistic scenario to plan around.
    # Policy: surface a breach only when it can be reached with haircut *under*
    # the 2.8 ceiling; if the only breach hugs that ceiling, report it as
    # not-found-frontier so the UI shows "no realistic reverse stress testing
    # scenario" rather than a misleading corner-of-the-box row.
    if getattr(reverse_result, "plausibility", None) == "frontier":
        return {
            "found": False,
            "frontier": True,
            "engine_used": engine_used,
            "stress_result": None,
            "scenario_metadata": None,
            "reverse_result": _clean_dict(reverse_result.to_dict()),
        }

    return {
        "found": True,
        "engine_used": engine_used,
        "stress_result": _clean_dict(scenario_result.to_dict()),
        "scenario_metadata": _clean_dict(_scenario_meta(scenario)),
        "reverse_result": _clean_dict(reverse_result.to_dict()),
    }


def run_waterfall_optimise(portfolio_results: dict) -> dict:
    """
    Re-run the liquidation waterfall against stored stress position buckets using
    the LP optimiser (``WaterfallEngine.run_lp_optimised``) instead of the greedy
    bucket-priority sell-down. No full pipeline re-run — instant response.

    ``portfolio_results`` is the single-portfolio sub-dict of a completed run.
    Returns the same shape as ``GET /run/{run_id}/waterfall``
    (``waterfall_meta``, ``waterfall``, ``waterfall_summary``) plus
    ``optimiser: "lp"``. Raises ``MissingWaterfallTarget`` if the run has no
    stored target.
    """
    r = portfolio_results

    stress_buckets_raw = r.get("stress_position_buckets") or r.get("position_buckets")
    stress_buckets = pd.DataFrame(stress_buckets_raw)

    target_eur = (r.get("waterfall_meta") or {}).get("target_eur")
    if target_eur is None:
        raise MissingWaterfallTarget(
            "No stored waterfall target for this run — run the pipeline first."
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


def run_lmt_simulation(portfolio_results: dict, cfg, scenarios=None) -> dict:
    """
    Re-run the RedemptionSimulator against stored ``position_buckets`` using a
    caller-supplied ``LmtConfig``. No full pipeline re-run — instant response.

    ``portfolio_results`` is the single-portfolio sub-dict of a completed run;
    ``cfg`` is a validated ``LmtConfig`` (AIFMD II §20.4 rules already enforced
    at the schema layer); ``scenarios`` is the optional list of redemption rates.
    Returns ``{"normal": ..., "stress": ..., "lmt_config_applied": ...}``.
    """
    r = portfolio_results

    normal_buckets = pd.DataFrame(r["position_buckets"])
    stress_buckets_raw = r.get("stress_position_buckets") or r.get("position_buckets")
    stress_buckets = pd.DataFrame(stress_buckets_raw)

    # Reconstruct minimal Portfolio stub — simulator only needs total_nav + concentration
    class _PortfolioStub:
        total_nav = r["total_nav_eur"]
        top_10_investor_concentration = r.get("top_10_concentration", 0.30)

    lmt_config_dict = cfg.model_dump(exclude_none=True)

    sim = RedemptionSimulator(
        portfolio=_PortfolioStub(),  # type: ignore[arg-type]
        liquid_profile=normal_buckets,
        stress_profile=stress_buckets,
        lmt_config=lmt_config_dict,
    )

    normal_df = sim.run(scenarios=scenarios, stress=False)
    stress_df = sim.run(scenarios=scenarios, stress=True)

    return {
        "normal": _clean_records(normal_df.to_dict(orient="records")),
        "stress": _clean_records(stress_df.to_dict(orient="records")),
        "lmt_config_applied": lmt_config_dict,
    }
