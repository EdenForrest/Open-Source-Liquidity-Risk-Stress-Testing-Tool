"""
AIFMD II leverage warnings — threshold comparisons only; the leverage
computations themselves (gross / commitment / loan share) stay in
``LeverageEngine``.
"""
from __future__ import annotations


def evaluate_leverage_warnings(
    gross: float,
    cap: float,
    loan_pct: float,
    is_loan_aif: bool,
    breach: bool,
    fund_type: str,
) -> list[str]:
    msgs = []
    if breach:
        msgs.append(
            f"Leverage breach: gross {gross*100:.1f}% exceeds "
            f"AIFMD II cap of {cap*100:.0f}% ({fund_type})"
        )
    if is_loan_aif:
        msgs.append(
            f"Loan origination AIF regime applies: {loan_pct*100:.1f}% NAV "
            "in originated loans (threshold 50%)"
        )
    # Threshold of 1.005 avoids false positives on pure long-only books where
    # floating-point arithmetic lands fractionally above 1.0.
    if gross > 1.005 and not is_loan_aif:
        msgs.append(
            f"Fund uses leverage ({gross*100:.1f}% gross); "
            "AIFMD II Art.15 disclosure required"
        )
    return msgs
