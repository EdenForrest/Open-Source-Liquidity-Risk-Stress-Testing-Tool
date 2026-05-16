"""
Report Builder
--------------
Assembles the full risk report as:
  * Console-formatted summary (print)
  * Excel workbook (multi-sheet)
  * JSON export (for downstream systems / API)
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

from .risk_metrics import RiskMetricsBuilder, LiquidityMetrics
from ..models.position import Portfolio
from ..config.settings import STRESS_SCENARIOS


class ReportBuilder:

    def __init__(self, portfolio: Portfolio, output_dir: str = "output"):
        self.portfolio   = portfolio
        self.output_dir  = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._builder    = RiskMetricsBuilder(portfolio)
        self._report: Optional[dict] = None

    def build(self) -> "ReportBuilder":
        self._report = self._builder.build_full_report()
        self._run_id = self._generate_run_id()
        return self

    def _generate_run_id(self) -> str:
        """SHA-256 fingerprint of portfolio positions + scenario config for audit trail."""
        positions_repr = sorted([
            f"{p.isin}:{p.market_value}:{p.asset_class}" for p in self.portfolio.positions
        ])
        scenarios_repr = [
            f"{s.name}:{s.equity_shock}:{s.credit_spread_shock_bps}:{s.liquidity_haircut_multiplier}"
            for s in STRESS_SCENARIOS
        ]
        payload = json.dumps({"positions": positions_repr, "scenarios": scenarios_repr}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def print_summary(self) -> None:
        self._check_built()
        lm: LiquidityMetrics = self._report["liquidity_metrics"]
        stress: pd.DataFrame = self._report["stress_summary"]
        redeem: pd.DataFrame = self._report["redemption_summary"]

        sep = "=" * 72
        run_id_short = self._run_id[:16] if hasattr(self, "_run_id") else "N/A"
        print(f"\n{sep}")
        print(f"  LIQUIDITY RISK REPORT — {lm.fund_name}")
        print(f"  Reporting Date : {lm.reporting_date}")
        print(f"  Total NAV      : EUR {lm.total_nav_eur:>14,.0f}")
        print(f"  Run ID         : {run_id_short}…")
        print(sep)

        # ── Liquidity Ladder ─────────────────────────────────────────
        print("\n  LIQUIDITY BUCKET BREAKDOWN")
        print(f"  {'Bucket':<12} {'Realisable (EUR)':>18} {'% NAV':>8} {'Cumulative':>12}")
        print(f"  {'-'*55}")
        for _, row in lm.bucket_breakdown.iterrows():
            print(
                f"  {row['bucket']:<12} "
                f"EUR {row['realisable_value_eur']:>14,.0f}  "
                f"{row['nav_pct']*100:>6.1f}%  "
                f"{row['cumulative_nav_pct']*100:>10.1f}%"
            )

        # ── Coverage Ratios ──────────────────────────────────────────
        print(f"\n  COVERAGE RATIOS (Normal Regime)")
        print(f"  {'LCR T+1:':<30} {lm.lcr_t1*100:>6.1f}%")
        print(f"  {'LCR T+3:':<30} {lm.lcr_t3*100:>6.1f}%")
        print(f"  {'LCR T+7:':<30} {lm.lcr_t7*100:>6.1f}%")
        print(f"  {'Illiquid (>T+7):':<30} {lm.illiquid_pct*100:>6.1f}%")

        # ── Time-to-Liquidate ────────────────────────────────────────
        print(f"\n  TIME-TO-LIQUIDATE")
        print(f"  {'50% of NAV:':<30} {lm.days_to_50pct:>6.1f} days")
        print(f"  {'75% of NAV:':<30} {lm.days_to_75pct:>6.1f} days")
        print(f"  {'90% of NAV:':<30} {lm.days_to_90pct:>6.1f} days")

        # ── Concentration ────────────────────────────────────────────
        print(f"\n  CONCENTRATION & REDEMPTION RISK")
        print(f"  {'Top-10 investor concentration:':<30} {lm.top10_concentration*100:>6.1f}%")
        print(f"  {'T+1 liquid / top-10 exposure:':<30} {lm.liquidity_vs_concentration:>6.2f}x")

        # ── Regulatory Flags ─────────────────────────────────────────
        print(f"\n  REGULATORY FLAGS")
        w = "YES ⚠" if lm.warning_flag else "No"
        b = "YES 🚨" if lm.breach_flag  else "No"
        print(f"  {'Liquidity Warning (<10% T0+T1):':<35} {w}")
        print(f"  {'Liquidity Breach  (<5%  T0+T1):':<35} {b}")

        # ── Stress Test Summary ──────────────────────────────────────
        print(f"\n  STRESS TEST RESULTS")
        cols = ["scenario_name", "nav_impact_pct", "liquid_pct_after",
                "time_to_liquidate_days", "can_meet_redemption"]
        sub = stress[cols].copy()
        sub["nav_impact_pct"]    = (sub["nav_impact_pct"] * 100).round(2)
        sub["liquid_pct_after"]  = (sub["liquid_pct_after"] * 100).round(1)
        sub.columns = ["Scenario", "NAV Chg%", "Liquid%", "Days-to-liq", "MeetRedemption"]
        print(sub.to_string(index=False))

        # ── Redemption Summary ───────────────────────────────────────
        print(f"\n  REDEMPTION SCENARIO ANALYSIS (Normal | Stress)")
        normal = redeem[redeem["regime"] == "normal"][[
            "scenario_pct", "redemption_eur", "can_meet_t1", "can_meet_t7",
            "gate_triggered", "days_to_clear"
        ]].copy()
        normal["scenario_pct"] = (normal["scenario_pct"] * 100).astype(int).astype(str) + "%"
        normal["redemption_eur"] = normal["redemption_eur"].apply(lambda x: f"EUR {x:,.0f}")
        print(normal.to_string(index=False))
        print(sep + "\n")

    def to_excel(self, filename: str = "liquidity_risk_report.xlsx") -> Path:
        self._check_built()
        path = self.output_dir / filename
        lm: LiquidityMetrics = self._report["liquidity_metrics"]

        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            # Sheet 1: Summary KPIs
            kpi_data = {
                "Metric": [
                    "Fund Name", "Reporting Date", "Total NAV (EUR)",
                    "LCR T+1", "LCR T+3", "LCR T+7", "Illiquid >T+7",
                    "Days to Liquidate 50%", "Days to Liquidate 75%", "Days to Liquidate 90%",
                    "Top-10 Investor Concentration", "Liquidity / Concentration Ratio",
                    "Warning Flag", "Breach Flag",
                ],
                "Value": [
                    lm.fund_name, lm.reporting_date, f"{lm.total_nav_eur:,.0f}",
                    f"{lm.lcr_t1*100:.1f}%", f"{lm.lcr_t3*100:.1f}%", f"{lm.lcr_t7*100:.1f}%",
                    f"{lm.illiquid_pct*100:.1f}%",
                    f"{lm.days_to_50pct:.1f}", f"{lm.days_to_75pct:.1f}", f"{lm.days_to_90pct:.1f}",
                    f"{lm.top10_concentration*100:.1f}%",
                    f"{lm.liquidity_vs_concentration:.2f}x",
                    str(lm.warning_flag), str(lm.breach_flag),
                ],
            }
            pd.DataFrame(kpi_data).to_excel(writer, sheet_name="Summary KPIs", index=False)

            # Sheet 2: Liquidity Ladder
            lm.bucket_breakdown.to_excel(writer, sheet_name="Liquidity Ladder", index=False)

            # Sheet 3: Stress Tests
            self._report["stress_summary"].to_excel(writer, sheet_name="Stress Tests", index=False)

            # Sheet 4: Redemption Analysis
            self._report["redemption_summary"].to_excel(writer, sheet_name="Redemption Analysis", index=False)

            # Sheet 5: ESMA Template (MMFR Art.28 / UCITS / AIFMD field codes A.1–E.6)
            self._build_esma_template(lm).to_excel(writer, sheet_name="ESMA_Template", index=False)

            # Sheet 6: Scenario Metadata (governance & calibration)
            pd.DataFrame([asdict(s) for s in STRESS_SCENARIOS]).to_excel(
                writer, sheet_name="Scenario_Metadata", index=False
            )

        print(f"  Report saved: {path}")
        return path

    def _build_esma_template(self, lm: "LiquidityMetrics") -> pd.DataFrame:
        """Build ESMA MMFR Art.28 / UCITS template with field codes A.1–E.6."""
        stress_df: pd.DataFrame = self._report["stress_summary"]
        worst = stress_df.iloc[-1] if not stress_df.empty else {}

        rows = [
            # A — Fund identification
            ("A.1", "Fund Name",                     lm.fund_name),
            ("A.2", "Fund ID (LEI/ISIN)",            self.portfolio.fund_id),
            ("A.3", "Reporting Date",                str(lm.reporting_date)),
            ("A.4", "Base Currency",                 self.portfolio.base_currency),
            ("A.5", "Total NAV (EUR)",               f"{lm.total_nav_eur:,.0f}"),
            ("A.6", "Run Fingerprint (SHA-256)",     getattr(self, "_run_id", "N/A")),
            # B — Liquidity Coverage Ratios
            ("B.1", "LCR T+0/T+1 (Normal)",         f"{lm.lcr_t1*100:.2f}%"),
            ("B.2", "LCR T+3 (Normal)",              f"{lm.lcr_t3*100:.2f}%"),
            ("B.3", "LCR T+7 (Normal)",              f"{lm.lcr_t7*100:.2f}%"),
            ("B.4", "Illiquid Fraction >T+7",        f"{lm.illiquid_pct*100:.2f}%"),
            ("B.5", "Warning Flag (<10% T0+T1)",     str(lm.warning_flag)),
            ("B.6", "Breach Flag (<5% T0+T1)",       str(lm.breach_flag)),
            # C — Concentration
            ("C.1", "Top-10 Investor Concentration", f"{lm.top10_concentration*100:.1f}%"),
            ("C.2", "Liquidity / Concentration Ratio", f"{lm.liquidity_vs_concentration:.2f}x"),
            ("C.3", "Positions Flagged (>5% NAV)",   str(
                (self._report.get("position_buckets", pd.DataFrame())
                 .get("concentration_flag", pd.Series(dtype=bool)).sum()
                 if "position_buckets" in self._report else "N/A")
            )),
            # D — Liquidation speed
            ("D.1", "Days to Liquidate 50% NAV",    f"{lm.days_to_50pct:.1f}"),
            ("D.2", "Days to Liquidate 75% NAV",    f"{lm.days_to_75pct:.1f}"),
            ("D.3", "Days to Liquidate 90% NAV",    f"{lm.days_to_90pct:.1f}"),
            # E — Stress summary
            ("E.1", "Worst Scenario Name",          worst.get("scenario_name", "N/A")),
            ("E.2", "Worst Scenario NAV Impact %",  f"{worst.get('nav_impact_pct', 0)*100:.2f}%" if worst.get("nav_impact_pct") is not None else "N/A"),
            ("E.3", "Worst Liquid % After Stress",  f"{worst.get('liquid_pct_after', 0)*100:.2f}%" if worst.get("liquid_pct_after") is not None else "N/A"),
            ("E.4", "Worst Days to Liquidate",      f"{worst.get('time_to_liquidate_days', 'N/A')}"),
            ("E.5", "Worst Redemption Coverable",   str(worst.get("can_meet_redemption", "N/A"))),
            ("E.6", "Number of Stress Scenarios",   str(len(STRESS_SCENARIOS))),
        ]
        return pd.DataFrame(rows, columns=["Code", "Field", "Value"])

    def to_json(self, filename: str = "liquidity_risk_report.json") -> Path:
        self._check_built()
        path = self.output_dir / filename
        lm: LiquidityMetrics = self._report["liquidity_metrics"]

        payload = {
            "fund":              lm.fund_name,
            "reporting_date":    lm.reporting_date,
            "total_nav_eur":     lm.total_nav_eur,
            "run_id":            getattr(self, "_run_id", None),
            "scenario_metadata": [asdict(s) for s in STRESS_SCENARIOS],
            "liquidity_metrics": lm.summary(),
            "stress_results":    self._report["stress_summary"].to_dict(orient="records"),
            "redemption_results": self._report["redemption_summary"].to_dict(orient="records"),
        }

        # Make JSON-serialisable
        def default_serialiser(obj):
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating, float)):
                return None if np.isnan(obj) or np.isinf(obj) else float(obj)
            if isinstance(obj, (np.bool_,)):
                return bool(obj)
            if isinstance(obj, pd.DataFrame):
                return obj.to_dict(orient="records")
            raise TypeError(f"Object of type {type(obj)} not serialisable")

        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=default_serialiser)

        print(f"  JSON saved: {path}")
        return path

    def _check_built(self):
        if self._report is None:
            raise RuntimeError("Call .build() before exporting.")
