"""
Synthetic data generator for liquidity risk tool.

Produces files that are structurally identical to the real input files
(same columns, delimiters, encoding, and value ranges) but contain
ZERO real data — every value is generated from scratch using only
Python's standard library random module and publicly known financial
conventions.

This complies with Refinitiv / LSEG license restrictions: no actual
market data, holdings data, or client data is copied, derived, or
transformed here.

Output files (written to the same directory as this script by default):
    HOLDINGS_<timestamp>.csv    — holdings (semicolon-delimited, European decimal)
    NAV_<timestamp>.csv         — NAV per portfolio (semicolon-delimited)
    market_data_ALL.csv             — market data (comma-delimited)
    market_data_ERRORS.csv          — fetch errors (comma-delimited)
    zero_coupon_yields.xlsx         — US zero-coupon yield curve (xlsx)

Column schemas are taken from the real file headers only.
"""

from __future__ import annotations

import csv
import os
import random
import string
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------

def _seed(s: int = 42) -> None:
    random.seed(s)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _eu(v: float, decimals: int = 2) -> str:
    """Format a float in European decimal style: comma as decimal separator."""
    return f"{v:.{decimals}f}".replace(".", ",")


def _isin(country: str = "DE") -> str:
    """Generate a plausible-looking but entirely synthetic ISIN."""
    digits = "".join(random.choices(string.digits, k=9))
    check  = random.randint(0, 9)
    return f"{country}{digits}{check}"


def _ric_equity(isin: str) -> str:
    suffix = random.choice([".DE", ".PA", ".AS", ".MI", ".L", ".SW"])
    stem   = "".join(random.choices(string.ascii_uppercase, k=random.randint(3, 5)))
    return f"{stem}{suffix}"


def _ric_bond(isin: str) -> str:
    return f"{isin}="


def _random_date_str(start: date, end: date, fmt: str = "%d.%m.%Y") -> str:
    delta = (end - start).days
    d = start + timedelta(days=random.randint(0, delta))
    return d.strftime(fmt)


def _rating() -> str:
    return random.choice(["AAA", "AA+", "AA", "AA-", "A+", "A", "A-",
                          "BBB+", "BBB", "BBB-", "BB+", "BB", "B+", "B", "CCC"])


# ---------------------------------------------------------------------------
# Portfolio / security universe
# ---------------------------------------------------------------------------

# Seven synthetic portfolios with distinct mandates:
#
#  SYN-EQUITY    : 100% listed equities → T+1 liquid, fully compliant
#  SYN-GOVBOND   : 100% government bonds → T+1 liquid, fully compliant
#  SYN-FIXEDINC  : Government + HY + IG bonds → T+1/T+3/T+7, compliant
#  SYN-MIXED     : Equities + gov + HY + IG + futures + forwards (hedging) → compliant
#  SYN-ILLIQ     : HY-heavy + illiquid IG + minimal cash → NON-COMPLIANT
#                  T+0/T+1 < 5% of NAV → triggers regulatory breach
#  SYN-LOANFUND  : >50% originated loans → triggers loan origination AIF regime
#                  one large borrower > 20% NAV → borrower concentration breach
#  SYN-LEVERAGED : heavy TRS + futures → gross leverage > 175% AIFMD II cap → BREACH
PORTFOLIOS = ["SYN-EQUITY", "SYN-GOVBOND", "SYN-FIXEDINC", "SYN-MIXED", "SYN-ILLIQ",
              "SYN-LOANFUND", "SYN-LEVERAGED"]

# Asset-class weights per portfolio mandate.
# Keys map to _holdings_per_portfolio weight dicts.
PORTFOLIO_WEIGHTS: dict[str, dict] = {
    # Portfolio 1: 100% listed equity — T+1 liquid, compliant
    "SYN-EQUITY": {
        "listed_equity":     0.97,
        "cash":              0.03,
    },
    # Portfolio 2: 100% government bonds — T+1 liquid, compliant
    "SYN-GOVBOND": {
        "government_bond":   0.95,
        "cash":              0.05,
    },
    # Portfolio 3: Government + HY + IG bond mix — compliant
    # Gov bonds (T+1) dominate; HY (T+7) and IG (T+3) are minority
    "SYN-FIXEDINC": {
        "government_bond":   0.55,
        "ig_corporate_bond": 0.25,
        "hy_corporate_bond": 0.12,
        "cash":              0.08,
    },
    # Portfolio 4: Mixed — equity + gov + HY + IG + futures + forwards (hedging)
    # + leveraged equity (margin) + TRS (total return swaps)
    # Liquid assets (equity + gov + cash) represent ~60% of NAV → compliant
    "SYN-MIXED": {
        "listed_equity":      0.25,
        "government_bond":    0.20,
        "ig_corporate_bond":  0.15,
        "hy_corporate_bond":  0.08,
        "future":             0.10,   # hedging — futures settle T+1
        "forward":            0.07,   # hedging — FX forwards
        "leveraged_equity":   0.07,   # equity on margin — Exposure (base) > MV
        "trs":                0.03,   # total return swap — MV ≈ 0, large notional
        "cash":               0.05,
    },
    # Portfolio 5: HY-dominated with minimal liquid buffer — NON-COMPLIANT
    # Cash is injected as a fixed tiny balance (€200k–€800k) separately.
    # Options have near-zero MV → T+0+T+1 < 5% of NAV → BREACH
    "SYN-ILLIQ": {
        "hy_corporate_bond": 0.76,
        "ig_corporate_bond": 0.24,
    },
    # Portfolio 6: Loan origination AIF — >50% of NAV in originated loans
    # Triggers AIFMD II loan origination AIF regime (Art. 15a CDR).
    # One large borrower exceeds 20% NAV concentration limit → breach.
    # Handled via special-case logic in generate_holdings (two-pass sizing).
    "SYN-LOANFUND": {
        "originated_loan":   0.55,
        "ig_corporate_bond": 0.30,
        "cash":              0.15,
    },
    # Portfolio 7: Heavily leveraged derivatives — gross leverage > 175% AIFMD II cap.
    # Handled via special-case logic in generate_holdings: TRS notionals are
    # sized to 120% of the base-asset NAV so that total gross exposure ≈ 2.2× NAV.
    "SYN-LEVERAGED": {
        "listed_equity":    0.60,
        "government_bond":  0.20,
        "trs":              0.15,
        "future":           0.05,
    },
}

ASSET_CLASSES = [
    "listed_equity",
    "government_bond",
    "ig_corporate_bond",
    "hy_corporate_bond",
    "etf",
    "option",
    "future",
    "forward",
    "leveraged_equity",
    "trs",
    "cash",
    "originated_loan",
]

CURRENCIES = ["EUR", "USD", "GBP", "CHF", "JPY", "SEK", "DKK"]

# FX rates to EUR (rough publicly-known mid-market levels, NOT Refinitiv data)
_FX_BASE = {
    "EUR": 1.0,
    "USD": 0.92,
    "GBP": 1.18,
    "CHF": 1.05,
    "JPY": 0.0062,
    "SEK": 0.088,
    "DKK": 0.134,
}

ISIN_COUNTRIES = ["DE", "FR", "NL", "BE", "AT", "ES", "IT", "FI",
                  "IE", "LU", "GB", "US", "CH", "SE", "DK"]

EQUITY_COUNTRIES = ["DE", "FR", "NL", "BE", "AT", "ES", "IT",
                    "FI", "GB", "US", "CH", "SE", "IE", "LU", "PT"]

BOND_COUNTRIES   = ["DE", "FR", "IT", "ES", "NL", "AT", "FI", "BE", "US", "GB"]

ETF_COUNTRIES    = ["IE", "LU"]   # UCITS domicile for ETFs

# Geo concentration overrides — force specific country ISINs at given probability
# to trigger AIFMD Annex IV geo flags in two demo portfolios.
# probability is per-position (applied independently to each bond/equity row).
PORTFOLIO_GEO_OVERRIDES: dict[str, dict] = {
    # SYN-GOVBOND: force ~75% of positions to DE → single country DE > 35% NAV → Warning
    "SYN-GOVBOND": {"country": "DE", "probability": 0.75},
    # SYN-ILLIQ: force ~38% of positions to US → single country US ~37-43% NAV → Warning (not breach)
    "SYN-ILLIQ":   {"country": "US", "probability": 0.38},
}

# Per-portfolio equity position size caps (EUR MV). Prevents a single large-price equity
# position from dominating a portfolio's geo distribution under an unlucky random seed.
# SYN-EQUITY cap keeps all positions T+1 liquidatable within ADV limits.
# All other equity-holding portfolios are capped at 30M to keep single-country exposure < 35% NAV.
EQUITY_MAX_MV: dict[str, float] = {
    "SYN-EQUITY":    8_000_000.0,
    "SYN-GOVBOND":  30_000_000.0,
    "SYN-FIXEDINC": 30_000_000.0,
    "SYN-MIXED":    30_000_000.0,
    "SYN-ILLIQ":    30_000_000.0,
    "SYN-LOANFUND": 30_000_000.0,
    "SYN-LEVERAGED":30_000_000.0,
}


# ---------------------------------------------------------------------------
# Security name generation (no real issuer names — fully synthetic)
# ---------------------------------------------------------------------------

_BOND_TYPES = ["MTN", "Note", "Bond", "Senior Note", "Covered Bond", "Pfandbrief"]
_GOV_LABELS = ["Republic", "Government", "Sovereign", "Treasury", "Bundesanleihe"]

def _synth_equity_name() -> str:
    syllables = ["Corp", "Tech", "Global", "Alpha", "Beta", "Delta",
                 "Nova", "Prime", "Apex", "Zeta", "Orion", "Vector"]
    suffixes  = ["AG", "SA", "NV", "PLC", "SE", "GmbH & Co KGaA", "Inc"]
    return f"{random.choice(syllables)} {random.choice(syllables)} {random.choice(suffixes)}"


def _synth_bond_name(asset_class: str, maturity_year: int) -> str:
    coupon = round(random.uniform(0.5, 6.5), 3)
    yy     = str(maturity_year)[2:]   # last 2 digits
    if asset_class == "government_bond":
        label = random.choice(_GOV_LABELS)
        return f"Synth {label} {coupon:.3f}% v{yy}"
    elif asset_class == "hy_corporate_bond":
        stem = random.choice(["HY", "HIGH YIELD"]) + " "
        return f"Synth {stem}{random.choice(_BOND_TYPES)} {coupon:.3f}% v{yy}"
    else:
        return f"Synth {random.choice(_BOND_TYPES)} {coupon:.3f}% v{yy}"


def _synth_etf_name() -> str:
    indices = ["Equity Index", "Bond Index", "Multi-Asset", "Dividend", "Growth"]
    return f"Synth {random.choice(indices)} UCITS ETF"


def _synth_option_name() -> str:
    direction = random.choice(["PUT", "CALL"])
    strike    = random.choice([3200, 3500, 3800, 4000, 4200, 4500, 5000])
    return f"{direction} Synth Index {strike}"


def _synth_future_name() -> str:
    return f"FUTURE Synth Index {random.randint(25, 27)}{random.choice(['03','06','09','12'])}"


# ---------------------------------------------------------------------------
# Per-asset-class row generators
# ---------------------------------------------------------------------------

def _gen_cash_row(portfolio: str, report_date: str) -> dict:
    ccy    = random.choice(["EUR", "USD", "GBP"])
    fx     = _FX_BASE[ccy] * random.uniform(0.97, 1.03)
    amt    = random.uniform(100_000, 5_000_000)
    mv_eur = amt / fx   # already in base currency
    return {
        "Portfolio Code":               portfolio,
        "Date":                         report_date,
        "Security Name":                f"Cash {ccy}",
        "ISIN":                         f"CASH-{ccy}",
        "Quantity":                     _eu(amt, 2),
        "Clean price (local)":          "1",
        "Exchange rate":                "1",   # MV already in EUR base
        "Market Value in Base Currency": _eu(mv_eur, 2),
        "Accruals in Base Currency":    "",
        "Currency":                     ccy,
        "Exposure (base)":              "",
        "Product Code":                 "",
        "Price Include":                "",
        "PriceFactor":                  "1",
    }


def _gen_equity_row(
    portfolio: str,
    report_date: str,
    forced_country: str | None = None,
    max_mv_eur: float | None = None,
) -> dict:
    country  = forced_country if forced_country else random.choice(EQUITY_COUNTRIES)
    isin     = _isin(country)
    ccy      = "EUR" if country not in ("GB", "US", "CH", "SE", "DK") else (
                "GBP" if country == "GB" else
                "USD" if country == "US" else
                "CHF" if country == "CH" else
                "SEK" if country == "SE" else "DKK")
    fx       = _FX_BASE[ccy] * random.uniform(0.97, 1.03)
    price    = random.uniform(5.0, 500.0)
    if max_mv_eur is not None:
        max_qty = max(1, int(max_mv_eur * fx / price))
        qty = random.randint(100, max(100, min(max_qty, 50_000)))
    else:
        qty = random.randint(500, 200_000)
    mv_local = price * qty
    mv_eur   = mv_local / fx
    return {
        "Portfolio Code":               portfolio,
        "Date":                         report_date,
        "Security Name":                _synth_equity_name(),
        "ISIN":                         isin,
        "Quantity":                     str(qty),
        "Clean price (local)":          _eu(price, 4),
        "Exchange rate":                "1",   # MV already in EUR base
        "Market Value in Base Currency": _eu(mv_eur, 10),
        "Accruals in Base Currency":    "",
        "Currency":                     ccy,
        "Exposure (base)":              "",
        "Product Code":                 "",
        "Price Include":                "",
        "PriceFactor":                  "1",
    }


def _gen_bond_row(portfolio: str, report_date: str, asset_class: str, forced_country: str | None = None) -> dict:
    country      = forced_country if forced_country is not None else random.choice(BOND_COUNTRIES)
    isin         = _isin(country)
    ccy          = "EUR" if country not in ("GB", "US") else ("GBP" if country == "GB" else "USD")
    fx           = _FX_BASE[ccy] * random.uniform(0.97, 1.03)
    report_year  = int(report_date[-4:])   # dd.mm.yyyy
    mat_year     = report_year + random.randint(1, 15)
    price_pct    = random.uniform(85.0, 105.0)   # % of par
    notional     = random.choice([100_000, 200_000, 500_000, 1_000_000, 2_000_000, 5_000_000])
    mv_eur       = notional * price_pct / 100.0 / fx   # already converted to EUR base
    accrual_eur  = notional * random.uniform(0.0, 0.02) / fx
    return {
        "Portfolio Code":               portfolio,
        "Date":                         report_date,
        "Security Name":                _synth_bond_name(asset_class, mat_year),
        "ISIN":                         isin,
        "Quantity":                     str(notional),
        "Clean price (local)":          _eu(price_pct, 4),
        "Exchange rate":                "1",   # MV already in EUR base
        "Market Value in Base Currency": _eu(mv_eur, 10),
        "Accruals in Base Currency":    _eu(accrual_eur, 10),
        "Currency":                     ccy,
        "Exposure (base)":              "",
        "Product Code":                 "",
        "Price Include":                "",
        "PriceFactor":                  "0,01",
    }


def _gen_etf_row(portfolio: str, report_date: str) -> dict:
    country = random.choice(ETF_COUNTRIES)
    isin    = _isin(country)
    ccy     = random.choice(["EUR", "USD"])
    fx      = _FX_BASE[ccy] * random.uniform(0.97, 1.03)
    price   = random.uniform(20.0, 200.0)
    qty     = random.randint(1_000, 100_000)
    mv_eur  = price * qty / fx   # already converted to EUR base
    return {
        "Portfolio Code":               portfolio,
        "Date":                         report_date,
        "Security Name":                _synth_etf_name(),
        "ISIN":                         isin,
        "Quantity":                     str(qty),
        "Clean price (local)":          _eu(price, 4),
        "Exchange rate":                "1",   # MV already in EUR base
        "Market Value in Base Currency": _eu(mv_eur, 10),
        "Accruals in Base Currency":    "",
        "Currency":                     ccy,
        "Exposure (base)":              "",
        "Product Code":                 "",
        "Price Include":                "",
        "PriceFactor":                  "1",
    }


def _gen_option_row(portfolio: str, report_date: str) -> dict:
    idx_code = f"OPO{random.choice(['ESX','SPX','DAX'])}"
    strike   = random.choice([3200, 3500, 3800, 4000, 4500, 5000])
    yymm     = random.choice(["0526", "0626", "0726", "0926"])
    isin     = f"{idx_code}/SYN{strike}{yymm}_SYN_EUR"
    qty      = random.randint(10, 500)
    price    = random.uniform(0.05, 10.0)
    mv       = qty * price
    exposure = qty * strike * random.uniform(0.8, 1.2)
    return {
        "Portfolio Code":               portfolio,
        "Date":                         report_date,
        "Security Name":                _synth_option_name(),
        "ISIN":                         isin,
        "Quantity":                     str(qty),
        "Clean price (local)":          _eu(price, 4),
        "Exchange rate":                "1",
        "Market Value in Base Currency": _eu(mv, 2),
        "Accruals in Base Currency":    "",
        "Currency":                     "EUR",
        "Exposure (base)":              _eu(exposure, 2),
        "Product Code":                 "9",
        "Price Include":                "",
        "PriceFactor":                  "10",
    }


def _gen_future_row(portfolio: str, report_date: str) -> dict:
    idx_code = f"FTF{random.choice(['DAX','ESX','ES'])}"
    yymm     = random.choice(["0626", "0926", "1226"])
    isin     = f"{idx_code}/SYN{yymm}_SYN_EUR"
    qty      = random.randint(1, 50)
    price    = random.uniform(4_000, 25_000)
    notional = qty * price * 1.0   # contracts at 1x multiplier (simplified)
    return {
        "Portfolio Code":               portfolio,
        "Date":                         report_date,
        "Security Name":                _synth_future_name(),
        "ISIN":                         isin,
        "Quantity":                     str(qty),
        "Clean price (local)":          _eu(price, 0),
        "Exchange rate":                "1",
        "Market Value in Base Currency": "0",
        "Accruals in Base Currency":    "",
        "Currency":                     "EUR",
        "Exposure (base)":              _eu(notional, 2),
        "Product Code":                 "8",
        "Price Include":                "",
        "PriceFactor":                  "25",
    }


def _gen_forward_row(portfolio: str, report_date: str) -> dict:
    """FX forward — hedging instrument, near-zero mark-to-market MV."""
    ccy_pair = random.choice(["USD", "GBP", "CHF"])
    yymm     = random.choice(["0626", "0926"])
    isin     = f"FWD-{ccy_pair}EUR/SYN{yymm}"
    notional = random.choice([1_000_000, 2_000_000, 5_000_000, 10_000_000])
    # Mark-to-market value of a forward is close to zero at inception
    mtm_eur  = notional * random.uniform(-0.005, 0.005)
    exposure = notional * _FX_BASE.get(ccy_pair, 1.0) * random.uniform(0.97, 1.03)
    return {
        "Portfolio Code":               portfolio,
        "Date":                         report_date,
        "Security Name":                f"FX FWD {ccy_pair}/EUR SYN {yymm}",
        "ISIN":                         isin,
        "Quantity":                     str(notional),
        "Clean price (local)":          _eu(1.0, 4),
        "Exchange rate":                "1",
        "Market Value in Base Currency": _eu(mtm_eur, 2),
        "Accruals in Base Currency":    "",
        "Currency":                     ccy_pair,
        "Exposure (base)":              _eu(exposure, 2),
        "Product Code":                 "7",   # OTC derivative
        "Price Include":                "",
        "PriceFactor":                  "1",
    }


def _gen_leveraged_equity_row(portfolio: str, report_date: str) -> dict:
    """Equity position bought on margin — Exposure (base) = MV × leverage_ratio.

    The market value reflects the current mark-to-market of the shares held;
    Exposure (base) reflects the full economic notional controlled by the fund
    including the borrowed portion (CDR 231/2013 Art.7 Gross Method).
    """
    row = _gen_equity_row(portfolio, report_date)
    # Parse European decimal string back to float (remove thousands sep, swap comma)
    mv_str = row["Market Value in Base Currency"]
    mv_eur = float(mv_str.replace(".", "").replace(",", "."))
    leverage_ratio = random.uniform(1.5, 3.0)
    exposure = mv_eur * leverage_ratio
    row["Exposure (base)"] = _eu(exposure, 2)
    return row


def _gen_trs_row(portfolio: str, report_date: str) -> dict:
    """Total Return Swap — MV ≈ 0 (mark-to-market), Exposure (base) = reference notional.

    A TRS passes the total return of a reference asset to the fund in exchange
    for a funding rate. The mark-to-market value is close to zero at inception
    and fluctuates as the reference asset moves; the full notional is the
    economic exposure that must be counted under AIFMD II Gross Method.
    """
    yymm     = random.choice(["0626", "0926", "1226"])
    isin     = f"TRS-SYN{yymm}"
    notional = random.choice([2_000_000, 5_000_000, 10_000_000, 20_000_000])
    # Small but non-zero mark-to-market so the position passes the MV > 1 filter
    mtm_eur = max(abs(notional * random.uniform(-0.003, 0.003)), 1_000.0)
    if random.random() < 0.5:
        mtm_eur = -mtm_eur   # TRS can have negative MTM (funding cost > accrued return)
    return {
        "Portfolio Code":               portfolio,
        "Date":                         report_date,
        "Security Name":                f"TRS Synth Equity Index SYN {yymm}",
        "ISIN":                         isin,
        "Quantity":                     str(int(notional)),
        "Clean price (local)":          _eu(1.0, 4),
        "Exchange rate":                "1",
        "Market Value in Base Currency": _eu(mtm_eur, 2),
        "Accruals in Base Currency":    "",
        "Currency":                     "EUR",
        "Exposure (base)":              _eu(notional, 2),
        "Product Code":                 "6",   # OTC derivative
        "Price Include":                "",
        "PriceFactor":                  "1",
    }


def _gen_loan_row(portfolio: str, report_date: str, notional: float | None = None) -> dict:
    """Originated loan — illiquid private debt position.

    PriceFactor = 0.01 (price expressed as percentage of par).
    Exposure (base) is blank — loans are not derivatives.
    MV = notional * price_pct / 100.
    """
    yymm   = report_date.replace("-", "")[:6]
    suffix = random.randint(10000, 99999)
    isin   = f"LOAN-SYN{yymm}-{suffix}"
    if notional is None:
        notional = random.choice([500_000, 1_000_000, 2_000_000, 5_000_000])
    price_pct = random.uniform(95.0, 102.0)
    mv_eur    = notional * price_pct / 100.0
    borrower  = random.choice([
        "SYNTH BORROWER ALPHA SA", "SYNTH BORROWER BETA GmbH",
        "SYNTH BORROWER GAMMA Ltd", "SYNTH BORROWER DELTA NV",
        "SYNTH BORROWER EPSILON SpA",
    ])
    return {
        "Portfolio Code":               portfolio,
        "Date":                         report_date,
        "Security Name":                f"ORIGINATED LOAN {borrower} {yymm}",
        "ISIN":                         isin,
        "Quantity":                     str(int(notional)),
        "Clean price (local)":          _eu(price_pct, 4),
        "Exchange rate":                "1",
        "Market Value in Base Currency": _eu(mv_eur, 2),
        "Accruals in Base Currency":    "",
        "Currency":                     "EUR",
        "Exposure (base)":              "",
        "Product Code":                 "5",   # private debt / loan
        "Price Include":                "",
        "PriceFactor":                  "0,01",
    }


# ---------------------------------------------------------------------------
# Holdings file
# ---------------------------------------------------------------------------

HOLDINGS_COLUMNS = [
    "Portfolio Code", "Date", "Security Name", "ISIN", "Quantity",
    "Clean price (local)", "Exchange rate", "Market Value in Base Currency",
    "Accruals in Base Currency", "Currency", "Exposure (base)",
    "Product Code", "Price Include", "PriceFactor",
]


def _holdings_per_portfolio(n_positions: int, portfolio: str = "") -> list[str]:
    """
    Return a weighted asset-class sequence for n_positions positions.
    Uses per-portfolio mandate weights when the portfolio name is recognised,
    otherwise falls back to a generic multi-asset distribution.
    """
    if portfolio in PORTFOLIO_WEIGHTS:
        weights = PORTFOLIO_WEIGHTS[portfolio]
    else:
        weights = {
            "listed_equity":     0.35,
            "government_bond":   0.20,
            "ig_corporate_bond": 0.18,
            "hy_corporate_bond": 0.08,
            "etf":               0.08,
            "option":            0.06,
            "future":            0.03,
            "cash":              0.02,
        }
    classes = list(weights.keys())
    probs   = list(weights.values())
    return random.choices(classes, weights=probs, k=n_positions)


def generate_holdings(
    report_date: str,
    portfolios: list[str],
    output_path: Path,
    positions_per_portfolio: tuple[int, int] = (20, 80),
) -> dict[str, tuple[str, str]]:
    """Write a synthetic holdings CSV.

    Returns a dict mapping isin -> (portfolio_code, asset_class) for every
    row written. This is used by generate_market_data to produce market data
    rows keyed to the exact same ISINs (no random ISIN mismatch).
    """
    rows: list[dict] = []
    isin_map: dict[str, tuple[str, str]] = {}  # isin -> (portfolio, asset_class)

    def _add(row: dict, pcode: str, ac: str) -> None:
        rows.append(row)
        isin = row["ISIN"].strip()
        if isin:
            isin_map[isin] = (pcode, ac)

    def _eu_float_local(s: str) -> float:
        """Parse European-formatted number string back to float."""
        try:
            return float(str(s).replace(".", "").replace(",", "."))
        except (ValueError, AttributeError):
            return 0.0

    for p_idx, pcode in enumerate(portfolios):
        # Re-seed per portfolio so changes to one portfolio don't shift others.
        random.seed(42 + p_idx * 1000)
        n = random.randint(*positions_per_portfolio)

        # ── SYN-LOANFUND: two-pass to guarantee one borrower > 20% NAV ──────
        if pcode == "SYN-LOANFUND":
            _add(_gen_cash_row(pcode, report_date), pcode, "cash")
            # Pass 1: generate IG bonds + regular loans + cash
            bulk_classes = _holdings_per_portfolio(n - 1, portfolio=pcode)
            pass1_rows: list[dict] = []
            for ac in bulk_classes:
                if ac in ("government_bond", "ig_corporate_bond"):
                    r = _gen_bond_row(pcode, report_date, ac)
                    pass1_rows.append((r, ac))
                elif ac == "originated_loan":
                    r = _gen_loan_row(pcode, report_date)
                    pass1_rows.append((r, ac))
                else:
                    r = _gen_cash_row(pcode, report_date)
                    pass1_rows.append((r, "cash"))
            for r, ac in pass1_rows:
                _add(r, pcode, ac)
            # Estimate NAV from pass-1 rows
            nav_est = sum(
                _eu_float_local(r["Market Value in Base Currency"])
                for r, _ in pass1_rows
            )
            # Pass 2: add one large loan at ~30% of estimated NAV → ~23% of final NAV
            big_notional = max(nav_est * 0.30, 1_000_000.0)
            _add(_gen_loan_row(pcode, report_date, notional=big_notional), pcode, "originated_loan")
            continue

        # ── SYN-LEVERAGED: two-pass to guarantee gross leverage > 175% ──────
        if pcode == "SYN-LEVERAGED":
            _add(_gen_cash_row(pcode, report_date), pcode, "cash")
            # Pass 1: base equity + bond positions
            base_classes = [ac for ac in _holdings_per_portfolio(n - 1, portfolio=pcode)
                            if ac not in ("trs", "future")]
            base_rows: list[tuple[dict, str]] = []
            for ac in base_classes:
                if ac == "listed_equity":
                    r = _gen_equity_row(pcode, report_date, max_mv_eur=EQUITY_MAX_MV.get(pcode))
                    base_rows.append((r, ac))
                elif ac in ("government_bond", "ig_corporate_bond"):
                    r = _gen_bond_row(pcode, report_date, ac)
                    base_rows.append((r, ac))
                else:
                    r = _gen_cash_row(pcode, report_date)
                    base_rows.append((r, "cash"))
            for r, ac in base_rows:
                _add(r, pcode, ac)
            # Compute base NAV from pass-1 rows
            base_nav = sum(
                abs(_eu_float_local(r["Market Value in Base Currency"]))
                for r, _ in base_rows
            )
            if base_nav < 1_000_000:
                base_nav = 10_000_000.0
            # Pass 2: add TRS with total notionals = 1.2× base NAV (→ gross ≈ 2.2×)
            trs_total = base_nav * 1.2
            n_trs = random.randint(3, 5)
            shares = sorted([random.random() for _ in range(n_trs - 1)] + [0.0, 1.0])
            for i in range(n_trs):
                notional_i = trs_total * (shares[i + 1] - shares[i])
                if notional_i < 100_000:
                    continue
                yymm   = random.choice(["0626", "0926", "1226"])
                isin   = f"TRS-SYN{yymm}-{random.randint(1000, 9999)}"
                mtm    = max(abs(notional_i * random.uniform(-0.003, 0.003)), 1_000.0)
                if random.random() < 0.5:
                    mtm = -mtm
                r = {
                    "Portfolio Code":               pcode,
                    "Date":                         report_date,
                    "Security Name":                f"TRS Synth Equity Index SYN {yymm}",
                    "ISIN":                         isin,
                    "Quantity":                     str(int(notional_i)),
                    "Clean price (local)":          _eu(1.0, 4),
                    "Exchange rate":                "1",
                    "Market Value in Base Currency": _eu(mtm, 2),
                    "Accruals in Base Currency":    "",
                    "Currency":                     "EUR",
                    "Exposure (base)":              _eu(notional_i, 2),
                    "Product Code":                 "6",
                    "Price Include":                "",
                    "PriceFactor":                  "1",
                }
                _add(r, pcode, "trs")
            # Add 2–3 futures (MV ≈ 0, don't inflate NAV)
            for _ in range(random.randint(2, 3)):
                _add(_gen_future_row(pcode, report_date), pcode, "future")
            continue

        # ── Standard portfolios ───────────────────────────────────────────────
        # Always include at least one cash row.
        # For SYN-ILLIQ, force a tiny cash balance so T+0 stays below 2% of NAV.
        if pcode == "SYN-ILLIQ":
            mv_eur = random.uniform(200_000, 800_000)
            cash_row = {
                "Portfolio Code":               pcode,
                "Date":                         report_date,
                "Security Name":                "Cash EUR",
                "ISIN":                         "CASH-EUR",
                "Quantity":                     _eu(mv_eur, 2),
                "Clean price (local)":          "1",
                "Exchange rate":                "1",
                "Market Value in Base Currency": _eu(mv_eur, 2),
                "Accruals in Base Currency":    "",
                "Currency":                     "EUR",
                "Exposure (base)":              "",
                "Product Code":                 "",
                "Price Include":                "",
                "PriceFactor":                  "1",
            }
        else:
            cash_row = _gen_cash_row(pcode, report_date)
        _add(cash_row, pcode, "cash")
        _geo     = PORTFOLIO_GEO_OVERRIDES.get(pcode)
        _eq_cap  = EQUITY_MAX_MV.get(pcode)
        for ac in _holdings_per_portfolio(n - 1, portfolio=pcode):
            if ac == "listed_equity":
                _fc = None
                if _geo and random.random() < _geo["probability"]:
                    _fc = _geo["country"]
                _add(_gen_equity_row(pcode, report_date, forced_country=_fc, max_mv_eur=_eq_cap), pcode, ac)
            elif ac in ("government_bond", "ig_corporate_bond", "hy_corporate_bond"):
                _fc = None
                if _geo and random.random() < _geo["probability"]:
                    _fc = _geo["country"]
                _add(_gen_bond_row(pcode, report_date, ac, forced_country=_fc), pcode, ac)
            elif ac == "etf":
                _add(_gen_etf_row(pcode, report_date), pcode, ac)
            elif ac == "option":
                _add(_gen_option_row(pcode, report_date), pcode, ac)
            elif ac == "future":
                _add(_gen_future_row(pcode, report_date), pcode, ac)
            elif ac == "forward":
                _add(_gen_forward_row(pcode, report_date), pcode, ac)
            elif ac == "leveraged_equity":
                _add(_gen_leveraged_equity_row(pcode, report_date), pcode, ac)
            elif ac == "trs":
                _add(_gen_trs_row(pcode, report_date), pcode, ac)
            elif ac == "originated_loan":
                _add(_gen_loan_row(pcode, report_date), pcode, ac)
            else:
                cash_row2 = _gen_cash_row(pcode, report_date)
                _add(cash_row2, pcode, "cash")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=HOLDINGS_COLUMNS, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  HOLDINGS -> {output_path}  ({len(rows)} rows)")
    return isin_map


# ---------------------------------------------------------------------------
# NAV file
# ---------------------------------------------------------------------------

NAV_COLUMNS = [
    "PortfolioCode", "Date", "TotalAssets",
    "Subscriptions", "Redemptions", "NetCashFlows",
]


def _last_n_working_days(end: date, n: int) -> list[date]:
    """Return n working days (Mon–Fri) ending on end (inclusive)."""
    days: list[date] = []
    cur = end
    while len(days) < n:
        if cur.weekday() < 5:
            days.append(cur)
        cur -= timedelta(days=1)
    return list(reversed(days))


def _random_walk_backward(final: float, steps: int, daily_vol: float = 0.005) -> list[float]:
    """Produce `steps` values ending at `final` via a geometric random walk."""
    vals = [final]
    for _ in range(steps - 1):
        shock = random.gauss(0, daily_vol)
        vals.append(vals[-1] / (1 + shock))
    return list(reversed(vals))


def generate_nav(
    report_date: str,
    portfolios: list[str],
    output_path: Path,
    nav_map: Optional[dict[str, float]] = None,
) -> dict[str, float]:
    """Write a synthetic NAV CSV (20 working days per portfolio) and return {portfolio: total_assets}.

    If nav_map is provided (computed from the MVHOL position sums) those values
    are used as the latest-date NAV so that NAV file and MVHOL always agree exactly.
    """
    if nav_map is None:
        nav_map = {pcode: random.uniform(20_000_000, 1_200_000_000) for pcode in portfolios}

    dd, mm, yyyy = report_date.split(".")
    end_date = date(int(yyyy), int(mm), int(dd))
    trading_days = _last_n_working_days(end_date, 20)

    rows: list[dict] = []
    for pcode in portfolios:
        latest_nav = nav_map.get(pcode, random.uniform(20_000_000, 1_200_000_000))
        navs = _random_walk_backward(latest_nav, steps=20)
        for d, nav in zip(trading_days, navs):
            subs  = round(random.uniform(0, nav * 0.002), 2)
            redms = round(random.uniform(0, nav * 0.003), 2)
            rows.append({
                "PortfolioCode": pcode,
                "Date":          d.strftime("%d.%m.%Y"),
                "TotalAssets":   _eu(nav, 2),
                "Subscriptions": _eu(subs, 2),
                "Redemptions":   _eu(redms, 2),
                "NetCashFlows":  _eu(subs - redms, 2),
            })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=NAV_COLUMNS, delimiter=";",
                                quoting=csv.QUOTE_NONE, escapechar="\\")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  NAV    -> {output_path}  ({len(rows)} rows, 20 days × {len(portfolios)} portfolios)")
    return nav_map


# ---------------------------------------------------------------------------
# Market data file
# ---------------------------------------------------------------------------

MARKET_DATA_COLUMNS = [
    "portfolio", "isin", "ric", "asset_class_hint", "currency",
    "bid", "ask", "bid_ask_spread_bps", "adv_30d_eur",
    "beta", "modified_duration", "convexity", "ytm",
    "open_interest", "option_volume", "credit_spread_bps",
    "rating", "amount_outstanding", "fx_rate_to_eur",
    "fetch_date", "fetch_errors",
]

MARKET_ERRORS_COLUMNS = [
    "portfolio", "isin", "ric", "asset_class_hint", "currency", "fetch_errors",
]

_ERROR_CODES = ["adv_missing", "spread_missing", "no_data", "stale_price"]


def _mkt_equity(portfolio: str, isin: str, fetch_date: str) -> dict:
    country = isin[:2]
    ccy     = "EUR" if country not in ("GB", "US", "CH", "SE", "DK") else (
               "GBP" if country == "GB" else
               "USD" if country == "US" else
               "CHF" if country == "CH" else
               "SEK" if country == "SE" else "DKK")
    fx      = _FX_BASE.get(ccy, 1.0) * random.uniform(0.97, 1.03)
    mid     = random.uniform(5.0, 500.0)
    # Equities: tightest spreads (0.5–5 bps), highest ADV
    # Floor at €200M so that SYN-EQUITY positions (capped at €8M MV) always
    # satisfy days_to_liq = ceil(8M / (200M × 0.20)) = ceil(0.2) = 1 → T+1.
    spread_bps = random.uniform(0.5, 5.0)
    half_spread_abs = mid * spread_bps / 2 / 10_000
    adv     = random.uniform(200_000_000, 2_000_000_000)   # €200M–€2B
    beta    = random.uniform(0.4, 1.8)
    ric     = _ric_equity(isin)
    return {
        "portfolio":            portfolio,
        "isin":                 isin,
        "ric":                  ric,
        "asset_class_hint":     "listed_equity",
        "currency":             ccy,
        "bid":                  f"{mid - half_spread_abs:.4f}",
        "ask":                  f"{mid + half_spread_abs:.4f}",
        "bid_ask_spread_bps":   f"{spread_bps:.2f}",
        "adv_30d_eur":          f"{adv:.0f}",
        "beta":                 f"{beta:.15f}",
        "modified_duration":    "",
        "convexity":            "",
        "ytm":                  "",
        "open_interest":        "",
        "option_volume":        f"{random.randint(0, 10_000_000)}",
        "credit_spread_bps":    "",
        "rating":               "",
        "amount_outstanding":   "",
        "fx_rate_to_eur":       f"{fx:.6f}" if ccy != "EUR" else "1.0",
        "fetch_date":           fetch_date,
        "fetch_errors":         "",
    }


def _mkt_bond(portfolio: str, isin: str, asset_class: str, fetch_date: str) -> dict:
    mid     = random.uniform(85.0, 105.0)
    hy      = asset_class == "hy_corporate_bond"
    ig      = asset_class == "ig_corporate_bond"
    gov     = asset_class == "government_bond"
    # Government bonds: tightest spreads, highest ADV for fixed income
    # IG corporate: moderate spreads
    # HY corporate: widest spreads, lowest ADV — least liquid
    if gov:
        spread_bps = random.uniform(1.0, 8.0)
        adv        = random.uniform(5_000_000, 80_000_000)
    elif ig:
        spread_bps = random.uniform(10.0, 40.0)
        adv        = random.uniform(500_000, 20_000_000)
    else:  # HY
        spread_bps = random.uniform(50.0, 200.0)
        adv        = random.uniform(100_000, 5_000_000)
    half_s  = mid * spread_bps / 2 / 10_000
    dur     = random.uniform(0.5, 15.0)
    conv    = round(dur ** 2 * random.uniform(0.8, 1.2) / 100, 4)
    ytm     = random.uniform(0.5, 8.0)
    cr_sprd = random.uniform(150, 600) if hy else (random.uniform(30, 150) if ig else random.uniform(5, 30))
    amt_out = random.uniform(100_000_000, 5_000_000_000)
    return {
        "portfolio":            portfolio,
        "isin":                 isin,
        "ric":                  _ric_bond(isin),
        "asset_class_hint":     asset_class,
        "currency":             "EUR",
        "bid":                  f"{mid - half_s:.3f}",
        "ask":                  f"{mid + half_s:.3f}",
        "bid_ask_spread_bps":   f"{spread_bps:.2f}",
        "adv_30d_eur":          f"{adv:.0f}",
        "beta":                 "",
        "modified_duration":    f"{dur:.4f}",
        "convexity":            f"{conv:.4f}",
        "ytm":                  f"{ytm:.4f}",
        "open_interest":        "",
        "option_volume":        "",
        "credit_spread_bps":    f"{cr_sprd:.2f}",
        "rating":               _rating(),
        "amount_outstanding":   f"{amt_out:.0f}",
        "fx_rate_to_eur":       "1.0",
        "fetch_date":           fetch_date,
        "fetch_errors":         "",
    }


def _mkt_etf(portfolio: str, isin: str, fetch_date: str) -> dict:
    ccy     = random.choice(["EUR", "USD"])
    fx      = _FX_BASE[ccy] * random.uniform(0.97, 1.03)
    mid     = random.uniform(20.0, 200.0)
    # ETFs: wider spreads than equities, lower ADV — less liquid than individual stocks
    spread_bps = random.uniform(8.0, 30.0)
    half_s  = mid * spread_bps / 2 / 10_000
    adv     = random.uniform(1_000_000, 30_000_000)   # €1M–€30M (below equities)
    vol     = random.randint(10_000, 5_000_000)
    return {
        "portfolio":            portfolio,
        "isin":                 isin,
        "ric":                  _ric_equity(isin),
        "asset_class_hint":     "etf",
        "currency":             ccy,
        "bid":                  f"{mid - half_s:.2f}",
        "ask":                  f"{mid + half_s:.2f}",
        "bid_ask_spread_bps":   f"{spread_bps:.2f}",
        "adv_30d_eur":          f"{adv:.0f}",
        "beta":                 "",
        "modified_duration":    "",
        "convexity":            "",
        "ytm":                  "",
        "open_interest":        "",
        "option_volume":        f"{vol}",
        "credit_spread_bps":    "",
        "rating":               "",
        "amount_outstanding":   "",
        "fx_rate_to_eur":       f"{fx:.6f}" if ccy != "EUR" else "1.0",
        "fetch_date":           fetch_date,
        "fetch_errors":         "",
    }


def _mkt_option(portfolio: str, isin: str, fetch_date: str) -> dict:
    return {
        "portfolio":            portfolio,
        "isin":                 isin,
        "ric":                  "",
        "asset_class_hint":     "option",
        "currency":             "EUR",
        "bid":                  "",
        "ask":                  "",
        "bid_ask_spread_bps":   "",
        "adv_30d_eur":          "",
        "beta":                 "",
        "modified_duration":    "",
        "convexity":            "",
        "ytm":                  "",
        "open_interest":        "",
        "option_volume":        "",
        "credit_spread_bps":    "",
        "rating":               "",
        "amount_outstanding":   "",
        "fx_rate_to_eur":       "1.0",
        "fetch_date":           fetch_date,
        "fetch_errors":         "",
    }


def _mkt_cash(portfolio: str, ccy: str, fetch_date: str) -> dict:
    fx = _FX_BASE.get(ccy, 1.0) * random.uniform(0.97, 1.03)
    return {
        "portfolio":            portfolio,
        "isin":                 f"CASH-{ccy}",
        "ric":                  "",
        "asset_class_hint":     "cash",
        "currency":             ccy,
        "bid":                  "",
        "ask":                  "",
        "bid_ask_spread_bps":   "",
        "adv_30d_eur":          "",
        "beta":                 "",
        "modified_duration":    "",
        "convexity":            "",
        "ytm":                  "",
        "open_interest":        "",
        "option_volume":        "",
        "credit_spread_bps":    "",
        "rating":               "",
        "amount_outstanding":   "",
        "fx_rate_to_eur":       "1.0" if ccy == "EUR" else f"{fx:.6f}",
        "fetch_date":           fetch_date,
        "fetch_errors":         "",
    }


def _mkt_loan(portfolio: str, isin: str, fetch_date: str) -> dict:
    """Market data row for an originated loan.

    No exchange ADV — loans are illiquid private instruments.
    asset_class_hint forces csv_loader to classify as 'originated_loan'
    so the leverage engine correctly counts it in loan_pct_nav.
    """
    return {
        "portfolio":            portfolio,
        "isin":                 isin,
        "ric":                  "",
        "asset_class_hint":     "originated_loan",
        "currency":             "EUR",
        "bid":                  "",
        "ask":                  "",
        "bid_ask_spread_bps":   "",
        "adv_30d_eur":          "",
        "beta":                 "",
        "modified_duration":    str(round(random.uniform(1.0, 5.0), 2)),
        "convexity":            "",
        "ytm":                  str(round(random.uniform(0.04, 0.12), 4)),
        "open_interest":        "",
        "option_volume":        "",
        "credit_spread_bps":    str(round(random.uniform(200, 800))),
        "rating":               random.choice(["B+", "B", "B-", "CCC+"]),
        "amount_outstanding":   "",
        "fx_rate_to_eur":       "1.0",
        "fetch_date":           fetch_date,
        "fetch_errors":         "",
    }


def generate_market_data(
    report_date_iso: str,
    portfolios: list[str],
    all_output: Path,
    errors_output: Path,
    isin_map: dict[str, tuple[str, str]] | None = None,
    error_rate: float = 0.015,
) -> None:
    """Write synthetic market_data_ALL.csv and market_data_ERRORS.csv.

    isin_map: dict of isin -> (portfolio_code, asset_class) returned by
    generate_mvhol.  When provided every MVHOL ISIN gets a market data row
    so that ADV enrichment matches and liquidity classification is correct.
    """
    all_rows:   list[dict] = []
    error_rows: list[dict] = []

    # Asset classes that need a full market data row (others get cash/skip)
    _mkt_generators = {
        "listed_equity":     lambda pcode, isin: _mkt_equity(pcode, isin, report_date_iso),
        "government_bond":   lambda pcode, isin: _mkt_bond(pcode, isin, "government_bond", report_date_iso),
        "ig_corporate_bond": lambda pcode, isin: _mkt_bond(pcode, isin, "ig_corporate_bond", report_date_iso),
        "hy_corporate_bond": lambda pcode, isin: _mkt_bond(pcode, isin, "hy_corporate_bond", report_date_iso),
        "etf":               lambda pcode, isin: _mkt_etf(pcode, isin, report_date_iso),
        "option":            lambda pcode, isin: _mkt_option(pcode, isin, report_date_iso),
        "originated_loan":   lambda pcode, isin: _mkt_loan(pcode, isin, report_date_iso),
    }

    if isin_map:
        # Generate a market data row for every ISIN that appears in the holdings file.
        # Cash ISINs (CASH-EUR etc.) get cash rows; futures/forwards get no ADV row
        # (they're exchange-traded or OTC with zero MV — the profiler handles them).
        for isin, (pcode, ac) in isin_map.items():
            if ac == "cash":
                ccy = isin.split("-", 1)[1] if isin.startswith("CASH-") else "EUR"
                all_rows.append(_mkt_cash(pcode, ccy, report_date_iso))
            elif ac in _mkt_generators:
                row = _mkt_generators[ac](pcode, isin)
                if random.random() < error_rate:
                    error_rows.append({
                        "portfolio":        row["portfolio"],
                        "isin":             row["isin"],
                        "ric":              row["ric"],
                        "asset_class_hint": row["asset_class_hint"],
                        "currency":         row["currency"],
                        "fetch_errors":     random.choice(_ERROR_CODES),
                    })
                else:
                    all_rows.append(row)
            # future / forward: no market data row needed (MV=0 or near-zero)
    else:
        # Fallback: generate random ISINs (legacy behaviour, not MVHOL-aligned)
        for pcode in portfolios:
            for ccy in random.sample(["EUR", "USD", "GBP"], k=random.randint(1, 3)):
                all_rows.append(_mkt_cash(pcode, ccy, report_date_iso))
        for _ in range(300):
            pcode = random.choice(portfolios)
            ac    = random.choice(list(_mkt_generators.keys()))
            if ac == "listed_equity":
                isin = _isin(random.choice(EQUITY_COUNTRIES))
            elif ac == "etf":
                isin = _isin(random.choice(ETF_COUNTRIES))
            elif ac == "option":
                idx_code = f"OPO{random.choice(['ESX','SPX'])}"
                isin     = f"{idx_code}/SYN{random.choice([3500,4000])}0626_SYN_EUR"
            else:
                isin = _isin(random.choice(BOND_COUNTRIES))
            row = _mkt_generators[ac](pcode, isin)
            if random.random() < error_rate:
                error_rows.append({k: row[k] for k in MARKET_ERRORS_COLUMNS})
            else:
                all_rows.append(row)

    all_output.parent.mkdir(parents=True, exist_ok=True)
    with all_output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MARKET_DATA_COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"  MktAll -> {all_output}  ({len(all_rows)} rows)")

    errors_output.parent.mkdir(parents=True, exist_ok=True)
    with errors_output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MARKET_ERRORS_COLUMNS)
        writer.writeheader()
        writer.writerows(error_rows)
    print(f"  MktErr -> {errors_output}  ({len(error_rows)} rows)")


# ---------------------------------------------------------------------------
# Zero-coupon yields xlsx
# ---------------------------------------------------------------------------

# Tenors present in the real file header (strip RIC and field suffix,
# keep just the tenor for generation purposes)
_ZCY_TENORS = [1, 2, 3, 5, 6, 7, 8, 9, 10, 12, 15, 17, 20, 25, 27, 30]

# Column headers exactly as in the real file
_ZCY_COLUMNS = [
    "Date",
    "USZCY10=FBNY (TRDPRC_1)",
    "USZCY1=FBNY (TRDPRC_1)",
    "USZCY2=FBNY (TRDPRC_1)",
    "USZCY3=FBNY (TRDPRC_1)",
    "USZCY5=FBNY (TRDPRC_1)",
    "USZCY6=FBNY (TRDPRC_1)",
    "USZCY7=FBNY (TRDPRC_1)",
    "USZCY8=FBNY (TRDPRC_1)",
    "USZCY9=FBNY (TRDPRC_1)",
    "USZCY12=FBNY (TRDPRC_1)",
    "USZCY15=FBNY (TRDPRC_1)",
    "USZCY17=FBNY (TRDPRC_1)",
    "USZCY20=FBNY (TRDPRC_1)",
    "USZCY25=FBNY (TRDPRC_1)",
    "USZCY27=FBNY (TRDPRC_1)",
    "USZCY30=FBNY (TRDPRC_1)",
]

# Tenor order matching the column order above
_ZCY_TENOR_ORDER = [10, 1, 2, 3, 5, 6, 7, 8, 9, 12, 15, 17, 20, 25, 27, 30]


def _generate_yield_curve(short_rate: float, long_rate: float) -> list[float]:
    """
    Generate a smooth, arbitrage-free synthetic yield curve using Nelson-Siegel
    parameterisation. All parameters are chosen at random — this produces
    plausible curves (normal, flat, inverted) without reference to any real data.
    """
    beta0 = long_rate                         # long-run level
    beta1 = short_rate - long_rate            # slope
    beta2 = random.uniform(-1.0, 1.5)        # hump
    tau   = random.uniform(1.5, 5.0)         # decay

    rates = []
    for t in _ZCY_TENOR_ORDER:
        lambda_t = (1 - (1 / (t / tau)) * (1 - (1 / (t / tau)))) if t > 0 else 1.0
        # Nelson-Siegel: y(t) = β0 + β1*(1-e^(-t/τ))/(t/τ) + β2*((1-e^(-t/τ))/(t/τ) - e^(-t/τ))
        x   = t / tau
        f1  = (1 - (1 / (1 + x) ** x)) if x > 0 else 1.0   # approximate factor
        # Simpler closed-form:
        exp_x = 2.71828 ** (-x)
        f1  = (1 - exp_x) / x if x > 0 else 1.0
        f2  = f1 - exp_x
        y   = beta0 + beta1 * f1 + beta2 * f2
        y   = max(0.01, round(y, 4))          # rates must be positive
        rates.append(y)
    return rates


def generate_zero_coupon_yields(
    output_path: Path,
    start_date: date = date(2019, 10, 25),
    end_date:   date = date(2025, 10, 17),
) -> None:
    """Write a synthetic zero_coupon_yields.xlsx with the same structure."""
    try:
        import openpyxl
    except ImportError:
        print("  WARNING: openpyxl not installed — skipping zero_coupon_yields.xlsx")
        return

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Table Data"

    # Row 1: column headers
    ws.append(_ZCY_COLUMNS)
    # Row 2: 'Close' labels (matches real file structure)
    ws.append([None] + ["Close"] * len(_ZCY_TENOR_ORDER))

    # Walk every weekday in the date range and generate a synthetic curve
    # using a random-walk on the short and long rates
    current = start_date
    short_rate = random.uniform(0.5, 2.5)   # starting short-end rate
    long_rate  = random.uniform(1.5, 4.5)   # starting long-end rate

    while current <= end_date:
        if current.weekday() < 5:   # Mon–Fri only
            rates = _generate_yield_curve(short_rate, long_rate)
            ws.append([current] + rates)
            # Random walk: small daily moves
            short_rate = max(0.01, short_rate + random.gauss(0, 0.03))
            long_rate  = max(0.10, long_rate  + random.gauss(0, 0.02))
        current += timedelta(days=1)

    # Blank Sheet1 to match real file structure
    wb.create_sheet("Sheet1")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    print(f"  ZCY    -> {output_path}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def generate_all(
    output_dir:  str | Path = None,
    report_date: str = None,
    seed:        int = 42,
    n_portfolios: int = 7,
    n_market_securities: int = 300,  # kept for CLI compat; no longer used internally
) -> Path:
    """
    Generate a complete set of synthetic input files.

    Parameters
    ----------
    output_dir:
        Where to write files. Defaults to ./synthetic/ next to this script.
    report_date:
        Reporting date as 'DD.MM.YYYY'. Defaults to today.
    seed:
        Random seed for reproducibility.
    n_portfolios:
        How many synthetic portfolios to generate (max 12).
    n_market_securities:
        How many security rows in the market data file.

    Returns
    -------
    Path to the output directory.
    """
    _seed(seed)

    if output_dir is None:
        output_dir = Path(__file__).parent / "sample"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if report_date is None:
        report_date = datetime.today().strftime("%d.%m.%Y")

    # Validate date format
    datetime.strptime(report_date, "%d.%m.%Y")

    dd, mm, yyyy = report_date.split(".")
    ts           = datetime.today().strftime("%Y%m%d%H%M%S")
    iso_date     = f"{yyyy}-{mm}-{dd}"

    portfolios = PORTFOLIOS[:max(1, min(n_portfolios, len(PORTFOLIOS)))]  # max 5

    print(f"\nGenerating synthetic data -> {output_dir}")
    print(f"  Report date : {report_date}")
    print(f"  Portfolios  : {portfolios}")
    print(f"  Seed        : {seed}\n")

    holdings_path = output_dir / f"HOLDINGS_{ts}.csv"
    nav_path      = output_dir / f"NAV_{ts}.csv"

    isin_map = generate_holdings(
        report_date=report_date,
        portfolios=portfolios,
        output_path=holdings_path,
    )

    # Compute NAV to match what csv_loader.load_portfolio_from_csv produces:
    #   - rows where |market_value| < 1.0 are skipped (futures with MV=0 are excluded)
    #   - aggregate duplicate ISINs (sum their market values)
    #   - NAV = sum of those market values (signed, as the loader does)
    # We replicate the loader's _eu_float inline here to stay independent.
    def _eu_float_local(s: str) -> float:
        s = s.strip()
        if not s:
            return 0.0
        s = s.replace(".", "").replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return 0.0

    nav_map: dict[str, float] = {}
    seen_isins: dict[str, dict[str, float]] = {}  # portfolio -> {isin: mv}
    with holdings_path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            pcode   = row["Portfolio Code"]
            isin    = row["ISIN"].strip()
            mv      = _eu_float_local(row["Market Value in Base Currency"])
            if abs(mv) < 1.0:
                continue
            if pcode not in seen_isins:
                seen_isins[pcode] = {}
            seen_isins[pcode][isin] = seen_isins[pcode].get(isin, 0.0) + mv

    for pcode, isin_mvs in seen_isins.items():
        nav_map[pcode] = sum(isin_mvs.values())  # signed, matches loader's position_sum

    generate_nav(
        report_date=report_date,
        portfolios=portfolios,
        output_path=nav_path,
        nav_map=nav_map,
    )

    generate_market_data(
        report_date_iso=iso_date,
        portfolios=portfolios,
        all_output=output_dir / "market_data_ALL.csv",
        errors_output=output_dir / "market_data_ERRORS.csv",
        isin_map=isin_map,
    )

    generate_zero_coupon_yields(
        output_path=output_dir / "zero_coupon_yields.xlsx",
    )

    print(f"\nDone. All files written to: {output_dir.resolve()}")
    return output_dir


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate synthetic input files for the liquidity risk tool. "
                    "No real data is read or referenced — all values are synthetic."
    )
    parser.add_argument(
        "--output-dir", "-o", default=None,
        help="Output directory (default: same directory as this script)"
    )
    parser.add_argument(
        "--date", "-d", default=None,
        help="Report date DD.MM.YYYY (default: today)"
    )
    parser.add_argument(
        "--seed", "-s", type=int, default=42,
        help="Random seed for reproducibility (default: 42)"
    )
    parser.add_argument(
        "--portfolios", "-p", type=int, default=7,
        help="Number of synthetic portfolios 1-7 (default: 7)"
    )
    parser.add_argument(
        "--securities", "-n", type=int, default=300,
        help="Number of securities in market data file (default: 300)"
    )
    args = parser.parse_args()

    generate_all(
        output_dir=args.output_dir,
        report_date=args.date,
        seed=args.seed,
        n_portfolios=args.portfolios,
        n_market_securities=args.securities,
    )
