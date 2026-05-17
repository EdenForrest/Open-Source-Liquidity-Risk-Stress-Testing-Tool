"""
Central configuration for the Liquidity Risk & Stress Testing Tool.
All thresholds, bucket definitions, and scenario parameters live here.
"""
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
        regulatory_basis="ESMA MMFR Art.28 — baseline calibration",
        is_worst_case=False, last_reviewed="2026-01-01",
    ),
    StressScenario(
        name="Equity-Led Stress -10%",
        equity_shock=-0.10, credit_spread_shock_bps=50,
        liquidity_haircut_multiplier=1.2, redemption_rate=0.10,
        adv_stress_scalar=0.80, rate_shock_bps=25,
        version="1.0",
        description="Equity-led correction (-10%) with correlated spread widening (+50bps) and partial ADV compression. All asset classes affected via haircut multiplier.",
        regulatory_basis="ESMA MMFR Art.28 Scenario A",
        is_worst_case=False, last_reviewed="2026-01-01",
    ),
    StressScenario(
        name="Credit-Led Stress +100bps",
        equity_shock=0.00, credit_spread_shock_bps=100,
        liquidity_haircut_multiplier=1.3, redemption_rate=0.10,
        adv_stress_scalar=0.85, rate_shock_bps=30,
        version="1.0",
        description="Credit-led stress with spreads +100bps and moderate rate shift. Equity market value unchanged; all asset liquidity compressed via haircut multiplier.",
        regulatory_basis="ESMA MMFR Art.28 Scenario C",
        is_worst_case=False, last_reviewed="2026-01-01",
    ),
    StressScenario(
        name="Equity-Led Stress -20%",
        equity_shock=-0.20, credit_spread_shock_bps=100,
        liquidity_haircut_multiplier=1.5, redemption_rate=0.15,
        adv_stress_scalar=0.70, rate_shock_bps=50,
        version="1.0",
        description="Equity-led drawdown (-20%) with material correlated spread widening (+100bps) and ADV compression. All asset classes affected via haircut multiplier.",
        regulatory_basis="ESMA MMFR Art.28 Scenario B",
        is_worst_case=False, last_reviewed="2026-01-01",
    ),
    StressScenario(
        name="Credit-Led Stress +300bps",
        equity_shock=-0.05, credit_spread_shock_bps=300,
        liquidity_haircut_multiplier=1.8, redemption_rate=0.20,
        adv_stress_scalar=0.60, rate_shock_bps=75,
        version="1.0",
        description="Severe credit dislocation (+300bps) with significant ADV collapse and correlated mild equity drawdown (-5%). All asset classes affected via haircut multiplier.",
        regulatory_basis="ESMA MMFR Art.28 Scenario D",
        is_worst_case=False, last_reviewed="2026-01-01",
    ),
    StressScenario(
        name="Severe Combined",
        equity_shock=-0.20, credit_spread_shock_bps=300,
        liquidity_haircut_multiplier=2.0, redemption_rate=0.30,
        adv_stress_scalar=0.50, rate_shock_bps=100,
        version="1.0",
        description="Simultaneous equity crash, credit crisis, and market freeze. Worst-case regulatory scenario.",
        regulatory_basis="ESMA MMFR Art.28 Scenario E — adverse",
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


def validate_scenario_severity_monotonic(scenarios: List[StressScenario] = None) -> bool:
    """Return True if liquidity_haircut_multiplier is non-decreasing across scenarios."""
    if scenarios is None:
        scenarios = STRESS_SCENARIOS
    multipliers = [s.liquidity_haircut_multiplier for s in scenarios]
    return all(multipliers[i] <= multipliers[i + 1] for i in range(len(multipliers) - 1))

