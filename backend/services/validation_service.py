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
        nav_drops = [s for s in stress_results if (s.get("nav_impact_pct") or 0) < -0.001]
        results.append(_check(
            "At least one scenario reduces NAV", "Stress",
            len(nav_drops) > 0,
            f"{len(nav_drops)} scenario(s) produce a NAV reduction" if nav_drops else "No scenario produces a NAV reduction — check shock parameters",
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

    # ── Market Data ───────────────────────────────────────────────────────
    # ADV defaults per asset class (from csv_loader._ADV_DEFAULTS)
    _ADV_DEFAULTS = {
        "cash": 1e12, "money_market": 50_000_000, "government_bond": 30_000_000,
        "ig_corporate_bond": 5_000_000, "hy_corporate_bond": 1_000_000,
        "listed_equity": 10_000_000, "etf": 10_000_000, "structured_credit": 500_000,
        "real_estate": 0, "private_equity": 0, "hedge_fund": 0,
        "future": 200_000_000, "option": 10_000_000,
    }
    tradeable = [
        b for b in buckets
        if b.get("asset_class") not in ("cash", "real_estate", "private_equity", "hedge_fund")
        and b.get("market_value_eur", 0) > 0
    ]
    if tradeable:
        # 1. ADV populated (non-zero) for all tradeable positions
        no_adv = [b.get("isin", b.get("name", "?")) for b in tradeable if not (b.get("adv_30d") or 0) > 0]
        results.append(_check(
            "ADV populated for all tradeable positions", "Market Data",
            len(no_adv) == 0,
            f"{len(no_adv)} position(s) have zero or missing ADV: {no_adv[:5]}" if no_adv
            else f"ADV present for all {len(tradeable)} tradeable positions",
        ))

        # 2. At least some ADV values differ from asset-class defaults (market data was ingested)
        default_adv_count = sum(
            1 for b in tradeable
            if abs((b.get("adv_30d") or 0) - _ADV_DEFAULTS.get(b.get("asset_class", ""), 5_000_000)) < 1
        )
        enriched_count = len(tradeable) - default_adv_count
        results.append(_check(
            "ADV enriched from market data (not all defaults)", "Market Data",
            enriched_count > 0,
            f"{enriched_count}/{len(tradeable)} positions have market-data ADV (vs defaults)"
            if enriched_count > 0
            else "All ADV values equal class defaults — market data file may not have been loaded",
        ))

        # 3. Bid-ask spread populated for liquid positions (non-illiquid asset classes)
        liquid_pos = [b for b in tradeable if b.get("bucket") != ">T+7"]
        no_spread = [b.get("isin", "?") for b in liquid_pos if b.get("bid_ask_spread_bps") is None]
        results.append(_check(
            "Bid-ask spread present for liquid positions", "Market Data",
            len(no_spread) == 0,
            f"{len(no_spread)} liquid position(s) missing bid-ask spread: {no_spread[:5]}" if no_spread
            else f"Bid-ask spread populated for all {len(liquid_pos)} liquid positions",
        ))

        # 4. FX rates applied for non-EUR positions
        non_eur = [b for b in buckets if b.get("currency") and b.get("currency") != "EUR"
                   and b.get("market_value_eur", 0) > 0]
        bad_fx = [b.get("isin", "?") for b in non_eur
                  if not (b.get("fx_rate") or 0) > 0 or abs((b.get("fx_rate") or 0) - 1.0) < 1e-6]
        results.append(_check(
            "FX rates applied for non-EUR positions", "Market Data",
            len(bad_fx) == 0,
            f"{len(bad_fx)} non-EUR position(s) with missing or 1.0 FX rate: {bad_fx[:5]}" if bad_fx
            else f"FX rates applied for all {len(non_eur)} non-EUR positions" if non_eur
            else "No non-EUR positions in portfolio",
        ))

        # 5. Duration present for bond positions
        bonds = [b for b in buckets if b.get("asset_class") in
                 ("government_bond", "ig_corporate_bond", "hy_corporate_bond", "structured_credit")
                 and b.get("market_value_eur", 0) > 0]
        if bonds:
            no_dur = [b.get("isin", "?") for b in bonds if b.get("duration") is None]
            results.append(_check(
                "Duration present for bond positions", "Market Data",
                len(no_dur) == 0,
                f"{len(no_dur)} bond(s) missing duration: {no_dur[:5]}" if no_dur
                else f"Duration populated for all {len(bonds)} bond positions",
            ))

        # 6. Beta present for equity positions
        equities = [b for b in buckets if b.get("asset_class") in ("listed_equity", "etf")
                    and b.get("market_value_eur", 0) > 0]
        if equities:
            no_beta = [b.get("isin", "?") for b in equities if b.get("beta") is None]
            results.append(_check(
                "Beta present for equity positions", "Market Data",
                len(no_beta) == 0,
                f"{len(no_beta)} equity position(s) missing beta: {no_beta[:5]}" if no_beta
                else f"Beta populated for all {len(equities)} equity positions",
            ))

        # 7. Realisable value reflects spread cost (realisable < market value for non-cash)
        non_cash = [b for b in buckets if b.get("asset_class") != "cash"
                    and b.get("market_value_eur", 0) > 0 and b.get("realisable_value") is not None]
        all_equal = all(abs((b.get("realisable_value") or 0) - (b.get("market_value_eur") or 0)) < 1
                        for b in non_cash)
        results.append(_check(
            "Realisable value reflects bid-ask haircut", "Market Data",
            not all_equal,
            "All realisable values equal market values — spread cost not being applied"
            if all_equal
            else f"Bid-ask haircut applied across {len(non_cash)} non-cash positions",
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

    # ── Reconciliation ────────────────────────────────────────────────────
    # Compute position_sum once — used by stress and redemption checks below.
    # The stress engine and redemption simulator both use position_sum as their
    # internal NAV basis (not the NAV file total), so cross-module checks must
    # compare against position_sum, not total_nav_eur.
    position_sum = sum(r.get("market_value_eur") or 0 for r in buckets)

    # 1. NAV vs sum of position market values (informational — NAV file and MVHOL
    #    are separate data sources whose totals may legitimately differ by design).
    if nav is not None and buckets:
        discrepancy = abs(position_sum - nav) / nav if nav else 0
        results.append(_check(
            "NAV vs position sum (≤25% tolerance)", "Reconciliation",
            discrepancy <= 0.25,
            f"NAV €{nav:,.0f} vs position sum €{position_sum:,.0f} — diff {discrepancy * 100:.3f}%",
        ))

    # 2. Waterfall nav_before matches total_nav_eur
    wf_nav_before = wf_meta.get("nav_before")
    if nav is not None and wf_nav_before is not None:
        wf_nav_ok = abs(wf_nav_before - nav) / nav < 0.001 if nav else wf_nav_before == 0
        results.append(_check(
            "Waterfall nav_before matches total NAV", "Reconciliation",
            wf_nav_ok,
            f"Waterfall nav_before €{wf_nav_before:,.0f} vs total_nav_eur €{nav:,.0f}",
        ))

    # 3. All stress nav_before values match position_sum (the engine baseline)
    if position_sum > 0 and stress_results:
        bad_nav = [s["scenario_name"] for s in stress_results
                   if s.get("nav_before") is not None
                   and abs(s["nav_before"] - position_sum) / position_sum > 0.001]
        results.append(_check(
            "All stress nav_before values match position sum", "Reconciliation",
            len(bad_nav) == 0,
            f"Mismatch in: {bad_nav}" if bad_nav else f"All {len(stress_results)} scenarios use consistent position-sum baseline",
        ))

    # 4–7. LCR metrics vs ladder bucket sums
    BUCKET_ORDER = ["T+0", "T+1", "T+3", "T+7", ">T+7"]
    if ladder and t1 is not None:
        nav_by_bucket = {r["bucket"]: (r.get("nav_pct") or 0) for r in ladder if r.get("bucket")}
        calc_t1 = sum(nav_by_bucket.get(b, 0) for b in ["T+0", "T+1"])
        results.append(_check(
            "LCR T+1 matches ladder (T+0 + T+1)", "Reconciliation",
            abs(calc_t1 - t1) < _TOL,
            f"Metric {_pct(t1)} vs ladder sum {_pct(calc_t1)} — diff {abs(calc_t1 - t1) * 100:.4f}%",
        ))

        if t3 is not None:
            calc_t3 = sum(nav_by_bucket.get(b, 0) for b in ["T+0", "T+1", "T+3"])
            results.append(_check(
                "LCR T+3 matches ladder (T+0 + T+1 + T+3)", "Reconciliation",
                abs(calc_t3 - t3) < _TOL,
                f"Metric {_pct(t3)} vs ladder sum {_pct(calc_t3)} — diff {abs(calc_t3 - t3) * 100:.4f}%",
            ))

        if t7 is not None:
            calc_t7 = sum(nav_by_bucket.get(b, 0) for b in ["T+0", "T+1", "T+3", "T+7"])
            results.append(_check(
                "LCR T+7 matches ladder (T+0 through T+7)", "Reconciliation",
                abs(calc_t7 - t7) < _TOL,
                f"Metric {_pct(t7)} vs ladder sum {_pct(calc_t7)} — diff {abs(calc_t7 - t7) * 100:.4f}%",
            ))

        if illiquid is not None:
            calc_illiquid = nav_by_bucket.get(">T+7", 0)
            results.append(_check(
                "Illiquid % matches ladder >T+7 bucket", "Reconciliation",
                abs(calc_illiquid - illiquid) < _TOL,
                f"Metric {_pct(illiquid)} vs ladder {_pct(calc_illiquid)} — diff {abs(calc_illiquid - illiquid) * 100:.4f}%",
            ))

    # 8. Redemption amounts: redemption_eur ≈ scenario_pct × position_sum
    #    The redemption simulator computes redemption_eur from the position sum
    #    (profile["market_value_eur"].sum()), not the NAV file total.
    if position_sum > 0 and redemption:
        bad_amounts = []
        for r in redemption:
            pct_val = r.get("scenario_pct")
            red_eur = r.get("redemption_eur")
            if pct_val is not None and red_eur is not None:
                expected = pct_val * position_sum
                if expected > 0 and abs(red_eur - expected) / expected > 0.001:
                    bad_amounts.append(f"{_pct(pct_val)}: expected €{expected:,.0f}, got €{red_eur:,.0f}")
        results.append(_check(
            "Redemption amounts = scenario% × position sum", "Reconciliation",
            len(bad_amounts) == 0,
            f"Mismatches: {'; '.join(bad_amounts)}" if bad_amounts else f"All {len(redemption)} redemption amounts reconcile",
        ))

    # 9. Stress result count matches scenario_metadata count
    scenario_meta = portfolio_results.get("scenario_metadata", [])
    if scenario_meta or stress_results:
        count_ok = len(stress_results) == len(scenario_meta)
        results.append(_check(
            "Stress result count matches scenario metadata", "Reconciliation",
            count_ok,
            f"{len(stress_results)} results vs {len(scenario_meta)} scenarios defined",
        ))

    # 10. Scenario severity: liquidity_haircut_multiplier non-decreasing
    if len(scenario_meta) > 1:
        multipliers = [s.get("liquidity_haircut_multiplier") for s in scenario_meta]
        valid_multipliers = [m for m in multipliers if m is not None]
        severity_ok = all(valid_multipliers[i] <= valid_multipliers[i + 1] + _TOL
                          for i in range(len(valid_multipliers) - 1))
        results.append(_check(
            "Scenario haircut multipliers non-decreasing", "Reconciliation",
            severity_ok,
            f"Multipliers: {[round(m, 2) for m in valid_multipliers]}" if not severity_ok
            else f"Haircut severity is monotone ({len(valid_multipliers)} scenarios)",
        ))

    return results


def _pct(v: Any) -> str:
    if v is None:
        return "—"
    return f"{float(v) * 100:.2f}%"
