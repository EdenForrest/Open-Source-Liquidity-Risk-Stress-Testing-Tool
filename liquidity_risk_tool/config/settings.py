"""
Central configuration for the Liquidity Risk & Stress Testing Tool.
All thresholds, bucket definitions, and scenario parameters live here.
"""
import os
from dataclasses import dataclass, field
from typing import Dict, List


# ---------------------------------------------------------------------------
# Liquidity bucket definitions (settlement days)
# ---------------------------------------------------------------------------
LIQUIDITY_BUCKETS: Dict[str, tuple] = {
    "T+0":  (0, 0),
    "T+1":  (1, 1),
    "T+3":  (2, 3),
    "T+7":  (4, 7),
    ">T+7": (8, 9999),
}

# Priority order for waterfall (most liquid first)
BUCKET_ORDER: List[str] = ["T+0", "T+1", "T+3", "T+7", ">T+7"]


# ---------------------------------------------------------------------------
# Asset-class default liquidity profiles
# ---------------------------------------------------------------------------
ASSET_CLASS_LIQUIDITY: Dict[str, dict] = {
    "cash":              {"bucket": "T+0", "haircut_normal": 0.00, "haircut_stress": 0.00, "market_impact_bps": 0},
    "money_market":      {"bucket": "T+0", "haircut_normal": 0.00, "haircut_stress": 0.01, "market_impact_bps": 2},
    "government_bond":   {"bucket": "T+1", "haircut_normal": 0.01, "haircut_stress": 0.05, "market_impact_bps": 5},
    "ig_corporate_bond": {"bucket": "T+3", "haircut_normal": 0.02, "haircut_stress": 0.10, "market_impact_bps": 15},
    "hy_corporate_bond": {"bucket": "T+7", "haircut_normal": 0.05, "haircut_stress": 0.20, "market_impact_bps": 40},
    "listed_equity":     {"bucket": "T+1", "haircut_normal": 0.02, "haircut_stress": 0.12, "market_impact_bps": 10},
    "etf":               {"bucket": "T+3", "haircut_normal": 0.03, "haircut_stress": 0.12, "market_impact_bps": 20},
    "real_estate":       {"bucket": ">T+7","haircut_normal": 0.10, "haircut_stress": 0.25, "market_impact_bps": 200},
    "private_equity":    {"bucket": ">T+7","haircut_normal": 0.15, "haircut_stress": 0.30, "market_impact_bps": 300},
    "hedge_fund":        {"bucket": ">T+7","haircut_normal": 0.10, "haircut_stress": 0.20, "market_impact_bps": 150},
    "structured_credit": {"bucket": "T+7", "haircut_normal": 0.08, "haircut_stress": 0.25, "market_impact_bps": 80},
    "option":            {"bucket": "T+1", "haircut_normal": 0.05, "haircut_stress": 0.30, "market_impact_bps": 50},
    "future":            {"bucket": "T+1", "haircut_normal": 0.03, "haircut_stress": 0.15, "market_impact_bps": 10},
}


# ---------------------------------------------------------------------------
# Stress scenario parameters
# ---------------------------------------------------------------------------
@dataclass
class StressScenario:
    name: str
    equity_shock: float          # multiplicative, e.g. -0.10 means -10%
    credit_spread_shock_bps: int  # additive basis points
    liquidity_haircut_multiplier: float  # applied on top of stress haircuts
    redemption_rate: float        # fraction of NAV redeemed
    adv_stress_scalar: float = 1.0       # volume collapse: 0.5 = 50% of normal ADV
    rate_shock_bps: int = 0              # parallel rate shift applied to gov bonds
    version: str = "1.0"
    description: str = ""
    regulatory_basis: str = ""           # e.g. "ESMA MMFR Art.28 Scenario A"
    is_worst_case: bool = False
    last_reviewed: str = "2026-01-01"


STRESS_SCENARIOS: List[StressScenario] = [
    StressScenario(
        name="Base",
        equity_shock=0.00, credit_spread_shock_bps=0,
        liquidity_haircut_multiplier=1.0, redemption_rate=0.05,
        adv_stress_scalar=1.0, rate_shock_bps=0,
        version="1.0",
        description="Normal operating conditions with modest redemption pressure.",
        regulatory_basis="ESMA MMFR Art.28 — baseline calibration; AIFMD II Art.16(1)",
        is_worst_case=False, last_reviewed="2026-01-01",
    ),
    StressScenario(
        name="Equity-Led Stress -10%",
        equity_shock=-0.10, credit_spread_shock_bps=50,
        liquidity_haircut_multiplier=1.2, redemption_rate=0.10,
        adv_stress_scalar=0.80, rate_shock_bps=25,
        version="1.0",
        description="Equity-led correction (-10%) with correlated spread widening (+50bps) and partial ADV compression. All asset classes affected via haircut multiplier.",
        regulatory_basis="ESMA MMFR Art.28 Scenario A; AIFMD II Art.16(1) LMT stress",
        is_worst_case=False, last_reviewed="2026-01-01",
    ),
    StressScenario(
        name="Credit-Led Stress +100bps",
        equity_shock=0.00, credit_spread_shock_bps=100,
        liquidity_haircut_multiplier=1.3, redemption_rate=0.10,
        adv_stress_scalar=0.85, rate_shock_bps=30,
        version="1.0",
        description="Credit-led stress with spreads +100bps and moderate rate shift. Equity market value unchanged; all asset liquidity compressed via haircut multiplier.",
        regulatory_basis="ESMA MMFR Art.28 Scenario C; AIFMD II Art.16(1) LMT stress",
        is_worst_case=False, last_reviewed="2026-01-01",
    ),
    StressScenario(
        name="Equity-Led Stress -20%",
        equity_shock=-0.20, credit_spread_shock_bps=100,
        liquidity_haircut_multiplier=1.5, redemption_rate=0.15,
        adv_stress_scalar=0.70, rate_shock_bps=50,
        version="1.0",
        description="Equity-led drawdown (-20%) with material correlated spread widening (+100bps) and ADV compression. All asset classes affected via haircut multiplier.",
        regulatory_basis="ESMA MMFR Art.28 Scenario B; AIFMD II Art.16(1) LMT stress",
        is_worst_case=False, last_reviewed="2026-01-01",
    ),
    StressScenario(
        name="Credit-Led Stress +300bps",
        equity_shock=-0.05, credit_spread_shock_bps=300,
        liquidity_haircut_multiplier=1.8, redemption_rate=0.20,
        adv_stress_scalar=0.60, rate_shock_bps=75,
        version="1.0",
        description="Severe credit dislocation (+300bps) with significant ADV collapse and correlated mild equity drawdown (-5%). All asset classes affected via haircut multiplier.",
        regulatory_basis="ESMA MMFR Art.28 Scenario D; AIFMD II Art.16(1) LMT stress",
        is_worst_case=False, last_reviewed="2026-01-01",
    ),
    StressScenario(
        name="Severe Combined",
        equity_shock=-0.20, credit_spread_shock_bps=300,
        liquidity_haircut_multiplier=2.0, redemption_rate=0.30,
        adv_stress_scalar=0.50, rate_shock_bps=100,
        version="1.0",
        description="Simultaneous equity crash, credit crisis, and market freeze. Worst-case regulatory scenario.",
        regulatory_basis="ESMA MMFR Art.28 Scenario E — adverse; AIFMD II Art.16(1) worst-case LMT",
        is_worst_case=True, last_reviewed="2026-01-01",
    ),
]

# Redemption scenarios (fraction of NAV)
REDEMPTION_SCENARIOS: List[float] = [0.05, 0.10, 0.20, 0.30]

# Duration sensitivity for bond price impact per 100bps spread widening
# Bond PV01 approximation: price_change ≈ -modified_duration * spread_change
DURATION_BY_ASSET_CLASS: Dict[str, float] = {
    "government_bond":   5.5,
    "ig_corporate_bond": 4.2,
    "hy_corporate_bond": 3.1,
    "structured_credit": 3.8,
    "money_market":      0.3,
}

# Concentration flag: positions > this fraction of NAV are flagged
CONCENTRATION_FLAG_THRESHOLD: float = 0.05

# Maximum haircut applied to any single position (caps haircut scaling under stress)
MAX_HAIRCUT: float = 0.99

# Maximum days simulated in the daily liquidation loop before declaring illiquid
MAX_LIQUIDATION_DAYS: int = 500

# Acceptable credit spread range in basis points
CREDIT_SPREAD_BPS_RANGE: tuple = (0, 5000)

# Acceptable equity beta range
EQUITY_BETA_RANGE: tuple = (0, 3)

# Duration inference limits for bond positions
MAX_DURATION_YEARS: float = 15.0
DEFAULT_DURATION_YEARS: float = 3.0

# Maximum single-position equity loss applied in stress (caps beta amplification)
EQUITY_SHOCK_MAX_LOSS: float = 0.50

# Minimum cash buffer the fund must retain (% of NAV)
MIN_CASH_BUFFER_PCT: float = 0.02

# Maximum single-day liquidation as % of ADV (average daily volume)
MAX_ADV_PARTICIPATION: float = 0.20

# Regulatory reporting thresholds (ESMA MMFR / UCITS style)
LIQUIDITY_WARNING_THRESHOLD: float = 0.10   # <10% liquid in T+0+1 triggers warning
LIQUIDITY_BREACH_THRESHOLD: float  = 0.05   # <5% triggers breach

# ADV scalar applied when building the stress liquidity profile for redemption simulation.
# Represents a moderate market stress where trading volumes compress to 60% of normal.
REDEMPTION_STRESS_ADV_SCALAR: float = 0.60


# ---------------------------------------------------------------------------
# AIFMD II (Directive (EU) 2024/927) — effective 16 April 2026
# ---------------------------------------------------------------------------

# Liquidity Management Tools: fund must pre-select at least 2
AIFMD2_PRESELECTED_LMTS: List[str] = ["gate", "suspension", "swing_pricing"]
AIFMD2_MIN_LMT_COUNT: int = 2

# AIFMD II LMT taxonomy. Suspension and side pockets are "always available" to every
# manager (Art. 16(2b) — they need not be pre-selected and do not count toward the
# AIFMD2_MIN_LMT_COUNT requirement). The remaining tools are the ones a fund must
# actively pre-select; the ≥2 rule is counted against SELECTABLE_TOOLS only.
ALWAYS_AVAILABLE_LMTS: List[str] = ["suspension", "side_pockets"]
SELECTABLE_TOOLS: List[str] = [
    "gate",
    "notice_period_extension",
    "redemption_in_kind",
    "redemption_fee",
    "swing_pricing",
    "dual_pricing",
    "adl",
]

# Allowed share-class redemption frequencies (validated in validators.py).
REDEMPTION_FREQUENCIES: List[str] = ["daily", "weekly", "fortnightly", "monthly", "quarterly"]

# Leverage caps — Art. 15 and Art. 26a
AIFMD2_LEVERAGE_CAP_OPEN_ENDED: float  = 1.75   # 175% gross exposure / NAV (open-ended loan AIFs)
AIFMD2_LEVERAGE_CAP_CLOSED_ENDED: float = 3.00  # 300% (closed-ended loan AIFs)

# Loan origination AIF: ≥50% NAV in originated loans triggers the regime
AIFMD2_LOAN_ORIGINATION_THRESHOLD: float = 0.50

# Risk retention: originating AIFM must retain ≥5% of each originated loan notional
AIFMD2_RISK_RETENTION_MINIMUM: float = 0.05

# Borrower concentration: no single borrower > 20% NAV (ESMA guidance)
AIFMD2_BORROWER_CONCENTRATION_LIMIT: float = 0.20

# Geographical concentration — AIFMD Annex IV / ESMA34-39-897 Section 4.2
GEO_CONCENTRATION_WARNING_SINGLE: float = 0.35   # single country > 35% NAV → Warning
GEO_CONCENTRATION_BREACH_NON_EU: float = 0.50    # non-EU aggregate > 50% NAV → Breach
EU_COUNTRIES: frozenset = frozenset({
    "DE", "FR", "NL", "BE", "AT", "ES", "IT", "FI", "IE", "LU", "SE", "DK",
    "PT", "PL", "CZ", "HU", "RO", "SK", "SI", "BG", "HR", "LT", "LV", "EE",
    "CY", "MT", "GR",
})

# UCITS 5/10/40 issuer concentration rule (UCITS Directive Art. 52)
# No single transferable security issuer may exceed 5% NAV; up to 40% may be held
# in issuers where the individual weight is between 5% and 10%.
UCITS_SINGLE_ISSUER_LIMIT: float = 0.05       # hard limit per issuer
UCITS_AGGREGATE_BUCKET_LIMIT: float = 0.40    # max aggregate of positions 5-10%
UCITS_AGGREGATE_BUCKET_SINGLE_CAP: float = 0.10  # upper bound of the bucket

# Swing pricing — activates when net redemptions exceed the threshold
SWING_PRICING_THRESHOLD: float = 0.02   # 2% NAV
SWING_FACTOR_MAX: float = 0.02          # cap swing adjustment at 200 bps (2%)

# Anti-dilution levy — alternative to swing pricing; expressed as a rate
ADL_LEVY_RATE: float = 0.005   # 50 bps default levy on redeeming investors


# Gate / suspension thresholds (also used by RedemptionSimulator as class defaults)
GATE_THRESHOLD: float       = 0.10   # UCITS/AIFMD common practice
SUSPENSION_THRESHOLD: float = 0.25


# ---------------------------------------------------------------------------
# AIFM-level identification (required for ESMA Annex IV Header)
# Values default to placeholders so the pipeline runs out of the box; production
# deployments should override via environment variables. Missing/placeholder
# values are flagged by the Annex IV validation checks rather than blocking
# the export — regulators still receive a structurally valid file.
# ---------------------------------------------------------------------------
AIFM_LEI: str = os.environ.get("AIFM_LEI", "")
AIFM_NATIONAL_CODE: str = os.environ.get("AIFM_NATIONAL_CODE", "")
AIFM_REPORTING_MEMBER_STATE: str = os.environ.get("AIFM_REPORTING_MEMBER_STATE", "LU")
AIFM_NAME: str = os.environ.get("AIFM_NAME", "")
AIF_LEI: str = os.environ.get("AIF_LEI", "")
AIF_NATIONAL_CODE: str = os.environ.get("AIF_NATIONAL_CODE", "")
ANNEX_IV_SCHEMA_VERSION: str = "1.2"
ANNEX_IV_REGULATORY_BASIS: str = (
    "AIFMD II (Directive (EU) 2024/927), Annex IV reporting, effective 16 April 2026"
)


REVOLUTION_SCENARIOS: List[StressScenario] = [
    StressScenario(
        name="Normal",
        equity_shock=0.00, credit_spread_shock_bps=0,
        liquidity_haircut_multiplier=1.0, redemption_rate=0.05,
        adv_stress_scalar=1.00, rate_shock_bps=0,
        version="1.0",
        description="Current market conditions with modest redemption pressure.",
        regulatory_basis="Revolution Framework — baseline calibration",
        is_worst_case=False, last_reviewed="2026-01-01",
    ),
    StressScenario(
        name="Stressed (H1 2008)",
        equity_shock=-0.15, credit_spread_shock_bps=150,
        liquidity_haircut_multiplier=1.4, redemption_rate=0.15,
        adv_stress_scalar=0.75, rate_shock_bps=50,
        version="1.0",
        description="Sub-prime deterioration: equity -15%, spreads +150bps, ADV at 75% of normal.",
        regulatory_basis="Revolution Framework — historically calibrated (H1 2008)",
        is_worst_case=False, last_reviewed="2026-01-01",
    ),
    StressScenario(
        name="Highly Stressed (Sep 2008–Mar 2009)",
        equity_shock=-0.35, credit_spread_shock_bps=400,
        liquidity_haircut_multiplier=2.0, redemption_rate=0.30,
        adv_stress_scalar=0.45, rate_shock_bps=100,
        version="1.0",
        description="Lehman collapse: equity -35%, spreads +400bps, severe ADV compression to 45%.",
        regulatory_basis="Revolution Framework — historically calibrated (Lehman, Sep 2008–Mar 2009)",
        is_worst_case=False, last_reviewed="2026-01-01",
    ),
    StressScenario(
        name="Extreme (Covid-19)",
        equity_shock=-0.30, credit_spread_shock_bps=250,
        liquidity_haircut_multiplier=2.2, redemption_rate=0.40,
        adv_stress_scalar=0.40, rate_shock_bps=-75,
        version="1.0",
        description="Pandemic liquidity freeze: equity -30%, spreads +250bps, rate rally -75bps, ADV at 40%.",
        regulatory_basis="Revolution Framework — historically calibrated (Covid-19, Mar 2020)",
        is_worst_case=True, last_reviewed="2026-01-01",
    ),
]


def validate_scenario_severity_monotonic(scenarios: List[StressScenario] = None) -> bool:
    """Return True if liquidity_haircut_multiplier is non-decreasing across scenarios."""
    if scenarios is None:
        scenarios = STRESS_SCENARIOS
    multipliers = [s.liquidity_haircut_multiplier for s in scenarios]
    return all(multipliers[i] <= multipliers[i + 1] for i in range(len(multipliers) - 1))

