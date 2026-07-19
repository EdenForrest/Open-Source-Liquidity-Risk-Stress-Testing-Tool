"""``compute_analysis`` — the shared pipeline orchestrator.

Library-level (no FastAPI/web-tier dependency) so both ``main.py`` (CLI) and
``backend/services/pipeline_service.py`` (web) can call it without pulling in
the web tier. Body is pipeline_service.py's original compute section moved
here, returning an ``AnalysisResult`` instead of a serialised dict.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..models.csv_loader import (
    load_portfolio_from_csv,
    enrich_portfolio_from_market_data,
)
from ..engines.liquidity_profiler import LiquidityProfiler
from ..engines.stress_engine import StressEngine
from ..engines.redemption_simulator import RedemptionSimulator
from ..engines.waterfall_engine import WaterfallEngine
from ..engines.leverage_engine import LeverageEngine
from ..config.settings import BUCKET_ORDER
from ..reporting.risk_metrics import RiskMetricsBuilder

from .result import AnalysisResult


def compute_analysis(
    holdings_path: str | Path,
    nav_path: str | Path,
    market_data_path: Optional[str | Path] = None,
    portfolio_code: Optional[str] = None,
    scenario_library: str = "esma",
    lmt_config: Optional[dict] = None,
    *,
    validate: bool = False,
    run_reverse_stress: bool = False,
    run_lp_waterfall: bool = False,
) -> AnalysisResult:
    """Run the full analytics pipeline and return an ``AnalysisResult``.

    ``validate``, ``run_reverse_stress`` and ``run_lp_waterfall`` are internal
    opt-in flags (not FastAPI-exposed) wired up fully in a later phase; for
    now they default to False, matching today's pipeline behaviour exactly.
    """

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

    # NOTE: reverse stress testing is intentionally NOT run here by default. It is
    # an expensive, multi-start optimisation that reprices the whole portfolio many
    # times, so running it on every pipeline call (upload / demo) made the /run
    # request hang past the client timeout. It is invoked on demand via
    # POST /run/{run_id}/reverse-stress, or here when run_reverse_stress=True.

    worst = max(stress_detail, key=lambda s: abs(s.nav_impact_pct))
    waterfall_target = portfolio.total_nav * worst.redemption_pct
    waterfall = WaterfallEngine(portfolio, stress_buckets, stress=True).run(waterfall_target)

    metrics = RiskMetricsBuilder(portfolio).build_liquidity_metrics()

    leverage = LeverageEngine(portfolio).run()

    # Build stressed ladder from the worst scenario's post-shock position detail
    # so that bucket migrations from equity/credit shocks are reflected — matching
    # the legacy GUI behaviour.
    _stressed_nav = worst.position_detail["market_value_eur"].sum() if not worst.position_detail.empty else 1.0
    _stressed_agg = (
        worst.position_detail
        .groupby("bucket")
        .agg(
            realisable_value_eur=("realisable_value", "sum"),
            market_value_eur=("market_value_eur", "sum"),
        )
        .reindex(BUCKET_ORDER, fill_value=0.0)
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

    market_data_loaded = bool(market_data_path and Path(market_data_path).exists())

    return AnalysisResult(
        portfolio=portfolio,
        normal_profiler=normal_profiler,
        stress_profiler=stress_profiler,
        redemption_normal=redemption_normal,
        redemption_stress=redemption_stress,
        stress_detail=stress_detail,
        worst=worst,
        waterfall=waterfall,
        leverage=leverage,
        metrics=metrics,
        scenario_metadata=scenario_meta,
        market_data_loaded=market_data_loaded,
        lmt_config=lmt_config,
        stress_ladder_df=_stressed_agg,
    )
