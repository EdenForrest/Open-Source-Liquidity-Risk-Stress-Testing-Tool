"""
Historical time-series generator for the liquidity risk tool.

Where ``generate_synthetic_data.py`` produces a *single-date* snapshot with a
fresh random security universe, this module produces a **coherent historical
time series**: one persistent book per portfolio, repriced across a range of
business days so that liquidity, stress and redemption metrics evolve smoothly
day to day instead of jumping around a new random universe every date.

Design
------
1. Bootstrap a base snapshot with the existing, carefully-tuned generator
   (``generate_synthetic_data.generate_all``). This guarantees every regulatory
   scenario baked into the single-date generator is preserved unchanged
   (SYN-ILLIQ breach, SYN-LOANFUND borrower concentration, SYN-LEVERAGED gross
   leverage > 175%, geo-concentration overrides, ADV/spread calibration, etc.).
2. Parse that snapshot into a fixed **security universe** — static identity
   (ISIN, name, asset_class, currency, country, quantity/notional, duration,
   beta, rating, ADV, spread) plus a base price and base market value.
3. Walk the requested date range and **reprice** the *same* securities each day
   via asset-class-appropriate stochastic processes. Quantities are held
   constant (buy-and-hold), so market-value moves are purely price-driven —
   the natural interpretation of "watch this book's risk over time".
4. Emit files in the **exact on-disk schema** the existing CSV loader reads:
       history/HOLDINGS_<YYYYMMDDHHMMSS>.csv     (one per date)
       history/market_data_ALL_<date>.csv        (one per date)
       history/NAV.csv                           (consolidated, all dates)
       history/market_data_ERRORS_<date>.csv     (one per date)
       history/manifest.json                     (index of the series)

The per-date holdings/market-data files load unchanged through
``load_portfolio_from_csv`` + ``enrich_portfolio_from_market_data``; the
consolidated NAV file is filtered per snapshot via the loader's ``as_of_date``
parameter (see csv_loader). No real market data is read or referenced — every
value is synthetic, same as the base generator.
"""

from __future__ import annotations

import csv
import json
import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

# Reuse the base generator's schema + helpers so the two stay in lock-step.
from . import generate_synthetic_data as base
from .generate_synthetic_data import (
    HOLDINGS_COLUMNS,
    NAV_COLUMNS,
    MARKET_DATA_COLUMNS,
    MARKET_ERRORS_COLUMNS,
    PORTFOLIOS,
    _eu,
)


# ---------------------------------------------------------------------------
# European-decimal parsing (mirror of csv_loader._eu_float, kept local so the
# generator has no dependency on the ingestion package)
# ---------------------------------------------------------------------------

def _eu_float(value: str) -> float:
    """'1.159.375,00' -> 1159375.0 ; '(21.016,00)' -> -21016.0 ; '' -> 0.0"""
    if value is None:
        return 0.0
    s = str(value).strip()
    if not s:
        return 0.0
    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1]
    s = s.replace(".", "").replace(",", ".")
    try:
        f = float(s)
    except ValueError:
        return 0.0
    if not math.isfinite(f):
        return 0.0
    return -f if negative else f


def _plain_float(value: str) -> Optional[float]:
    """Parse a plain (dot-decimal) market-data cell; blank/invalid -> None."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return f if math.isfinite(f) else None


# ---------------------------------------------------------------------------
# Business-day calendar
# ---------------------------------------------------------------------------

def _business_days(start: date, end: date, freq: str = "daily") -> list[date]:
    """Return business days (Mon-Fri) between start and end inclusive.

    freq: 'daily' (every weekday), 'weekly' (Fridays), 'monthly' (month-end
    business day). Always includes ``end`` if it is a weekday.
    """
    if end < start:
        start, end = end, start
    days: list[date] = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            days.append(cur)
        cur += timedelta(days=1)
    if not days:
        return []
    if freq == "daily":
        picked = days
    elif freq == "weekly":
        picked = [d for d in days if d.weekday() == 4]  # Fridays
    elif freq == "monthly":
        picked = []
        for i, d in enumerate(days):
            is_last = (i == len(days) - 1) or (days[i + 1].month != d.month)
            if is_last:
                picked.append(d)
    else:
        raise ValueError(f"Unknown freq '{freq}' (use daily|weekly|monthly)")
    # Guarantee the final observation date is present.
    if days[-1] not in picked:
        picked.append(days[-1])
    return picked


# ---------------------------------------------------------------------------
# Security universe
# ---------------------------------------------------------------------------

# Asset classes whose market value is price-driven (quantity * price).
_PRICE_DRIVEN = {
    "listed_equity", "leveraged_equity", "etf",
    "government_bond", "ig_corporate_bond", "hy_corporate_bond",
    "originated_loan",
}
# Derivatives: MV stays ~0, economic exposure carried in Exposure (base).
_DERIVATIVE = {"future", "forward", "trs", "option"}


@dataclass
class SynthSecurity:
    """A single security whose identity is fixed across the whole time series."""
    portfolio: str
    isin: str
    asset_class: str
    row: dict                       # the base holdings row (schema-complete)
    mkt: Optional[dict] = None      # the base market-data row, if any

    # Static identity captured from the base snapshot
    quantity: float = 0.0
    price_factor: float = 1.0
    currency: str = "EUR"
    base_price: float = 1.0         # 'Clean price (local)' at base date
    base_mv_eur: float = 0.0        # 'Market Value in Base Currency' at base date
    base_exposure: Optional[float] = None
    base_accrual: float = 0.0

    # Fixed market-microstructure attributes (from market_data row)
    base_adv: Optional[float] = None
    base_spread_bps: Optional[float] = None
    duration: Optional[float] = None


def _build_universe(
    base_dir: Path,
    portfolios: list[str],
    base_report_date: str,
) -> tuple[dict[str, list[SynthSecurity]], dict[str, dict]]:
    """Bootstrap a base snapshot and parse it into a persistent universe.

    Returns (universe_by_portfolio, market_rows_by_key) where
    market_rows_by_key maps (portfolio, isin) -> base market-data row.
    """
    holdings_path = base_dir / f"_base_HOLDINGS.csv"
    mkt_all_path  = base_dir / "_base_market_data_ALL.csv"
    mkt_err_path  = base_dir / "_base_market_data_ERRORS.csv"

    isin_map = base.generate_holdings(
        report_date=base_report_date,
        portfolios=portfolios,
        output_path=holdings_path,
    )
    base.generate_market_data(
        report_date_iso="-".join(reversed(base_report_date.split("."))),
        portfolios=portfolios,
        all_output=mkt_all_path,
        errors_output=mkt_err_path,
        isin_map=isin_map,
    )

    # Parse market data into (portfolio, isin) -> row
    mkt_by_key: dict[tuple[str, str], dict] = {}
    with mkt_all_path.open("r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            mkt_by_key[(r["portfolio"].strip(), r["isin"].strip())] = r

    # Parse holdings into securities
    universe: dict[str, list[SynthSecurity]] = {p: [] for p in portfolios}
    with holdings_path.open("r", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f, delimiter=";"):
            pcode = r["Portfolio Code"].strip()
            isin  = r["ISIN"].strip()
            ac    = isin_map.get(isin, (pcode, "cash"))[1]
            mkt   = mkt_by_key.get((pcode, isin))

            price_factor = _eu_float(r.get("PriceFactor", "1")) or 1.0
            sec = SynthSecurity(
                portfolio=pcode,
                isin=isin,
                asset_class=ac,
                row=dict(r),
                mkt=dict(mkt) if mkt else None,
                quantity=_eu_float(r.get("Quantity", "0")),
                price_factor=price_factor,
                currency=(r.get("Currency") or "EUR").strip() or "EUR",
                base_price=_eu_float(r.get("Clean price (local)", "0")),
                base_mv_eur=_eu_float(r.get("Market Value in Base Currency", "0")),
                base_exposure=_eu_float(r["Exposure (base)"]) if r.get("Exposure (base)", "").strip() else None,
                base_accrual=_eu_float(r.get("Accruals in Base Currency", "0")),
            )
            if mkt:
                sec.base_adv = _plain_float(mkt.get("adv_30d_eur"))
                sec.base_spread_bps = _plain_float(mkt.get("bid_ask_spread_bps"))
                sec.duration = _plain_float(mkt.get("modified_duration"))
            if sec.duration is None and ac in ("government_bond", "ig_corporate_bond", "hy_corporate_bond"):
                sec.duration = 5.0
            universe.setdefault(pcode, []).append(sec)

    # Clean up the temporary base files
    for p in (holdings_path, mkt_all_path, mkt_err_path):
        try:
            p.unlink()
        except OSError:
            pass

    return universe, {f"{k[0]}|{k[1]}": v for k, v in mkt_by_key.items()}


# ---------------------------------------------------------------------------
# Market regime — one correlated set of factors per portfolio, per day
# ---------------------------------------------------------------------------

@dataclass
class Regime:
    """Per-portfolio market state that evolves across the series."""
    equity_cum: float = 1.0        # cumulative equity price multiplier
    yield_bps: float = 0.0         # cumulative parallel yield shift (bps)
    spread_mult: float = 1.0       # credit-spread multiplier
    adv_mult: float = 1.0          # ADV multiplier (liquidity regime)


def _step_regime(reg: Regime, rng: random.Random, stressed: bool) -> Regime:
    """Advance the regime one business day."""
    if stressed:
        eq_drift, eq_vol = -0.006, 0.020      # drawdown + elevated vol
        dy = rng.gauss(3.0, 6.0)              # yields drift up under stress
        spread_step = rng.gauss(0.03, 0.05)  # spreads widen
        adv_step = rng.gauss(-0.02, 0.03)    # volumes thin out
    else:
        eq_drift, eq_vol = 0.0003, 0.009
        dy = rng.gauss(0.0, 2.0)
        spread_step = rng.gauss(0.0, 0.02)
        adv_step = rng.gauss(0.0, 0.02)

    shock = rng.gauss(eq_drift, eq_vol)
    return Regime(
        equity_cum=max(0.2, reg.equity_cum * (1.0 + shock)),
        yield_bps=reg.yield_bps + dy,
        spread_mult=min(4.0, max(0.5, reg.spread_mult * (1.0 + spread_step))),
        adv_mult=min(2.0, max(0.25, reg.adv_mult * (1.0 + adv_step))),
    )


def _reprice_row(
    sec: SynthSecurity,
    reg: Regime,
    idio: float,
    report_date_ddmmyyyy: str,
) -> dict:
    """Return a repriced holdings row for this security on the given date."""
    row = dict(sec.row)
    row["Date"] = report_date_ddmmyyyy

    ac = sec.asset_class
    if ac in ("listed_equity", "leveraged_equity", "etf"):
        # Geometric move: market factor * idiosyncratic beta-scaled noise
        price = sec.base_price * reg.equity_cum * idio
        mv = sec.base_mv_eur * reg.equity_cum * idio
        row["Clean price (local)"] = _eu(price, 4)
        row["Market Value in Base Currency"] = _eu(mv, 10)
        if sec.base_exposure is not None:
            # leveraged equity: exposure scales with the same move
            row["Exposure (base)"] = _eu(sec.base_exposure * reg.equity_cum * idio, 2)

    elif ac in ("government_bond", "ig_corporate_bond", "hy_corporate_bond"):
        dur = sec.duration if sec.duration else 5.0
        dy = reg.yield_bps / 10_000.0
        # credit names also feel the spread multiplier as extra yield
        if ac != "government_bond":
            base_spread = (sec.base_spread_bps or 60.0) / 10_000.0
            dy += base_spread * (reg.spread_mult - 1.0)
        # price return via modified duration + small convexity term
        conv = (dur ** 2) / 2.0
        ret = (-dur * dy + 0.5 * conv * dy * dy) * idio
        price = max(1.0, sec.base_price * (1.0 + ret))
        mv = sec.base_mv_eur * (1.0 + ret)
        row["Clean price (local)"] = _eu(price, 4)
        row["Market Value in Base Currency"] = _eu(mv, 10)

    elif ac == "originated_loan":
        # Private debt: slow drift near par, mild idiosyncratic noise
        ret = (idio - 1.0) * 0.3
        row["Clean price (local)"] = _eu(max(50.0, sec.base_price * (1.0 + ret)), 4)
        row["Market Value in Base Currency"] = _eu(sec.base_mv_eur * (1.0 + ret), 2)

    elif ac in _DERIVATIVE:
        # MV stays near its base MTM (~0); exposure notional jitters slightly.
        if sec.base_exposure is not None:
            row["Exposure (base)"] = _eu(sec.base_exposure * idio, 2)
        # small MTM wobble for TRS/forwards that carry a non-zero MV
        if abs(sec.base_mv_eur) >= 1.0:
            row["Market Value in Base Currency"] = _eu(sec.base_mv_eur * idio, 2)

    elif ac == "cash":
        # Cash drifts very slightly (overnight rate); keep it essentially flat.
        row["Market Value in Base Currency"] = _eu(sec.base_mv_eur * idio, 2)
        row["Quantity"] = _eu(sec.quantity * idio, 2)

    return row


def _reprice_market_row(sec: SynthSecurity, reg: Regime, fetch_date_iso: str) -> Optional[dict]:
    """Return a repriced market-data row (ADV/spread evolve with the regime)."""
    if sec.mkt is None:
        return None
    m = dict(sec.mkt)
    m["fetch_date"] = fetch_date_iso
    if sec.base_adv is not None:
        m["adv_30d_eur"] = f"{sec.base_adv * reg.adv_mult:.0f}"
    if sec.base_spread_bps is not None:
        # spreads widen when the credit-spread regime widens / liquidity thins
        widen = 1.0 + 0.5 * (reg.spread_mult - 1.0) + 0.5 * (1.0 / reg.adv_mult - 1.0)
        m["bid_ask_spread_bps"] = f"{max(0.1, sec.base_spread_bps * widen):.2f}"
    return m


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_timeseries(
    output_dir: str | Path = None,
    start_date: str = None,
    end_date: str = None,
    freq: str = "daily",
    seed: int = 42,
    n_portfolios: int = 7,
    stress_window: tuple[str, str] | None = None,
) -> Path:
    """Generate a historical time series of synthetic input files.

    Parameters
    ----------
    output_dir : where to write the ``history/`` series (default: data/history).
    start_date, end_date : 'DD.MM.YYYY'. Default: a 60-business-day window
        ending today.
    freq : 'daily' | 'weekly' | 'monthly'.
    seed : reproducibility seed.
    n_portfolios : how many synthetic portfolios (max 7).
    stress_window : optional ('DD.MM.YYYY','DD.MM.YYYY') sub-range over which a
        drawdown / spread-widening / liquidity-thinning regime is applied, so
        the series contains a crisis the stress & redemption engines can bite on.

    Returns the output directory (``.../history``).
    """
    if output_dir is None:
        output_dir = Path(__file__).parent / "history"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Default window: 60 business days ending today.
    if end_date is None:
        end_d = date.today()
    else:
        end_d = datetime.strptime(end_date, "%d.%m.%Y").date()
    if start_date is None:
        start_d = end_d - timedelta(days=int(60 * 7 / 5) + 5)
    else:
        start_d = datetime.strptime(start_date, "%d.%m.%Y").date()

    days = _business_days(start_d, end_d, freq=freq)
    if not days:
        raise ValueError("No business days in the requested range.")

    portfolios = PORTFOLIOS[: max(1, min(n_portfolios, len(PORTFOLIOS)))]
    base_report_date = days[0].strftime("%d.%m.%Y")

    # Stress sub-window as a set of dates.
    stress_dates: set[date] = set()
    if stress_window:
        s0 = datetime.strptime(stress_window[0], "%d.%m.%Y").date()
        s1 = datetime.strptime(stress_window[1], "%d.%m.%Y").date()
        stress_dates = {d for d in days if s0 <= d <= s1}

    print(f"\nGenerating historical time series -> {output_dir}")
    print(f"  Range      : {days[0]}  ->  {days[-1]}  ({len(days)} obs, freq={freq})")
    print(f"  Portfolios : {portfolios}")
    print(f"  Seed       : {seed}")
    if stress_dates:
        print(f"  Stress     : {min(stress_dates)} -> {max(stress_dates)} ({len(stress_dates)} obs)")
    print()

    # Bootstrap the persistent universe from the base generator.
    base._seed(seed)
    universe, _ = _build_universe(output_dir, portfolios, base_report_date)

    # Independent RNG for the time-series walk (don't disturb base determinism).
    rng = random.Random(seed ^ 0x51F5)

    # Per-portfolio regime + per-security idiosyncratic walk state.
    regimes: dict[str, Regime] = {p: Regime() for p in portfolios}
    idio_state: dict[str, float] = {}  # key portfolio|isin -> cumulative idio multiplier
    for p in portfolios:
        for sec in universe[p]:
            idio_state[f"{p}|{sec.isin}"] = 1.0

    nav_rows: list[dict] = []
    manifest: dict = {
        "seed": seed,
        "freq": freq,
        "start": days[0].isoformat(),
        "end": days[-1].isoformat(),
        "portfolios": portfolios,
        "stress_window": [min(stress_dates).isoformat(), max(stress_dates).isoformat()] if stress_dates else None,
        "snapshots": [],
    }

    prev_nav: dict[str, float] = {}

    for step, d in enumerate(days):
        ddmmyyyy = d.strftime("%d.%m.%Y")
        iso = d.strftime("%Y-%m-%d")
        ts = d.strftime("%Y%m%d") + f"{step:06d}"[-6:]  # unique, date-ordered
        stressed = d in stress_dates

        holdings_rows: list[dict] = []
        mkt_rows: list[dict] = []

        for p in portfolios:
            reg = regimes[p]
            if step > 0:
                reg = _step_regime(reg, rng, stressed)
                regimes[p] = reg

            for sec in universe[p]:
                key = f"{p}|{sec.isin}"
                # advance idiosyncratic component (mean-reverting-ish light noise)
                if step > 0 and sec.asset_class in _PRICE_DRIVEN | _DERIVATIVE | {"cash"}:
                    vol = 0.012 if sec.asset_class in ("listed_equity", "leveraged_equity", "etf") else 0.004
                    if sec.asset_class == "cash":
                        vol = 0.0005
                    idio_state[key] *= (1.0 + rng.gauss(0.0, vol))
                idio = idio_state[key]

                holdings_rows.append(_reprice_row(sec, reg, idio, ddmmyyyy))
                mr = _reprice_market_row(sec, reg, iso)
                if mr is not None:
                    mkt_rows.append(mr)

        # ---- write per-date holdings file ----
        h_path = output_dir / f"HOLDINGS_{ts}.csv"
        with h_path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=HOLDINGS_COLUMNS, delimiter=";")
            w.writeheader()
            w.writerows(holdings_rows)

        # ---- write per-date market-data file ----
        m_path = output_dir / f"market_data_ALL_{iso}.csv"
        with m_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=MARKET_DATA_COLUMNS)
            w.writeheader()
            w.writerows(mkt_rows)
        # empty errors file per date (schema parity with the base generator)
        e_path = output_dir / f"market_data_ERRORS_{iso}.csv"
        with e_path.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=MARKET_ERRORS_COLUMNS).writeheader()

        # ---- compute NAV per portfolio (loader rules: skip |MV|<1, sum by ISIN) ----
        nav_by_p: dict[str, dict[str, float]] = {p: {} for p in portfolios}
        for r in holdings_rows:
            pcode = r["Portfolio Code"]
            isin = r["ISIN"].strip()
            mv = _eu_float(r["Market Value in Base Currency"])
            if abs(mv) < 1.0:
                continue
            nav_by_p[pcode][isin] = nav_by_p[pcode].get(isin, 0.0) + mv

        for p in portfolios:
            nav = sum(nav_by_p[p].values())
            # Subscriptions / redemptions: realistic flows relative to NAV.
            base_redem = 0.006 if not (stressed) else 0.02
            subs = round(rng.uniform(0, abs(nav) * 0.003), 2)
            redms = round(rng.uniform(0, abs(nav) * base_redem), 2)
            nav_rows.append({
                "PortfolioCode": p,
                "Date": ddmmyyyy,
                "TotalAssets": _eu(nav, 2),
                "Subscriptions": _eu(subs, 2),
                "Redemptions": _eu(redms, 2),
                "NetCashFlows": _eu(subs - redms, 2),
            })
            prev_nav[p] = nav

        manifest["snapshots"].append({
            "date": iso,
            "holdings": h_path.name,
            "market_data": m_path.name,
            "market_errors": e_path.name,
            "stressed": stressed,
            "nav": {p: round(sum(nav_by_p[p].values()), 2) for p in portfolios},
        })

    # ---- write consolidated NAV file ----
    nav_path = output_dir / "NAV.csv"
    with nav_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=NAV_COLUMNS, delimiter=";",
                           quoting=csv.QUOTE_NONE, escapechar="\\")
        w.writeheader()
        w.writerows(nav_rows)

    # ---- reuse base generator for date-invariant artefacts ----
    base.generate_zero_coupon_yields(output_path=output_dir / "zero_coupon_yields.xlsx")
    base.generate_annex_iv_meta(output_path=output_dir / "annex_iv_meta.json", portfolios=portfolios)

    with (output_dir / "manifest.json").open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"  NAV      -> {nav_path}  ({len(nav_rows)} rows)")
    print(f"  Snapshots-> {len(days)} holdings + market-data file pairs")
    print(f"  Manifest -> {output_dir / 'manifest.json'}")
    print(f"\nDone. Time series written to: {output_dir.resolve()}")
    return output_dir


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Generate a synthetic HISTORICAL TIME SERIES for the "
                    "liquidity risk tool. All values are synthetic."
    )
    ap.add_argument("--output-dir", "-o", default=None, help="Output dir (default: data/history)")
    ap.add_argument("--start", default=None, help="Start date DD.MM.YYYY (default: 60 business days before end)")
    ap.add_argument("--end", default=None, help="End date DD.MM.YYYY (default: today)")
    ap.add_argument("--freq", "-f", default="daily", choices=["daily", "weekly", "monthly"])
    ap.add_argument("--seed", "-s", type=int, default=42)
    ap.add_argument("--portfolios", "-p", type=int, default=7)
    ap.add_argument("--stress-start", default=None, help="Stress window start DD.MM.YYYY (optional)")
    ap.add_argument("--stress-end", default=None, help="Stress window end DD.MM.YYYY (optional)")
    args = ap.parse_args()

    sw = None
    if args.stress_start and args.stress_end:
        sw = (args.stress_start, args.stress_end)

    generate_timeseries(
        output_dir=args.output_dir,
        start_date=args.start,
        end_date=args.end,
        freq=args.freq,
        seed=args.seed,
        n_portfolios=args.portfolios,
        stress_window=sw,
    )
