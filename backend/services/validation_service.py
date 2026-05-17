"""
Validation checks run against a completed pipeline results dict.
Each check returns a dict with: name, category, passed (bool), message (str).
"""
from __future__ import annotations

from typing import Any

_TOL = 1e-4


def _check(name: str, category: str, passed: bool, message: str) -> dict:
    return {"name": name, "category": category, "passed": passed, "message": message}


def run_checks(portfolio_results: dict) -> list[dict]:
    """
    Run all validation checks against a single portfolio's results dict
    (the value stored under results['portfolios'][code]).
    Returns a list of check dicts ordered by category.
    """
    results: list[dict] = []

    # ── Portfolio ──────────────────────────────────────────────────────────
    nav = portfolio_results.get("total_nav_eur")
    results.append(_check(
        "NAV is positive", "Portfolio",
        nav is not None and nav > 0,
        f"NAV = €{nav:,.0f}" if nav else "NAV is None or zero",
    ))

    buckets = portfolio_results.get("position_buckets", [])
    results.append(_check(
        "Positions non-empty", "Portfolio",
        len(buckets) > 0,
        f"{len(buckets)} position(s) in portfolio",
    ))

    unbucketed = [r for r in buckets if not r.get("bucket")]
    results.append(_check(
        "All positions have a bucket", "Portfolio",
        len(unbucketed) == 0,
        f"{len(unbucketed)} position(s) missing bucket assignment" if unbucketed else "All positions assigned to a liquidity bucket",
    ))

    bad_realisable = [
        r for r in buckets
        if r.get("realisable_value") is not None
        and r.get("market_value_eur") is not None
        and r["realisable_value"] > r["market_value_eur"] + 1
    ]
    results.append(_check(
        "Realisable value ≤ market value", "Portfolio",
        len(bad_realisable) == 0,
        f"{len(bad_realisable)} position(s) have realisable > market value" if bad_realisable else "Realisable values within market value bounds",
    ))

    # ── Liquidity metrics ──────────────────────────────────────────────────
    lm = portfolio_results.get("liquidity_metrics", {})
    t1, t3, t7 = lm.get("lcr_t1"), lm.get("lcr_t3"), lm.get("lcr_t7")

    mono_ok = (t1 is not None and t3 is not None and t7 is not None
               and t1 <= t3 + _TOL and t3 <= t7 + _TOL)
    results.append(_check(
        "LCR T+1 ≤ T+3 ≤ T+7 (monotone)", "Liquidity Metrics",
        mono_ok,
        f"LCR T+1={_pct(t1)}, T+3={_pct(t3)}, T+7={_pct(t7)}" if (t1 is not None) else "LCR values missing",
    ))

    illiquid = lm.get("illiquid_pct")
    sum_ok = (t7 is not None and illiquid is not None and t7 + illiquid <= 1.01)
    results.append(_check(
        "LCR T+7 + illiquid ≤ 100%", "Liquidity Metrics",
        sum_ok,
        f"T+7={_pct(t7)} + illiquid={_pct(illiquid)} = {_pct((t7 or 0) + (illiquid or 0))}" if t7 is not None else "Values missing",
    ))

    # ── Liquidity ladder ───────────────────────────────────────────────────
    ladder = portfolio_results.get("liquidity_ladder", [])
    if ladder:
        nav_pct_sum = sum(r.get("nav_pct", 0) or 0 for r in ladder)
        results.append(_check(
            "Normal ladder nav_pct sums to 100%", "Liquidity Ladder",
            abs(nav_pct_sum - 1.0) < _TOL,
            f"Sum = {nav_pct_sum * 100:.4f}%",
        ))
        cumul_end = ladder[-1].get("cumulative_nav_pct")
        results.append(_check(
            "Normal ladder cumulative ends at 100%", "Liquidity Ladder",
            cumul_end is not None and abs(cumul_end - 1.0) < _TOL,
            f"Cumulative end = {_pct(cumul_end)}",
        ))
        neg_buckets = [r["bucket"] for r in ladder if (r.get("nav_pct") or 0) < -_TOL]
        results.append(_check(
            "Normal ladder nav_pct all non-negative", "Liquidity Ladder",
            len(neg_buckets) == 0,
            f"Negative buckets: {neg_buckets}" if neg_buckets else "All buckets non-negative",
        ))

    stress_ladder = portfolio_results.get("stress_ladder", [])
    if stress_ladder:
        s_sum = sum(r.get("nav_pct", 0) or 0 for r in stress_ladder)
        results.append(_check(
            "Stress ladder nav_pct sums to 100%", "Liquidity Ladder",
            abs(s_sum - 1.0) < _TOL,
            f"Sum = {s_sum * 100:.4f}%",
        ))
        s_cumul_end = stress_ladder[-1].get("cumulative_nav_pct")
        results.append(_check(
            "Stress ladder cumulative ends at 100%", "Liquidity Ladder",
            s_cumul_end is not None and abs(s_cumul_end - 1.0) < _TOL,
            f"Cumulative end = {_pct(s_cumul_end)}",
        ))

    # ── Redemption ────────────────────────────────────────────────────────
    redemption = portfolio_results.get("redemption_results", [])
    if redemption:
        neg_shortfall = [r for r in redemption if (r.get("shortfall_eur") or 0) < -1]
        results.append(_check(
            "Shortfall is non-negative", "Redemption",
            len(neg_shortfall) == 0,
            f"{len(neg_shortfall)} scenario(s) with negative shortfall" if neg_shortfall else "All shortfalls ≥ 0",
        ))

        sorted_r = sorted(redemption, key=lambda r: r.get("scenario_pct", 0))
        t1_flags = [int(bool(r.get("can_meet_t1"))) for r in sorted_r]
        mono_red = all(t1_flags[i] >= t1_flags[i + 1] for i in range(len(t1_flags) - 1))
        results.append(_check(
            "Larger redemption → harder to meet T+1", "Redemption",
            mono_red,
            "can_meet_t1 is monotone non-increasing with scenario_pct" if mono_red else "can_meet_t1 is NOT monotone — unexpected result",
        ))

        row_10 = next((r for r in redemption if abs((r.get("scenario_pct") or 0) - 0.10) < 0.001), None)
        if row_10 is not None:
            gate_ok = bool(row_10.get("gate_triggered"))
            results.append(_check(
                "Gate triggered at 10% redemption", "Redemption",
                gate_ok,
                "Gate correctly triggered at 10% scenario" if gate_ok else "Gate NOT triggered at 10% — check gate threshold",
            ))

    # ── Stress engine ─────────────────────────────────────────────────────
    stress_results = portfolio_results.get("stress_results", [])
    if stress_results:
        nav_drops = [s for s in stress_results if (s.get("nav_impact_pct") or 0) > 0.001]
        results.append(_check(
            "At least one scenario reduces NAV", "Stress",
            len(nav_drops) > 0,
            f"{len(nav_drops)} scenario(s) with NAV impact > 0.1%" if nav_drops else "No scenario produces a NAV reduction — check shock parameters",
        ))

        liquid_pcts = [s.get("liquid_pct_after") for s in stress_results if s.get("liquid_pct_after") is not None]
        in_range = all(0 <= v <= 1.0 + _TOL for v in liquid_pcts)
        results.append(_check(
            "Stressed liquid_pct_after in [0, 1]", "Stress",
            in_range,
            f"All {len(liquid_pcts)} scenario liquid_pct_after values in [0, 1]" if in_range else "Some liquid_pct_after values out of range",
        ))

        base = next((s for s in stress_results if s.get("scenario_name") == "Base"), None)
        if base is not None:
            base_ok = abs(base.get("nav_impact_pct") or 0) < 0.001
            results.append(_check(
                "Base scenario has near-zero NAV impact", "Stress",
                base_ok,
                f"Base nav_impact_pct = {_pct(base.get('nav_impact_pct'))}",
            ))

    # ── Waterfall ─────────────────────────────────────────────────────────
    wf_meta = portfolio_results.get("waterfall_meta", {})
    proceeds = wf_meta.get("total_proceeds_eur")
    results.append(_check(
        "Waterfall proceeds non-negative", "Waterfall",
        proceeds is not None and proceeds >= 0,
        f"Total proceeds = €{proceeds:,.0f}" if proceeds is not None else "Proceeds missing",
    ))

    nav_impact = wf_meta.get("nav_impact_pct")
    results.append(_check(
        "Waterfall NAV impact in [0, 1]", "Waterfall",
        nav_impact is not None and 0 <= nav_impact <= 1.0 + _TOL,
        f"NAV impact = {_pct(nav_impact)}",
    ))

    return results


def _pct(v: Any) -> str:
    if v is None:
        return "—"
    return f"{float(v) * 100:.2f}%"
