# Liquidity Risk & Stress Testing Tool

**Live demo:** [https://liquidity-risk-stress-testing.onrender.com](https://liquidity-risk-stress-testing.onrender.com)

A Luxembourg ManCo-grade liquidity risk analytics platform for UCITS/AIFMD funds. Performs a full end-to-end pipeline — liquidity profiling, redemption simulation, stress testing, forced liquidation waterfall, input validation, reverse stress testing, and multi-format regulatory reporting — aligned with ESMA, CSSF, and AIFMD II (Directive (EU) 2024/927, effective April 2026) standards.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Project Structure](#project-structure)
3. [How the Code Works — Module by Module](#how-the-code-works--module-by-module)
   - [Data Model](#1-data-model--positionpy)
   - [Configuration](#2-configuration--settingspy)
   - [Input Validation](#3-input-validation--validatorspy)
   - [Liquidity Profiler](#4-liquidity-profiler--liquidity_profilerpy)
   - [Stress Engine](#5-stress-engine--stress_enginepy)
   - [Redemption Simulator](#6-redemption-simulator--redemption_simulatorpy)
   - [Waterfall Engine](#7-waterfall-engine--waterfall_enginepy)
   - [Risk Metrics & Reporting](#8-risk-metrics--reporting)
   - [GUI](#9-graphical-user-interface--guipy)
4. [Full Pipeline](#full-pipeline)
5. [Configuration Reference](#configuration-reference)
6. [Outputs](#outputs)
7. [Regulatory Alignment](#regulatory-alignment)
8. [Theoretical Background](#theoretical-background)

---

## Quick Start

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the command-line pipeline

```bash
py main.py
```

### 3. Launch the web UI (FastAPI + React)

Or run locally:

```bash
# Terminal 1 — backend API
cd backend
uvicorn main:app --reload --port 8080

# Terminal 2 — frontend dev server
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser. Upload your holdings and NAV CSV files using the sidebar, then click **Run Analysis**.

### 4. Launch the legacy desktop GUI (Tkinter)

```bash
py gui.py
```

### 5. Optional CLI flags

| Flag | Effect |
|------|--------|
| `--no-charts` | Skip PNG chart generation |
| `--scenario "Severe Combined"` | Run a single named scenario only |
| `--lp` | Use LP-optimised waterfall sell scheduler instead of greedy |

---

## Project Structure

```
liquidity_risk_tool/
├── main.py                          # CLI entry point — 8-step pipeline
├── requirements.txt
├── backend/                         # FastAPI application
│   ├── main.py                      # API entrypoint (uvicorn)
│   ├── routers/                     # Endpoint modules (analysis, health)
│   └── services/                    # Business logic wrappers + validation_service.py
├── frontend/                        # React + Vite + TailwindCSS v4 web UI
│   ├── src/
│   │   ├── pages/                   # AllPortfolios, Dashboard, StressTests, Waterfall, Charts, Leverage, …
│   │   ├── components/              # KPICard, MetricTooltip, EmptyState, …
│   │   ├── AnalysisContext.jsx      # Global analysis state
│   │   └── theme.js                 # Colour tokens for light/dark mode
│   └── package.json
├── ui-tk/                           # Legacy Tkinter desktop GUI (6 tabs)
│   └── gui.py
├── liquidity_risk_tool/             # Core analytics engine (Python package)
│   ├── config/
│   │   └── settings.py              # All thresholds, haircuts, scenarios, constants
│   ├── models/
│   │   ├── position.py              # Position, ShareClass, Portfolio dataclasses
│   │   ├── sample_portfolio.py      # EUR ~320M sample UCITS fund (31 positions)
│   │   └── csv_loader.py            # Load portfolio from holdings + NAV CSV files
│   ├── engines/
│   │   ├── validators.py            # Input validation — positions and portfolios
│   │   ├── liquidity_profiler.py    # Bucket assignment, haircuts, ADV cap, concentration flags
│   │   ├── redemption_simulator.py  # Redemption scenario flow and coverage
│   │   ├── stress_engine.py         # ESMA equity/credit shocks + reverse stress
│   │   └── waterfall_engine.py      # Greedy and LP-optimised forced sell-down
│   ├── reporting/
│   │   ├── risk_metrics.py          # KPI aggregation (LiquidityMetrics)
│   │   └── report_builder.py        # Excel (6 sheets) / JSON / console export
│   └── visualization/
│       └── charts.py                # 7-chart matplotlib pack
├── data/
│   ├── sample/                      # Synthetic demo data (safe to commit)
│   └── generate_synthetic_data.py   # Generates sample holdings + NAV CSVs
├── tests/
│   ├── test_pipeline.py
│   ├── test_validators.py
│   ├── test_stress_engine_enhanced.py
│   └── test_report_builder.py
└── output/                          # Generated reports (git-ignored)
    ├── liquidity_risk_report.xlsx
    ├── liquidity_risk_report.json
    └── charts/
```

---

## How the Code Works — Module by Module

---

### 1. Data Model — `position.py`

**File:** `liquidity_risk_tool/models/position.py`

Three dataclasses form the foundation:

#### `Position`

Represents a single fund holding. Key fields:

| Field | Type | Meaning |
|-------|------|---------|
| `isin` | str | ISIN identifier |
| `name` | str | Human-readable name |
| `asset_class` | str | One of ~11 classes (e.g. `"listed_equity"`, `"ig_corporate_bond"`) |
| `market_value` | float | Value in the position's local currency |
| `fx_rate` | float | Exchange rate to EUR (1.0 if already EUR) |
| `adv_30d` | float | 30-day average daily trading volume in EUR |
| `beta` | float | Equity beta — scales equity shock sensitivity |
| `duration` | float | Modified duration in years (bonds) |
| `credit_spread_bps` | float | Current credit spread in basis points |
| `convexity` | float or None | Explicit convexity; if None, derived as `duration² / 2` |
| `is_government` | bool | True = pure gov bond (rate shock only, no credit spread) |
| `settlement_days` | int or None | Actual settlement lag in calendar days |
| `liquidity_bucket_override` | str or None | Force into a specific liquidity bucket |
| `is_locked` | bool | If True, position is illiquid |

`market_value_eur` is a computed property (`market_value × fx_rate`).

`effective_convexity` property returns the explicit value if set, otherwise `duration² / 2`.

#### `ShareClass`

| Field | Meaning |
|-------|---------|
| `name` | Share class label |
| `nav_per_share` | NAV per share in EUR |
| `shares_outstanding` | Number of shares |
| `notice_period_days` | Redemption notice period |
| `redemption_frequency` | `"daily"`, `"weekly"`, or `"monthly"` |

#### `Portfolio`

- `total_nav` — sums share class NAVs; falls back to summing `market_value_eur` across positions if no share classes are defined
- `positions_df` — flattens all positions into a pandas DataFrame
- `_refresh_weights()` — recomputes each position's weight after shocks

---

### 2. Configuration — `settings.py`

**File:** `liquidity_risk_tool/config/settings.py`

All thresholds and parameters live here — nothing is hard-coded in engine files.

#### `StressScenario` fields

| Field | Meaning |
|-------|---------|
| `name` | Scenario label |
| `equity_shock` | Fractional price shock on equities (e.g. `-0.20`) |
| `credit_spread_shock_bps` | Spread widening in bps |
| `liquidity_haircut_multiplier` | Multiplier on all haircuts |
| `redemption_rate` | Assumed outflow as fraction of NAV |
| `adv_stress_scalar` | Volume collapse factor (e.g. `0.5` = 50% of normal ADV) |
| `rate_shock_bps` | Parallel rate shift for bond repricing |
| `version` | Scenario version string |
| `description` | Free-text description |
| `regulatory_basis` | e.g. `"ESMA MMFR Art.28 Scenario A"` |
| `is_worst_case` | Boolean flag |
| `last_reviewed` | ISO date string |

#### Key constants

| Constant | Default | Purpose |
|----------|---------|---------|
| `LIQUIDITY_WARNING_THRESHOLD` | 0.10 | Flag if T+0+T+1 < 10% NAV |
| `LIQUIDITY_BREACH_THRESHOLD` | 0.05 | Flag if T+0+T+1 < 5% NAV |
| `ADV_PARTICIPATION_CAP` | 0.20 | Max 20% of ADV sold per day |
| `CASH_BUFFER_PCT` | 0.02 | Minimum 2% NAV retained as cash buffer |
| `GATE_THRESHOLD_PCT` | 0.10 | Gate if redemption ≥ 10% NAV |
| `SUSPENSION_THRESHOLD_PCT` | 0.25 | Suspension if redemption ≥ 25% NAV |
| `CONCENTRATION_FLAG_THRESHOLD` | 0.05 | Flag positions > 5% weight |
| `EQUITY_SHOCK_MAX_LOSS` | 0.50 | Cap equity loss at 50% of market value |

---

### 3. Input Validation — `validators.py`

**File:** `liquidity_risk_tool/engines/validators.py`

**Purpose:** Catch bad input data before it propagates silently through the pipeline.

```python
from liquidity_risk_tool.engines.validators import validate_position, validate_portfolio, ValidationError
```

#### `validate_position(pos) -> List[str]`

Returns a list of error strings. Checks:
- `market_value > 0`
- `adv_30d >= 0`
- `duration` in `[0, 30]` if set
- `credit_spread_bps` in `[0, 5000]` if set
- `beta` in `[0, 3]` if set
- `convexity >= 0` if set
- `fx_rate > 0`

#### `validate_portfolio(portfolio, strict=True) -> List[str]`

Aggregates all position errors. If `strict=True`, raises `ValidationError` on the first error. Non-strict mode returns the full error list and continues.

In `main.py`, validation runs in non-strict mode — warnings are printed but the pipeline continues.

---

### 4. Liquidity Profiler — `liquidity_profiler.py`

**File:** `liquidity_risk_tool/engines/liquidity_profiler.py`

**Purpose:** Classify every position into a liquidity bucket, compute realisable value after haircuts, enforce ADV selling capacity limits, and flag concentrated positions.

#### Step 1 — `_assign_buckets()`

1. If `is_locked` → bucket = `">T+7"`
2. Else if `liquidity_bucket_override` is set → use that
3. Else → look up `ASSET_CLASS_LIQUIDITY[asset_class]["normal" or "stress"]["bucket"]`

#### Step 2 — `_apply_haircuts()`

```
realisable_value = market_value_eur × (1 − haircut)
```

Under stress, haircuts are higher. The `liquidity_haircut_multiplier` from the scenario is applied on top:

```
effective_haircut = min(haircut_stress × multiplier, 0.99)
```

#### Step 3 — `_apply_adv_cap(adv_stress_scalar)`

```
effective_adv     = adv_30d × adv_stress_scalar
daily_capacity    = effective_adv × ADV_PARTICIPATION_CAP
days_to_liquidate = ceil(market_value_eur / daily_capacity)
```

The `adv_stress_scalar` from the scenario collapses trading volume (e.g. 0.5 = half normal ADV). Positions that take multiple days to sell have their effective bucket pushed back.

#### Step 4 — `_flag_concentration()`

```python
df["concentration_flag"] = df["weight"] > CONCENTRATION_FLAG_THRESHOLD
```

Positions above 5% weight are flagged for review.

---

### 5. Stress Engine — `stress_engine.py`

**File:** `liquidity_risk_tool/engines/stress_engine.py`

**Purpose:** Apply ESMA-style market shocks, compute NAV impact, re-profile liquidity, and support reverse stress testing.

#### Equity shock with cap

```
price_return = (equity_shock × beta).clip(lower=−EQUITY_SHOCK_MAX_LOSS)
shocked_mv   = market_value_eur × (1 + price_return)
```

The 50% cap prevents extreme scenarios from modelling a total wipe-out of equity positions.

#### Bond repricing — gov/credit separation with convexity

Government bonds respond only to rate shocks. Credit bonds respond to both rate and spread shocks. Both use the convexity-adjusted duration formula:

```
dy (gov)    = rate_shock_bps / 10,000
dy (credit) = rate_shock_bps / 10,000 + spread_shock_bps / 10,000

ΔP/P = −MD × dy + 0.5 × convexity × dy²
```

This is more accurate than the linear approximation for large moves. `effective_convexity` is used — either explicit or derived from `duration² / 2`.

#### `ScenarioResult` fields

| Field | Meaning |
|-------|---------|
| `nav_before` | Pre-shock NAV (EUR) |
| `nav_after_shock` | Post-shock NAV (EUR) |
| `nav_impact_pct` | NAV loss as fraction |
| `equity_loss_eur` | Loss from equity repricing |
| `credit_loss_eur` | Loss from spread/rate repricing |
| `rate_loss_eur` | Loss from rate shock component |
| `liquid_pct_before` | T+0+T+1 % of NAV before shock |
| `liquid_pct_after` | T+0+T+1 % of NAV after shock |
| `time_to_liquidate_days` | Days to raise redemption cash |
| `can_meet_redemption` | True if waterfall covers full demand |

#### Reverse stress testing — `run_reverse_stress()`

Binary search for the minimum shock level that pushes liquid coverage below a target threshold:

```python
result = engine.run_reverse_stress(
    target_liquid_pct=0.05,
    shock_parameter="equity_shock",
    lo=0.0, hi=0.60,
    tolerance=0.005, max_iterations=40
)
```

Returns `{"found": bool, "breach_shock_level": float, "iterations": int, "liquid_pct_at_breach": float}`.

---

### 6. Redemption Simulator — `redemption_simulator.py`

**File:** `liquidity_risk_tool/engines/redemption_simulator.py`

**Purpose:** For a given redemption outflow, determine whether the fund can meet it and within what time horizon.

#### Liquidity Coverage Ratio

```
coverage_ratio(horizon) = liquidity_available(horizon) / redemption_demand
```

A ratio ≥ 1.0 means the fund can fully meet the redemption within that horizon.

#### Gate and suspension logic

| Trigger | Condition |
|---------|-----------|
| Gate | redemption ≥ 10% NAV |
| Suspension | redemption ≥ 25% NAV |

#### `RedemptionResult` key fields

| Field | Meaning |
|-------|---------|
| `can_meet_t1 / t3 / t7` | Coverage within T+1, T+3, T+7 |
| `gate_triggered` | True if redemption ≥ gate threshold |
| `suspension_triggered` | True if redemption ≥ suspension threshold |
| `days_to_clear` | Days needed to raise full redemption |
| `notice_extension_days` | Days extended by notice period extension tool |
| `in_kind_pct_used` | Fraction of redemption met via in-kind transfer (0–1) |
| `dual_spread_bps` | Dual pricing spread applied in bps |
| `swing_factor` | Swing pricing multiplier (1 + swing bps / 10000) |
| `adl_bps` | Anti-dilution levy rate in basis points |
| `fee_bps` | Redemption fee applied in basis points |
| `lmt_activated` | True if any LMT was triggered |
| `lmt_tools_used` | List of active LMT tool names |

#### AIFMD II Liquidity Management Tools (LMTs)

Nine tools are implemented in `_evaluate_scenario()`:

1. **Gate** — If redemption ≥ 10% NAV, gate is triggered and redemption is deferred. Coverage ratios reflect delayed cash availability.
2. **Suspension** — If redemption ≥ 25% NAV, fund temporarily suspends redemptions.
3. **Notice Period Extension** — Extra N days (3/7/14/30) to liquidate before payment is due; effective_days_to_clear = max(0, days_to_clear − extension_days).
4. **Redemptions in Kind** — M% of redemption demand met via asset transfer, reducing cash shortfall by M%. Professional investors only.
5. **Redemption Fee** — Charge X bps to redeeming investors; reduces effective redemption demand.
6. **Swing Pricing** — On days with net redemptions > threshold, adjust NAV by ± swing factor to pass costs to redeeming investors; reduces effective shortfall.
7. **Dual Pricing** — Always apply spread to redemption price (unlike swing pricing which has a threshold); redemption NAV = NAV × (1 − dual_spread_bps / 10000).
8. **Anti-Dilution Levy (ADL)** — Charge Y bps to redeeming investors; directly reduces cash demand.
9. **Side Pockets** — Segment illiquid holdings (currently informational only; full implementation pending).

**AIFMD II compliance:** Managers must pre-select ≥2 tools. Swing pricing + dual pricing is a prohibited combination (both adjust NAV on redemptions). The LMT Simulator enforces these rules via a compliance checker.

#### Horizon Display in Redemption Table

The redemption analysis table now displays which settlement horizon is achievable for each scenario. The **Without LMT** column shows the horizon under normal liquidity conditions, while the **With LMT** column shows how tools like Notice Period Extension or Redemptions in Kind improve achievable horizon. Horizons are labeled as T+1, T+3, T+7, or shown as absent (✕) if no coverage exists at any horizon. This enables direct visual comparison of tool impact on settlement speed.

#### Validation Framework for LMT Configurations

Two automated validation checks verify correct LMT mechanics:

1. **Multiplicative composition**: When ≥2 demand-reducing tools (ADL, fees, in-kind, dual pricing) are active, they must compose multiplicatively. Validation confirms that shortfall after all tools applied is < 0.1% NAV.
2. **Non-zero cost**: When a tool is activated, it must carry measurable cost (non-zero bps or percentage). Prevents misconfiguration where tools are marked active but inactive.

Both checks run automatically and appear in the Validation sidebar under "LMT Composition." They help users validate that their tool configuration is both compliant and mechanically correct.

---

### 7. Waterfall Engine — `waterfall_engine.py`

**File:** `liquidity_risk_tool/engines/waterfall_engine.py`

**Purpose:** Simulate the day-by-day sell schedule when the fund must raise cash.

#### Sell priority

`T+0 → T+1 → T+3 → T+7 → >T+7`, within each bucket sorted by realisable value descending (largest positions first per MiFID II best-execution).

#### Net proceeds formula

```
net_proceeds = gross_value × (1 − haircut) − gross_value × (market_impact_bps / 10,000)
```

#### LP-optimised mode (`run_lp_optimised`)

Uses `scipy.optimize.linprog` to minimise total liquidation time:
- Decision variables: `x[i]` = gross sell amount per position
- Objective: `min Σ(x[i] / daily_cap[i])` — proxy for total days
- Constraints: net proceeds ≥ target; `0 ≤ x[i] ≤ market_value[i]`; locked positions excluded

Falls back to the greedy `run()` if scipy is unavailable or LP is infeasible. Activated by `--lp` flag in CLI.

---

### 8. Risk Metrics & Reporting

**Files:** `liquidity_risk_tool/reporting/risk_metrics.py`, `report_builder.py`

#### `LiquidityMetrics` key fields

| Field | Meaning |
|-------|---------|
| `lcr_t1 / lcr_t3 / lcr_t7` | Liquidity coverage ratios |
| `illiquid_pct` | % NAV in >T+7 |
| `regulatory_warning / breach` | Threshold flags |

#### `ReportBuilder` — Excel output (6 sheets)

| Sheet | Contents |
|-------|---------|
| KPIs | Fund-level summary and regulatory status |
| Liquidity Ladder | Per-position bucket detail, normal and stress |
| Stress Tests | NAV impact and coverage per scenario |
| Redemption Analysis | Coverage matrix: redemption sizes × time horizons |
| ESMA_Template | 22 rows covering ESMA field codes A.1–E.6 |
| Scenario_Metadata | One row per scenario with all `StressScenario` fields |

#### Run fingerprint

Each report includes a SHA-256 fingerprint derived from the portfolio positions and scenario config, printed in the console header and embedded in JSON output. Enables audit-trail reproducibility.

#### JSON output

Structured export including `run_id`, `scenario_metadata`, fund metrics, ladder, stress, and redemption data.

---

### 9. User Interfaces

#### 9a. Web UI — `backend/` + `frontend/`

The primary interface is a browser-based application (FastAPI + React/Vite/TailwindCSS v4). Upload your holdings and NAV CSV files via the sidebar, click **Run Analysis**, and results appear across four tabs.

| Tab | Contents |
|-----|---------|
| All Portfolios | Cross-portfolio comparison table — NAV, LCR T+1/T+3/T+7, illiquid %, concentration, days-to-liquidate, leverage, and unified breach/warning status for every fund in the run |
| Dashboard | Fund name, reporting date, 6 LCR KPI cards, liquidity ladder chart (normal vs stressed), positions table with bucket badges |
| Stress Tests | Per-scenario NAV impact, liquidity before/after, scenario config expandable panel |
| Waterfall | Forced sell-down KPIs (target, proceeds, residual shortfall, NAV impact), daily proceeds chart by bucket, sell-order table |
| Charts | Liquidity ladder, portfolio composition pie, stress NAV impact, liquidity before/after, days-to-liquidate by position, waterfall cumulative proceeds line |
| LMT Simulator | AIFMD II Liquidity Management Tools (LMTs) configuration and impact dashboard — select from gate, notice period extension, redemptions in kind, suspension, swing pricing, dual pricing, redemption fee, and anti-dilution levy; run instant simulation to compare coverage before and after tools applied; compliance checker warns if conflicting tools selected |

Supports **light / dark / Bloomberg Terminal** theme toggle. All charts are theme-aware with consistent colour tokens. Tooltips are fully readable in both modes.

#### 9b. Legacy Desktop GUI — `ui-tk/gui.py`

Tkinter desktop application with 6 tabs. The pipeline runs on a background thread to keep the UI responsive.

| Tab | Contents |
|-----|---------|
| Dashboard | KPI cards, liquidity ladder table, regulatory flags, positions table |
| Stress Tests | Per-scenario results table + scenario config panel |
| Redemption | Coverage matrix across scenarios and time horizons |
| Waterfall | Day-by-day forced sell schedule |
| Charts | 7 embedded matplotlib figures |
| Risk Story | Auto-generated narrative risk summary with copy button |

Key UX: "▶ Run Analysis" becomes "✓ Analysis Complete" (green) after a successful run; a "Re-run ↺" button replaces it for subsequent runs. All pipeline work runs in a `threading.Thread`; UI updates dispatch back to the main thread via `root.after(0, callback)`.

#### 9c. LMT Simulator API Endpoint — `POST /api/run/{run_id}/lmt-simulate`

**File:** `backend/routers/analysis.py`

Lightweight endpoint for instant AIFMD II Liquidity Management Tool simulation without re-running the full pipeline. Accepts a tool configuration, applies it to cached position and stress data, and returns coverage comparison.

**Request:**
```json
{
  "lmt_config": {
    "active_tools": ["gate", "swing_pricing", "adl"],
    "gate_pct": 0.10,
    "swing_threshold": 0.02,
    "swing_factor": 0.01,
    "adl_bps": 100,
    "redemption_fee_bps": 0,
    "dual_spread_bps": 0,
    "notice_extension_days": 0,
    "in_kind_pct": 0.0
  },
  "scenarios": null,
  "portfolio": null
}
```

**Response:**
```json
{
  "normal": [
    {
      "redemption_rate": 0.05,
      "can_meet_t1": true,
      "can_meet_t3": true,
      "can_meet_t7": true,
      "shortfall_eur": 0.0,
      "days_to_clear": 1,
      "lmt_activated": true,
      "lmt_tools_used": ["gate", "swing_pricing", "adl"],
      ...
    }
  ],
  "stress": [...],
  "lmt_config_applied": { ... }
}
```

**Key characteristics:**
- No full pipeline re-run; reuses cached `position_buckets` and `stress_buckets` from the original run
- Executes in milliseconds
- Returns results for both normal and worst-case (Severe Combined) stress scenarios
- Integrates seamlessly with the LMT Simulator web tab for interactive tool selection and comparison

---

## Full Pipeline

| Step | Code location | What happens |
|------|--------------|--------------|
| 1 | `models/` | Load portfolio (CSV or sample) |
| 1b | `engines/validators.py` | Validate all positions — print warnings |
| 2 | `engines/liquidity_profiler.py` | Assign buckets, apply haircuts, enforce ADV cap, flag concentration |
| 3 | `reporting/risk_metrics.py` | Compute regulatory KPIs |
| 4 | `engines/redemption_simulator.py` | Model 5/10/20/30% outflow scenarios |
| 4b | `engines/stress_engine.py` | Reverse stress test — find breach threshold |
| 5 | `engines/stress_engine.py` | Apply 6 ESMA-style shocks |
| 6 | `engines/waterfall_engine.py` | Simulate forced sell-down for worst-case scenario |
| 7 | `reporting/report_builder.py` + `visualization/charts.py` | Write Excel/JSON, generate charts |

---

## Configuration Reference

### Asset-Class Haircuts

| Asset Class | Bucket (Normal) | Haircut (Normal) | Bucket (Stress) | Haircut (Stress) |
|-------------|-----------------|-----------------|-----------------|-----------------|
| Cash | T+0 | 0% | T+0 | 0% |
| Money Market | T+0 | 0% | T+0 | 1% |
| Government Bond | T+1 | 1% | T+1 | 5% |
| IG Corporate | T+3 | 2% | T+3 | 10% |
| HY Corporate | T+3 | 5% | T+7 | 20% |
| Listed Equity | T+1 | 2% | T+1 | 12% |
| ETF | T+0 | 1% | T+1 | 8% |
| Structured Credit | T+7 | 8% | >T+7 | 25% |
| Real Estate | >T+7 | 10% | >T+7 | 25% |
| Private Equity | >T+7 | 15% | >T+7 | 30% |
| Hedge Fund | >T+7 | 10% | >T+7 | 20% |

### Stress Scenarios

| Scenario | Equity Shock | Spread (bps) | Rate (bps) | ADV Scalar | Haircut Mult. | Redemption | Regulatory Basis |
|----------|-------------|-------------|-----------|-----------|--------------|-----------|-----------------|
| Base | 0% | 0 | 0 | 1.0× | 1.0× | 5% | ESMA MMFR Art.28 — baseline |
| Equity-Led Stress -10% | −10% | +50 | +25 | 0.8× | 1.2× | 10% | ESMA MMFR Art.28 Scenario A |
| Equity-Led Stress -20% | −20% | +100 | +50 | 0.7× | 1.5× | 15% | ESMA MMFR Art.28 Scenario B |
| Credit-Led Stress +100bps | 0% | +100 | +30 | 0.85× | 1.3× | 10% | ESMA MMFR Art.28 Scenario C |
| Credit-Led Stress +300bps | −5% | +300 | +75 | 0.6× | 1.8× | 20% | ESMA MMFR Art.28 Scenario D |
| Severe Combined | −20% | +300 | +100 | 0.5× | 2.0× | 30% | ESMA MMFR Art.28 Scenario E — adverse |

---

## Outputs

### Console

Step-by-step progress log with run fingerprint (SHA-256), key metrics, and warnings highlighted for threshold breaches.

### Excel — `output/liquidity_risk_report.xlsx`

Six sheets as described above. The ESMA_Template sheet is pre-formatted for submission.

### JSON — `output/liquidity_risk_report.json`

Structured export with `run_id`, `scenario_metadata`, and all engine outputs. Suitable for API integration or downstream dashboards.

### Charts — `output/charts/`

| File | Description |
|------|-------------|
| `01_liquidity_ladder.png` | Stacked bars — normal vs stress bucket values |
| `02_redemption_heatmap.png` | Coverage % by scenario and time horizon |
| `03_stress_nav_impact.png` | NAV change % per scenario |
| `04_time_to_liquidate.png` | Cumulative % NAV liquidated over days |
| `05_portfolio_composition.png` | Donut chart by asset class |
| `06_waterfall_schedule.png` | Day-by-day sell orders under worst-case scenario |

---

## Regulatory Alignment

| Standard | Implementation |
|----------|---------------|
| ESMA MMFR stress scenarios | Six pre-defined scenarios in `settings.py` with `regulatory_basis` metadata |
| ESMA MMFR Art.28 | ESMA_Template Excel sheet with field codes A.1–E.6 |
| UCITS liquidity requirements | T+0+T+1 warning/breach thresholds, daily redemption capability |
| AIFMD Article 16 | ADV participation cap, liquidity ladder by settlement day |
| CSSF Circular 18/698 | Worst-case scenario calibration, ESMA_Template output |
| Redemption gates | Gate at 10% NAV, suspension at 25% NAV |
| ADV cap | 20% daily participation limit in `_apply_adv_cap()` |
| Audit trail | SHA-256 run fingerprint on every report |
| **AIFMD II Art.15** | Gross leverage computed via Gross Method (CDR 231/2013 Art.7); caps 175% open-ended / 300% closed-ended loan AIFs — `leverage_engine.py` |
| **AIFMD II Art.16 + Annex V** | ≥2 LMTs pre-selected (gate, suspension, swing pricing); swing pricing formula and ADL computed in `redemption_simulator.py`; **LMT Simulator tab** allows dynamic selection and comparison of all nine AIFMD II LMTs: always-available (suspension, side pockets); quantitative (gate, notice period extension, redemptions in kind); anti-dilution (redemption fee, swing pricing, dual pricing, ADL). Interactive dashboard shows coverage impact, investor cost summary, and AIFMD II compliance validation. New endpoint `POST /api/run/{run_id}/lmt-simulate` executes instant simulations without re-running full pipeline. |
| **AIFMD II loan origination** | Loan origination AIF detection (≥50% NAV in loans), 5% risk retention check, 20% borrower concentration limit — `leverage_engine.py` |

---

## Theoretical Background

### Liquidity Ladder

Regulators require fund managers to classify every holding by settlement horizon. The tool uses five buckets: T+0 (cash), T+1 (govies, equities), T+3 (IG bonds), T+7 (HY, structured), >T+7 (alternatives). The cumulative liquidity coverage ratio at horizon H:

```
LCR(H) = Σ realisable_value(buckets ≤ H) / total_NAV
```

### Bond Repricing with Convexity

Linear duration alone overstates losses for large yield moves. The tool uses the second-order approximation:

```
ΔP/P ≈ −MD × dy + 0.5 × convexity × dy²
```

Government bonds receive only the rate shock component (`dy = rate_shock_bps / 10,000`). Credit bonds receive both rate and spread (`dy = (rate_shock_bps + spread_shock_bps) / 10,000`). `effective_convexity` defaults to `duration² / 2` when no explicit value is provided.

### Equity Shock Cap

The 50% cap (`EQUITY_SHOCK_MAX_LOSS`) prevents scenarios with extreme equity shocks (e.g. −80%) from producing implausible results — no listed equity has ever gone to zero in a single stress period modelled here.

### ADV Stress Scalar

In a crisis, market volume collapses. The `adv_stress_scalar` scales the assumed daily trading capacity:

```
effective_daily_capacity = adv_30d × adv_stress_scalar × ADV_PARTICIPATION_CAP
```

The Severe Combined scenario uses 0.5×, reflecting the ~50% volume collapse observed in 2008 and March 2020.

### Reverse Stress Testing

Binary search over the equity shock dimension finds the minimum shock that breaks fund liquidity below the 5% NAV threshold. This inverts the normal stress test question ("what happens if X occurs?") to ask "what would have to happen to breach our limit?" — a requirement under ESMA MMFR and AIFMD Article 16.

### Known Limitations

| Limitation | Effect |
|-----------|--------|
| Beta is static | In a crash, betas spike; consider regime-switching |
| No second-order contagion | Selling bonds doesn't feed back into equity prices |
| Flat haircuts per asset class | Ignores issuer-level or size-specific differences |
| No FX stress | FX rates are held constant across scenarios |
