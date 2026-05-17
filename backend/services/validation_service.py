"""
Strict validation checks run against a completed pipeline results dict.
Each check returns a dict with: name, category, passed (bool), message (str).

Validation philosophy: expose reality, not manufactured correctness.
- Zero tolerance on reconciliation checks unless explicitly noted.
- Missing data = FAIL. No fallbacks, no defaults, no rounding away discrepancies.
- Messages show raw inputs, formula used, computed value, expected value, and delta.
"""
from __future__ import annotations

from typing import Any

_FLOAT_ZERO = 0.01   # cents — smallest meaningful delta, not a tolerance band
_LCR_TOL = 1e-4      # floating-point accumulation only; not a data-quality tolerance


def _check(name: str, category: str, passed: bool, message: str) -> dict:
    return {"name": name, "category": category, "passed": passed, "message": message}


def _pct(v: Any) -> str:
    if v is None:
        return "—"
    return f"{float(v) * 100:.4f}%"


def _eur(v: Any) -> str:
    if v is None:
        return "—"
    return f"€{float(v):,.2f}"


def run_checks(portfolio_results: dict) -> list[dict]:
    """
    Run all validation checks against a single portfolio's results dict.
    Returns a list of check dicts ordered by category.
    """
    results: list[dict] = []

    # ── Portfolio ──────────────────────────────────────────────────────────
    nav = portfolio_results.get("total_nav_eur")
    results.append(_check(
        "NAV is positive", "Portfolio",
        nav is not None and nav > 0,
        f"NAV = {_eur(nav)}" if nav else "NAV is None or zero",
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
        f"{len(unbucketed)} position(s) missing bucket assignment" if unbucketed
        else "All positions assigned to a liquidity bucket",
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
        f"{len(bad_realisable)} position(s) have realisable > market value" if bad_realisable
        else "Realisable values within market value bounds",
    ))

    # ── Liquidity metrics ──────────────────────────────────────────────────
    lm = portfolio_results.get("liquidity_metrics", {})
    t1, t3, t7 = lm.get("lcr_t1"), lm.get("lcr_t3"), lm.get("lcr_t7")

    mono_ok = (t1 is not None and t3 is not None and t7 is not None
               and t1 <= t3 + _LCR_TOL and t3 <= t7 + _LCR_TOL)
    results.append(_check(
        "LCR T+1 ≤ T+3 ≤ T+7 (monotone)", "Liquidity Metrics",
        mono_ok,
        f"LCR T+1={_pct(t1)}, T+3={_pct(t3)}, T+7={_pct(t7)}" if t1 is not None
        else "LCR values missing",
    ))

    illiquid = lm.get("illiquid_pct")
    sum_ok = (t7 is not None and illiquid is not None and t7 + illiquid <= 1.0 + _LCR_TOL)
    results.append(_check(
        "LCR T+7 + illiquid ≤ 100%", "Liquidity Metrics",
        sum_ok,
        f"T+7={_pct(t7)} + illiquid={_pct(illiquid)} = {_pct((t7 or 0) + (illiquid or 0))}"
        if t7 is not None else "Values missing",
    ))

    # ── Liquidity ladder ───────────────────────────────────────────────────
    ladder = portfolio_results.get("liquidity_ladder", [])
    if ladder:
        nav_pct_sum = sum(r.get("nav_pct", 0) or 0 for r in ladder)
        results.append(_check(
            "Normal ladder nav_pct sums to 100%", "Liquidity Ladder",
            abs(nav_pct_sum - 1.0) < _LCR_TOL,
            f"Sum = {nav_pct_sum * 100:.4f}%",
        ))
        cumul_end = ladder[-1].get("cumulative_nav_pct")
        results.append(_check(
            "Normal ladder cumulative ends at 100%", "Liquidity Ladder",
            cumul_end is not None and abs(cumul_end - 1.0) < _LCR_TOL,
            f"Cumulative end = {_pct(cumul_end)}",
        ))
        neg_buckets = [r["bucket"] for r in ladder if (r.get("nav_pct") or 0) < -_LCR_TOL]
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
            abs(s_sum - 1.0) < _LCR_TOL,
            f"Sum = {s_sum * 100:.4f}%",
        ))
        s_cumul_end = stress_ladder[-1].get("cumulative_nav_pct")
        results.append(_check(
            "Stress ladder cumulative ends at 100%", "Liquidity Ladder",
            s_cumul_end is not None and abs(s_cumul_end - 1.0) < _LCR_TOL,
            f"Cumulative end = {_pct(s_cumul_end)}",
        ))

    # ── Redemption ────────────────────────────────────────────────────────
    redemption = portfolio_results.get("redemption_results", [])
    if redemption:
        neg_shortfall = [r for r in redemption if (r.get("shortfall_eur") or 0) < -1]
        results.append(_check(
            "Shortfall is non-negative", "Redemption",
            len(neg_shortfall) == 0,
            f"{len(neg_shortfall)} scenario(s) with negative shortfall" if neg_shortfall
            else "All shortfalls ≥ 0",
        ))

        sorted_r = sorted(redemption, key=lambda r: r.get("scenario_pct", 0))
        t1_flags = [int(bool(r.get("can_meet_t1"))) for r in sorted_r]
        mono_red = all(t1_flags[i] >= t1_flags[i + 1] for i in range(len(t1_flags) - 1))
        results.append(_check(
            "Larger redemption → harder to meet T+1", "Redemption",
            mono_red,
            "can_meet_t1 is monotone non-increasing with scenario_pct" if mono_red
            else "can_meet_t1 is NOT monotone — unexpected result",
        ))

        row_10 = next((r for r in redemption if abs((r.get("scenario_pct") or 0) - 0.10) < 0.001), None)
        if row_10 is not None:
            gate_ok = bool(row_10.get("gate_triggered"))
            results.append(_check(
                "Gate triggered at 10% redemption", "Redemption",
                gate_ok,
                "Gate correctly triggered at 10% scenario" if gate_ok
                else "Gate NOT triggered at 10% — check gate threshold",
            ))

    # ── Stress engine ─────────────────────────────────────────────────────
    stress_results = portfolio_results.get("stress_results", [])
    if stress_results:
        nav_drops = [s for s in stress_results if (s.get("nav_impact_pct") or 0) < -0.001]
        results.append(_check(
            "At least one scenario reduces NAV", "Stress",
            len(nav_drops) > 0,
            f"{len(nav_drops)} scenario(s) produce a NAV reduction" if nav_drops
            else "No scenario produces a NAV reduction — check shock parameters",
        ))

        liquid_pcts = [s.get("liquid_pct_after") for s in stress_results
                       if s.get("liquid_pct_after") is not None]
        in_range = all(0 <= v <= 1.0 + _LCR_TOL for v in liquid_pcts)
        results.append(_check(
            "Stressed liquid_pct_after in [0, 1]", "Stress",
            in_range,
            f"All {len(liquid_pcts)} scenario liquid_pct_after values in [0, 1]" if in_range
            else "Some liquid_pct_after values out of range",
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
        no_adv = [b.get("isin", b.get("name", "?")) for b in tradeable
                  if not (b.get("adv_30d") or 0) > 0]
        results.append(_check(
            "ADV populated for all tradeable positions", "Market Data",
            len(no_adv) == 0,
            f"{len(no_adv)} position(s) have zero or missing ADV: {no_adv[:5]}" if no_adv
            else f"ADV present for all {len(tradeable)} tradeable positions",
        ))

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

        liquid_pos = [b for b in tradeable if b.get("bucket") != ">T+7"]
        no_spread = [b.get("isin", "?") for b in liquid_pos if b.get("bid_ask_spread_bps") is None]
        results.append(_check(
            "Bid-ask spread present for liquid positions", "Market Data",
            len(no_spread) == 0,
            f"{len(no_spread)} liquid position(s) missing bid-ask spread: {no_spread[:5]}" if no_spread
            else f"Bid-ask spread populated for all {len(liquid_pos)} liquid positions",
        ))

        # FX Integrity — strict: FAIL if FX missing or FX=1.0 for any non-EUR position
        non_eur = [b for b in buckets if b.get("currency") and b.get("currency") != "EUR"
                   and b.get("market_value_eur", 0) > 0]
        fx_failures = []
        for b in non_eur:
            isin = b.get("isin", "?")
            ccy = b.get("currency", "?")
            fx = b.get("fx_rate")
            if fx is None:
                fx_failures.append(f"{isin}|{ccy}|MISSING")
            elif abs(fx - 1.0) < 1e-6:
                fx_failures.append(f"{isin}|{ccy}|fx=1.0 (default — not applied)")

        if non_eur:
            results.append(_check(
                "FX rates applied for non-EUR positions", "Market Data",
                len(fx_failures) == 0,
                (f"FAIL — {len(fx_failures)} position(s) with invalid FX rate: "
                 + "; ".join(fx_failures[:5]))
                if fx_failures
                else f"FX rates applied for all {len(non_eur)} non-EUR positions",
            ))
        else:
            results.append(_check(
                "FX rates applied for non-EUR positions", "Market Data",
                True,
                "No non-EUR positions in portfolio",
            ))

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
        f"Total proceeds = {_eur(proceeds)}" if proceeds is not None else "Proceeds missing",
    ))

    nav_impact = wf_meta.get("nav_impact_pct")
    results.append(_check(
        "Waterfall NAV impact in [0, 1]", "Waterfall",
        nav_impact is not None and 0 <= nav_impact <= 1.0 + _LCR_TOL,
        f"NAV impact = {_pct(nav_impact)}",
    ))

    # ── Reconciliation ────────────────────────────────────────────────────
    # position_sum: sum of MVHOL market values (the engine's internal NAV basis)
    position_sum = sum(r.get("market_value_eur") or 0 for r in buckets)

    # 1. NAV vs position sum — exact reconciliation.
    #    Formula: diff = |position_sum - NAV| / NAV
    #    Any non-zero difference exposes a data integrity problem.
    if nav is not None and buckets:
        diff_eur = position_sum - nav
        diff_pct = diff_eur / nav if nav else 0
        passed = abs(diff_eur) < _FLOAT_ZERO
        results.append(_check(
            "NAV vs position sum (exact reconciliation)", "Reconciliation",
            passed,
            (f"NAV={_eur(nav)} | position_sum=Σ(MV×FX)={_eur(position_sum)} | "
             f"Δ={_eur(diff_eur)} ({diff_pct * 100:.4f}%) — "
             + ("PASS" if passed else "FAIL: input files are not reconciled")),
        ))

    # 2. Waterfall nav_before matches total_nav_eur
    wf_nav_before = wf_meta.get("nav_before")
    if nav is not None and wf_nav_before is not None:
        wf_diff = wf_nav_before - nav
        wf_ok = abs(wf_diff) < _FLOAT_ZERO
        results.append(_check(
            "Waterfall nav_before = total NAV", "Reconciliation",
            wf_ok,
            (f"nav_before={_eur(wf_nav_before)} | total_nav_eur={_eur(nav)} | "
             f"Δ={_eur(wf_diff)} — " + ("PASS" if wf_ok else "FAIL")),
        ))

    # 3. Stress nav_before values must equal total_nav_eur (authoritative NAV).
    #    Formula: nav_before == total_nav_eur for every scenario.
    #    A discrepancy means the stress engine used a different baseline than the NAV file.
    if nav is not None and stress_results:
        bad_stress_nav = []
        for s in stress_results:
            nb = s.get("nav_before")
            if nb is not None:
                delta = nb - nav
                if abs(delta) >= _FLOAT_ZERO:
                    bad_stress_nav.append(
                        f"{s['scenario_name']}: nav_before={_eur(nb)} vs NAV={_eur(nav)} Δ={_eur(delta)}"
                    )
        results.append(_check(
            "All stress nav_before values = total NAV", "Reconciliation",
            len(bad_stress_nav) == 0,
            ("FAIL — engine used a different baseline than the authoritative NAV file:\n  "
             + "\n  ".join(bad_stress_nav))
            if bad_stress_nav
            else f"All {len(stress_results)} scenarios use nav_before = {_eur(nav)}",
        ))

    # 4–7. LCR metrics vs ladder bucket sums
    BUCKET_ORDER = ["T+0", "T+1", "T+3", "T+7", ">T+7"]
    if ladder and t1 is not None:
        nav_by_bucket = {r["bucket"]: (r.get("nav_pct") or 0) for r in ladder if r.get("bucket")}

        calc_t1 = sum(nav_by_bucket.get(b, 0) for b in ["T+0", "T+1"])
        delta_t1 = abs(calc_t1 - t1)
        results.append(_check(
            "LCR T+1 matches ladder (T+0 + T+1)", "Reconciliation",
            delta_t1 < _LCR_TOL,
            (f"metric={_pct(t1)} | ladder_sum(T+0+T+1)={_pct(calc_t1)} | "
             f"Δ={delta_t1 * 100:.6f}%"),
        ))

        if t3 is not None:
            calc_t3 = sum(nav_by_bucket.get(b, 0) for b in ["T+0", "T+1", "T+3"])
            delta_t3 = abs(calc_t3 - t3)
            results.append(_check(
                "LCR T+3 matches ladder (T+0 + T+1 + T+3)", "Reconciliation",
                delta_t3 < _LCR_TOL,
                (f"metric={_pct(t3)} | ladder_sum(T+0..T+3)={_pct(calc_t3)} | "
                 f"Δ={delta_t3 * 100:.6f}%"),
            ))

        if t7 is not None:
            calc_t7 = sum(nav_by_bucket.get(b, 0) for b in ["T+0", "T+1", "T+3", "T+7"])
            delta_t7 = abs(calc_t7 - t7)
            results.append(_check(
                "LCR T+7 matches ladder (T+0 through T+7)", "Reconciliation",
                delta_t7 < _LCR_TOL,
                (f"metric={_pct(t7)} | ladder_sum(T+0..T+7)={_pct(calc_t7)} | "
                 f"Δ={delta_t7 * 100:.6f}%"),
            ))

        if illiquid is not None:
            calc_illiquid = nav_by_bucket.get(">T+7", 0)
            delta_illiq = abs(calc_illiquid - illiquid)
            results.append(_check(
                "Illiquid % matches ladder >T+7 bucket", "Reconciliation",
                delta_illiq < _LCR_TOL,
                (f"metric={_pct(illiquid)} | ladder[>T+7]={_pct(calc_illiquid)} | "
                 f"Δ={delta_illiq * 100:.6f}%"),
            ))

    # 8. Redemption amounts: expected = total_nav_eur × scenario_pct
    #    Formula: expected = NAV × pct; diff = |actual - expected| / expected
    #    Any difference → FAIL (exposes engine baseline mismatch if it used position_sum)
    if nav is not None and nav > 0 and redemption:
        bad_amounts = []
        for r in redemption:
            pct_val = r.get("scenario_pct")
            red_eur = r.get("redemption_eur")
            if pct_val is not None and red_eur is not None:
                expected = pct_val * nav
                delta = red_eur - expected
                if abs(delta) >= _FLOAT_ZERO:
                    bad_amounts.append(
                        f"{_pct(pct_val)}: expected=NAV×{_pct(pct_val)}={_eur(expected)}, "
                        f"actual={_eur(red_eur)}, Δ={_eur(delta)}"
                    )
        results.append(_check(
            "Redemption amounts = NAV × scenario%", "Reconciliation",
            len(bad_amounts) == 0,
            ("FAIL — engine used a different NAV baseline:\n  " + "\n  ".join(bad_amounts))
            if bad_amounts
            else f"All {len(redemption)} redemption amounts = {_eur(nav)} × scenario%",
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
    #     Flag inconsistencies — do NOT reorder or fix.
    if len(scenario_meta) > 1:
        multipliers = [s.get("liquidity_haircut_multiplier") for s in scenario_meta]
        valid_multipliers = [m for m in multipliers if m is not None]
        violations = [
            f"position {i}: {valid_multipliers[i]:.2f} > {valid_multipliers[i + 1]:.2f}"
            for i in range(len(valid_multipliers) - 1)
            if valid_multipliers[i] > valid_multipliers[i + 1] + _LCR_TOL
        ]
        severity_ok = len(violations) == 0
        results.append(_check(
            "Scenario haircut multipliers non-decreasing", "Reconciliation",
            severity_ok,
            (f"FAIL — sequence not monotone: {[round(m, 2) for m in valid_multipliers]}; "
             f"violations: {violations}")
            if not severity_ok
            else f"Monotone: {[round(m, 2) for m in valid_multipliers]}",
        ))

    return results
