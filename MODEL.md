# Liquidity Risk & Stress Testing Tool — Model Documentation

**Version:** 1.2  
**Last reviewed:** 2026-05-20  
**Regulatory basis:** ESMA MMFR Article 28 / UCITS LVLR / AIFMD Annex IV / AIFMD II (Directive (EU) 2024/927)  
**Purpose:** Complete audit trail for every metric displayed in the GUI, its mathematical definition, and the theoretical framework used to derive it.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Liquidity Bucket Assignment](#2-liquidity-bucket-assignment)
3. [Normal Liquidity Ladder](#3-normal-liquidity-ladder)
4. [Stressed Liquidity Ladder](#4-stressed-liquidity-ladder)
5. [Liquidity Coverage Ratios (LCR)](#5-liquidity-coverage-ratios-lcr)
6. [Realisable Value and Haircuts](#6-realisable-value-and-haircuts)
7. [Stress Scenarios — Shock Mechanics](#7-stress-scenarios--shock-mechanics)
8. [Stress Test Metrics (Stress Tab)](#8-stress-test-metrics-stress-tab)
9. [Redemption Scenario Analysis](#9-redemption-scenario-analysis)
10. [Liquidation Waterfall](#10-liquidation-waterfall)
11. [Days-to-Liquidate Percentiles](#11-days-to-liquidate-percentiles)
12. [Concentration Risk and Liquidity/Concentration Ratio](#12-concentration-risk-and-liquidityconcentration-ratio)
13. [Regulatory Flags](#13-regulatory-flags)
14. [Reverse Stress Testing](#14-reverse-stress-testing)
15. [Synthetic Data Generation](#15-synthetic-data-generation)
16. [Asset-Class Parameter Table](#16-asset-class-parameter-table)
17. [Scenario Parameter Table](#17-scenario-parameter-table)
18. [AIFMD II — Directive (EU) 2024/927](#18-aifmd-ii--directive-eu-2024927)

---

## 1. Architecture Overview

The tool is structured as a pipeline of five analytical layers:

```
Portfolio (positions_df)
    │
    ▼
LiquidityProfiler          — assigns buckets, computes haircuts, ADV caps
    │
    ├─► Normal ladder       → Dashboard KPIs, LCR metrics
    └─► Stressed profiler   → fed into StressEngine
            │
            ▼
        StressEngine        — shocks NAV, re-runs profiler on shocked portfolio
            │
            ├─► ScenarioResult.position_detail  → Stressed Liquidity Ladder
            └─► WaterfallEngine                 → Forced sell-down schedule
                    │
                    ▼
            RedemptionSimulator  — coverage ratios across 4 redemption sizes
```

**Key invariant:** The stressed liquidity ladder is derived from `ScenarioResult.position_detail` (the Severe Combined scenario), which already contains shocked market values, ADV-compressed bucket assignments, and stress haircuts. It is never re-built from the original unshocked portfolio.

---

## 2. Liquidity Bucket Assignment

**Code:** `LiquidityProfiler._assign_buckets()` — `liquidity_profiler.py`

### 2.1 Asset-class settlement bucket

Each asset class has a structural settlement bucket based on market microstructure convention (e.g., government bonds settle T+1 under TARGET2-Securities). See the full mapping in [Section 16](#16-asset-class-parameter-table).

### 2.2 ADV-implied bucket

For each position $i$, the number of trading days required to exit the full position at the regulatory participation cap is:

$$d_i = \left\lceil \frac{MV_i}{\kappa \cdot \sigma \cdot ADV_i} \right\rceil$$

Where:
- $MV_i$ = market value of position $i$ in EUR
- $ADV_i$ = 30-day average daily volume in EUR
- $\sigma$ = ADV stress scalar (= 1.0 in normal regime, scenario-specific under stress; Severe Combined uses $\sigma = 0.50$)
- $\kappa$ = maximum ADV participation rate = **0.20** (20%), sourced from MiFID II large-in-scale thresholds and ESMA liquidity stress-testing guidelines

This gives a numeric day count which is then mapped to a bucket:

| $d_i$      | Bucket |
|------------|--------|
| $d_i \leq 0$ | T+0  |
| $d_i \leq 1$ | T+1  |
| $d_i \leq 3$ | T+3  |
| $d_i \leq 7$ | T+7  |
| $d_i > 7$    | >T+7 |

### 2.3 Effective bucket (worst-of rule)

The effective bucket is the **worse** (less liquid) of the asset-class bucket and the ADV-implied bucket:

$$\text{bucket}_i = \arg\max_{\text{rank}} \{ \text{bucket}_{\text{asset class}},\ \text{bucket}_{\text{ADV}} \}$$

Where rank order is T+0 < T+1 < T+3 < T+7 < >T+7 (integer ranks 0–4).

**Theoretical basis:** This follows ESMA's Guideline 2 on liquidity classification (ESMA34-39-897), which requires that size-driven illiquidity is captured even when the asset class is inherently liquid. A large concentrated equity position may be structurally T+1 but practically >T+7 at 20% ADV participation — classifying it as T+1 would overstate short-term liquidity.

**Override:** A position-level `bucket_override` (set in the CSV input) takes precedence over both rules above. Locked positions are always classified as >T+7.

---

## 3. Normal Liquidity Ladder

**Code:** `LiquidityProfiler.liquidity_ladder()` — `liquidity_profiler.py`  
**Displayed:** Dashboard tab → Liquidity Ladder table; Charts tab → Liquidity Ladder chart (blue bars)

For each bucket $b$:

$$MV_b = \sum_{i \in b} MV_i \qquad RV_b = \sum_{i \in b} RV_i$$

$$\mathrm{navPct}_b = \frac{MV_b}{NAV} \qquad \mathrm{cumulativeNavPct}_b = \sum_{b' \leq b} \mathrm{navPct}_{b'}$$

Where $NAV$ is the position-sum NAV (sum of all $MV_i$ across all positions). This is used as the ladder denominator rather than the NAV file total to ensure LCR fractions are on the same basis as the realisable values computed from position data. The position-sum and the NAV file total must reconcile exactly (Δ < €0.01); the validation service rejects any discrepancy as a FAIL — no tolerance band is applied.

---

## 4. Stressed Liquidity Ladder

**Code:** `gui.py` pipeline thread, lines 1432–1449; source data from `StressEngine._apply_scenario()` — `stress_engine.py`  
**Displayed:** Charts tab → Liquidity Ladder chart (red bars)

The stressed ladder represents the distribution of portfolio liquidity under the **Severe Combined** scenario — the most adverse scenario defined in the regulatory framework (ESMA MMFR Art.28 Scenario E). It is derived in four stages:

### Stage 1: NAV shock

Market values are shocked according to the scenario shocks (see Section 7). Let $MV_i^*$ denote the shocked market value of position $i$.

### Stage 2: ADV compression and re-bucketing

The ADV stress scalar $\sigma_{\text{Severe}} = 0.50$ is applied to all positions:

$$ADV_i^* = \sigma \cdot ADV_i = 0.50 \cdot ADV_i$$

$$d_i^* = \left\lceil \frac{MV_i^*}{\kappa \cdot ADV_i^*} \right\rceil = \left\lceil \frac{MV_i^*}{0.20 \times 0.50 \times ADV_i} \right\rceil$$

Because $ADV_i^*$ is halved, $d_i^*$ is approximately double $d_i$, causing positions to migrate to worse (less liquid) buckets.

### Stage 3: Stress haircut multiplier

The scenario-level haircut multiplier $\lambda_{\text{Severe}} = 2.0$ is applied on top of the stress haircut:

$$h_i^{**} = \min\!\left(0.99,\ \lambda \cdot h_i^*\right) \qquad RV_i^{**} = MV_i^* \cdot \left(1 - h_i^{**}\right)$$

### Stage 4: Ladder aggregation

The stressed ladder is aggregated from `worst.position_detail` — the final `position_buckets` DataFrame produced by the stress engine for the Severe Combined scenario:

$$MV_b^* = \sum_{i \in b^*} MV_i^* \qquad NAV^* = \sum_i MV_i^* \qquad \mathrm{navPct}_b^* = \frac{MV_b^*}{NAV^*}$$

The denominator $NAV^*$ is the post-shock position sum (stressed NAV), so percentages are relative to the stressed portfolio — consistent with ESMA guidance that stressed liquidity metrics should be expressed as a fraction of stressed NAV.

---

## 5. Liquidity Coverage Ratios (LCR)

**Code:** `LiquidityProfiler.liquidity_at_horizon()` → `RiskMetricsBuilder.build_liquidity_metrics()`  
**Displayed:** Dashboard tab → KPI cards LCR T+1, LCR T+3, LCR T+7

$$LCR_{T+h} = \sum_{\substack{b \,:\, lo(b) \leq h}} \mathrm{navPct}_b$$

Where $lo(b)$ is the lower bound (in days) of bucket $b$:

| Bucket | $lo(b)$ | $hi(b)$ |
|--------|---------|---------|
| T+0    | 0       | 0       |
| T+1    | 1       | 1       |
| T+3    | 2       | 3       |
| T+7    | 4       | 7       |
| >T+7   | 8       | $\infty$ |

So:

$$LCR_{T+1} = \mathrm{navPct}_{T+0} + \mathrm{navPct}_{T+1}$$

$$LCR_{T+3} = \mathrm{navPct}_{T+0} + \mathrm{navPct}_{T+1} + \mathrm{navPct}_{T+3}$$

$$LCR_{T+7} = \mathrm{navPct}_{T+0} + \mathrm{navPct}_{T+1} + \mathrm{navPct}_{T+3} + \mathrm{navPct}_{T+7}$$

**Theoretical basis:** LCR as defined here is an adaptation of the BCBS Basel III Liquidity Coverage Ratio concept applied at the fund level. For UCITS and AIFs the equivalent concept is the liquidity profile (ESMA LVLR Q&A), which expresses what fraction of NAV can be liquidated within a given settlement horizon.

---

## 6. Realisable Value and Haircuts

**Code:** `LiquidityProfiler._apply_haircuts()` — `liquidity_profiler.py`

### 6.1 Normal-regime realisable value

$$h_i = h_{AC}^{\text{normal}} + \frac{s_i}{2 \times 10{,}000} \qquad RV_i = MV_i \cdot (1 - h_i)$$

Where:
- $h_{AC}^{\text{normal}}$ = asset-class normal-regime haircut (see Section 16)
- $s_i$ = position bid-ask spread in basis points; dividing by 2 gives the half-spread, representing the cost of crossing from mid-price to exit price on liquidation

$h_i$ is clamped to $[0,\ 0.99]$.

### 6.2 Stress-regime realisable value (pre-multiplier)

$$h_i^* = h_{AC}^{\text{stress}} + \frac{s_i}{2 \times 10{,}000} \qquad RV_i^* = MV_i \cdot (1 - h_i^*)$$

### 6.3 Haircut multiplier (applied by StressEngine)

$$h_i^{**} = \min\!\left(0.99,\ \lambda \cdot h_i^*\right) \qquad RV_i^{**} = MV_i^* \cdot (1 - h_i^{**})$$

**Theoretical basis:** Liquidation haircuts model the bid-ask spread widening and price concession that occurs when a seller is forced to liquidate quickly. The decomposition into a structural asset-class haircut plus a bid-ask spread component is consistent with the Amihud (2002) illiquidity measure framework and the Bank of England's liquidity-adjusted mark-to-market approach.

---

## 7. Stress Scenarios — Shock Mechanics

**Code:** `StressEngine._apply_scenario()`, `_shock_equities()`, `_shock_credit()` — `stress_engine.py`

### 7.1 Equity shock

For equity and ETF positions:

$$MV_i^* = MV_i \cdot \left(1 + \varepsilon \cdot \beta_i\right) \qquad \text{subject to} \quad \varepsilon \cdot \beta_i \geq -\Omega_{\max} = -0.50$$

Where:
- $\varepsilon$ = scenario equity shock (e.g., $-0.10$ for $-10\%$)
- $\beta_i$ = position beta to market index (defaults to 1.0 if not provided)
- $\Omega_{\max} = 0.50$ = maximum single-position loss cap

The aggregate equity loss for the scenario is:

$$L_{\text{equity}} = \sum_{i \in \text{equity}} \left(MV_i^* - MV_i\right)$$

**Theoretical basis:** The beta-scaled price return is the standard CAPM-based single-factor shock model. It preserves cross-sectional differentiation — high-beta positions suffer proportionally larger losses — consistent with empirical equity crash behaviour (Ang et al., 2006).

### 7.2 Credit spread shock (bond repricing)

Bonds are repriced using the modified duration–convexity approximation, a second-order Taylor expansion of the bond price function $P(y)$ around the current yield $y_0$:

$$\frac{dP_i}{P_i} \approx -D_i^{\text{mod}} \cdot \Delta y_i + \frac{1}{2} \cdot C_i \cdot (\Delta y_i)^2$$

Where:
- $D_i^{\text{mod}}$ = modified duration of position $i$ (years)
- $C_i$ = effective convexity of position $i$ (falls back to 0 if not provided)
- $\Delta y_i$ = total yield change in the scenario

**Yield changes by instrument type:**

| Asset class | $\Delta y_i$ |
|-------------|-------------|
| Government bonds | $\Delta r$ (rate shock only) |
| IG/HY corporate, structured credit, money market | $\Delta r + \Delta s$ (rate + spread) |

Where $\Delta r = \mathrm{rateShockBps} / 10{,}000$ and $\Delta s = \mathrm{creditSpreadShockBps} / 10{,}000$.

The shocked market value is:

$$MV_i^* = MV_i \cdot \left(1 - D_i^{\text{mod}} \cdot \Delta y_i + \frac{1}{2} \cdot C_i \cdot (\Delta y_i)^2\right)$$

**Theoretical basis:** The duration–convexity expansion is the standard fixed income valuation framework (Fabozzi, 2007). Including convexity is important at large yield shocks (>100 bps): at +300 bps, ignoring convexity overstates the price decline by approximately $\frac{1}{2} C_i (\Delta y_i)^2$ per unit of market value.

---

## 8. Stress Test Metrics (Stress Tab)

**Code:** `StressEngine._apply_scenario()`, displayed in `StressTab.populate()` — `gui.py`

### 8.1 NAV after shock

$$NAV^* = NAV_{\text{before}} + L_{\text{equity}} + L_{\text{credit}} + L_{\text{rate}}$$

Where all loss terms are negative numbers (losses reduce NAV).

### 8.2 NAV impact

$$\Delta NAV_{\%} = \frac{NAV^* - NAV_{\text{before}}}{NAV_{\text{before}}}$$

Displayed as: **NAV delta%** in the stress table, and **Worst NAV Impact** KPI (minimum across all scenarios).

### 8.3 Liquid % before shock

$$L_{\text{before}} = LCR_{T+1}^{\text{normal}} = \frac{MV_{T+0} + MV_{T+1}}{NAV_{\text{before}}}$$

### 8.4 Liquid % after shock

$$L_{\text{after}} = \frac{RV_{T+0}^{**} + RV_{T+1}^{**}}{NAV^*}$$

Note: expressed in realisable value (not market value) and divided by stressed NAV, making it a more conservative measure than $L_{\text{before}}$.

### 8.5 Days to liquidate (stress scenario)

The waterfall engine is run within each stress scenario to estimate how many calendar days are required to raise $\mathrm{redemptionPct} \times NAV^*$ in net proceeds. The result is `WaterfallResult.days_to_target` (see Section 10).

### 8.6 Can meet redemption

$$\mathrm{CanMeet} = \mathbf{1}\!\left[\sum_i \mathrm{netProceeds}_i \geq R\right] \qquad \text{where} \quad R = NAV^* \cdot \mathrm{redemptionRate}$$

---

## 9. Redemption Scenario Analysis

**Code:** `RedemptionSimulator._evaluate_scenario()` — `redemption_simulator.py`  
**Displayed:** Redemption tab (Normal and Stress regime tables), Charts tab → Redemption Heatmap

Four redemption sizes are modelled: 5%, 10%, 20%, 30% of NAV.

### 9.1 Redemption amount

$$R = NAV \cdot p \qquad p \in \{0.05,\ 0.10,\ 0.20,\ 0.30\}$$

### 9.2 Liquidity available at horizon (with cash buffer)

$$L_h = \max\!\left(0,\ \sum_{\substack{b \,:\, lo(b) \leq h}} RV_b - \delta \cdot NAV\right) \qquad h \in \{1, 3, 7\}$$

Where $\delta = 0.02$ (`MIN_CASH_BUFFER_PCT`) is the minimum operational cash reserve retained during a forced sell-down.

### 9.3 Coverage tests

$$\mathrm{CanMeet}_{T+h} = \mathbf{1}\!\left[L_h \geq R\right]$$

### 9.4 Shortfall

$$\text{Shortfall} = \max(0,\ R - L_{T+7}) \qquad \text{Shortfall}_{\%} = \frac{\text{Shortfall}}{NAV}$$

### 9.5 Gate and suspension triggers

$$\mathrm{GateTriggered} = \mathbf{1}[p \geq 0.10] \qquad \mathrm{SuspensionTriggered} = \mathbf{1}[p \geq 0.25]$$

The 10% gate threshold is consistent with UCITS LVLR practice (Article 47 UCITS Directive). The 25% suspension threshold is consistent with AIFMD Article 23 disclosure requirements.

### 9.6 Days to clear

A greedy waterfall is run over the position profile, selling most-liquid positions first:

$$\mathrm{DaysToClear} = \max_{i \in \text{sold}} \left\lceil \frac{\min(RV_i,\ R_{\text{remaining}})}{\kappa \cdot \mathrm{effectiveADV}_i} \right\rceil$$

Where $\mathrm{effectiveADV}_i = \sigma \cdot ADV_i$ and $\sigma$ is the ADV stress scalar. Under the normal regime $\sigma = 1.0$; under the stressed Redemption tab profile $\sigma = 0.60$ (`REDEMPTION_STRESS_ADV_SCALAR` in `settings.py`). This compression reflects reduced market liquidity and causes stressed `DaysToClear` values to be strictly greater than their normal-regime counterparts.

**Code:** `RedemptionSimulator._estimate_days_to_cover()` reads `pos["effective_adv"]` (stored by `LiquidityProfiler._apply_adv_cap()`). The stressed profile is built with `LiquidityProfiler(portfolio, stress=True, adv_stress_scalar=REDEMPTION_STRESS_ADV_SCALAR)`.

---

## 10. Liquidation Waterfall

**Code:** `WaterfallEngine.run()` and `_liquidate_position()` — `waterfall_engine.py`  
**Displayed:** Waterfall tab — sell schedule table and KPI cards

The waterfall is a greedy, ADV-constrained forced sell-down that raises a target cash amount $T$ by selling assets in liquidity-bucket priority order (T+0 first, >T+7 last). Within each bucket, positions are sorted by descending ADV.

### 10.1 Position-level sell calculation

For each position $i$ (iterated in bucket × descending-ADV order):

**Step 1 — Gross sell amount**

$$\mathrm{sellGross}_i = \min\!\left(|MV_i|,\ \frac{R_{\text{remaining}}}{1 - h_i - \mu_i}\right)$$

Where $\mu_i = \mathrm{marketImpactBps}_i / 10{,}000$ is the market impact cost rate, and $h_i$ is read directly from `pos["haircut"]` in the position profile. Under stress, this value already incorporates the scenario's liquidity haircut multiplier $\lambda$ (applied by `StressEngine._apply_haircut_multiplier()` before the waterfall runs), so $h_i^{\text{stress}} = \min(h_i^{\text{base}} \cdot \lambda,\ 0.99)$. The waterfall no longer re-derives $h_i$ from the static `ASSET_CLASS_LIQUIDITY` config.

**Step 2 — Days to execute**

$$\text{days}_i = \left\lceil \frac{\mathrm{sellGross}_i}{\kappa \cdot ADV_i} \right\rceil$$

**Step 3 — Market impact and net proceeds**

$$\mathrm{impactCost}_i = \mathrm{sellGross}_i \cdot \mu_i$$

$$\mathrm{netProceeds}_i = \max\!\left(0,\ \mathrm{sellGross}_i \cdot (1 - h_i) - \mathrm{impactCost}_i\right)$$

**Step 4 — Remaining target update**

$$R_{\text{remaining}} \leftarrow R_{\text{remaining}} - \mathrm{netProceeds}_i$$

### 10.2 Waterfall summary metrics

$$\mathrm{TotalProceeds} = \sum_i \mathrm{netProceeds}_i \qquad \mathrm{TargetMet} = \mathbf{1}\!\left[\mathrm{TotalProceeds} \geq T\right]$$

$$\mathrm{ResidualShortfall} = \max(0,\ T - \mathrm{TotalProceeds})$$

$$\mathrm{DaysToTarget} = \max_i \text{days}_i \qquad NAV_{\text{after}} = NAV_{\text{before}} - \sum_i \mathrm{sellGross}_i$$

$$\mathrm{NAVImpact}_{\%} = \frac{NAV_{\text{before}} - NAV_{\text{after}}}{NAV_{\text{before}}}$$

### 10.3 LP-optimised waterfall (alternative)

`WaterfallEngine.run_lp_optimised()` solves a linear programme that minimises total liquidation time:

$$\min_{x_i} \sum_i \frac{x_i}{c_i} \qquad \text{subject to} \quad \sum_i x_i \cdot r_i \geq T,\quad 0 \leq x_i \leq MV_i$$

Where $c_i = \kappa \cdot ADV_i$ is the daily capacity and $r_i = 1 - h_i - \mu_i$ is the net proceeds rate. The GUI uses the greedy `run()` method (not the LP).

---

## 11. Days-to-Liquidate Percentiles

**Code:** `RiskMetricsBuilder._days_to_liquidate_pct()` — `risk_metrics.py`  
**Displayed:** Dashboard tab → Regulatory Flags panel: Days to 50% NAV, Days to 75% NAV, Days to 90% NAV

For a target liquidation fraction $\alpha \in \{0.50,\ 0.75,\ 0.90\}$, positions are sold greedily in ascending order of $d_i$ (most liquid first) until cumulative realisable value reaches $\alpha \cdot NAV$:

$$T_\alpha = \max_{i \in \text{selected}} \left\lceil \frac{MV_i}{c_i} \right\rceil \qquad \text{where} \quad c_i = \kappa \cdot ADV_i$$

Returns $\infty$ if the portfolio lacks sufficient sellable assets to reach the target fraction.

---

## 12. Concentration Risk and Liquidity/Concentration Ratio

**Code:** `RiskMetricsBuilder.build_liquidity_metrics()` — `risk_metrics.py`  
**Displayed:** Dashboard tab → KPI card "Liq / Conc Ratio", Regulatory Flags panel "Top-10 Concentration"

### 12.1 Top-10 investor concentration

$$C_{10} = \frac{\sum_{k=1}^{10} AuM_k}{NAV}$$

### 12.2 Liquidity / Concentration Ratio

$$\mathrm{LiqConc} = \frac{LCR_{T+1}}{C_{10}}$$

A ratio $\geq 1.0$ means the fund holds sufficient T+0/T+1 liquidity to cover a simultaneous full redemption by all top-10 investors.

**Theoretical basis:** This ratio implements the investor concentration test described in ESMA's AIFMD stress-testing guidelines (ESMA34-39-897, Section 4.2). The underlying concern is the liquidity spirals mechanism (Brunnermeier & Pedersen, 2009): when large investors redeem simultaneously, forced liquidation at distressed prices depresses NAV further, triggering additional redemptions.

---

## 13. Regulatory Flags

**Code:** `LiquidityProfiler.regulatory_flags()` — `liquidity_profiler.py`  
**Displayed:** Dashboard tab → Regulatory Flags panel

### 13.1 T+0/T+1 liquid percentage

$$L_{T+0,T+1} = LCR_{T+1} = \mathrm{navPct}_{T+0} + \mathrm{navPct}_{T+1}$$

### 13.2 Warning flag

$$\text{Warning} = \mathbf{1}\!\left[L_{T+0,T+1} < 0.10\right]$$

Triggered when less than 10% of NAV is in T+0/T+1 assets — calibrated to ESMA UCITS LVLR minimum liquidity guidance and MMFR Article 24 daily/weekly liquid asset minimums.

### 13.3 Breach flag

$$\text{Breach} = \mathbf{1}\!\left[L_{T+0,T+1} < 0.05\right]$$

Triggered when less than 5% of NAV is in T+0/T+1 assets. At this level the fund is approaching a position where it cannot meet even a 5% redemption from daily-liquid assets, and would be expected to engage liquidity management tools (gates, in-kind redemption, side pockets) under AIFMD Article 16.

---

## 14. Reverse Stress Testing

**Code:** `StressEngine.run_reverse_stress()` — `stress_engine.py`  
**Not displayed in GUI directly — available via API**

Binary search for the minimum shock magnitude $\varepsilon^*$ that drives T+0/T+1 liquidity below the breach threshold:

$$\varepsilon^* = \min \varepsilon \quad \text{such that} \quad L_{\text{after}}(\varepsilon) \leq L_{\text{breach}} = 0.05$$

The search uses bisection with tolerance $0.005$ and maximum 40 iterations:

$$\varepsilon_{n+1} = \begin{cases} \frac{\varepsilon_{\text{lo}} + \varepsilon_n}{2} & \text{if } L_{\text{after}}(\varepsilon_n) > L_{\text{breach}} \\ \frac{\varepsilon_n + \varepsilon_{\text{hi}}}{2} & \text{otherwise} \end{cases}$$

**Theoretical basis:** Reverse stress testing is mandated by EBA/GL/2018/04 and ESMA guidance as a complement to forward stress testing. Where forward tests ask "what is the impact of scenario X?", reverse tests ask "what scenario breaks the fund?" — providing a direct measure of margin of safety.

---

## 15. Synthetic Data Generation

**Code:** `liquidity_risk_tool/data/generate_synthetic_data.py`  
**Output directory:** `liquidity_risk_tool/data/synthetic/`

The tool ships with a fully synthetic dataset that is structurally identical to real input files but contains **zero real data** — every value is generated from Python's `random` module using publicly known financial conventions. This satisfies Refinitiv/LSEG license restrictions: no actual market data, holdings data, or client data is copied, derived, or transformed.

### 15.1 Portfolio mandates

Seven portfolios are generated, each with a distinct investment mandate and target liquidity profile:

| Portfolio | Mandate | Asset Allocation | Expected T+0/T+1 | Compliant? |
|-----------|---------|-----------------|-----------------|------------|
| `SYN-EQUITY`     | Large-cap equities | 97% listed equity, 3% cash | ~100% | Yes |
| `SYN-GOVBOND`    | Government bonds | 95% government bonds, 5% cash | ~70% | Yes |
| `SYN-FIXEDINC`   | Fixed income | 55% govt, 25% IG, 12% HY, 8% cash | ~44% | Yes |
| `SYN-MIXED`      | Multi-asset with hedging | 35% equity, 20% govt, 15% IG, 8% HY, 10% futures, 7% forwards, 5% cash | ~94% | Yes |
| `SYN-ILLIQ`      | HY-heavy (stress test) | 76% HY bonds, 24% IG bonds, tiny forced cash | <1% | **No** |
| `SYN-LEVERAGED`  | Leveraged equity/credit | Equity + derivatives overlay; gross leverage >175% NAV | ~80% | Warning |
| `SYN-LOANFUND`   | Loan origination AIF | >50% NAV in originated loans; subject to AIFMD II loan AIF rules | ~5% | Warning |

`SYN-ILLIQ` is the sole non-compliant portfolio by design, with T+0/T+1 deliberately held below the 5% regulatory breach threshold. It serves as the benchmark adversarial case for stress testing and regulatory flag validation.

### 15.2 Position size constraints for SYN-EQUITY

Equity positions in `SYN-EQUITY` are size-constrained to guarantee that every position liquidates within one trading day. The constraint is derived from the ADV participation cap:

$$MV_i^{\text{equity}} \leq \kappa \cdot ADV_i^{\min} \cdot 1 \text{ day}$$

With $\kappa = 0.20$ and a minimum synthetic ADV floor of $ADV_{\min} = \text{€}200\text{M}$:

$$MV_i^{\text{equity}} \leq 0.20 \times 200{,}000{,}000 = \text{€}40\text{M per day}$$

In practice positions are capped at €8M (20% of the floor capacity) to provide a conservative margin:

$$d_i = \left\lceil \frac{8{,}000{,}000}{0.20 \times 200{,}000{,}000} \right\rceil = \lceil 0.20 \rceil = 1 \implies \text{bucket} = T+1$$

All equity market data ADV values are drawn from $\mathcal{U}[200\text{M},\ 2{,}000\text{M}]$ EUR, ensuring that even the maximum generated position size stays within the T+1 capacity.

### 15.3 ISIN alignment between holdings and market data

A key design invariant is that every ISIN generated in the MVHOL holdings file has a matching row in the market data file. This is achieved via an `isin_map` returned by `generate_mvhol()` and consumed by `generate_market_data()`:

```
isin_map : dict[str, tuple[str, str]]
           isin → (portfolio_code, asset_class)
```

Without this alignment, `enrich_portfolio_from_market_data()` in the CSV loader would find no ISIN matches, ADV values would fall back to hard-coded defaults, and bucket assignments would diverge from what the synthetic ADV values imply. The `isin_map` mechanism eliminates this mismatch.

### 15.4 Synthetic ADV ranges by asset class

| Asset class | ADV range (EUR) | Basis |
|-------------|----------------|-------|
| `listed_equity` | €200M – €2B | Large-cap European/US equity turnover |
| `government_bond` | €5M – €80M | Sovereign secondary market |
| `ig_corporate_bond` | €500K – €20M | IG bond secondary market |
| `hy_corporate_bond` | €100K – €5M | HY bond secondary market |
| `etf` | €1M – €30M | UCITS ETF turnover |

These ranges are calibrated to publicly documented market microstructure data (BIS Quarterly Review, ECB Bond Market Surveys) and not to any proprietary data source.

### 15.5 Cash position sign convention

All synthetic cash amounts are drawn from $\mathcal{U}[100{,}000,\ 5{,}000{,}000]$ EUR (positive only). Negative cash (overdrafts) are excluded because they produce negative T+0 realisable values in the liquidity ladder, which have no economic meaning for a liquidity coverage calculation. Overdraft positions are liabilities, not liquidatable assets.

### 15.6 SYN-ILLIQ forced non-compliance

`SYN-ILLIQ` is forced non-compliant by injecting a single small cash position ($\text{€}200{,}000 – \text{€}800{,}000$) alongside high-notional HY and IG bond positions. Because HY bonds carry a T+7 structural bucket and IG bonds are T+3, the T+0/T+1 fraction is dominated by the tiny cash balance. The portfolio NAV is typically €100M+, making:

$$L_{T+0,T+1} = \frac{\text{cash}}{NAV} \approx \frac{500{,}000}{100{,}000{,}000} = 0.5\% \ll 5\%$$

This reliably triggers the `Breach` regulatory flag in every run, enabling end-to-end testing of the alert pipeline.

### 15.7 Zero-coupon yield curve

The synthetic yield curve is generated using the **Nelson–Siegel** parameterisation:

$$y(t) = \beta_0 + \beta_1 \cdot \frac{1 - e^{-t/\tau}}{t/\tau} + \beta_2 \cdot \left(\frac{1 - e^{-t/\tau}}{t/\tau} - e^{-t/\tau}\right)$$

Where $\beta_0$ (long-run level), $\beta_1$ (slope), $\beta_2$ (hump), and $\tau$ (decay speed) are drawn randomly to produce plausible normal, flat, and inverted curve shapes. A random walk is applied daily across the historical series:

$$r_t^{\text{short}} = \max(0.01,\ r_{t-1}^{\text{short}} + \varepsilon_t) \qquad \varepsilon_t \sim \mathcal{N}(0,\ 0.03)$$

The resulting `.xlsx` file matches the column structure of the real Refinitiv zero-coupon yield file but contains no real rate observations.

### 15.8 Regenerating the dataset

To regenerate all synthetic files with a new random seed:

```bash
python -m liquidity_risk_tool.data.generate_synthetic_data --seed 42 --date 12.05.2026
```

The `--seed` parameter ensures full reproducibility. Output files are written to `liquidity_risk_tool/data/synthetic/` and are loaded automatically by the GUI on startup.

---

## 16. Asset-Class Parameter Table

All parameters are defined in `settings.py` → `ASSET_CLASS_LIQUIDITY`.

| Asset Class         | Structural Bucket | Normal Haircut | Stress Haircut | Market Impact (bps) | Duration Default (yrs) |
|---------------------|------------------|---------------|---------------|--------------------|-----------------------|
| cash                | T+0              | 0.00%         | 0.00%         | 0                  | —                     |
| money\_market       | T+0              | 0.00%         | 1.00%         | 2                  | 0.3                   |
| government\_bond    | T+1              | 1.00%         | 5.00%         | 5                  | 5.5                   |
| ig\_corporate\_bond | T+3              | 2.00%         | 10.00%        | 15                 | 4.2                   |
| hy\_corporate\_bond | T+7              | 5.00%         | 20.00%        | 40                 | 3.1                   |
| listed\_equity      | T+1              | 2.00%         | 12.00%        | 10                 | —                     |
| etf                 | T+1              | 1.00%         | 8.00%         | 8                  | —                     |
| real\_estate        | >T+7             | 10.00%        | 25.00%        | 200                | —                     |
| private\_equity     | >T+7             | 15.00%        | 30.00%        | 300                | —                     |
| hedge\_fund         | >T+7             | 10.00%        | 20.00%        | 150                | —                     |
| structured\_credit  | T+7              | 8.00%         | 25.00%        | 80                 | 3.8                   |
| option              | T+1              | 5.00%         | 30.00%        | 50                 | —                     |
| future              | T+1              | 3.00%         | 15.00%        | 10                 | —                     |

**Calibration basis:** Normal haircuts are calibrated to typical bid-ask spreads and short-term price concession observed under normal market conditions (BIS Working Papers on market liquidity, 2016). Stress haircuts reflect spreads observed during the 2008 GFC and March 2020 COVID sell-off.

---

## 17. Scenario Parameter Table

All parameters are defined in `settings.py` → `STRESS_SCENARIOS`.

| Scenario               | Equity Shock | Credit Spread | Rate Shock  | ADV Scalar ($\sigma$) | Haircut Mult ($\lambda$) | Redemption Rate | Regulatory Basis                        |
|------------------------|-------------|--------------|-------------|--------------------|-----------------------|----------------|-----------------------------------------|
| Base                   | 0%          | +0 bps       | +0 bps      | 1.00×              | 1.0×                  | 5%             | ESMA MMFR Art.28 — baseline; AIFMD II Art.16(1)             |
| Equity-Led Stress -10% | -10%        | +50 bps      | +25 bps     | 0.80×              | 1.2×                  | 10%            | ESMA MMFR Art.28 Scenario A; AIFMD II Art.16(1)             |
| Equity-Led Stress -20% | -20%        | +100 bps     | +50 bps     | 0.70×              | 1.5×                  | 15%            | ESMA MMFR Art.28 Scenario B; AIFMD II Art.16(1)             |
| Credit-Led Stress +100bps | 0%       | +100 bps     | +30 bps     | 0.85×              | 1.3×                  | 10%            | ESMA MMFR Art.28 Scenario C; AIFMD II Art.16(1)             |
| Credit-Led Stress +300bps | -5%      | +300 bps     | +75 bps     | 0.60×              | 1.8×                  | 20%            | ESMA MMFR Art.28 Scenario D; AIFMD II Art.16(1)             |
| Severe Combined        | -20%        | +300 bps     | +100 bps    | **0.50×**          | **2.0×**              | **30%**        | ESMA MMFR Art.28 Scenario E — adverse; AIFMD II Art.16(1) worst-case LMT |

The Severe Combined scenario is the source of the stressed liquidity ladder displayed in the GUI.

---

## 18. AIFMD II — Directive (EU) 2024/927

**Effective:** 16 April 2026  
**Code:** `leverage_engine.py`, `redemption_simulator.py`, `config/settings.py`

### 18.1 Leverage — Gross Method (Art.15)

$$\text{GrossLeverage} = \frac{\sum_i |MV_i|}{NAV}$$

Where $MV_i$ is the market value of each position in base currency. This is the conservative fallback mandated by CDR 231/2013 Art. 7 when derivative notional data is unavailable. The tool treats all positions as long exposures.

**Caps:**

| Fund type | AIFMD II leverage cap |
|-----------|----------------------|
| Open-ended (non-loan) | no hard cap; disclosure required above 100% |
| Open-ended loan origination AIF | **175%** gross |
| Closed-ended loan origination AIF | **300%** gross |

A breach flag is raised when `gross_leverage > leverage_cap`.

### 18.2 Leverage — Commitment Method (Art.15 / CDR 231/2013 Art.8)

The commitment method nets eligible hedging positions and converts derivatives to delta-equivalent notionals. In the CSV data model, full netting agreement data is unavailable; the tool approximates by excluding locked illiquid positions (private equity, real estate lock-ups) that cannot participate in hedging:

$$\text{CommitmentLeverage} \approx \frac{\sum_{i:\,\text{not locked}} |MV_i|}{NAV}$$

This is conservative. A fund with true derivatives hedges would have lower commitment leverage.

### 18.3 Loan Origination AIF Detection (Art.15 / Recital 17)

A fund is classified as a loan origination AIF if:

$$\frac{\sum_{i:\,\text{asset\_class} \in \{\text{loan, originated\_loan}\}} MV_i}{NAV} \geq 50\%$$

When the flag is set, the AIFMD II loan origination regime applies: stricter leverage caps, mandatory risk retention, and borrower concentration limits.

**Risk retention (Art.15(4)):** Each originated loan must have ≥5% retained by the AIFM. The tool flags a warning if any single loan position represents >95% NAV (implying the external distribution cannot be verified from position data alone).

**Borrower concentration (ESMA guideline):** Any single borrower (ISIN) exceeding 20% NAV generates a breach entry in `borrower_breaches`.

### 18.4 Liquidity Management Tools — LMT Framework (Art.16 + Annex V)

AIFMD II requires open-ended AIFs to pre-select at least **two** LMTs from the Annex V list (excluding side pockets). The tool pre-selects: `gate`, `suspension`, `swing_pricing`.

#### Activation triggers

| Tool | Trigger threshold | Code constant |
|------|-------------------|---------------|
| Gate | redemption ≥ 10% NAV | `GATE_THRESHOLD = 0.10` |
| Suspension | redemption ≥ 25% NAV | `SUSPENSION_THRESHOLD = 0.25` |
| Swing pricing | net redemptions ≥ 2% NAV | `SWING_PRICING_THRESHOLD = 0.02` |

### 18.5 Swing Pricing (Annex V, Pt. 1)

When net redemptions exceed `SWING_PRICING_THRESHOLD`, the NAV is adjusted downward so that redeeming investors bear the transaction costs of the liquidation rather than remaining investors:

$$\text{SwingFactor} = \min\!\left(\bar{h} \times r,\; \text{SWING\_FACTOR\_MAX}\right)$$

Where:
- $\bar{h}$ = portfolio average haircut $= 1 - \frac{\sum_i RV_i}{\sum_i MV_i}$
- $r$ = redemption rate (fraction of NAV)
- $\text{SWING\_FACTOR\_MAX} = 0.02$ (200 bps cap)

The adjusted NAV paid to redeeming investors is $NAV \times (1 - \text{SwingFactor})$.

### 18.6 Anti-Dilution Levy (ADL) (Annex V, Pt. 2)

An explicit levy on redeeming investors as an alternative/complement to swing pricing. Calibrated to estimated transaction costs:

$$\text{ADL} = \text{ADL\_LEVY\_RATE} \times \text{RedemptionAmount}$$

Default rate: `ADL_LEVY_RATE = 0.005` (50 bps). The ADL is shown in basis points on the Redemption page alongside the swing factor.

---

## References

- European Parliament & Council (2024). *Directive (EU) 2024/927 (AIFMD II)* — amending AIFMD and UCITS Directive
- ESMA (2019). *Guidelines on liquidity stress testing in UCITS and AIFs* (ESMA34-39-897)
- ESMA (2020). *MMFR Stress-Testing Guidelines* (ESMA34-49-172)
- IOSCO (2018). *Liquidity Risk Management Recommendations* (FR07/2018)
- BCBS (2013). *Basel III: The Liquidity Coverage Ratio* (BCBS238)
- Kyle, A.S. (1985). Continuous auctions and insider trading. *Econometrica*, 53(6), 1315–1335
- Almgren, R. & Chriss, N. (2001). Optimal execution of portfolio transactions. *Journal of Risk*, 3(2), 5–39
- Brunnermeier, M. & Pedersen, L. (2009). Market liquidity and funding liquidity. *Review of Financial Studies*, 22(6), 2201–2238
- Amihud, Y. (2002). Illiquidity and stock returns. *Journal of Financial Markets*, 5(1), 31–56
- Fabozzi, F. (2007). *Fixed Income Mathematics* (4th ed.). McGraw-Hill
- Ang, A., Hodrick, R., Xing, Y. & Zhang, X. (2006). The cross-section of volatility and expected returns. *Journal of Finance*, 61(1), 259–299
- Glosten, L. & Milgrom, P. (1985). Bid, ask and transaction prices in a specialist market. *Journal of Financial Economics*, 14(1), 71–100
- Nelson, C.R. & Siegel, A.F. (1987). Parsimonious modelling of yield curves. *Journal of Business*, 60(4), 473–489
