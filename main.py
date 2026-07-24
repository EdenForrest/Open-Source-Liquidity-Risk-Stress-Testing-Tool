"""
main.py — Liquidity Risk & Stress Testing Tool
-----------------------------------------------
Entry point.  Runs the full pipeline:
  1. Load portfolio
  2. Normal + stress liquidity profiling
  3. Redemption scenario analysis
  4. Bps-based stress testing
  5. Liquidation waterfall (worst-case scenario)
  6. Risk report (console + Excel + JSON)
  7. Chart pack

Usage
-----
  python main.py                         # full run, sample portfolio
  python main.py --no-charts             # skip charting
  python main.py --scenario "Severe Combined"  # single stress scenario
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)

# ---------------------------------------------------------------------------
# Ensure package is importable when run from project root
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))

from liquidity_risk_tool.models          import (
    build_sample_portfolio,
    find_latest_files,
    enrich_portfolio_from_market_data,
)
from liquidity_risk_tool.engines         import (
    LiquidityProfiler,
    RedemptionSimulator,
    StressEngine,
    WaterfallEngine,
    validate_portfolio,
)
from liquidity_risk_tool.analysis        import compute_analysis
from liquidity_risk_tool.reporting       import ReportBuilder
from liquidity_risk_tool.visualization   import ChartPack
from liquidity_risk_tool.config          import STRESS_SCENARIOS, LIQUIDITY_BREACH_THRESHOLD


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    charts: bool = True,
    scenario_filter: str | None = None,
    mvhol_path: str | None = None,
    nav_path: str | None = None,
    portfolio_code: str | None = None,
    use_sample: bool = False,
    use_lp: bool = False,
) -> None:

    print("\n" + "=" * 72)
    print("  LRI Liquidity Risk & Stress Testing Tool  v1.0")
    print("  Luxembourg ManCo  |  UCITS / AIFMD compliant")
    print("=" * 72)

    # ── 1. Portfolio + pipeline ──────────────────────────────────────────
    print("\n[1/7] Loading portfolio...")
    scenarios = STRESS_SCENARIOS
    if scenario_filter:
        scenarios = [s for s in scenarios if scenario_filter.lower() in s.name.lower()]

    _mkt_path = Path(__file__).parent / "data" / "market_data_ALL.csv"

    if use_sample:
        # Sample-mode has no CSV inputs, so it can't go through compute_analysis
        # (which always loads a portfolio from holdings/NAV CSV paths). Kept as a
        # separate lightweight path that mirrors compute_analysis's steps directly.
        portfolio = build_sample_portfolio()
        if _mkt_path.exists():
            enrich_portfolio_from_market_data(portfolio, _mkt_path)
            print(f"      Market data: enriched from {_mkt_path.name}")
        else:
            print(f"      Market data: {_mkt_path.name} not found — using defaults")

        errors = validate_portfolio(portfolio, strict=False)
        normal_profiler = LiquidityProfiler(portfolio, stress=False).run()
        stress_profiler = LiquidityProfiler(portfolio, stress=True).run()
        sim = RedemptionSimulator(
            portfolio,
            normal_profiler.position_buckets,
            stress_profiler.position_buckets,
            lmt_config={"active_tools": []},
        )
        redemption_normal = sim.run(stress=False)
        redemption_stress = sim.run(stress=True)
        engine = StressEngine(portfolio, scenarios)
        stress_results = engine.run_detail()
        rev = engine.run_reverse_stress(target_liquid_pct=LIQUIDITY_BREACH_THRESHOLD)
        worst = max(stress_results, key=lambda s: abs(s.nav_impact_pct))
        waterfall_engine = WaterfallEngine(portfolio, worst.position_detail, stress=True)
        target = portfolio.total_nav * 0.30
        wf_result = waterfall_engine.run_lp_optimised(target) if use_lp else waterfall_engine.run(target)
        artifacts = None
    else:
        try:
            if mvhol_path and nav_path:
                mv, nv = mvhol_path, nav_path
            else:
                mv, nv = find_latest_files()
                print(f"      Auto-discovered: {mv.name} / {nv.name}")
        except FileNotFoundError as exc:
            print(f"      CSV files not found ({exc}). Falling back to sample portfolio.")
            return run_pipeline(
                charts=charts, scenario_filter=scenario_filter, use_sample=True, use_lp=use_lp,
            )

        result = compute_analysis(
            mv, nv,
            market_data_path=_mkt_path,
            portfolio_code=portfolio_code,
            scenarios=scenarios,
            validate=True,
            run_reverse_stress=True,
            run_lp_waterfall=use_lp,
        )
        if result.market_data_loaded:
            print(f"      Market data: enriched from {_mkt_path.name}")
        else:
            print(f"      Market data: {_mkt_path.name} not found — using defaults")

        portfolio = result.portfolio
        errors = result.validation
        normal_profiler = result.normal_profiler
        stress_profiler = result.stress_profiler
        redemption_normal = result.redemption_normal
        redemption_stress = result.redemption_stress
        stress_results = result.stress_detail
        rev = result.reverse_stress
        worst = result.worst
        wf_result = result.waterfall
        target = portfolio.total_nav * worst.redemption_pct
        artifacts = result

    nav = portfolio.total_nav
    print(f"      Fund : {portfolio.fund_name}")
    print(f"      Date : {portfolio.reporting_date.date()}")
    print(f"      NAV  : EUR {nav:,.0f}  ({len(portfolio.positions)} positions)")

    # ── 1b. Validation ───────────────────────────────────────────────────
    if errors:
        print(f"      Validation warnings ({len(errors)}):")
        for e in errors:
            print(f"        ! {e}")
    else:
        print("      Validation: OK")

    # ── 2. Liquidity Profiling ───────────────────────────────────────────
    print("\n[2/7] Running liquidity profiling (normal + stress)...")
    ladder_normal = normal_profiler.liquidity_ladder()
    ladder_stress = stress_profiler.liquidity_ladder()

    print("      Normal liquidity ladder:")
    for _, row in ladder_normal.iterrows():
        print(f"        {row['bucket']:<8} {row['nav_pct']*100:5.1f}%  (cumul: {row['cumulative_nav_pct']*100:.1f}%)")

    flags = normal_profiler.regulatory_flags()
    if flags["breach"]:
        print("      *** LIQUIDITY BREACH FLAG RAISED ***")
    elif flags["warning"]:
        print("      *** Liquidity Warning Flag Raised ***")

    # ── 3. Redemption Scenarios ──────────────────────────────────────────
    print("\n[3/7] Simulating redemption scenarios...")
    for _, row in redemption_normal.iterrows():
        pct = int(row["scenario_pct"] * 100)
        status = "OK" if row["can_meet_t7"] else "SHORTFALL"
        print(f"      {pct:>3}% redemption (normal): T+1={row['can_meet_t1']} T+7={row['can_meet_t7']}  [{status}]")

    # ── 4. Stress Testing ────────────────────────────────────────────────
    print("\n[4/7] Running stress tests...")
    for r in stress_results:
        impact = r.nav_impact_pct * 100
        liquid = r.liquid_pct_after * 100
        print(
            f"      {r.scenario_name:<30}  "
            f"NAV: {impact:+.1f}%   "
            f"Liquid: {liquid:.1f}%   "
            f"Days: {r.time_to_liquidate_days:.0f}   "
            f"Redemption met: {r.can_meet_redemption}"
        )

    # ── 4b. Reverse Stress ───────────────────────────────────────────────
    print("\n      Reverse stress test (min equity shock to breach liquidity threshold):")
    if rev["found"]:
        print(
            f"      Breach at equity shock = {rev['breach_shock_level']*100:.1f}%  "
            f"(liquid {rev['liquid_pct_at_breach']*100:.1f}%  "
            f"in {rev['iterations']} iterations)"
        )
    else:
        print("      No breach found within search bounds — portfolio is robust.")

    # ── 5. Waterfall (worst-case scenario) ───────────────────────────────
    print("\n[5/7] Running liquidation waterfall (30% NAV redemption, severe stress)...")
    if use_lp:
        print("      (LP-optimised sell scheduler)")

    print(f"      Target      : EUR {target:,.0f}")
    print(f"      Raised      : EUR {wf_result.total_proceeds_eur:,.0f}")
    print(f"      Target met  : {wf_result.target_met}")
    print(f"      Days needed : {wf_result.days_to_target:.1f}")
    print(f"      NAV impact  : {wf_result.nav_impact_pct*100:.1f}%")
    if wf_result.residual_shortfall_eur > 0:
        print(f"      *** SHORTFALL: EUR {wf_result.residual_shortfall_eur:,.0f} ***")

    # ── 6. Risk Report ───────────────────────────────────────────────────
    print("\n[6/7] Building risk report...")
    report = ReportBuilder(portfolio, output_dir="output", artifacts=artifacts)
    report.build()
    report.print_summary()
    report.to_excel("liquidity_risk_report.xlsx")
    report.to_json("liquidity_risk_report.json")

    # ── 7. Charts ────────────────────────────────────────────────────────
    if charts:
        print("[7/7] Generating chart pack...")
        cp = ChartPack(output_dir="output/charts")

        cp.plot_liquidity_ladder(ladder_normal, ladder_stress, fund_name=portfolio.fund_name)
        print("      Chart 1/6: Liquidity Ladder")

        redemption_normal["regime"] = "normal"
        redemption_stress["regime"] = "stress"
        redeem_all = pd.concat([redemption_normal, redemption_stress], ignore_index=True)
        cp.plot_redemption_heatmap(redeem_all)
        print("      Chart 2/6: Redemption Heatmap")

        stress_df = pd.DataFrame([r.to_dict() for r in stress_results])
        cp.plot_stress_nav_impact(stress_df)
        print("      Chart 3/6: Stress NAV Impact")

        cp.plot_time_to_liquidate(normal_profiler.position_buckets, nav)
        print("      Chart 4/6: Time-to-Liquidate")

        cp.plot_portfolio_composition(normal_profiler.position_buckets, nav)
        print("      Chart 5/6: Portfolio Composition")

        sell_df = wf_result.sell_schedule_df()
        if not sell_df.empty:
            cp.plot_waterfall_schedule(sell_df, target)
            print("      Chart 6/6: Waterfall Schedule")

        print(f"\n  Charts saved to: output/charts/")

    print("\n  Run complete.\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LRI Liquidity Risk & Stress Testing Tool",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--no-charts",  action="store_true", help="Skip chart generation")
    parser.add_argument("--scenario",   type=str, default=None, help="Filter to a single stress scenario by name")
    parser.add_argument("--mvhol",      type=str, default=None, help="Path to MVHOL CSV file (default: latest on Desktop)")
    parser.add_argument("--nav",        type=str, default=None, help="Path to NAV CSV file (default: latest on Desktop)")
    parser.add_argument("--portfolio",  type=str, default=None, help="Portfolio code to load (default: first found)")
    parser.add_argument("--sample",     action="store_true",    help="Use hardcoded sample portfolio instead of CSV files")
    parser.add_argument("--lp",         action="store_true",    help="Use LP-optimised waterfall sell scheduler (requires scipy)")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_pipeline(
        charts=not args.no_charts,
        scenario_filter=args.scenario,
        mvhol_path=args.mvhol,
        nav_path=args.nav,
        portfolio_code=args.portfolio,
        use_sample=args.sample,
        use_lp=args.lp,
    )
