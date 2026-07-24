"""
Regulatory rule evaluations
---------------------------
Pure functions encoding the compliance rules the engines report against:

* ``geo``      — geographical concentration (AIFMD Annex IV / ESMA34-39-897 §4.2)
* ``ucits``    — UCITS 5/10/40 issuer concentration (Art. 52 UCITS Directive)
* ``aifmd``    — AIFMD II Art. 16 LMT pre-selection rules (MODEL.md §20.4)
* ``leverage`` — AIFMD II leverage-cap / loan-origination warnings

These are evaluations only — LMT *mechanics* (gates, swing pricing, ADL
application) live in the redemption simulator, and threshold values live in
``liquidity_risk_tool.config.settings``.
"""
from .aifmd import check_lmt_count, check_lmt_declared
from .geo import evaluate_geo_concentration
from .leverage import evaluate_leverage_warnings
from .ucits import evaluate_ucits_5_10_40

__all__ = [
    "check_lmt_count",
    "check_lmt_declared",
    "evaluate_geo_concentration",
    "evaluate_leverage_warnings",
    "evaluate_ucits_5_10_40",
]
