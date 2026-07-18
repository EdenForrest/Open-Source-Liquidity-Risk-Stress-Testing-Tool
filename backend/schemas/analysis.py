"""
Request models for ``backend.routers.analysis``.

These were previously defined inline in the router. They are moved here so the
router is a thin HTTP layer; the regulatory invariants encoded by
``LmtConfig._enforce_aifmd2_rules`` (AIFMD II §20.4) are preserved exactly.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from liquidity_risk_tool.config.settings import (
    AIFMD2_MIN_LMT_COUNT,
    SELECTABLE_TOOLS,
)


class LmtConfig(BaseModel):
    """
    Typed AIFMD II LMT configuration with server-side compliance enforcement.

    All cost params are fractions in [0, 1]; day params are >= 0. The
    ``model_validator`` enforces the two MODEL.md §20.4 rules:
      1. at least ``AIFMD2_MIN_LMT_COUNT`` selectable LMTs active (suspension /
         side_pockets are always-available and do not count — only
         ``SELECTABLE_TOOLS`` are counted), and
      2. swing_pricing and dual_pricing are mutually exclusive.
    Violations raise a ``ValueError`` → FastAPI returns HTTP 422.

    ``dual_spread_frac`` is the canonical bid-spread key; ``dual_spread_bps`` is
    still accepted as a backward-compatible alias (also a fraction on the wire).
    """

    model_config = {"extra": "allow"}

    active_tools: List[str] = Field(default_factory=list)
    gate_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    suspension_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    swing_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    swing_factor_max: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    adl_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    fee_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    notice_extension_days: Optional[int] = Field(default=None, ge=0)
    in_kind_pct: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    dual_spread_frac: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    dual_spread_bps: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _enforce_aifmd2_rules(self) -> "LmtConfig":
        # Rule 1: at least AIFMD2_MIN_LMT_COUNT *selectable* LMTs must be active.
        selectable = {t for t in self.active_tools if t in SELECTABLE_TOOLS}
        if len(selectable) < AIFMD2_MIN_LMT_COUNT:
            raise ValueError(
                f"AIFMD II requires at least {AIFMD2_MIN_LMT_COUNT} selectable LMTs "
                f"active (suspension and side_pockets are always-available and do "
                f"not count); got {sorted(selectable)} from {self.active_tools}."
            )
        # Rule 2: swing_pricing and dual_pricing are mutually exclusive.
        if "swing_pricing" in self.active_tools and "dual_pricing" in self.active_tools:
            raise ValueError(
                "swing_pricing and dual_pricing are mutually exclusive anti-dilution "
                "tools — activate at most one."
            )
        return self


class LMTSimRequest(BaseModel):
    lmt_config: LmtConfig = Field(default_factory=LmtConfig)
    scenarios: Optional[List[float]] = None
    portfolio: Optional[str] = None


class CustomScenarioRequest(BaseModel):
    """
    A user-defined stress scenario. Field semantics mirror ``StressScenario``:

      equity_shock                multiplicative price shock on equities/ETFs,
                                  e.g. -0.10 == -10% (range [-1, 1]).
      credit_spread_shock_bps     additive credit-spread widening in basis points.
      rate_shock_bps              parallel rate shift applied to government bonds.
      liquidity_haircut_multiplier  uplift on stress haircuts (1.0 == no uplift).
      redemption_rate             fraction of NAV redeemed in the scenario (0–1).
      adv_stress_scalar           ADV collapse: 0.5 == 50% of normal volume.

    The scenario is run via the StressEngine against a freshly re-loaded
    portfolio (the engine reprices real positions, so a results-only stub will
    not do), and the resulting ScenarioResult + parameter metadata are returned
    in the same shape as the pipeline's ``stress_results`` / ``scenario_metadata``
    so the UI can append them to the existing tables.
    """

    name: str = Field(default="Custom Scenario", min_length=1, max_length=80)
    equity_shock: float = Field(default=0.0, ge=-1.0, le=1.0)
    credit_spread_shock_bps: int = Field(default=0, ge=0, le=10000)
    rate_shock_bps: int = Field(default=0, ge=-10000, le=10000)
    # Bounded by the severe corner of the plausible-shock box (ParameterAxis
    # severe=2.8 in reverse_stress_engine.py). Custom what-if scenarios must
    # stay inside the same regulatory plausible box as the reverse-stress
    # search, so a manual entry cannot exceed the haircut bound it reports.
    liquidity_haircut_multiplier: float = Field(default=1.0, ge=1.0, le=2.8)
    redemption_rate: float = Field(default=0.05, ge=0.0, le=1.0)
    adv_stress_scalar: float = Field(default=1.0, gt=0.0, le=5.0)
    portfolio: Optional[str] = None


class ReverseStressRequest(BaseModel):
    portfolio: Optional[str] = None
    # Prefer the compiled C++ search core when available. Purely a performance
    # choice: the native and Python paths are numerically identical, so this
    # only changes speed. Falls back to Python when the core is not built.
    use_native: bool = True
    # Optional user-tunable severe-endpoint ("ceiling") overrides for the five
    # reverse-stress axes. Each is the value the severity fraction s=1 maps to;
    # omitting one leaves the calibrated DEFAULT_AXES ceiling in place. Bounds
    # below keep every override inside a severe-but-plausible envelope so the box
    # the optimiser searches can never become economically incoherent (e.g. a
    # positive equity "shock" or a >100% single-period redemption). The fraction
    # is always clamped to [0, 1], so a lever can only run calm -> ceiling.
    equity_shock_severe: Optional[float] = Field(default=None, ge=-0.90, le=-0.05)
    rate_shock_bps_severe: Optional[float] = Field(default=None, ge=50.0, le=800.0)
    adv_stress_scalar_severe: Optional[float] = Field(default=None, ge=0.05, le=0.95)
    liquidity_haircut_multiplier_severe: Optional[float] = Field(default=None, ge=1.1, le=5.0)
    redemption_rate_severe: Optional[float] = Field(default=None, ge=0.05, le=0.60)


class WaterfallOptimiseRequest(BaseModel):
    portfolio: Optional[str] = None
