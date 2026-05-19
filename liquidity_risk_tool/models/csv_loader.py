"""
CSV loader for daily holdings and NAV files.

Reads semicolon-delimited, European-decimal-format files produced by the
portfolio management system and returns a Portfolio compatible with the
full liquidity risk pipeline.

File naming convention:
    HOLDINGS_<YYYYMMDDHHMMSS>.csv   — holdings
    NAV_<YYYYMMDDHHMMSS>.csv        — total assets per portfolio
"""
from __future__ import annotations

import math
import re
import warnings
from pathlib import Path
from typing import Optional

import pandas as pd

from .position import Position, ShareClass, Portfolio
from ..config.settings import DEFAULT_DURATION_YEARS, MAX_DURATION_YEARS
from ..engines.validators import ValidationError


# ---------------------------------------------------------------------------
# European decimal parsing
# ---------------------------------------------------------------------------

def _eu_float(value: str) -> float:
    """'1.159.375,000000' → 1159375.0  |  '(21.016.625,00)' → -21016625.0"""
    if not isinstance(value, str):
        return float(value) if value else 0.0
    s = value.strip()
    if not s:
        return 0.0
    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1]
    s = s.replace(".", "").replace(",", ".")
    try:
        result = float(s)
        return -result if negative else result
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# Bond duration inference from security name
# ---------------------------------------------------------------------------

# Matches patterns like: v2530, 202530, 20252030, 2029, 2031, v 2030, etc.
_MATURITY_PATTERNS = [
    re.compile(r"v\s?(\d{2})(\d{2})\b"),        # v2530 → 2025, 2030 (take last 4 as YYYY)
    re.compile(r"\b(20\d{2})(20\d{2})\b"),       # 20252030
    re.compile(r"\b(20\d{2})(\d{2})\b"),          # 202530 → 2025, 30 → 2030
    re.compile(r"\b(20\d{2})\b"),                 # standalone year
]


def _parse_maturity_year(name: str) -> Optional[int]:
    """Extract the latest maturity year from a bond security name."""
    years: list[int] = []
    for pat in _MATURITY_PATTERNS:
        for m in pat.finditer(name):
            for g in m.groups():
                if g:
                    y = int(g)
                    if y < 100:
                        y += 2000
                    if 2024 <= y <= 2060:
                        years.append(y)
    return max(years) if years else None


def _estimate_duration(name: str, reporting_year: int) -> float:
    """Years-to-maturity as a duration proxy, capped at reasonable bounds."""
    mat = _parse_maturity_year(name)
    if mat is None:
        return DEFAULT_DURATION_YEARS
    ytm = max(mat - reporting_year - 0.5, 0.25)
    # Modified duration ≈ ytm for rough purposes (ignores coupon)
    return round(min(ytm, MAX_DURATION_YEARS), 1)


# ---------------------------------------------------------------------------
# Asset class inference
# ---------------------------------------------------------------------------

_GOV_BOND_KEYWORDS = (
    "BUND", "OAT ", "BTP ", "GILT", "BONO", "OLO ",
    "REPUBLIC", "SOVEREIGN", "KONINKRIJKSNL",
    "NIEDERSACHS", "SACHSEN", "FREISTAAT", "BUNDESLAND",
    "INVESTITIONSBANK", "FÖRDERBANK", "FOERDERBANK",
    "LAND NORDRHEIN", "LAND BERLIN", "LAND HAMBURG", "LAND BREMEN",
    "DEUTSCHLAND", "BUNDESREPUBLIK",
    "EU BILL", "EUROPEAN UNION", "EU MTN",
    "FINLAND", "FINLANDE", "SUOMI",
    "AUSTRIA", "ÖSTERREICH",
    "NIEDERLANDE", "NEDERLAND",
    "POLAND REPUBLIC", "REPUBLIC OF POLAND", "POLEN REPUBLIK",
    "LANDESSCH", "LANDESSCHATZ",
)

_COVERED_BOND_KEYWORDS = (
    "PFANDBRIEF", "PFANDBR", "PFBR",
    "PANDBR", "PANDBRIEVEN",
    "COVERED", "OBLIGATION FONCIERE", "OBLFONCIERE",
    "FONCIERE", "HYPOTHEK",
    "COVERED BOND", "CEDULAS",
    "HYP ", "HYPO",
)

_HY_BOND_KEYWORDS = (
    "HIGH YIELD", "HY ", " HY", "JUNK",
    "ALTICE", "LOXAM", "SOFTBANK",
)

_FUTURES_CODES  = ("FTFDAX", "FTFESX", "FTFES", "FTF")
_OPTIONS_CODES  = ("OPOESX", "OPSPIO", "OPO", "OPS")

# ISIN country → equity beta heuristic
_COUNTRY_BETA: dict[str, float] = {
    "DE": 0.90, "AT": 0.85, "CH": 0.80, "LU": 0.85,
    "FR": 1.00, "BE": 0.90, "NL": 0.90,
    "ES": 1.20, "IT": 1.20, "PT": 1.10,
    "FI": 0.85, "SE": 0.95, "NO": 0.90, "DK": 0.85,
    "GB": 0.85, "IE": 0.90,
    "US": 0.95, "CA": 0.90, "JP": 0.85, "AU": 0.90,
}


def _infer_asset_class(
    isin: str,
    name: str,
    product_code: str,
    price_factor: float,
) -> str:
    isin_u = (isin or "").upper()
    name_u = (name or "").upper()
    pc_u   = (product_code or "").upper()

    # Cash
    if isin_u.startswith("CASH-") or isin_u in ("CASH-EUR", "CASH-USD", "CASH-GBP", "CASH-JPY"):
        return "cash"

    # Futures (ProductCode or ISIN contains futures identifier)
    if any(fc in pc_u for fc in _FUTURES_CODES) or any(fc in isin_u for fc in _FUTURES_CODES):
        return "future"

    # Options
    if any(oc in pc_u for oc in _OPTIONS_CODES) or any(oc in isin_u for oc in _OPTIONS_CODES):
        return "option"

    # Bonds: PriceFactor = 0.01
    if abs(price_factor - 0.01) < 1e-6:
        if any(kw in name_u for kw in _HY_BOND_KEYWORDS):
            return "hy_corporate_bond"
        if any(kw in name_u for kw in _COVERED_BOND_KEYWORDS):
            return "ig_corporate_bond"
        if any(kw in name_u for kw in _GOV_BOND_KEYWORDS):
            return "government_bond"
        return "ig_corporate_bond"

    # Fund units / ETFs: domiciled in IE or LU (UCITS)
    if isin_u[:2] in ("IE", "LU") and abs(price_factor - 1.0) < 1e-6:
        return "etf"

    # Listed equity (PriceFactor = 1, known country ISIN)
    if abs(price_factor - 1.0) < 1e-6:
        return "listed_equity"

    return "listed_equity"


def _equity_beta(isin: str) -> float:
    country = (isin or "")[:2].upper()
    return _COUNTRY_BETA.get(country, 1.0)


# ---------------------------------------------------------------------------
# Liquidity defaults by asset class
# ---------------------------------------------------------------------------

_ADV_DEFAULTS: dict[str, float] = {
    "cash":              1e12,
    "money_market":      50_000_000,
    "government_bond":   30_000_000,   # sovereign/SSA bonds — liquid but below equities
    "ig_corporate_bond": 5_000_000,
    "hy_corporate_bond": 1_000_000,    # materially less liquid than IG
    "listed_equity":     10_000_000,   # mid-cap equities — realistic default when ADV not provided
    "etf":               10_000_000,   # less liquid than individual equities
    "structured_credit": 500_000,
    "real_estate":       0,
    "private_equity":    0,
    "hedge_fund":        0,
    "future":            200_000_000,  # exchange-traded futures — highly liquid
    "option":            10_000_000,
}

_SPREAD_DEFAULTS: dict[str, float] = {
    "cash":              0,
    "money_market":      1,
    "government_bond":   4,    # tight but wider than equities
    "ig_corporate_bond": 20,
    "hy_corporate_bond": 100,  # materially wider to reflect illiquidity
    "listed_equity":     2,    # tightest — large-cap stocks
    "etf":               15,   # wider than equities; varies by underlying
    "structured_credit": 60,
    "real_estate":       200,
    "private_equity":    300,
    "hedge_fund":        150,
    "future":            3,    # exchange-traded, very tight
    "option":            25,
}


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------

def load_portfolio_from_csv(
    holdings_path: str | Path,
    nav_path: str | Path,
    portfolio_code: Optional[str] = None,
) -> Portfolio:
    """Load a Portfolio from daily holdings and NAV CSV files.

    Parameters
    ----------
    holdings_path:
        Path to the holdings CSV (semicolon-delimited, European decimals).
    nav_path:
        Path to the NAV CSV (semicolon-delimited, quoted fields).
    portfolio_code:
        Which portfolio to load (e.g. "AL-A", "AL-H3"). If None, uses the
        first portfolio code found in the file.
    """
    holdings_path = Path(holdings_path)
    nav_path      = Path(nav_path)

    # ── 1. NAV file ─────────────────────────────────────────────────────────
    try:
        nav_df = pd.read_csv(nav_path, sep=";", quotechar='"', dtype=str)
    except Exception as exc:
        raise ValidationError(f"Cannot read NAV file '{nav_path.name}': {exc}") from exc
    nav_df.columns = [c.strip().strip('"') for c in nav_df.columns]

    _NAV_AMOUNT_KEYWORDS = {"totalassets", "total assets", "nav", "totalnav",
                             "total nav", "netassets", "net assets", "amount",
                             "totalassets"}
    _NAV_CODE_KEYWORDS   = {"portfoliocode", "portfolio code", "fundcode",
                             "fund code", "portfolio"}

    def _match_col(df, keywords):
        for col in df.columns:
            if col.strip().lower() in keywords:
                return col
        return None

    _nav_amt_col  = _match_col(nav_df, _NAV_AMOUNT_KEYWORDS)
    _nav_code_col = _match_col(nav_df, _NAV_CODE_KEYWORDS)

    if _nav_amt_col is None:
        raise KeyError(
            f"NAV file has no recognised total-assets column. "
            f"Found: {list(nav_df.columns)}"
        )
    if _nav_code_col is None:
        raise KeyError(
            f"NAV file has no recognised portfolio-code column. "
            f"Found: {list(nav_df.columns)}"
        )

    nav_df[_nav_amt_col] = nav_df[_nav_amt_col].apply(
        lambda v: _eu_float(str(v).strip().strip('"'))
    )
    nav_by_code: dict[str, float] = dict(
        zip(
            nav_df[_nav_code_col].str.strip().str.strip('"'),
            nav_df[_nav_amt_col],
        )
    )

    # ── 2. Holdings file ─────────────────────────────────────────────────────
    try:
        holdings_df = pd.read_csv(holdings_path, sep=";", dtype=str, header=0)
    except Exception as exc:
        raise ValidationError(f"Cannot read holdings file '{holdings_path.name}': {exc}") from exc
    holdings_df.columns = [c.strip() for c in holdings_df.columns]

    available = sorted(holdings_df["Portfolio Code"].dropna().unique().tolist())
    if portfolio_code is None:
        portfolio_code = available[0]
    elif portfolio_code not in available:
        raise ValueError(
            f"Portfolio '{portfolio_code}' not found. Available: {available}"
        )

    rows = holdings_df[holdings_df["Portfolio Code"] == portfolio_code].copy()
    if rows.empty:
        raise ValueError(f"No holdings for portfolio '{portfolio_code}'.")

    # ── 3. Reporting date ────────────────────────────────────────────────────
    raw_date = rows["Date"].iloc[0]
    try:
        reporting_date = pd.to_datetime(raw_date, dayfirst=True)
    except Exception as exc:
        raise ValidationError(f"Cannot parse reporting date '{raw_date}': {exc}") from exc
    reporting_year = reporting_date.year

    # ── 4. Build positions ───────────────────────────────────────────────────
    positions: list[Position] = []

    def _s(val, default="") -> str:
        """Convert a CSV cell (possibly NaN float) to a stripped string."""
        if val is None:
            return default
        s = str(val).strip()
        return default if s in ("", "nan", "NaN", "None") else s

    for _, row in rows.iterrows():
        isin         = _s(row.get("ISIN"))
        name         = _s(row.get("Security Name"))
        currency     = _s(row.get("Currency"), "EUR")
        product_code = _s(row.get("Product Code"))
        csc          = _s(row.get("CustomSecurityCode"))

        market_value     = _eu_float(_s(row.get("Market Value in Base Currency"), "0"))
        fx_rate          = _eu_float(_s(row.get("Exchange rate"), "1")) or 1.0
        price_factor     = _eu_float(_s(row.get("PriceFactor"), "1"))
        exposure_base_str = _s(row.get("Exposure (base)"), "")
        exposure_base    = _eu_float(exposure_base_str) if exposure_base_str else None
        if exposure_base is not None and abs(exposure_base) < 1.0:
            exposure_base = None

        if abs(market_value) < 1.0:
            continue

        asset_class = _infer_asset_class(isin, name, product_code or csc, price_factor)

        # Duration for bond asset classes
        duration: Optional[float] = None
        if asset_class in ("government_bond", "ig_corporate_bond", "hy_corporate_bond",
                           "structured_credit", "money_market"):
            duration = _estimate_duration(name, reporting_year)

        # Beta for equities
        beta: Optional[float] = None
        if asset_class == "listed_equity":
            beta = _equity_beta(isin)

        adv_30d     = _ADV_DEFAULTS.get(asset_class, 5_000_000)
        bid_ask_bps = _SPREAD_DEFAULTS.get(asset_class, 10)

        # Normalise cash rows
        if asset_class == "cash":
            isin = f"CASH-{currency}"
            name = f"Cash {currency}"

        positions.append(
            Position(
                isin=isin or csc,
                name=name,
                asset_class=asset_class,
                market_value=market_value,  # preserve sign (negative for short derivatives)
                weight=0.0,
                currency=currency,
                fx_rate=fx_rate,
                adv_30d=adv_30d,
                bid_ask_spread_bps=bid_ask_bps,
                duration=duration,
                beta=beta,
                exposure_base=exposure_base,
            )
        )

    # ── 5. Aggregate duplicate ISINs ─────────────────────────────────────────
    positions = _aggregate_positions(positions)

    # ── 6. Share class from NAV total ────────────────────────────────────────
    total_nav = nav_by_code.get(portfolio_code, 0.0)
    position_sum = sum(p.market_value_eur for p in positions)

    if total_nav <= 0:
        total_nav = position_sum

    # NAV consistency check: holdings position sum must equal NAV file within 0.0001%
    if total_nav > 0 and position_sum > 0:
        nav_diff_pct = abs(position_sum - total_nav) / total_nav
        if nav_diff_pct > 0.000001:  # 0.0001%
            warnings.warn(
                f"Portfolio '{portfolio_code}': holdings position sum "
                f"({position_sum:,.2f}) differs from NAV file "
                f"({total_nav:,.2f}) by {nav_diff_pct*100:.4f}%. "
                f"Weights may exceed 100%. Using NAV file value as authoritative total NAV.",
                UserWarning,
                stacklevel=2,
            )

    # Single-position weight validation using NAV file as denominator
    for pos in positions:
        w = pos.market_value_eur / total_nav if total_nav > 0 else 0.0
        if abs(w) > 1.0:
            warnings.warn(
                f"Position '{pos.name}' ({pos.isin}): weight {w*100:.1f}% of NAV "
                f"(market value {pos.market_value_eur:,.0f}, NAV {total_nav:,.0f}). "
                f"Check holdings data for this position.",
                UserWarning,
                stacklevel=2,
            )

    share_classes = [
        ShareClass(
            name=f"{portfolio_code}",
            nav_per_share=100.0,
            shares_outstanding=total_nav / 100.0,
            notice_period_days=0,
            redemption_frequency="daily",
        )
    ]

    # ── 7. Compute top-10 investor concentration from position weights ────────
    # Use absolute weights (short positions count towards concentration risk)
    weights_sorted = sorted(
        [abs(p.market_value_eur) / total_nav for p in positions if total_nav > 0],
        reverse=True,
    )
    top10_concentration = min(sum(weights_sorted[:10]), 1.0)

    # ── 8. Portfolio ──────────────────────────────────────────────────────────
    return Portfolio(
        fund_name=portfolio_code,
        fund_id=portfolio_code,
        reporting_date=reporting_date,
        share_classes=share_classes,
        positions=positions,
        base_currency="EUR",
        top_10_investor_concentration=top10_concentration,
    )


def _aggregate_positions(positions: list[Position]) -> list[Position]:
    """Sum market values of rows with the same ISIN (multiple sub-ledger rows)."""
    seen: dict[str, Position] = {}
    for pos in positions:
        key = pos.isin
        if key in seen:
            seen[key].market_value += pos.market_value
        else:
            seen[key] = pos
    return list(seen.values())


# ---------------------------------------------------------------------------
# Desktop file discovery
# ---------------------------------------------------------------------------

def find_latest_files(
    folder: str | Path = None,
    holdings_glob: str = "HOLDINGS_*.csv",
    nav_glob: str = "NAV_*.csv",
) -> tuple[Path, Path]:
    """Return the most-recently-modified holdings and NAV files in *folder*.

    Defaults to the current user's Desktop.
    """
    if folder is None:
        import os
        folder = Path(os.path.expanduser("~")) / "Desktop"
    folder = Path(folder)

    holdings_files = sorted(folder.glob(holdings_glob), key=lambda p: p.stat().st_mtime, reverse=True)
    nav_files      = sorted(folder.glob(nav_glob),      key=lambda p: p.stat().st_mtime, reverse=True)

    if not holdings_files:
        raise FileNotFoundError(f"No holdings file matching '{holdings_glob}' in {folder}")
    if not nav_files:
        raise FileNotFoundError(f"No NAV file matching '{nav_glob}' in {folder}")

    return holdings_files[0], nav_files[0]


def enrich_portfolio_from_market_data(
    portfolio: "Portfolio",
    market_data_path: str | Path,
) -> "Portfolio":
    """Overwrite Position fields with real Refinitiv data from fetch_market_data output.

    Columns consumed (all optional — missing columns are skipped gracefully):
        isin, portfolio, asset_class_hint, adv_30d_eur, bid_ask_spread_bps,
        modified_duration, convexity, ytm, beta
    """
    mkt = pd.read_csv(market_data_path, dtype=str)
    mkt.columns = [c.strip() for c in mkt.columns]

    def _f(val) -> Optional[float]:
        try:
            f = float(val)
            return None if math.isnan(f) else f
        except (TypeError, ValueError):
            return None

    # Build lookup: isin → row (prefer matching portfolio code if column present)
    has_portfolio_col = "portfolio" in mkt.columns
    fund_id = portfolio.fund_id

    rows_by_isin: dict[str, pd.Series] = {}
    for _, row in mkt.iterrows():
        isin = str(row.get("isin", "")).strip()
        if not isin:
            continue
        # Prefer rows from matching portfolio; fall back to first occurrence
        if isin not in rows_by_isin:
            rows_by_isin[isin] = row
        elif has_portfolio_col and str(row.get("portfolio", "")).strip() == fund_id:
            rows_by_isin[isin] = row

    enriched = 0
    for pos in portfolio.positions:
        row = rows_by_isin.get(pos.isin)
        if row is None:
            continue

        hint = str(row.get("asset_class_hint", "")).strip()
        if hint:
            pos.asset_class = hint

        adv = _f(row.get("adv_30d_eur"))
        if adv is not None and adv > 0:
            pos.adv_30d = adv

        spread = _f(row.get("bid_ask_spread_bps"))
        if spread is not None and spread >= 0:
            pos.bid_ask_spread_bps = spread

        dur = _f(row.get("modified_duration"))
        if dur is not None:
            pos.duration = dur

        conv = _f(row.get("convexity"))
        if conv is not None:
            pos.convexity = conv

        beta = _f(row.get("beta"))
        if beta is not None:
            pos.beta = beta

        enriched += 1

    portfolio._refresh_weights()
    return portfolio


def available_portfolio_codes(mvhol_path: str | Path) -> list[str]:
    """Return the sorted list of portfolio codes present in an MVHOL file."""
    df = pd.read_csv(mvhol_path, sep=";", dtype=str, usecols=["Portfolio Code"])
    return sorted(df["Portfolio Code"].dropna().unique().tolist())
