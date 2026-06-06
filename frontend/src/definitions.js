// Metric definitions sourced from MODEL.md
// Key: metric id used in MetricTooltip; Value: { label, body, section }

export const DEFINITIONS = {
  // ── Dashboard KPIs ───────────────────────────────────────────────────────
  lcr_t1: {
    label: 'LCR T+1',
    section: '§5',
    body: 'Liquidity Coverage Ratio at the 1-day horizon. Fraction of NAV that can be liquidated by end of T+1 — sum of T+0 and T+1 bucket weights. Analogous to the BCBS Basel III LCR applied at fund level (ESMA LVLR Q&A).',
  },
  lcr_t3: {
    label: 'LCR T+3',
    section: '§5',
    body: 'Liquidity Coverage Ratio at the 3-day horizon. Cumulative NAV% liquidatable within T+0, T+1 and T+3 buckets. Covers settlement cycles for most exchange-traded instruments.',
  },
  lcr_t7: {
    label: 'LCR T+7',
    section: '§5',
    body: 'Liquidity Coverage Ratio at the 7-day horizon. All buckets except >T+7 (illiquid). A fund below 80% here has significant illiquid exposure relative to regulatory guidance.',
  },
  illiquid_pct: {
    label: 'Illiquid %',
    section: '§2',
    body: 'Percentage of NAV classified as >T+7 — assets that cannot be liquidated within one week under normal market conditions at the 20% ADV participation cap. Triggers a warning above 20%.',
  },
  status: {
    label: 'Status',
    section: '§13',
    body: 'Regulatory compliance flag.\n\nBREACH: T+0/T+1 liquidity < 5% NAV — fund cannot meet a 5% redemption from liquid assets; liquidity management tools (gates, side pockets) may be required under AIFMD Art. 16.\n\nWARNING: T+0/T+1 < 10% NAV — calibrated to ESMA UCITS LVLR minimum liquidity guidance.\n\nOK: compliant.',
  },
  total_nav: {
    label: 'Total NAV',
    section: '§3',
    body: 'Sum of all position market values (MV). Used as the denominator for all NAV-percentage metrics in the ladder and LCR calculations.',
  },

  // ── Days-to-liquidate percentiles ────────────────────────────────────────
  days_to_50pct: {
    label: 'Days to 50% NAV',
    section: '§11',
    body: 'Number of trading days required to liquidate 50% of NAV, selling the most-liquid positions first at the 20% ADV participation cap. Computed as the maximum execution days across positions selected until 50% cumulative realisable value is reached.',
  },
  days_to_75pct: {
    label: 'Days to 75% NAV',
    section: '§11',
    body: 'Number of trading days to liquidate 75% of NAV (greedy, most-liquid first, 20% ADV cap).',
  },
  days_to_90pct: {
    label: 'Days to 90% NAV',
    section: '§11',
    body: 'Number of trading days to liquidate 90% of NAV (greedy, most-liquid first, 20% ADV cap). A high value indicates significant tail illiquidity.',
  },
  top10_concentration: {
    label: 'Top-10 Concentration',
    section: '§12',
    body: 'Share of fund AuM held by the top-10 investors (C₁₀). Used to compute the Liquidity/Concentration Ratio (LCR T+1 ÷ C₁₀). A ratio ≥ 1.0 means the fund can cover a simultaneous full redemption by its top-10 investors from daily-liquid assets (ESMA AIFMD stress-testing guidelines §4.2).',
  },

  // ── Stress test KPIs ─────────────────────────────────────────────────────
  worst_nav_impact: {
    label: 'Worst NAV Impact',
    section: '§8.2',
    body: 'Minimum NAV delta % across all stress scenarios — ΔNAV% = (NAV* − NAV_before) / NAV_before. NAV* is the post-shock portfolio value after applying equity, credit and rate shocks (see §7). The most adverse scenario is Severe Combined (ESMA Art.28 Scenario E): −20% equity, +300 bps credit, +100 bps rates.',
  },
  worst_liq_after: {
    label: 'Worst Liquidity After',
    section: '§8.4',
    body: 'Lowest post-shock liquid % across scenarios. Defined as (RV_T0** + RV_T1**) / NAV*, using stressed realisable values in the numerator and stressed NAV in the denominator — more conservative than the pre-shock liquid %.',
  },
  max_days_to_liq: {
    label: 'Max Days to Liquidate',
    section: '§8.5',
    body: "Longest waterfall execution time across scenarios. The waterfall engine is run within each scenario to estimate how many calendar days are needed to raise (redemption rate × NAV*) in net proceeds at the scenario's compressed ADV.",
  },
  redemptions_met: {
    label: 'Redemptions Met',
    section: '§8.6',
    body: 'Number of scenarios where total net waterfall proceeds ≥ redemption target (scenario_redemption_rate × NAV*). A fund failing all scenarios cannot meet any redemption without gating or asset disposal beyond the liquid book.',
  },

  // ── Stress table columns ─────────────────────────────────────────────────
  nav_delta_pct: {
    label: 'NAV Δ%',
    section: '§8.2',
    body: 'Percentage change in NAV after applying all shocks in the scenario: ΔNAV% = (NAV* − NAV_before) / NAV_before. Losses are always negative. Driven by equity beta-scaled shocks (§7.1) and duration–convexity bond repricing (§7.2).',
  },
  equity_loss: {
    label: 'Equity Loss',
    section: '§7.1',
    body: 'Aggregate mark-to-market loss on equity and ETF positions: MV_i* = MV_i × (1 + ε × β_i), capped at −50% per position. β_i is position beta; ε is the scenario equity shock.',
  },
  credit_loss: {
    label: 'Credit Loss',
    section: '§7.2',
    body: 'Aggregate loss on bond positions from credit spread widening, computed via the duration–convexity approximation: ΔP/P ≈ −D_mod × Δy + ½ × C × Δy². Govts receive rate shock only; IG/HY/structured also receive the credit spread shock.',
  },
  liq_before: {
    label: 'Liq Before',
    section: '§8.3',
    body: 'T+0/T+1 liquid % before the scenario shock — equal to LCR T+1 on the unshocked portfolio: (MV_T0 + MV_T1) / NAV_before.',
  },
  liq_after: {
    label: 'Liq After',
    section: '§8.4',
    body: 'T+0/T+1 liquid % after the scenario shock, using stressed realisable values: (RV_T0** + RV_T1**) / NAV*. The haircut multiplier (λ) is applied — Severe Combined uses λ = 2.0×.',
  },
  days_to_liq: {
    label: 'Days to Liq.',
    section: '§8.5',
    body: "Trading days to raise the scenario redemption target via the greedy waterfall at the scenario's ADV scalar. Severe Combined uses ADV scalar σ = 0.50 (market liquidity halved).",
  },
  meets_redemption: {
    label: 'Meets Redemption',
    section: '§8.6',
    body: 'Whether total waterfall net proceeds ≥ (redemption_rate × NAV*). The redemption rate is scenario-specific — Severe Combined sets 30% of NAV.',
  },

  // ── Waterfall KPIs ───────────────────────────────────────────────────────
  wf_target: {
    label: 'Target',
    section: '§10',
    body: 'Cash target T that the waterfall must raise. Set to (redemption_rate × NAV) for the selected scenario. The greedy sell-down stops as soon as cumulative net proceeds reach T.',
  },
  wf_total_proceeds: {
    label: 'Total Proceeds',
    section: '§10.2',
    body: 'Sum of net proceeds across all sell orders: Σ netProceeds_i = Σ [sellGross_i × (1 − h_i) − marketImpact_i]. Green if target is met; red if shortfall remains.',
  },
  wf_days_to_target: {
    label: 'Days to Target',
    section: '§10.2',
    body: 'Calendar days to reach the cash target: max_i(⌈sellGross_i / (κ × ADV_i)⌉) across all executed sell orders. κ = 0.20 (MiFID II 20% ADV participation cap).',
  },
  wf_residual_shortfall: {
    label: 'Residual Shortfall',
    section: '§10.2',
    body: 'max(0, T − TotalProceeds). Non-zero when the entire liquid book cannot raise the redemption target — the fund would need to apply a gate or suspend redemptions.',
  },
  wf_nav_before: {
    label: 'NAV Before',
    section: '§10.2',
    body: 'Portfolio NAV at the start of the waterfall, before any sell orders are executed.',
  },
  wf_nav_after: {
    label: 'NAV After',
    section: '§10.2',
    body: 'NAV_after = NAV_before − Σ sellGross_i. Represents the remaining portfolio value after completing the forced sell-down.',
  },
  wf_nav_impact: {
    label: 'NAV Impact',
    section: '§10.2',
    body: 'NAVImpact% = (NAV_before − NAV_after) / NAV_before. Measures the portfolio dilution caused by the forced liquidation. High values indicate that remaining investors absorb a significant mark-down.',
  },

  // ── Redemption table columns ─────────────────────────────────────────────
  redemption_coverage: {
    label: 'Coverage',
    section: '§9.0',
    body: 'Whether the fund can meet the full redemption demand from liquid assets at each horizon (T+1 / T+3 / T+7), after retaining the minimum cash buffer. ✓ = covered; ✕ = shortfall.\n\nLiquidity available = sum of realisable values for all positions whose liquidation horizon ≤ T+n, minus the minimum cash buffer (1% NAV by default).',
  },
  redemption_gate: {
    label: 'Gate',
    section: '§9.1',
    body: 'Liquidity gate flag. Triggered when the requested redemption ≥ 10% of NAV — a common UCITS/AIFMD threshold above which the manager may pro-rate redemptions across dealing days rather than meeting them in full on the requested date.\n\nRegulatory basis: AIFMD Art. 16(2); ESMA UCITS LVLR Art. 4.',
  },
  redemption_suspension: {
    label: 'Suspension',
    section: '§9.2',
    body: 'Full suspension flag. Triggered when redemption ≥ 25% of NAV — the level at which orderly liquidation of the liquid book is unlikely and a full trading halt may be warranted to protect remaining investors.\n\nRegulatory basis: UCITS LVLR Art. 5; AIFMD Art. 16(1).',
  },
  redemption_days_to_clear: {
    label: 'Days to Clear',
    section: '§9.3',
    body: 'Estimated calendar days to raise the redemption amount via parallel sell-down of all unlocked positions, each capped at 20% of its 30-day ADV (MiFID II participation cap). Each day every liquid position contributes min(daily_cap, remaining_position_value); the simulation runs until cumulative net proceeds reach the target. Stressed regime uses a reduced ADV scalar (e.g. 0.50×) reflecting market volume collapse.',
  },

  // ── AIFMD II KPIs ────────────────────────────────────────────────────────
  commitment_leverage: {
    label: 'Commitment Leverage',
    section: '§AIFMD II',
    body: 'Exposure / NAV under the Commitment Method (CDR 231/2013 Art. 8). Locked illiquid positions (e.g. private equity, real estate under lock-up) are excluded from netting. Derivatives are converted to delta-equivalent notionals. A conservative approximation — full netting requires trade-level agreements not captured in the holdings file.',
  },
  gross_leverage: {
    label: 'Gross Leverage',
    section: '§AIFMD II',
    body: 'Sum of |market value| / NAV (Gross Method per CDR 231/2013 Art. 7). Under AIFMD II Art. 15, open-ended loan AIFs are capped at 175% and closed-ended loan AIFs at 300%. Non-loan AIFs must disclose leverage but are not subject to the same hard caps unless the fund-level limit set in the fund rules is lower.',
  },
  lmt_count: {
    label: 'LMTs Pre-selected',
    section: '§AIFMD II',
    body: 'Number of Liquidity Management Tools (LMTs) pre-selected in the fund prospectus, as required by AIFMD II Art. 16 and Annex V. At least 2 tools must be selected (excluding side pockets). Pre-selected tools here: gate, suspension, swing pricing. Each tool has activation triggers calibrated to scenario redemption rates.',
  },
  cap_utilization: {
    label: 'Cap Utilization',
    section: '§AIFMD II',
    body: 'Gross leverage as a percentage of the applicable AIFMD II leverage cap: Cap Utilization = Gross Leverage / Cap. Open-ended loan AIFs are capped at 175% NAV; closed-ended loan AIFs at 300% NAV. Non-loan AIFs have no hard regulatory cap but must disclose leverage under Art. 15.\n\nHeadroom = Cap − Gross Leverage — the remaining capacity before the cap is breached. Turns amber above 80% utilization.',
  },
  swing_factor: {
    label: 'Swing Factor',
    section: '§AIFMD II',
    body: 'NAV adjustment applied under swing pricing when net redemptions exceed the threshold (2% NAV). Swing factor ≈ average portfolio haircut × redemption %, capped at 200 bps. The adjusted NAV is paid to redeeming investors, passing transaction costs to the party causing them rather than to remaining investors. Mandatory LMT under AIFMD II Art. 16 and Annex V, Pt. 1.',
  },
  adl_bps: {
    label: 'ADL (bps)',
    section: '§AIFMD II',
    body: 'Anti-Dilution Levy: a charge on redeeming investors equal to the estimated transaction costs of meeting their redemption. Default rate 50 bps. Alternative to swing pricing; both are pre-selected LMTs under AIFMD II Art. 16. Shown when swing pricing is active to illustrate the effective cost passed to redeeming investors.',
  },

  // ── Position table columns ───────────────────────────────────────────────
  bucket: {
    label: 'Bucket',
    section: '§2',
    body: 'Liquidity bucket: worst-of (asset-class settlement bucket, ADV-implied bucket). ADV-implied days = ⌈MV_i / (0.20 × ADV_i)⌉. Buckets: T+0 (same day), T+1 (1 day), T+3 (≤3 days), T+7 (≤7 days), >T+7 (illiquid).',
  },
  haircut: {
    label: 'Haircut',
    section: '§6.1',
    body: 'Liquidation discount applied on exit: h_i = asset-class structural haircut + bid-ask half-spread (bps/20000). Models price concession from crossing the bid-ask spread and forced liquidation pressure (Amihud 2002).',
  },
  realisable_value: {
    label: 'Realisable (€)',
    section: '§6.1',
    body: 'Net proceeds achievable on orderly exit: RV_i = MV_i × (1 − h_i). This is the value actually counted in LCR and ladder metrics — always ≤ market value.',
  },
  pos_days_to_liq: {
    label: 'Days to Liq.',
    section: '§2.2',
    body: 'Trading days to fully exit this position at the 20% ADV cap: d_i = ⌈MV_i / (0.20 × ADV_i)⌉. Drives bucket assignment — if d_i > 7 the position is classified >T+7 regardless of asset class.',
  },

  ucits_5_10_40: {
    label: 'UCITS 5/10/40 Rule',
    section: '§Art. 52',
    body: 'ESMA Art. 52 UCITS Directive — Issuer Diversification Rule.\n\nNo single transferable security issuer may represent more than 10% of NAV.\n\nIssuers between 5–10% of NAV are placed in a "5–10% bucket" whose aggregate must not exceed 40% of NAV.\n\nCash positions are excluded — cash is not a transferable security and falls outside the Art. 52 issuer limits.',
  },
}
