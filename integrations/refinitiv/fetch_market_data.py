"""
Standalone Refinitiv/LSEG Workspace market data retrieval script.

Run this inside the Refinitiv Workspace Python environment (or any environment
where the Workspace proxy is running on localhost:9000).

Configuration — set the REFINITIV_APP_KEY environment variable before running:
    export REFINITIV_APP_KEY=your_key_here       # Linux/macOS
    set REFINITIV_APP_KEY=your_key_here          # Windows cmd
    $env:REFINITIV_APP_KEY = "your_key_here"     # PowerShell

As a script:
    python fetch_market_data.py --mvhol MVHOL_ALT_20260507120000.csv
    python fetch_market_data.py --mvhol MVHOL_ALT_*.csv --portfolio AL-A --out enriched.csv

As a notebook cell (set these variables, then run fetch_and_save()):
    MVHOL_PATH  = "MVHOL_ALT_20260507120000.csv"
    PORTFOLIO   = None   # or "AL-A"
    OUT_PATH    = None   # or "enriched.csv"
    fetch_and_save(MVHOL_PATH, PORTFOLIO, OUT_PATH)

Output: flat CSV with one row per ISIN containing bid-ask spreads, ADV,
beta, duration, convexity, credit spread, rating, FX rates.

This script is self-contained — no dependency on the liquidity_risk_tool package.

NOTE ON DATA RESTRICTIONS
--------------------------
Outputs produced by this script are derived from Refinitiv/LSEG licensed data.
They must NOT be committed to version control, published, or shared publicly.
Add output paths to .gitignore and keep them in data/real/ (also gitignored).
"""
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Direct Workspace proxy client (bypasses eikon library's broken async layer)
# ---------------------------------------------------------------------------

import os as _os
_APP_KEY = _os.environ.get("REFINITIV_APP_KEY", "")
if not _APP_KEY:
    raise EnvironmentError(
        "REFINITIV_APP_KEY environment variable is not set. "
        "See the module docstring for setup instructions."
    )
_PROXY_PORT = int(_os.environ.get("REFINITIV_PROXY_PORT", "9000"))
_BASE_URL = f"http://127.0.0.1:{_PROXY_PORT}"
_TOKEN: Optional[str] = None


def _handshake() -> str:
    resp = requests.post(
        f"{_BASE_URL}/api/handshake",
        json={
            "AppKey": _APP_KEY,
            "AppScope": "trapi",
            "ApiVersion": "1",
            "LibraryName": "RDP Python Library",
            "LibraryVersion": "1.1.18",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _get_token() -> str:
    global _TOKEN
    if _TOKEN is None:
        _TOKEN = _handshake()
        print(f"[INFO] Connected to Workspace proxy on port {_PROXY_PORT}")
    return _TOKEN


def _udf_request(payload: dict) -> dict:
    token = _get_token()
    resp = requests.post(
        f"{_BASE_URL}/api/v1/data",
        headers={
            "Content-Type": "application/json",
            "x-tr-applicationid": _APP_KEY,
            "Authorization": f"Bearer {token}",
        },
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _get_data(universe: List[str], fields: List[str]) -> pd.DataFrame:
    """Equivalent to ek.get_data() — returns a DataFrame."""
    payload = {
        "Entity": {
            "E": "DataGrid_StandardAsync",
            "W": {
                "requests": [{
                    "instruments": universe,
                    "fields": [{"name": f} for f in fields],
                }]
            },
        }
    }
    result = _udf_request(payload)
    # DataGrid response: top-level responses[] or nested in Entity
    responses = result.get("responses") or result.get("data", {}).get("responses", [])
    if not responses:
        return pd.DataFrame()
    data = responses[0].get("data", [])
    headers = responses[0].get("headers", [[]])[0] if isinstance(responses[0].get("headers", []), list) and responses[0].get("headers") else responses[0].get("headers", [])
    if not data or not headers:
        return pd.DataFrame()
    if isinstance(headers, list) and headers and isinstance(headers[0], list):
        headers = headers[0]
    cols = [h.get("displayName") or h.get("name", "") for h in headers]
    rows = [[cell.get("value") if isinstance(cell, dict) else cell for cell in row] for row in data]
    return pd.DataFrame(rows, columns=cols)


def _get_timeseries(rics: List[str], fields: List[str], start_date: str, end_date: str, interval: str = "daily") -> pd.DataFrame:
    """Equivalent to ek.get_timeseries() — returns a DataFrame."""
    payload = {
        "Entity": {
            "E": "DataGrid_StandardAsync",
            "W": {
                "requests": [{
                    "instruments": rics,
                    "fields": [{"name": f} for f in fields],
                    "parameters": {
                        "SDate": start_date,
                        "EDate": end_date,
                        "Frq": interval[0].upper(),
                        "Sort": "asc",
                    },
                }]
            },
        }
    }
    result = _udf_request(payload)
    responses = result.get("responses") or result.get("data", {}).get("responses", [])
    if not responses:
        return pd.DataFrame()
    data = responses[0].get("data", [])
    headers = responses[0].get("headers", [])
    if not data or not headers:
        return pd.DataFrame()
    if isinstance(headers, list) and headers and isinstance(headers[0], list):
        headers = headers[0]
    cols = [h.get("displayName") or h.get("name", "") for h in headers]
    rows = [[cell.get("value") if isinstance(cell, dict) else cell for cell in row] for row in data]
    return pd.DataFrame(rows, columns=cols)


# ---------------------------------------------------------------------------
# European decimal parsing (mirrors csv_loader._eu_float)
# ---------------------------------------------------------------------------

def _eu_float(value) -> float:
    if not isinstance(value, str):
        return float(value) if value else 0.0
    s = value.strip()
    if not s:
        return 0.0
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _s(val, default="") -> str:
    if val is None:
        return default
    s = str(val).strip()
    return default if s in ("", "nan", "NaN", "None") else s


# ---------------------------------------------------------------------------
# Asset class inference (mirrors csv_loader._infer_asset_class)
# ---------------------------------------------------------------------------

_GOV_KW = (
    "BUND", "OAT ", "BTP ", "GILT", "BONO", "OLO ",
    "REPUBLIC", "SOVEREIGN", "KONINKRIJKSNL",
    "NIEDERSACHS", "SACHSEN", "FREISTAAT", "BUNDESLAND",
    "INVESTITIONSBANK", "FÖRDERBANK", "FOERDERBANK",
    "LAND NORDRHEIN", "LAND BERLIN", "LAND HAMBURG", "LAND BREMEN",
    "DEUTSCHLAND", "BUNDESREPUBLIK", "BUNDESREP",
    "EU BILL", "EUROPEAN UNION", "EU MTN", "EUROPISCHE UNION", "EUROP UNION",
    "EUROPISCHER STABILITTS", "EUROPAEISCHER STABILITAETS",
    "FINLAND", "FINLANDE", "SUOMI", "FINNLAND REPUBLIK",
    "AUSTRIA", "ÖSTERREICH",
    "NIEDERLANDE", "NEDERLAND",
    "POLAND REPUBLIC", "REPUBLIC OF POLAND", "POLEN REPUBLIK",
    "LANDESSCH", "LANDESSCHATZ",
    "INVESTITIONSBANK BERLIN", "NORDDEUTSCHE LANDESBANK",
    "IRLAND", "IRELAND",
    "COMMUNAUT", "COMMUNAUTE",
)
_HY_KW = ("HIGH YIELD", "HY ", " HY", "JUNK", "ALTICE", "LOXAM", "SOFTBANK")
_COVERED_KW = (
    "PFANDBRIEF", "PFANDBR", "PFBR", "PANDBR", "PANDBRIEVEN",
    "COVERED", "OBLIGATION FONCIERE", "OBLFONCIERE",
    "FONCIERE", "HYPOTHEK", "COVERED BOND", "CEDULAS", "HYP ", "HYPO",
    "PANDBR", "MORTG COV", "MORTGCOV", "COV BD", "COVBDS",
)
_FUTURES = ("FTFDAX", "FTFESX", "FTFES", "FTF")
_OPTIONS = ("OPOESX", "OPSPIO", "OPO", "OPS", "PUT ", "CALL ")

# Bond price factors used in this custodian system: 0.03 (= price stored as % × 3)
_BOND_PRICE_FACTORS = (0.01, 0.03)


def _infer_asset_class(isin: str, name: str, product_code: str, price_factor: float) -> str:
    iu = (isin or "").upper()
    nu = (name or "").upper()
    pu = (product_code or "").upper()

    if iu.startswith("CASH-"):
        return "cash"
    # FX forwards (custodian pseudo-ISINs, e.g. SPFXFWDCNHUSD2026-05-18...)
    if iu.startswith("SPFXFWD"):
        return "fx_forward"
    # Bloomberg futures format (e.g. "TYM6 COMDTY", "G M6 COMDTY")
    if " COMDTY" in iu or iu.endswith("COMDTY"):
        return "futures"
    # Structured/synthetic futures products (e.g. FTTSPF/OSE...)
    if iu.startswith("FTTSPF"):
        return "futures"
    if any(fc in pu or fc in iu for fc in _FUTURES):
        return "listed_equity"
    if any(oc in pu or oc in iu for oc in _OPTIONS):
        return "option"

    if any(abs(price_factor - bf) < 1e-6 for bf in _BOND_PRICE_FACTORS):
        if any(kw in nu for kw in _HY_KW):
            return "hy_corporate_bond"
        if any(kw in nu for kw in _COVERED_KW):
            return "ig_corporate_bond"
        if any(kw in nu for kw in _GOV_KW):
            return "government_bond"
        if iu.startswith("XS") or iu.startswith("DE") or iu.startswith("FR") or iu.startswith("AT"):
            return "ig_corporate_bond"
        return "ig_corporate_bond"

    # IE/LU ISINs that aren't bonds → fund/ETF regardless of price_factor
    # (price_factor varies: 1.0 for NAV-priced funds, 100.0 for some custodians)
    if iu[:2] in ("IE", "LU"):
        return "etf"

    # Korean government/municipal bonds stored with non-standard price_factor
    # ISIN type codes: KR10=KTB gov, KR20=municipal, KR30=special/agency
    if iu[:2] == "KR" and len(iu) == 12 and iu[2:4] in ("10", "20"):
        return "government_bond"
    if iu[:2] == "KR" and len(iu) == 12 and iu[2:4] == "30":
        return "ig_corporate_bond"

    return "listed_equity"


# ---------------------------------------------------------------------------
# ISIN → RIC resolution
# ---------------------------------------------------------------------------

_STATIC_OVERRIDES: Dict[str, Optional[str]] = {
    # Pseudo-ISINs → skip
    "CASH-EUR": None, "CASH-USD": None, "CASH-GBP": None,
    "CASH-JPY": None, "CASH-CHF": None,
    # FX forwards (custodian pseudo-ISINs) → skip; no exchange RIC
    # (all SPFXFWD* are caught by startswith in resolve_rics)
    # Futures — Bloomberg ticker → Refinitiv RIC
    "FTFDAX": ".GDAXI", "FTFESX": ".STOXX50E", "FTFES": ".STOXX50E",
    "TYM6 COMDTY":  "TYM6",    # CBOT 10Y US Treasury Note Jun 2026
    "FVM6 COMDTY":  "FVM6",    # CBOT 5Y US Treasury Note Jun 2026
    "USM6 COMDTY":  "USM6",    # CBOT US Treasury Bond Jun 2026
    "WNM6 COMDTY":  "WNM6",    # CBOT Ultra US Treasury Bond Jun 2026
    "G M6 COMDTY":  "FLGm6",   # ICE Liffe UK Long Gilt Jun 2026
    "OATM6 COMDTY": "FOATm6",  # Eurex French OAT Future Jun 2026
    "RXM6 COMDTY":  "FBUm6",   # Eurex Euro-Bund Future Jun 2026
    "OEM6 COMDTY":  "FBOBLm6", # Eurex Euro-Bobl Future Jun 2026
    "DUM6 COMDTY":  "FBSm6",   # Eurex Euro-Schatz Future Jun 2026
    "IKM6 COMDTY":  "FBTP m6", # Eurex BTP Italian Future Jun 2026
    # Structured products with no public RIC → skip
    "FTTSPF/OSE2606_346012_JPY": None,
}

# Futures-month → Refinitiv month code (used in option RIC construction)
_MONTH_CODE = {1:"F",2:"G",3:"H",4:"J",5:"K",6:"M",7:"N",8:"Q",9:"U",10:"V",11:"X",12:"Z"}


def _parse_option_ric(product_code: str) -> Optional[str]:
    """
    Converts internal custodian option product codes to Refinitiv RICs.

    Supported formats:
      OPOESX/EUX{strike100}{YYMM}_{seq}_EUR  → OESXp{MonthCode}{YearDigit}{strike}.EX
      OPSPIO/CBOE{strike100}{YYMM}_{seq}_USD → SPXp{MonthCode}{YearDigit}{strike}.CB
    """
    import re
    pu = (product_code or "").upper().strip()

    # Eurex EURO STOXX 50 put
    m = re.match(r"OPOESX/EUX(\d+)(\d{2})(\d{2})_\d+_EUR", pu)
    if m:
        strike100, yy, mm = m.group(1), m.group(2), m.group(3)
        strike = int(strike100) // 100
        month_code = _MONTH_CODE.get(int(mm))
        if month_code:
            return f"OESXp{month_code}{yy[-1]}{strike}.EX"

    # CBOE S&P 500 put
    m = re.match(r"OPSPIO/CBOE(\d+)(\d{2})(\d{2})_\d+_USD", pu)
    if m:
        strike100, yy, mm = m.group(1), m.group(2), m.group(3)
        strike = int(strike100) // 100
        month_code = _MONTH_CODE.get(int(mm))
        if month_code:
            return f"SPXp{month_code}{yy[-1]}{strike}.CB"

    return None


def resolve_rics(
    isins: List[str],
    asset_classes: Dict[str, str],
    batch_size: int = 50,
) -> Dict[str, Optional[str]]:
    """Two-tier ISIN → RIC: static override → DataGrid TR.RIC lookup (raw ISIN accepted)."""
    result: Dict[str, Optional[str]] = {}
    need_api: List[str] = []

    for isin in isins:
        iu = isin.upper()
        if iu in _STATIC_OVERRIDES:
            result[isin] = _STATIC_OVERRIDES[iu]
            continue
        if iu.startswith("CASH-"):
            result[isin] = None
            continue
        # FX forwards: pseudo-ISIN, no exchange RIC → skip API
        if iu.startswith("SPFXFWD") or asset_classes.get(isin) == "fx_forward":
            result[isin] = None
            continue
        # Futures with Bloomberg ticker not in static overrides → skip API (will miss)
        if asset_classes.get(isin) == "futures":
            result[isin] = None
            continue
        # Options: construct RIC from custodian product code (isin field holds the product code)
        if asset_classes.get(isin) == "option":
            parsed = _parse_option_ric(isin)
            if parsed:
                result[isin] = parsed
                continue
            # Unparseable option — fall through to API (unlikely to succeed but worth trying)
        need_api.append(isin)

    # DataGrid accepts raw ISINs and returns TR.RIC (the canonical ticker RIC)
    api_hits: Dict[str, str] = {}
    for i in range(0, len(need_api), batch_size):
        batch = need_api[i : i + batch_size]
        try:
            df = _get_data(batch, ["TR.RIC"])
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    instrument = _s(row.get("Instrument", ""))
                    ric_val = _s(row.get("RIC") or row.get("TR.RIC"))
                    # Only accept if RIC differs from the input ISIN (i.e. it resolved)
                    if instrument and ric_val and ric_val != instrument:
                        api_hits[instrument] = ric_val
        except Exception as exc:
            print(f"  [WARN] RIC API lookup batch {i//batch_size + 1} failed: {exc}", file=sys.stderr)

    for isin in need_api:
        if isin in api_hits:
            result[isin] = api_hits[isin]
        else:
            # Structural fallback only for bonds (ISIN= convention sometimes works)
            ac = asset_classes.get(isin, "listed_equity")
            if ac in ("government_bond", "ig_corporate_bond", "hy_corporate_bond",
                      "structured_credit", "money_market"):
                result[isin] = f"{isin.upper()}="
            elif ac in ("fx_forward", "futures"):
                result[isin] = None  # expected — no RIC for these asset classes
            else:
                result[isin] = None  # No valid fallback for equities/ETFs
                print(f"  [WARN] No RIC found for {isin} ({ac})", file=sys.stderr)

    return result


# ---------------------------------------------------------------------------
# Snapshot fields
# ---------------------------------------------------------------------------

_EQUITY_FIELDS = [
    "TR.BidPrice", "TR.AskPrice", "TR.PriceClose",
    "CF_BID", "CF_ASK", "CF_LAST",
    "TR.BetaFiveYear", "TR.Volume", "TR.NAV",
]
_BOND_FIELDS = [
    "TR.BidPrice", "TR.AskPrice", "TR.PriceClose",
    "CF_BID", "CF_ASK", "CF_LAST", "YIELD_MID",
    "TR.ModifiedDuration", "TR.Convexity", "TR.YieldToMaturity",
]
_OPTION_FIELDS = [
    "TR.BidPrice", "TR.AskPrice", "TR.PriceClose",
    "CF_BID", "CF_ASK", "CF_LAST",
    "TR.OpenInterest", "TR.Volume",
]


def _safe_float(val) -> Optional[float]:
    try:
        f = float(val)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def fetch_snapshots(
    ric_to_isin: Dict[str, str],
    asset_classes: Dict[str, str],
    batch_size: int = 50,
) -> Dict[str, dict]:
    """Fetch snapshot fields; returns dict keyed by ISIN."""
    equity_rics = [r for r, i in ric_to_isin.items()
                   if asset_classes.get(i, "") in ("listed_equity", "etf", "futures")]
    bond_rics   = [r for r, i in ric_to_isin.items()
                   if asset_classes.get(i, "") in (
                       "government_bond", "ig_corporate_bond", "hy_corporate_bond",
                       "structured_credit", "money_market",
                   )]
    option_rics = [r for r, i in ric_to_isin.items()
                   if asset_classes.get(i, "") == "option"]

    raw: Dict[str, dict] = {}  # keyed by RIC

    def _fetch_batch(rics, fields):
        for i in range(0, len(rics), batch_size):
            batch = rics[i : i + batch_size]
            try:
                df = _get_data(batch, fields)
                if df is None or df.empty:
                    continue
                for _, row in df.iterrows():
                    ric = _s(row.get("Instrument", ""))
                    if ric:
                        raw[ric] = row.to_dict()
            except Exception as exc:
                print(f"  [WARN] snapshot fetch failed for batch starting {batch[0]}: {exc}", file=sys.stderr)

    _fetch_batch(equity_rics, _EQUITY_FIELDS)
    _fetch_batch(bond_rics, _BOND_FIELDS)
    _fetch_batch(option_rics, _OPTION_FIELDS)

    # Remap RIC → ISIN
    result: Dict[str, dict] = {}
    for ric, data in raw.items():
        isin = ric_to_isin.get(ric)
        if isin:
            result[isin] = data
    return result


# ---------------------------------------------------------------------------
# ADV via 30-day history
# ---------------------------------------------------------------------------

def fetch_adv(
    ric_to_isin: Dict[str, str],
    asset_classes: Dict[str, str],
    snapshot_data: Dict[str, dict],
    batch_size: int = 50,
) -> Dict[str, Optional[float]]:
    """Returns adv_30d_eur keyed by ISIN."""
    today = date.today()
    start = (today - timedelta(days=45)).isoformat()  # extra buffer for weekends/holidays
    end   = today.isoformat()

    equity_rics = [r for r, i in ric_to_isin.items()
                   if asset_classes.get(i, "") in ("listed_equity", "etf", "futures")]

    adv: Dict[str, Optional[float]] = {}

    # Equities: sum(Volume × PriceClose) / 30 from history
    for i in range(0, len(equity_rics), batch_size):
        batch = equity_rics[i : i + batch_size]
        try:
            df = _get_timeseries(
                rics=batch,
                fields=["TR.Volume", "TR.PriceClose"],
                start_date=start,
                end_date=end,
                interval="daily",
            )
            if df is None or df.empty:
                continue
            # Response has Instrument column repeated per row; group by it
            inst_col = next((c for c in df.columns if c.lower() == "instrument"), None)
            vol_col  = next((c for c in df.columns if "volume" in c.lower()), None)
            price_col = next((c for c in df.columns if "price close" in c.lower() or "priceclose" in c.lower()), None)
            if not (vol_col and price_col):
                continue
            for ric in batch:
                sub = df[df[inst_col] == ric] if inst_col else df
                vol   = pd.to_numeric(sub[vol_col],   errors="coerce")
                price = pd.to_numeric(sub[price_col], errors="coerce")
                daily = (vol * price).dropna()
                if len(daily) >= 5:
                    isin = ric_to_isin.get(ric)
                    if isin:
                        adv[isin] = daily.sum() / 30
        except Exception as exc:
            print(f"  [WARN] ADV history fetch failed for batch starting {batch[0]}: {exc}", file=sys.stderr)

    # Bonds: TR.IssueAmountOutstanding is unlicensed — use tier-based ADV fallback
    _BOND_ADV_TIER = {
        "government_bond":   50_000_000,   # sovereign / agency / Bund / OAT / etc.
        "ig_corporate_bond":  2_000_000,
        "hy_corporate_bond":    500_000,
        "structured_credit":    500_000,
        "money_market":      10_000_000,
    }
    for isin, ac in asset_classes.items():
        if ac in _BOND_ADV_TIER and isin not in adv:
            adv[isin] = float(_BOND_ADV_TIER[ac])

    return adv


# ---------------------------------------------------------------------------
# FX rates
# ---------------------------------------------------------------------------

def fetch_fx_rates(currencies: Set[str]) -> Dict[str, float]:
    """Returns fx_to_eur keyed by currency code. EUR → 1.0."""
    non_eur = [c for c in currencies if c.upper() != "EUR"]
    fx: Dict[str, float] = {"EUR": 1.0}
    if not non_eur:
        return fx

    # {CCY}=X returns units-of-CCY per 1 EUR (e.g. USD=X → 1.1725 means 1 EUR = 1.1725 USD)
    rics = [f"{c.upper()}=X" for c in non_eur]
    try:
        df = _get_data(rics, ["CF_LAST"])
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                instrument = _s(row.get("Instrument", "") or row.get("RIC", ""))
                ccy = instrument.replace("=X", "").strip()
                rate = _safe_float(row.get("CF_LAST") or row.get("Last"))
                if rate and ccy:
                    fx[ccy] = rate
    except Exception as exc:
        print(f"  [WARN] FX fetch failed: {exc}", file=sys.stderr)

    return fx


# ---------------------------------------------------------------------------
# MVHOL reader
# ---------------------------------------------------------------------------

def read_mvhol(mvhol_path: Path, portfolio_code: Optional[str] = None):
    """Returns list of dicts with keys: isin, name, currency, market_value, asset_class."""
    df = pd.read_csv(mvhol_path, sep=";", dtype=str, header=0)
    df.columns = [c.strip() for c in df.columns]

    available = sorted(df["Portfolio Code"].dropna().unique().tolist())
    if portfolio_code is None:
        portfolio_code = available[0]
        print(f"  Using portfolio: {portfolio_code}  (available: {available})")
    elif portfolio_code not in available:
        raise ValueError(f"Portfolio '{portfolio_code}' not found. Available: {available}")

    rows = df[df["Portfolio Code"] == portfolio_code].copy()

    positions = []
    for _, row in rows.iterrows():
        isin         = _s(row.get("ISIN"))
        name         = _s(row.get("Security Name"))
        currency     = _s(row.get("Currency"), "EUR")
        product_code = _s(row.get("Product Code"))
        csc          = _s(row.get("CustomSecurityCode"))
        price_factor = _eu_float(_s(row.get("PriceFactor"), "1"))
        market_value = _eu_float(_s(row.get("Market Value in Base Currency"), "0"))
        raw_exp      = _s(row.get("Exposure (base)"))

        if market_value == 0 and raw_exp:
            market_value = abs(_eu_float(raw_exp))
        if abs(market_value) < 1.0:
            continue

        asset_class = _infer_asset_class(isin, name, product_code or csc, price_factor)

        if asset_class == "cash":
            isin = f"CASH-{currency}"
            name = f"Cash {currency}"

        positions.append({
            "isin":        isin or csc,
            "name":        name,
            "currency":    currency,
            "market_value": market_value,
            "asset_class": asset_class,
        })

    # Deduplicate ISINs (sum market value)
    seen: Dict[str, dict] = {}
    for p in positions:
        k = p["isin"]
        if k in seen:
            seen[k]["market_value"] += p["market_value"]
        else:
            seen[k] = p
    return list(seen.values())


# ---------------------------------------------------------------------------
# Per-ISIN cache  (market_data_cache.csv sitting next to the output file)
# ---------------------------------------------------------------------------

_CACHE_COLS = [
    "isin", "ric", "asset_class_hint", "currency",
    "bid", "ask", "bid_ask_spread_bps", "adv_30d_eur",
    "beta", "modified_duration", "convexity", "ytm",
    "open_interest", "option_volume", "credit_spread_bps",
    "rating", "amount_outstanding", "fx_rate_to_eur",
    "fetch_date", "fetch_errors",
]


def _cache_path(out_path: Path) -> Path:
    return out_path.parent / "market_data_cache.csv"


def _load_cache(cache_file: Path, today: str) -> Dict[str, dict]:
    """Return dict[isin → row_dict] for rows fetched today."""
    if not cache_file.exists():
        return {}
    try:
        df = pd.read_csv(cache_file, dtype=str)
        df.columns = [c.strip() for c in df.columns]
        today_rows = df[df.get("fetch_date", pd.Series(dtype=str)) == today] if "fetch_date" in df.columns else pd.DataFrame()
        return {str(row["isin"]).strip(): row.to_dict() for _, row in today_rows.iterrows() if row.get("isin")}
    except Exception:
        return {}


def _append_cache(cache_file: Path, new_rows: List[dict]) -> None:
    """Append freshly fetched rows to the cache file (create if missing)."""
    if not new_rows:
        return
    new_df = pd.DataFrame(new_rows, columns=_CACHE_COLS)
    if cache_file.exists():
        try:
            existing = pd.read_csv(cache_file, dtype=str)
            # Remove any stale entries for the same ISINs so we don't accumulate duplicates
            existing = existing[~existing["isin"].isin(new_df["isin"].tolist())]
            combined = pd.concat([existing, new_df], ignore_index=True)
        except Exception:
            combined = new_df
    else:
        combined = new_df
    combined.to_csv(cache_file, index=False)


# ---------------------------------------------------------------------------
# Core fetch pipeline (callable from notebook or CLI)
# ---------------------------------------------------------------------------

def fetch_and_save(
    mvhol_path,
    portfolio_code: Optional[str] = None,
    out_path=None,
):
    mvhol_path = Path(mvhol_path)
    if not mvhol_path.exists():
        raise FileNotFoundError(f"File not found: {mvhol_path}")

    fetch_date = date.today().isoformat()
    if out_path is not None:
        out_path = Path(out_path)

    print(f"Reading holdings: {mvhol_path}")
    positions = read_mvhol(mvhol_path, portfolio_code)
    print(f"  {len(positions)} unique positions")

    isins         = [p["isin"] for p in positions]
    asset_classes = {p["isin"]: p["asset_class"] for p in positions}
    currencies    = {p["currency"] for p in positions}

    # ── Cache check ──────────────────────────────────────────────────────────
    cache_file = _cache_path(out_path) if out_path is not None else None
    cached: Dict[str, dict] = _load_cache(cache_file, fetch_date) if cache_file else {}
    need_fetch = [isin for isin in isins if isin not in cached]

    if cached:
        print(f"  Cache hit: {len(cached)} ISINs already fetched today, {len(need_fetch)} need API calls")
    # ─────────────────────────────────────────────────────────────────────────

    if need_fetch:
        fresh_asset_classes = {k: v for k, v in asset_classes.items() if k in need_fetch}
        fresh_currencies    = {p["currency"] for p in positions if p["isin"] in need_fetch}

        print("Resolving ISINs to RICs...")
        ric_map = resolve_rics(need_fetch, fresh_asset_classes)
        resolved = sum(1 for v in ric_map.values() if v is not None)
        print(f"  {resolved}/{len(need_fetch)} resolved")

        ric_to_isin: Dict[str, str] = {ric: isin for isin, ric in ric_map.items() if ric is not None}

        print("Fetching snapshot fields...")
        snapshot_data = fetch_snapshots(ric_to_isin, fresh_asset_classes)
        print(f"  {len(snapshot_data)} positions with snapshot data")

        print("Fetching 30-day ADV...")
        adv_data = fetch_adv(ric_to_isin, fresh_asset_classes, snapshot_data)
        print(f"  {len(adv_data)} positions with ADV data")

        print("Fetching FX rates...")
        fx_rates = fetch_fx_rates(fresh_currencies)
        print(f"  FX rates: {fx_rates}")
    else:
        print("  All ISINs served from cache — skipping API calls")
        ric_map = {}
        snapshot_data = {}
        adv_data = {}
        fx_rates = {"EUR": 1.0}

    # ── Build output rows (cache-first) ──────────────────────────────────────
    new_rows: List[dict] = []
    output_rows = []

    for pos in positions:
        isin   = pos["isin"]
        ac     = pos["asset_class"]
        ccy    = pos["currency"]

        if isin in cached:
            row = dict(cached[isin])
            # Normalise numeric-as-string fields back to Python native where possible
            output_rows.append(row)
            continue

        ric    = ric_map.get(isin)
        snap   = snapshot_data.get(isin, {})
        errors: List[str] = []

        if ric is None and ac not in ("cash", "fx_forward", "futures"):
            errors.append("ric_not_found")

        bid  = _safe_float(snap.get("Bid Price") or snap.get("TR.BidPrice") or snap.get("CF_BID") or snap.get("Bid"))
        ask  = _safe_float(snap.get("Ask Price") or snap.get("TR.AskPrice") or snap.get("CF_ASK") or snap.get("Ask"))
        last = _safe_float(snap.get("Price Close") or snap.get("TR.PriceClose") or snap.get("CF_LAST") or snap.get("Last"))
        nav  = _safe_float(snap.get("Net Asset Value") or snap.get("TR.NAV"))
        if bid is not None and ask is not None and bid > 0 and ask > 0:
            mid = (bid + ask) / 2
            bid_ask_bps = round((ask - bid) / mid * 10_000, 2)
        else:
            bid_ask_bps = None
            if last is not None and last > 0:
                bid = last
                ask = last
            elif ac == "etf" and nav is not None and nav > 0:
                # Funds publish NAV not live quotes — use NAV as mid, spread = 0
                bid = nav
                ask = nav
                bid_ask_bps = 0.0
            elif ric is not None and ac not in ("cash", "money_market", "etf", "option", "fx_forward", "futures"):
                errors.append("bid_ask_missing")

        adv = adv_data.get(isin)
        if adv is None and ac not in ("cash", "money_market", "private_equity", "hedge_fund",
                                      "real_estate", "etf", "option", "fx_forward", "futures"):
            errors.append("adv_missing")

        beta        = _safe_float(snap.get("Beta 5 Year") or snap.get("TR.BetaFiveYear"))
        duration    = _safe_float(snap.get("Modified Duration"))
        convexity   = _safe_float(snap.get("Convexity"))
        ytm         = _safe_float(snap.get("Yield To Maturity"))
        open_interest = _safe_float(snap.get("Open Interest"))
        opt_volume    = _safe_float(snap.get("Volume"))
        spread      = None
        rating      = None
        outstanding = None

        fx = fx_rates.get(ccy.upper(), None)
        if fx is None and ccy.upper() != "EUR":
            errors.append(f"fx_missing_{ccy}")

        row = {
            "isin":               isin,
            "ric":                ric or "",
            "asset_class_hint":   ac,
            "currency":           ccy,
            "bid":                bid,
            "ask":                ask,
            "bid_ask_spread_bps": bid_ask_bps,
            "adv_30d_eur":        round(adv, 0) if adv is not None else None,
            "beta":               beta,
            "modified_duration":  duration,
            "convexity":          convexity,
            "ytm":                ytm,
            "open_interest":      open_interest,
            "option_volume":      opt_volume,
            "credit_spread_bps":  spread,
            "rating":             rating,
            "amount_outstanding": outstanding,
            "fx_rate_to_eur":     fx,
            "fetch_date":         fetch_date,
            "fetch_errors":       "; ".join(errors),
        }
        output_rows.append(row)
        new_rows.append(row)

    # ── Persist newly fetched rows to cache ──────────────────────────────────
    if cache_file and new_rows:
        _append_cache(cache_file, new_rows)
        print(f"  Cached {len(new_rows)} new rows → {cache_file.name}")

    out_df = pd.DataFrame(output_rows)
    if out_path is not None:
        out_df.to_csv(out_path, index=False)
        print(f"\nWrote {len(out_df)} rows -> {out_path}")

    n_errors = out_df["fetch_errors"].astype(str).str.len().gt(0).sum()
    print(f"Positions with fetch errors: {n_errors}/{len(out_df)}")
    if n_errors:
        err_sub = out_df[out_df["fetch_errors"].astype(str).str.len() > 0]
        for col in ("isin", "asset_class_hint", "fetch_errors"):
            if col not in err_sub.columns:
                err_sub = err_sub.copy(); err_sub[col] = ""
        print(err_sub[["isin", "asset_class_hint", "fetch_errors"]].to_string(index=False))

    return out_df


# ---------------------------------------------------------------------------
# Portfolio scanner — shows asset class breakdown per portfolio
# ---------------------------------------------------------------------------

def scan_portfolios(mvhol_path):
    """Print asset class breakdown for every portfolio in the MVHOL file."""
    df = pd.read_csv(mvhol_path, sep=";", dtype=str, header=0)
    df.columns = [c.strip() for c in df.columns]
    portfolios = sorted(df["Portfolio Code"].dropna().unique().tolist())
    print(f"Portfolios in file: {portfolios}\n")
    bond_classes = {"government_bond", "ig_corporate_bond", "hy_corporate_bond", "structured_credit", "money_market"}
    rows = []
    for pf in portfolios:
        sub = df[df["Portfolio Code"] == pf]
        counts = {}
        has_bonds = False
        for _, row in sub.iterrows():
            isin         = _s(row.get("ISIN"))
            name         = _s(row.get("Security Name"))
            product_code = _s(row.get("Product Code") or row.get("CustomSecurityCode"))
            price_factor = _eu_float(_s(row.get("PriceFactor"), "1"))
            market_value = _eu_float(_s(row.get("Market Value in Base Currency"), "0"))
            if abs(market_value) < 1.0:
                continue
            ac = _infer_asset_class(isin, name, product_code, price_factor)
            counts[ac] = counts.get(ac, 0) + 1
            if ac in bond_classes:
                has_bonds = True
        summary = ", ".join(f"{ac}:{n}" for ac, n in sorted(counts.items()))
        rows.append((pf, "YES" if has_bonds else "no", summary))
    print(f"{'Portfolio':<14} {'Bonds?':<8} Asset class counts")
    print("-" * 80)
    for pf, bonds, summary in rows:
        print(f"{pf:<14} {bonds:<8} {summary}")


# ---------------------------------------------------------------------------
# Entry point
#   python integrations/refinitiv/fetch_market_data.py --mvhol path/to/MVHOL.csv
#   python integrations/refinitiv/fetch_market_data.py --mvhol path/to/MVHOL.csv --out data/real/market_data_ALL.csv
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fetch Refinitiv market data for all portfolios in an MVHOL file.")
    parser.add_argument("--mvhol", required=True, help="Path to the MVHOL CSV file (semicolon-delimited)")
    parser.add_argument("--portfolio", default=None, help="Portfolio code to fetch (default: all)")
    parser.add_argument("--out", default=None, help="Output CSV path (default: data/real/market_data_ALL.csv next to this script)")
    args = parser.parse_args()

    MVHOL_PATH = Path(args.mvhol)
    OUT_PATH = Path(args.out) if args.out else Path(__file__).parent.parent.parent / "data" / "real" / "market_data_ALL.csv"
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    _index_df = pd.read_csv(MVHOL_PATH, sep=";", dtype=str, header=0)
    _index_df.columns = [c.strip() for c in _index_df.columns]

    if args.portfolio:
        _all_portfolios = [args.portfolio]
    else:
        _all_portfolios = sorted(_index_df["Portfolio Code"].dropna().unique().tolist())
    print(f"Running portfolios: {_all_portfolios}")

    _frames = []
    for _pf in _all_portfolios:
        _df = fetch_and_save(MVHOL_PATH, _pf, out_path=None)
        if _df is not None and not _df.empty:
            _df.insert(0, "portfolio", _pf)
            _frames.append(_df)

    _combined = pd.concat([f.convert_dtypes() for f in _frames], ignore_index=True)
    _combined.to_csv(OUT_PATH, index=False)
    print(f"\nSaved {len(_combined)} rows → {OUT_PATH}")

    _ERRORS_PATH = OUT_PATH.parent / "market_data_ERRORS.csv"
    _errors_df = (
        _combined[_combined["fetch_errors"].str.len() > 0]
        [["portfolio", "isin", "ric", "asset_class_hint", "currency", "fetch_errors"]]
        .sort_values(["fetch_errors", "portfolio", "asset_class_hint"])
        .reset_index(drop=True)
    )
    _errors_df.to_csv(_ERRORS_PATH, index=False)
    print(f"Saved error summary ({len(_errors_df)} rows) → {_ERRORS_PATH}")

    print(f"\n{'='*60}")
    print(f"ERROR SUMMARY  ({len(_errors_df)} positions with errors / {len(_combined)} total)")
    print(f"{'='*60}")
    print(_errors_df.groupby("fetch_errors")["isin"].count().rename("count").to_string())
    print(f"\nBy portfolio:")
    print(_errors_df.groupby(["portfolio", "fetch_errors"])["isin"].count().rename("count").to_string())
    print(f"{'='*60}")









