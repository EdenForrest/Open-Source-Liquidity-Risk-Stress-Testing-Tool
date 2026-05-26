"""
Pure data mapper: pipeline results → ESMA AIFMD Annex IV Part 2 data dict.
No I/O. Decoupled from the XML serialiser so the schema can be swapped without
rewriting the mapping logic.
"""
from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# ESMA Annex IV liquidity horizon codes (Part 2, Section 43)
# ---------------------------------------------------------------------------
_ESMA_HORIZONS = [
    "DAY_1", "DAY_2_7", "DAY_8_30", "DAY_31_90",
    "DAY_91_180", "DAY_181_365", "DAY_MORE_365",
]

_BUCKET_TO_ESMA: dict[str, str] = {
    "T+0": "DAY_1",
    "T+1": "DAY_1",
    "T+3": "DAY_2_7",
    "T+7": "DAY_2_7",
}


def _map_bucket_to_esma(bucket: str, lock_expiry_days: Optional[int] = None) -> str:
    """Map an internal liquidity bucket to an ESMA Annex IV horizon code."""
    if bucket in _BUCKET_TO_ESMA:
        return _BUCKET_TO_ESMA[bucket]
    # >T+7 — use lock_expiry_days if available
    days = lock_expiry_days
    if days is None:
        return "DAY_MORE_365"  # conservative default
    if days <= 30:
        return "DAY_8_30"
    if days <= 90:
        return "DAY_31_90"
    if days <= 180:
        return "DAY_91_180"
    if days <= 365:
        return "DAY_181_365"
    return "DAY_MORE_365"


def _map_buckets(position_buckets: list[dict]) -> dict[str, float]:
    """
    Aggregate position_buckets into ESMA horizon → % NAV mapping.
    Returns a dict keyed by horizon code; values are fractions (0–1).
    """
    totals: dict[str, float] = {h: 0.0 for h in _ESMA_HORIZONS}
    for pos in position_buckets:
        bucket = pos.get("bucket", ">T+7")
        lock = pos.get("lock_expiry_days")
        horizon = _map_bucket_to_esma(bucket, int(lock) if lock is not None else None)
        nav_pct = pos.get("weight") or pos.get("nav_pct") or 0.0
        totals[horizon] += float(nav_pct)
    return totals


def _top_n_instruments(position_buckets: list[dict], n: int = 5) -> list[dict]:
    """Return top-N instruments by NAV weight."""
    sorted_pos = sorted(
        position_buckets,
        key=lambda p: float(p.get("weight") or p.get("nav_pct") or 0.0),
        reverse=True,
    )
    result = []
    for pos in sorted_pos[:n]:
        result.append({
            "isin": pos.get("isin", ""),
            "name": pos.get("name", ""),
            "asset_class": pos.get("asset_class", ""),
            "market_value_eur": pos.get("market_value_eur") or pos.get("realisable_value_eur") or 0.0,
            "nav_pct": float(pos.get("weight") or pos.get("nav_pct") or 0.0),
            "bucket": pos.get("bucket", ""),
        })
    return result


def _top_n_countries(liquidity_metrics: dict, n: int = 5) -> list[dict]:
    """Extract top-N countries from liquidity_metrics.top_countries."""
    top = liquidity_metrics.get("top_countries") or []
    result = []
    for entry in top[:n]:
        if isinstance(entry, dict):
            result.append({
                "country_code": entry.get("country") or entry.get("country_code", ""),
                "nav_pct": float(entry.get("pct") or entry.get("nav_pct") or 0.0),
            })
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            result.append({"country_code": str(entry[0]), "nav_pct": float(entry[1])})
    return result


def _aggregate_concentrations(position_buckets: list[dict]) -> list[dict]:
    """Aggregate NAV % by asset class for portfolio concentration section."""
    agg: dict[str, float] = {}
    for pos in position_buckets:
        ac = pos.get("asset_class", "other")
        nav_pct = float(pos.get("weight") or pos.get("nav_pct") or 0.0)
        agg[ac] = agg.get(ac, 0.0) + nav_pct
    return [
        {"asset_class": ac, "nav_pct": pct}
        for ac, pct in sorted(agg.items(), key=lambda x: x[1], reverse=True)
    ]


def _investor_profile_from_share_classes(portfolio_results: dict) -> dict:
    """
    Build investor liquidity profile.
    share_classes are not serialised in the current pipeline output, so we
    return conservative defaults and flag the gap.
    """
    # If share_classes ever surfaces in the output use them; otherwise defaults
    share_classes = portfolio_results.get("share_classes") or []
    if share_classes:
        min_notice = min(
            (sc.get("notice_period_days", 90) for sc in share_classes), default=90
        )
        redemption_freq = share_classes[0].get("redemption_frequency", "monthly")
    else:
        min_notice = 90          # conservative default
        redemption_freq = "monthly"

    return {
        "min_notice_period_days": min_notice,
        "redemption_frequency": redemption_freq,
        "data_complete": bool(share_classes),  # False → gap flag in validation
    }


def _period_dates(period_code: str) -> tuple[str, str, str]:
    """
    Parse a period_code like '2026Q1', '2026H1', '2026' into
    (period_type, start_date, end_date) strings.
    Falls back to annual if code is unrecognised.
    """
    code = period_code.upper().strip()
    if "Q1" in code:
        year = code[:4]
        return "Q1", f"{year}-01-01", f"{year}-03-31"
    if "Q2" in code:
        year = code[:4]
        return "Q2", f"{year}-04-01", f"{year}-06-30"
    if "Q3" in code:
        year = code[:4]
        return "Q3", f"{year}-07-01", f"{year}-09-30"
    if "Q4" in code:
        year = code[:4]
        return "Q4", f"{year}-10-01", f"{year}-12-31"
    if "H1" in code:
        year = code[:4]
        return "H1", f"{year}-01-01", f"{year}-06-30"
    if "H2" in code:
        year = code[:4]
        return "H2", f"{year}-07-01", f"{year}-12-31"
    # Annual or bare year
    year = code[:4] if len(code) >= 4 else "2026"
    return "Annual", f"{year}-01-01", f"{year}-12-31"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_annex_iv(
    portfolio_results: dict,
    period_code: str = "2026Q1",
    aifm_metadata: dict | None = None,
) -> dict:
    """
    Map pipeline portfolio_results to an ESMA AIFMD Annex IV Part 2 data dict.

    Returns a structured dict — no XML or I/O.  The export_service serialises
    this to XML or adds it as an Excel sheet.

    Args:
        portfolio_results: single-portfolio result dict from pipeline_service
        period_code: reporting period string e.g. '2026Q1', '2026H1', '2026'
        aifm_metadata: override dict for AIFM-level fields (LEI, name, etc.)
                       falls back to settings constants if not supplied
    """
    from liquidity_risk_tool.config import settings

    meta = aifm_metadata or {}

    aifm_lei = meta.get("aifm_lei") or settings.AIFM_LEI or ""
    aifm_national_code = meta.get("aifm_national_code") or settings.AIFM_NATIONAL_CODE or ""
    aifm_name = meta.get("aifm_name") or settings.AIFM_NAME or ""
    aifm_member_state = meta.get("reporting_member_state") or settings.AIFM_REPORTING_MEMBER_STATE or "LU"
    aif_lei = meta.get("aif_lei") or settings.AIF_LEI or ""
    aif_national_code = meta.get("aif_national_code") or settings.AIF_NATIONAL_CODE or ""
    schema_version = settings.ANNEX_IV_SCHEMA_VERSION

    period_type, period_start, period_end = _period_dates(period_code)

    position_buckets = portfolio_results.get("position_buckets") or []
    liquidity_metrics = portfolio_results.get("liquidity_metrics") or {}
    aifmd2 = portfolio_results.get("aifmd2") or {}
    stress_results = portfolio_results.get("stress_results") or []

    # --- Worst-case stress scenario (Severe Combined or highest haircut multiplier)
    worst_stress = next(
        (s for s in stress_results if s.get("is_worst_case")),
        stress_results[-1] if stress_results else {},
    )

    # --- Asset liquidity profile
    asset_liquidity = _map_buckets(position_buckets)

    # --- Investor liquidity profile
    investor_profile = _investor_profile_from_share_classes(portfolio_results)

    # --- LMT / special arrangements
    lmts = aifmd2.get("lmt_preselected") or []
    lmt_config = aifmd2.get("lmt_config_applied") or {}

    # Determine which tools are active
    gate_active = "gate" in lmts
    suspension_active = "suspension" in lmts
    swing_pricing_active = "swing_pricing" in lmts
    side_pocket_active = "side_pocket" in lmts or lmt_config.get("side_pocket", False)

    return {
        # ---- Header --------------------------------------------------------
        "schema_version": schema_version,
        "reporting_member_state": aifm_member_state,
        "period_code": period_code,
        "period_type": period_type,
        "period_start": period_start,
        "period_end": period_end,

        # ---- AIFM identification -------------------------------------------
        "aifm": {
            "lei": aifm_lei,
            "national_code": aifm_national_code,
            "name": aifm_name,
            "reporting_member_state": aifm_member_state,
        },

        # ---- AIF identification --------------------------------------------
        "aif": {
            "lei": aif_lei,
            "national_code": aif_national_code,
            "name": portfolio_results.get("fund_name", ""),
            "reporting_date": portfolio_results.get("reporting_date", ""),
            "total_nav_eur": portfolio_results.get("total_nav_eur", 0.0),
        },

        # ---- Principal markets (top 5 countries by NAV) --------------------
        "principal_markets": _top_n_countries(liquidity_metrics, n=5),

        # ---- Principal instruments (top 5 by NAV weight) -------------------
        "principal_instruments": _top_n_instruments(position_buckets, n=5),

        # ---- Portfolio concentration by asset class ------------------------
        "portfolio_concentrations": _aggregate_concentrations(position_buckets),

        # ---- Asset liquidity profile (ESMA 7-bucket horizon) ---------------
        "asset_liquidity_profile": asset_liquidity,

        # ---- Investor liquidity profile ------------------------------------
        "investor_liquidity_profile": investor_profile,

        # ---- Geographical concentration ------------------------------------
        "geographical_concentration": {
            "eu_pct": liquidity_metrics.get("eu_pct", 0.0),
            "non_eu_pct": liquidity_metrics.get("non_eu_pct", 0.0),
            "top_countries": _top_n_countries(liquidity_metrics, n=5),
            "geo_status": liquidity_metrics.get("geo_status", ""),
        },

        # ---- Special arrangements / LMTs -----------------------------------
        "special_arrangements": {
            "gate": gate_active,
            "suspension": suspension_active,
            "swing_pricing": swing_pricing_active,
            "side_pocket": side_pocket_active,
            "lmt_list": lmts,
            "lmt_count": len(lmts),
            "lmt_compliant": aifmd2.get("lmt_compliant", False),
            "gate_threshold": lmt_config.get("gate_threshold", 0.10),
            "suspension_threshold": lmt_config.get("suspension_threshold", 0.25),
            "swing_factor_max": lmt_config.get("swing_factor_max", 0.02),
        },

        # ---- Leverage (Art. 15 AIFMD II / CDR 231/2013 Art. 7-8) ----------
        "leverage": {
            "gross_leverage": aifmd2.get("gross_leverage"),
            "commitment_leverage": aifmd2.get("commitment_leverage"),
            "leverage_cap": aifmd2.get("leverage_cap"),
            "leverage_breach": aifmd2.get("leverage_breach", False),
            "cap_utilization_pct": (
                (aifmd2.get("gross_leverage") or 0.0) / (aifmd2.get("leverage_cap") or 1.0)
                if aifmd2.get("leverage_cap") else None
            ),
        },

        # ---- Stress testing disclosure (Annex IV §48) ----------------------
        "stress_disclosure": {
            "scenario_name": worst_stress.get("scenario", ""),
            "nav_before_eur": worst_stress.get("nav_before_eur"),
            "nav_after_eur": worst_stress.get("nav_after_eur"),
            "nav_impact_pct": worst_stress.get("nav_impact_pct"),
            "liquid_pct_before": worst_stress.get("liquid_pct_before"),
            "liquid_pct_after": worst_stress.get("liquid_pct_after"),
            "equity_shock": worst_stress.get("equity_shock"),
            "credit_spread_shock_bps": worst_stress.get("credit_spread_shock_bps"),
            "regulatory_basis": worst_stress.get("regulatory_basis", ""),
        },

        # ---- Gaps / completeness flags -------------------------------------
        "gaps": {
            "aifm_lei_missing": not aifm_lei,
            "aifm_national_code_missing": not aifm_national_code,
            "aif_lei_missing": not aif_lei,
            "investor_profile_incomplete": not investor_profile["data_complete"],
            "country_data_missing": not _top_n_countries(liquidity_metrics, n=1),
            "leverage_missing": not aifmd2.get("gross_leverage"),
            "stress_missing": not stress_results,
        },
    }
