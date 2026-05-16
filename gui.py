"""
gui.py — Liquidity Risk & Stress Testing Tool — GUI
-----------------------------------------------------
Tkinter-based dashboard with seven tabs:
  0. Overview       — Cross-portfolio liquidity snapshot, all funds at a glance
  1. Dashboard      — KPIs, liquidity ladder, regulatory flags
  2. Stress Tests   — Per-scenario NAV/liquidity/redemption table + scenario config panel
  3. Redemption     — Coverage matrix across 4 scenarios × 2 regimes
  4. Waterfall      — Day-by-day forced sell-down schedule
  5. Charts         — Embedded matplotlib figures
  6. Risk Story     — Auto-generated narrative risk summary

Run:
    python gui.py
"""
from __future__ import annotations

import math
import sys
import traceback
import threading
import warnings
from pathlib import Path
from typing import Optional

warnings.filterwarnings("ignore", category=FutureWarning)
sys.path.insert(0, str(Path(__file__).parent))

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from liquidity_risk_tool.models    import (
    load_portfolio_from_csv, build_sample_portfolio,
    enrich_portfolio_from_market_data, available_portfolio_codes,
)
from liquidity_risk_tool.engines   import (
    LiquidityProfiler, RedemptionSimulator,
    WaterfallEngine, StressEngine,
)
from liquidity_risk_tool.config    import STRESS_SCENARIOS, BUCKET_ORDER
from liquidity_risk_tool.config.settings import REDEMPTION_STRESS_ADV_SCALAR, MAX_ADV_PARTICIPATION
from liquidity_risk_tool.reporting import ReportBuilder
from liquidity_risk_tool.reporting.risk_metrics import RiskMetricsBuilder

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
CLR_BG        = "#0f1117"   # near-black background
CLR_SURFACE   = "#1a1d27"   # card/panel background
CLR_BORDER    = "#2a2d3e"   # subtle borders
CLR_ACCENT    = "#4f8ef7"   # primary blue
CLR_ACCENT2   = "#7c5cbf"   # purple accent
CLR_TEXT      = "#e8eaf0"   # primary text
CLR_MUTED     = "#8b92a8"   # secondary text
CLR_GREEN     = "#3ecf8e"   # positive / OK
CLR_YELLOW    = "#f5a623"   # warning
CLR_RED       = "#e35b5b"   # breach / error
CLR_HEADER_BG = "#12141f"   # table header background

FONT_FAMILY  = "Segoe UI"
FONT_TITLE   = (FONT_FAMILY, 13, "bold")
FONT_SUBTITLE= (FONT_FAMILY, 10, "bold")
FONT_BODY    = (FONT_FAMILY, 9)
FONT_MONO    = ("Consolas", 9)
FONT_KPI     = (FONT_FAMILY, 20, "bold")
FONT_KPI_LBL = (FONT_FAMILY, 8)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_eur(v: float) -> str:
    return f"EUR {v:,.0f}"

def _fmt_pct(v: float) -> str:
    return f"{v*100:.1f}%"

def _fmt_days(v: float) -> str:
    if math.isinf(v) or math.isnan(v):
        return ">60 days (illiquid tail)"
    return f"{v:.1f} days"

def _status_color(ok: bool) -> str:
    return CLR_GREEN if ok else CLR_RED

def _flag_color(flagged: bool, critical: bool = False) -> str:
    if flagged and critical:
        return CLR_RED
    if flagged:
        return CLR_YELLOW
    return CLR_GREEN


# ---------------------------------------------------------------------------
# Styled widget helpers
# ---------------------------------------------------------------------------

def _label(parent, text, font=FONT_BODY, fg=CLR_TEXT, bg=None, **kw):
    return tk.Label(parent, text=text, font=font, fg=fg,
                    bg=bg or parent["bg"], **kw)

def _frame(parent, bg=CLR_SURFACE, relief="flat", bd=0, **kw):
    return tk.Frame(parent, bg=bg, relief=relief, bd=bd, **kw)

def _separator(parent, orient="horizontal"):
    s = ttk.Separator(parent, orient=orient)
    return s

def _card_frame(parent, **kw):
    return _frame(parent, highlightbackground=CLR_BORDER, highlightthickness=1, **kw)

def _build_tab_header(parent, title: str, subtitle: str) -> None:
    _label(parent, title, font=FONT_TITLE, fg=CLR_TEXT).pack(anchor="w")
    _label(parent, subtitle, font=FONT_BODY, fg=CLR_MUTED).pack(anchor="w", pady=(2, 0))

def _make_scrollable_table(parent, cols, col_widths, height=12):
    """Return (DataTable, vsb, hsb) pre-wired with grid layout inside parent."""
    tbl = DataTable(parent, cols, col_widths, height=height)
    vsb = ttk.Scrollbar(parent, orient="vertical",   command=tbl.yview)
    hsb = ttk.Scrollbar(parent, orient="horizontal", command=tbl.xview)
    tbl.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    tbl.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="ew")
    parent.grid_rowconfigure(0, weight=1)
    parent.grid_columnconfigure(0, weight=1)
    return tbl, vsb, hsb


# ---------------------------------------------------------------------------
# Scrollable frame
# ---------------------------------------------------------------------------

class ScrollFrame(tk.Frame):
    def __init__(self, parent, bg=CLR_BG, **kw):
        super().__init__(parent, bg=bg, **kw)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical",
                                        command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.inner.bind("<Configure>", self._on_inner_config)
        self.canvas.bind("<Configure>", self._on_canvas_config)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_inner_config(self, _e):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_config(self, e):
        self.canvas.itemconfig(self._win, width=e.width)

    def _on_mousewheel(self, e):
        self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")


# ---------------------------------------------------------------------------
# KPI Card
# ---------------------------------------------------------------------------

class KPICard(tk.Frame):
    def __init__(self, parent, label: str, value: str, color: str = CLR_ACCENT,
                 subtext: str = "", **kw):
        super().__init__(parent, bg=CLR_SURFACE, relief="flat", bd=0,
                         highlightbackground=CLR_BORDER, highlightthickness=1, **kw)
        self.configure(padx=16, pady=12)

        tk.Label(self, text=label, font=FONT_KPI_LBL, fg=CLR_MUTED,
                 bg=CLR_SURFACE).pack(anchor="w")
        self.val_lbl = tk.Label(self, text=value, font=FONT_KPI, fg=color,
                                bg=CLR_SURFACE)
        self.val_lbl.pack(anchor="w", pady=(2, 0))
        if subtext:
            tk.Label(self, text=subtext, font=FONT_KPI_LBL, fg=CLR_MUTED,
                     bg=CLR_SURFACE).pack(anchor="w", pady=(2, 0))

    def update(self, value: str, color: str = CLR_ACCENT):
        self.val_lbl.config(text=value, fg=color)


# ---------------------------------------------------------------------------
# Styled Treeview (data table)
# ---------------------------------------------------------------------------

class DataTable(ttk.Treeview):
    def __init__(self, parent, columns: list[str], col_widths: dict = None,
                 height: int = 10, **kw):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Dark.Treeview",
                        background=CLR_SURFACE,
                        foreground=CLR_TEXT,
                        fieldbackground=CLR_SURFACE,
                        rowheight=24,
                        font=FONT_MONO,
                        bordercolor=CLR_BORDER,
                        relief="flat")
        style.configure("Dark.Treeview.Heading",
                        background=CLR_HEADER_BG,
                        foreground=CLR_MUTED,
                        font=(FONT_FAMILY, 8, "bold"),
                        relief="flat",
                        bordercolor=CLR_BORDER)
        style.map("Dark.Treeview",
                  background=[("selected", CLR_ACCENT2)],
                  foreground=[("selected", CLR_TEXT)])

        super().__init__(parent, columns=columns, show="headings",
                         style="Dark.Treeview", height=height, **kw)

        col_widths = col_widths or {}
        for col in columns:
            w = col_widths.get(col, 120)
            self.heading(col, text=col)
            self.column(col, width=w, anchor="center", stretch=True)

        # alternating row colours
        self.tag_configure("odd",  background="#1e2130")
        self.tag_configure("even", background=CLR_SURFACE)
        self.tag_configure("warn", background="#3a2e0f", foreground=CLR_YELLOW)
        self.tag_configure("bad",  background="#2e0f0f", foreground=CLR_RED)
        self.tag_configure("good", background="#0f2e1e", foreground=CLR_GREEN)

    def load_df(self, df: pd.DataFrame, tag_col: str = None,
                tag_map: dict = None):
        for row in self.get_children():
            self.delete(row)
        for i, (_, row) in enumerate(df.iterrows()):
            vals = list(row)
            base_tag = "even" if i % 2 == 0 else "odd"
            tag = base_tag
            if tag_col and tag_map:
                cell = row.get(tag_col)
                for key, t in tag_map.items():
                    if str(cell) == str(key):
                        tag = t
                        break
            self.insert("", "end", values=vals, tags=(tag,))


# ---------------------------------------------------------------------------
# Tab: Overview (cross-portfolio summary)
# ---------------------------------------------------------------------------

class OverviewTab(tk.Frame):
    def __init__(self, parent, app: "App"):
        super().__init__(parent, bg=CLR_BG)
        self.app = app
        self._build()

    def _build(self):
        top = _frame(self, bg=CLR_BG)
        top.pack(fill="x", padx=20, pady=(16, 0))
        _label(top, "Portfolio Overview", font=FONT_TITLE,
               fg=CLR_TEXT, bg=CLR_BG).pack(side="left")
        _label(top, "Cross-portfolio liquidity snapshot — all funds at a glance",
               font=FONT_BODY, fg=CLR_MUTED, bg=CLR_BG).pack(
               side="left", padx=(12, 0), pady=(4, 0))

        # Aggregate KPI row
        self.kpi_frame = _frame(self, bg=CLR_BG)
        self.kpi_frame.pack(fill="x", padx=20, pady=(12, 0))
        self.kpi_funds   = KPICard(self.kpi_frame, "Portfolios",   "—", CLR_ACCENT)
        self.kpi_nav     = KPICard(self.kpi_frame, "Combined NAV", "—", CLR_TEXT)
        self.kpi_avg_lcr = KPICard(self.kpi_frame, "Avg LCR T+1",  "—", CLR_ACCENT2)
        self.kpi_warn    = KPICard(self.kpi_frame, "Warnings",     "—", CLR_YELLOW)
        self.kpi_breach  = KPICard(self.kpi_frame, "Breaches",     "—", CLR_RED)
        for w in (self.kpi_funds, self.kpi_nav, self.kpi_avg_lcr,
                  self.kpi_warn, self.kpi_breach):
            w.pack(side="left", padx=(0, 10), pady=4, ipadx=4, ipady=4)

        # Comparison table
        card = _frame(self, bg=CLR_SURFACE,
                      highlightbackground=CLR_BORDER, highlightthickness=1)
        card.pack(fill="both", expand=True, padx=20, pady=(12, 4))
        _label(card, "All Portfolios — Key Liquidity Metrics",
               font=FONT_SUBTITLE, fg=CLR_TEXT, bg=CLR_SURFACE).pack(
               anchor="w", padx=12, pady=(10, 4))

        cols = ["Fund ID", "Fund Name", "NAV (EUR)", "LCR T+1",
                "LCR T+3", "LCR T+7", "Illiquid%",
                "Days→50% NAV", "Top-10 Conc", "Liq/Conc", "Status"]
        cw = {c: 105 for c in cols}
        cw["Fund Name"] = 200
        cw["Fund ID"]   = 90
        cw["Status"]    = 80

        tbl_frame = _frame(card, bg=CLR_SURFACE)
        tbl_frame.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        tbl_frame.rowconfigure(0, weight=1)
        tbl_frame.columnconfigure(0, weight=1)
        self.tbl = DataTable(tbl_frame, cols, cw, height=14)
        vsb = ttk.Scrollbar(tbl_frame, orient="vertical",   command=self.tbl.yview)
        hsb = ttk.Scrollbar(tbl_frame, orient="horizontal", command=self.tbl.xview)
        self.tbl.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tbl.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.tbl.bind("<Double-1>", self._on_row_dbl_click)

        _label(card, "Double-click a row to load that portfolio in the detail tabs.",
               font=(FONT_FAMILY, 7), fg=CLR_MUTED, bg=CLR_SURFACE).pack(
               anchor="w", padx=12, pady=(2, 8))

    def _on_row_dbl_click(self, event):
        sel = self.tbl.selection()
        if not sel:
            return
        fund_id = self.tbl.item(sel[0], "values")[0]
        self.app._portfolio_var.set(str(fund_id))
        self.app._on_portfolio_selected()

    def populate(self, rows: list):
        n = len(rows)
        if n == 0:
            return
        total_nav = sum(r["nav"]    for r in rows)
        n_warn    = sum(1 for r in rows if r["warning"])
        n_breach  = sum(1 for r in rows if r["breach"])
        avg_lcr   = sum(r["lcr_t1"] for r in rows) / n

        self.kpi_funds.update(str(n), CLR_ACCENT)
        self.kpi_nav.update(_fmt_eur(total_nav), CLR_TEXT)
        self.kpi_avg_lcr.update(_fmt_pct(avg_lcr),
                                 CLR_GREEN if avg_lcr > 0.15 else CLR_YELLOW)
        self.kpi_warn.update(str(n_warn),
                              CLR_YELLOW if n_warn > 0 else CLR_GREEN)
        self.kpi_breach.update(str(n_breach),
                                CLR_RED if n_breach > 0 else CLR_GREEN)

        tbl_rows = []
        for r in rows:
            status = "BREACH" if r["breach"] else ("WARN" if r["warning"] else "OK")
            tbl_rows.append({
                "Fund ID":      r["fund_id"],
                "Fund Name":    r["fund_name"],
                "NAV (EUR)":    f"{r['nav']:>14,.0f}",
                "LCR T+1":      f"{r['lcr_t1']*100:.1f}%",
                "LCR T+3":      f"{r['lcr_t3']*100:.1f}%",
                "LCR T+7":      f"{r['lcr_t7']*100:.1f}%",
                "Illiquid%":    f"{r['illiquid_pct']*100:.1f}%",
                "Days→50% NAV": _fmt_days(r["days_to_50pct"]),
                "Top-10 Conc":  f"{r['top10_conc']*100:.1f}%",
                "Liq/Conc":     f"{r['liq_conc']:.2f}x",
                "Status":       status,
            })

        df = pd.DataFrame(tbl_rows)
        self.tbl.load_df(df, tag_col="Status",
                         tag_map={"BREACH": "bad", "WARN": "warn", "OK": "good"})


# ---------------------------------------------------------------------------
# Tab: Dashboard
# ---------------------------------------------------------------------------

class DashboardTab(tk.Frame):
    def __init__(self, parent, app: "App"):
        super().__init__(parent, bg=CLR_BG)
        self.app = app
        self._build()

    def _build(self):
        # Title bar
        top = _frame(self, bg=CLR_BG)
        top.pack(fill="x", padx=20, pady=(16, 0))
        _label(top, "Dashboard", font=FONT_TITLE, fg=CLR_TEXT, bg=CLR_BG).pack(side="left")
        _label(top, "Normal-regime liquidity overview", font=FONT_BODY,
               fg=CLR_MUTED, bg=CLR_BG).pack(side="left", padx=(12, 0), pady=(4, 0))

        # KPI row
        self.kpi_frame = _frame(self, bg=CLR_BG)
        self.kpi_frame.pack(fill="x", padx=20, pady=(12, 0))

        self.kpi_lcr_t1   = KPICard(self.kpi_frame, "LCR T+1",  "—",  CLR_ACCENT)
        self.kpi_lcr_t3   = KPICard(self.kpi_frame, "LCR T+3",  "—",  CLR_ACCENT)
        self.kpi_lcr_t7   = KPICard(self.kpi_frame, "LCR T+7",  "—",  CLR_ACCENT)
        self.kpi_illiquid = KPICard(self.kpi_frame, "Illiquid >T+7", "—", CLR_YELLOW)
        self.kpi_nav      = KPICard(self.kpi_frame, "Total NAV", "—",  CLR_TEXT)
        self.kpi_conc     = KPICard(self.kpi_frame, "Liq / Conc Ratio", "—", CLR_ACCENT2)

        for w in (self.kpi_lcr_t1, self.kpi_lcr_t3, self.kpi_lcr_t7,
                  self.kpi_illiquid, self.kpi_nav, self.kpi_conc):
            w.pack(side="left", padx=(0, 10), pady=4, ipadx=4, ipady=4)

        # Main content: ladder + flags side by side
        content = _frame(self, bg=CLR_BG)
        content.pack(fill="both", expand=True, padx=20, pady=12)
        content.columnconfigure(0, weight=3)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(0, weight=1)

        # Liquidity Ladder table
        left = _frame(content, bg=CLR_SURFACE,
                      highlightbackground=CLR_BORDER, highlightthickness=1)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        _label(left, "Liquidity Ladder", font=FONT_SUBTITLE,
               fg=CLR_TEXT, bg=CLR_SURFACE).pack(anchor="w", padx=12, pady=(10, 4))

        cols = ["Bucket", "Market Value (EUR)", "Realisable (EUR)", "% NAV", "Cumulative %", "Stressed %", "Stressed Cumul."]
        cw   = {"Bucket": 70, "Market Value (EUR)": 145, "Realisable (EUR)": 145, "% NAV": 65, "Cumulative %": 85, "Stressed %": 75, "Stressed Cumul.": 95}
        self.ladder_tbl = DataTable(left, cols, cw, height=6)
        self.ladder_tbl.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        # Portfolio position table
        pos_frame = _frame(content, bg=CLR_SURFACE,
                           highlightbackground=CLR_BORDER, highlightthickness=1)
        pos_frame.grid(row=0, column=1, sticky="nsew")
        _label(pos_frame, "Regulatory Flags & Metrics", font=FONT_SUBTITLE,
               fg=CLR_TEXT, bg=CLR_SURFACE).pack(anchor="w", padx=12, pady=(10, 4))
        self.flags_frame = _frame(pos_frame, bg=CLR_SURFACE)
        self.flags_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        # Positions table (full width, below)
        bot = _frame(self, bg=CLR_SURFACE,
                     highlightbackground=CLR_BORDER, highlightthickness=1)
        bot.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        _label(bot, "Portfolio Positions", font=FONT_SUBTITLE,
               fg=CLR_TEXT, bg=CLR_SURFACE).pack(anchor="w", padx=12, pady=(10, 4))

        pos_cols = ["ISIN", "Name", "Asset Class", "Mkt Value (EUR)", "Weight%",
                    "Bucket", "Haircut%", "Realisable (EUR)", "Days-to-Liq"]
        pos_cw   = {c: 120 for c in pos_cols}
        pos_cw["Name"] = 200
        self.pos_tbl = DataTable(bot, pos_cols, pos_cw, height=8)
        vsb = ttk.Scrollbar(bot, orient="vertical", command=self.pos_tbl.yview)
        hsb = ttk.Scrollbar(bot, orient="horizontal", command=self.pos_tbl.xview)
        self.pos_tbl.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.pos_tbl.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 8))
        vsb.pack(side="right", fill="y", pady=(0, 8))

    def populate(self, data: dict):
        lm = data["liquidity_metrics"]

        # KPIs
        self.kpi_lcr_t1.update(_fmt_pct(lm.lcr_t1),
                                CLR_GREEN if lm.lcr_t1 > 0.15 else CLR_YELLOW)
        self.kpi_lcr_t3.update(_fmt_pct(lm.lcr_t3), CLR_ACCENT)
        self.kpi_lcr_t7.update(_fmt_pct(lm.lcr_t7), CLR_ACCENT)
        self.kpi_illiquid.update(_fmt_pct(lm.illiquid_pct),
                                  CLR_RED if lm.illiquid_pct > 0.15 else CLR_YELLOW)
        self.kpi_nav.update(_fmt_eur(lm.total_nav_eur), CLR_TEXT)
        self.kpi_conc.update(f"{lm.liquidity_vs_concentration:.2f}x",
                              CLR_GREEN if lm.liquidity_vs_concentration >= 1 else CLR_RED)

        # Ladder — merge normal + stressed so both % columns appear side-by-side
        ld_n = data["ladder_normal"].copy()
        ld_s = (
            data["ladder_stress"][["bucket", "nav_pct", "cumulative_nav_pct"]]
            .copy()
            .rename(columns={"nav_pct": "s_nav_pct", "cumulative_nav_pct": "s_cumul_pct"})
        )
        ld = ld_n.merge(ld_s, on="bucket", how="left")
        rows = []
        for _, r in ld.iterrows():
            rows.append({
                "Bucket":              r["bucket"],
                "Market Value (EUR)":  f"{r['market_value_eur']:>14,.0f}",
                "Realisable (EUR)":    f"{r['realisable_value_eur']:>14,.0f}",
                "% NAV":               f"{r['nav_pct']*100:.1f}%",
                "Cumulative %":        f"{r['cumulative_nav_pct']*100:.1f}%",
                "Stressed %":          f"{r['s_nav_pct']*100:.1f}%" if pd.notna(r.get("s_nav_pct")) else "—",
                "Stressed Cumul.":     f"{r['s_cumul_pct']*100:.1f}%" if pd.notna(r.get("s_cumul_pct")) else "—",
            })
        self.ladder_tbl.load_df(pd.DataFrame(rows))

        # Flags
        for w in self.flags_frame.winfo_children():
            w.destroy()

        items = [
            ("Fund Name",          lm.fund_name,                             CLR_TEXT,   False),
            ("Reporting Date",     lm.reporting_date,                        CLR_TEXT,   False),
            ("T+0+T+1 Liquid",     _fmt_pct(lm.liquid_T0_T1_pct),           CLR_MUTED,  False),
            ("Days to 50% NAV",    _fmt_days(lm.days_to_50pct),              CLR_MUTED,  False),
            ("Days to 75% NAV",    _fmt_days(lm.days_to_75pct),              CLR_MUTED,  False),
            ("Days to 90% NAV",    _fmt_days(lm.days_to_90pct),              CLR_MUTED,  False),
            ("Top-10 Concentration", _fmt_pct(lm.top10_concentration),      CLR_MUTED,  False),
            ("Liquidity Warning",  "YES" if lm.warning_flag else "No",
                _flag_color(lm.warning_flag, critical=False), lm.warning_flag),
            ("Liquidity Breach",   "YES" if lm.breach_flag  else "No",
                _flag_color(lm.breach_flag,  critical=True),  lm.breach_flag),
        ]

        for row_i, (k, v, color, _bold) in enumerate(items):
            row_frame = _frame(self.flags_frame, bg=CLR_SURFACE)
            row_frame.pack(fill="x", pady=2)
            _label(row_frame, k, font=FONT_BODY, fg=CLR_MUTED,
                   bg=CLR_SURFACE, width=26, anchor="w").pack(side="left")
            _label(row_frame, v, font=(FONT_FAMILY, 9, "bold"), fg=color,
                   bg=CLR_SURFACE).pack(side="left")

        # Positions
        pos_df = data["position_buckets"]
        rows = []
        for _, r in pos_df.iterrows():
            rows.append({
                "ISIN":              r.get("isin", ""),
                "Name":              r.get("name", ""),
                "Asset Class":       r.get("asset_class", ""),
                "Mkt Value (EUR)":   f"{r.get('market_value_eur', 0):,.0f}",
                "Weight%":           f"{r.get('weight', 0)*100:.1f}%",
                "Bucket":            r.get("bucket", ""),
                "Haircut%":          f"{r.get('haircut', 0)*100:.1f}%",
                "Realisable (EUR)":  f"{r.get('realisable_value', 0):,.0f}",
                "Days-to-Liq":       f"{r.get('days_to_liquidate', 0):.1f}",
            })
        self.pos_tbl.load_df(pd.DataFrame(rows))


# ---------------------------------------------------------------------------
# Tab: Stress Tests
# ---------------------------------------------------------------------------

class StressTab(tk.Frame):
    def __init__(self, parent, app: "App"):
        super().__init__(parent, bg=CLR_BG)
        self.app = app
        self._build()

    def _build(self):
        top = _frame(self, bg=CLR_BG)
        top.pack(fill="x", padx=20, pady=(16, 4))
        _label(top, "Stress Test Results", font=FONT_TITLE,
               fg=CLR_TEXT, bg=CLR_BG).pack(side="left")
        _label(top, "ESMA-style scenarios applied to portfolio", font=FONT_BODY,
               fg=CLR_MUTED, bg=CLR_BG).pack(side="left", padx=(12, 0), pady=(4, 0))

        # Stress KPI cards
        self.kpi_row = _frame(self, bg=CLR_BG)
        self.kpi_row.pack(fill="x", padx=20, pady=(0, 10))
        self.kpi_worst_nav = KPICard(self.kpi_row, "Worst NAV Impact", "—", CLR_RED)
        self.kpi_worst_liq = KPICard(self.kpi_row, "Worst Liquidity After", "—", CLR_YELLOW)
        self.kpi_max_days  = KPICard(self.kpi_row, "Max Days to Liquidate", "—", CLR_ACCENT)
        self.kpi_scenarios_met = KPICard(self.kpi_row, "Redemptions Met", "— / 6", CLR_GREEN)
        for w in (self.kpi_worst_nav, self.kpi_worst_liq, self.kpi_max_days, self.kpi_scenarios_met):
            w.pack(side="left", padx=(0, 10), pady=4)

        # Stress results table
        card = _frame(self, bg=CLR_SURFACE,
                      highlightbackground=CLR_BORDER, highlightthickness=1)
        card.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        _label(card, "Per-Scenario Results", font=FONT_SUBTITLE,
               fg=CLR_TEXT, bg=CLR_SURFACE).pack(anchor="w", padx=12, pady=(10, 4))

        cols = ["Scenario", "NAV Before (EUR)", "NAV After (EUR)", "NAV Δ%",
                "Equity Loss (EUR)", "Credit Loss (EUR)",
                "Liquid% Before", "Liquid% After",
                "Days-to-Liq", "Can Meet Redemption"]
        cw = {c: 130 for c in cols}
        cw["Scenario"] = 200
        tbl_frame = _frame(card, bg=CLR_SURFACE)
        tbl_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        tbl_frame.rowconfigure(0, weight=1)
        tbl_frame.columnconfigure(0, weight=1)
        self.tbl = DataTable(tbl_frame, cols, cw, height=8)
        vsb = ttk.Scrollbar(tbl_frame, orient="vertical",   command=self.tbl.yview)
        hsb = ttk.Scrollbar(tbl_frame, orient="horizontal", command=self.tbl.xview)
        self.tbl.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tbl.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, columnspan=2, sticky="ew")

        # Scenario governance / config panel
        cfg_card = _frame(self, bg=CLR_SURFACE,
                          highlightbackground=CLR_BORDER, highlightthickness=1)
        cfg_card.pack(fill="x", padx=20, pady=(0, 16))
        _label(cfg_card, "Scenario Governance — Calibration & Regulatory Basis",
               font=FONT_SUBTITLE, fg=CLR_TEXT, bg=CLR_SURFACE).pack(
               anchor="w", padx=12, pady=(10, 4))

        cfg_cols = ["Scenario", "Equity Shock", "Spread +bps", "Rate +bps",
                    "ADV Scalar", "Haircut Mult", "Redemption%",
                    "Version", "Worst Case", "Regulatory Basis"]
        cfg_cw = {c: 110 for c in cfg_cols}
        cfg_cw["Scenario"] = 190
        cfg_cw["Regulatory Basis"] = 260
        cfg_cw["Version"] = 65
        cfg_cw["Worst Case"] = 80
        self.cfg_tbl = DataTable(cfg_card, cfg_cols, cfg_cw, height=6)
        cfg_hsb = ttk.Scrollbar(cfg_card, orient="horizontal",
                                 command=self.cfg_tbl.xview)
        self.cfg_tbl.configure(xscrollcommand=cfg_hsb.set)
        self.cfg_tbl.pack(fill="x", padx=8, pady=(0, 0))
        cfg_hsb.pack(fill="x", padx=8, pady=(0, 8))

        # Populate scenario config table immediately (static data)
        self._populate_cfg_tbl()

    def _populate_cfg_tbl(self):
        rows = []
        for s in STRESS_SCENARIOS:
            rows.append({
                "Scenario":        s.name,
                "Equity Shock":    f"{s.equity_shock*100:+.0f}%",
                "Spread +bps":     str(s.credit_spread_shock_bps),
                "Rate +bps":       str(getattr(s, "rate_shock_bps", 0)),
                "ADV Scalar":      f"{getattr(s, 'adv_stress_scalar', 1.0):.2f}x",
                "Haircut Mult":    f"{s.liquidity_haircut_multiplier:.2f}x",
                "Redemption%":     f"{s.redemption_rate*100:.0f}%",
                "Version":         getattr(s, "version", "1.0"),
                "Worst Case":      "YES" if getattr(s, "is_worst_case", False) else "No",
                "Regulatory Basis": getattr(s, "regulatory_basis", ""),
            })
        df = pd.DataFrame(rows)
        self.cfg_tbl.load_df(df, tag_col="Worst Case", tag_map={"YES": "warn"})

    def populate(self, data: dict):
        stress_df = data["stress_summary"]

        nav_impacts = stress_df["nav_impact_pct"].values
        liq_afters  = stress_df["liquid_pct_after"].values
        days_liq    = stress_df["time_to_liquidate_days"].values
        met_count   = stress_df["can_meet_redemption"].sum()

        self.kpi_worst_nav.update(f"{min(nav_impacts)*100:.1f}%", CLR_RED)
        self.kpi_worst_liq.update(f"{min(liq_afters)*100:.1f}%", CLR_YELLOW)
        self.kpi_max_days.update(f"{max(days_liq):.0f} days", CLR_ACCENT)
        self.kpi_scenarios_met.update(
            f"{met_count} / {len(stress_df)}",
            CLR_GREEN if met_count == len(stress_df) else CLR_RED
        )

        rows = []
        for _, r in stress_df.iterrows():
            met = r["can_meet_redemption"]
            rows.append({
                "Scenario":          r["scenario_name"],
                "NAV Before (EUR)":  f"{r['nav_before']:,.0f}",
                "NAV After (EUR)":   f"{r['nav_after_shock']:,.0f}",
                "NAV Δ%":            f"{r['nav_impact_pct']*100:+.2f}%",
                "Equity Loss (EUR)": f"{r.get('equity_loss_eur', 0):,.0f}",
                "Credit Loss (EUR)": f"{r.get('credit_loss_eur', 0):,.0f}",
                "Liquid% Before":    f"{r['liquid_pct_before']*100:.1f}%",
                "Liquid% After":     f"{r['liquid_pct_after']*100:.1f}%",
                "Days-to-Liq":       _fmt_days(r['time_to_liquidate_days']),
                "Can Meet Redemption": "YES" if met else "NO",
            })

        df = pd.DataFrame(rows)
        self.tbl.load_df(df, tag_col="Can Meet Redemption",
                         tag_map={"YES": "good", "NO": "bad"})


# ---------------------------------------------------------------------------
# Tab: Redemption Analysis
# ---------------------------------------------------------------------------

class RedemptionTab(tk.Frame):
    def __init__(self, parent, app: "App"):
        super().__init__(parent, bg=CLR_BG)
        self.app = app
        self._build()

    def _build(self):
        top = _frame(self, bg=CLR_BG)
        top.pack(fill="x", padx=20, pady=(16, 4))
        _label(top, "Redemption Scenario Analysis", font=FONT_TITLE,
               fg=CLR_TEXT, bg=CLR_BG).pack(side="left")
        _label(top, "5% / 10% / 20% / 30% NAV — Normal & Stress regimes",
               font=FONT_BODY, fg=CLR_MUTED, bg=CLR_BG).pack(side="left",
               padx=(12, 0), pady=(4, 0))

        # Normal
        n_card = _frame(self, bg=CLR_SURFACE,
                        highlightbackground=CLR_BORDER, highlightthickness=1)
        n_card.pack(fill="both", expand=True, padx=20, pady=(8, 6))
        _label(n_card, "Normal Regime", font=FONT_SUBTITLE, fg=CLR_GREEN,
               bg=CLR_SURFACE).pack(anchor="w", padx=12, pady=(10, 4))

        n_cols = ["Scenario%", "Redemption (EUR)", "Can Meet T+1", "Can Meet T+3",
                  "Can Meet T+7", "Shortfall (EUR)", "Gate Triggered",
                  "Suspension Triggered", "Days to Clear"]
        n_cw = {c: 130 for c in n_cols}
        n_cw["Redemption (EUR)"] = 160
        self.n_tbl = DataTable(n_card, n_cols, n_cw, height=5)
        self.n_tbl.pack(fill="x", padx=8, pady=(0, 10))

        # Stress
        s_card = _frame(self, bg=CLR_SURFACE,
                        highlightbackground=CLR_BORDER, highlightthickness=1)
        s_card.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        _label(s_card, "Stress Regime", font=FONT_SUBTITLE, fg=CLR_RED,
               bg=CLR_SURFACE).pack(anchor="w", padx=12, pady=(10, 4))
        self.s_tbl = DataTable(s_card, n_cols, n_cw, height=5)
        self.s_tbl.pack(fill="x", padx=8, pady=(0, 10))

    def _tbl_rows(self, df: pd.DataFrame) -> list[dict]:
        rows = []
        for _, r in df.iterrows():
            tag = "good" if r["can_meet_t7"] else ("warn" if r["gate_triggered"] else "bad")
            rows.append({
                "Scenario%":          f"{int(r['scenario_pct']*100)}%",
                "Redemption (EUR)":   f"{r['redemption_eur']:,.0f}",
                "Can Meet T+1":       "YES" if r["can_meet_t1"] else "NO",
                "Can Meet T+3":       "YES" if r["can_meet_t3"] else "NO",
                "Can Meet T+7":       "YES" if r["can_meet_t7"] else "NO",
                "Shortfall (EUR)":    f"{r.get('shortfall_eur', 0):,.0f}",
                "Gate Triggered":     "YES" if r["gate_triggered"] else "No",
                "Suspension Triggered": "YES" if r["suspension_triggered"] else "No",
                "Days to Clear":      f"{r['days_to_clear']:.1f}",
                "_tag":               tag,
            })
        return rows

    def populate(self, data: dict):
        redeem = data["redemption_summary"]
        normal = redeem[redeem["regime"] == "normal"]
        stress = redeem[redeem["regime"] == "stress"]

        for tbl, df_src in [(self.n_tbl, normal), (self.s_tbl, stress)]:
            rows = pd.DataFrame(self._tbl_rows(df_src))
            tbl.load_df(rows, tag_col="_tag",
                        tag_map={"good": "good", "warn": "warn", "bad": "bad"})


# ---------------------------------------------------------------------------
# Tab: Waterfall
# ---------------------------------------------------------------------------

class WaterfallTab(tk.Frame):
    def __init__(self, parent, app: "App"):
        super().__init__(parent, bg=CLR_BG)
        self.app = app
        self._build()

    def _build(self):
        top = _frame(self, bg=CLR_BG)
        top.pack(fill="x", padx=20, pady=(16, 4))
        _label(top, "Liquidation Waterfall", font=FONT_TITLE,
               fg=CLR_TEXT, bg=CLR_BG).pack(side="left")
        _label(top, "30% NAV — Severe Combined stress, most-liquid-first sell-down",
               font=FONT_BODY, fg=CLR_MUTED, bg=CLR_BG).pack(side="left",
               padx=(12, 0), pady=(4, 0))

        # Summary KPIs
        self.kpi_row = _frame(self, bg=CLR_BG)
        self.kpi_row.pack(fill="x", padx=20, pady=(0, 10))
        self.kpi_target   = KPICard(self.kpi_row, "Target Cash", "—", CLR_TEXT)
        self.kpi_raised   = KPICard(self.kpi_row, "Total Raised", "—", CLR_GREEN)
        self.kpi_met      = KPICard(self.kpi_row, "Target Met", "—", CLR_GREEN)
        self.kpi_days     = KPICard(self.kpi_row, "Days Needed", "—", CLR_ACCENT)
        self.kpi_shortfall= KPICard(self.kpi_row, "Residual Shortfall", "—", CLR_RED)
        for w in (self.kpi_target, self.kpi_raised, self.kpi_met,
                  self.kpi_days, self.kpi_shortfall):
            w.pack(side="left", padx=(0, 10), pady=4)

        # Sell schedule table
        card = _frame(self, bg=CLR_SURFACE,
                      highlightbackground=CLR_BORDER, highlightthickness=1)
        card.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        _label(card, "Sell Schedule (Day-by-Day)", font=FONT_SUBTITLE,
               fg=CLR_TEXT, bg=CLR_SURFACE).pack(anchor="w", padx=12, pady=(10, 4))

        cols = ["Day", "ISIN", "Name", "Asset Class", "Bucket",
                "Gross (EUR)", "Mkt Impact (EUR)", "Net Proceeds (EUR)", "Partial?"]
        cw = {c: 120 for c in cols}
        cw["Name"] = 180
        cw["Day"] = 50
        tbl_frame = _frame(card, bg=CLR_SURFACE)
        tbl_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        tbl_frame.rowconfigure(0, weight=1)
        tbl_frame.columnconfigure(0, weight=1)
        self.tbl = DataTable(tbl_frame, cols, cw, height=14)
        vsb = ttk.Scrollbar(tbl_frame, orient="vertical",   command=self.tbl.yview)
        hsb = ttk.Scrollbar(tbl_frame, orient="horizontal", command=self.tbl.xview)
        self.tbl.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tbl.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, columnspan=2, sticky="ew")

    def populate(self, data: dict):
        wf = data["waterfall"]

        self.kpi_target.update(_fmt_eur(wf.target_eur), CLR_TEXT)
        self.kpi_raised.update(_fmt_eur(wf.total_proceeds_eur),
                                CLR_GREEN if wf.target_met else CLR_YELLOW)
        self.kpi_met.update("YES" if wf.target_met else "NO",
                             CLR_GREEN if wf.target_met else CLR_RED)
        self.kpi_days.update(f"{wf.days_to_target:.1f}", CLR_ACCENT)
        self.kpi_shortfall.update(
            _fmt_eur(wf.residual_shortfall_eur),
            CLR_GREEN if wf.residual_shortfall_eur == 0 else CLR_RED
        )

        sell_df = wf.sell_schedule_df()
        if sell_df.empty:
            return

        rows = []
        for _, r in sell_df.iterrows():
            rows.append({
                "Day":             str(int(r.get("day", 0))),
                "ISIN":            r.get("isin", ""),
                "Name":            r.get("name", ""),
                "Asset Class":     r.get("asset_class", ""),
                "Bucket":          r.get("bucket", ""),
                "Gross (EUR)":     f"{r.get('gross_value_eur', 0):,.0f}",
                "Mkt Impact (EUR)":f"{r.get('market_impact_eur', 0):,.0f}",
                "Net Proceeds (EUR)": f"{r.get('net_proceeds_eur', 0):,.0f}",
                "Partial?":        "Yes" if r.get("is_partial") else "No",
            })

        self.tbl.load_df(pd.DataFrame(rows))


# ---------------------------------------------------------------------------
# Tab: Charts
# ---------------------------------------------------------------------------

class ChartsTab(tk.Frame):
    def __init__(self, parent, app: "App"):
        super().__init__(parent, bg=CLR_BG)
        self.app = app
        self._canvases: list[FigureCanvasTkAgg] = []
        self._build()

    def _build(self):
        top = _frame(self, bg=CLR_BG)
        top.pack(fill="x", padx=20, pady=(16, 4))
        _label(top, "Charts", font=FONT_TITLE, fg=CLR_TEXT, bg=CLR_BG).pack(side="left")

        # Chart selector + display area
        ctrl = _frame(self, bg=CLR_BG)
        ctrl.pack(fill="x", padx=20, pady=(0, 8))

        _label(ctrl, "Select chart:", font=FONT_BODY, fg=CLR_MUTED, bg=CLR_BG).pack(side="left")
        self.chart_var = tk.StringVar(value="Liquidity Ladder")
        self.chart_names = [
            "Liquidity Ladder",
            "Portfolio Composition",
            "Stress NAV Impact",
            "Redemption Heatmap",
            "Time-to-Liquidate",
            "Waterfall Schedule",
        ]
        cb = ttk.Combobox(ctrl, textvariable=self.chart_var,
                          values=self.chart_names, state="readonly", width=28)
        cb.pack(side="left", padx=8)
        cb.bind("<<ComboboxSelected>>", lambda _: self._show_selected())

        save_btn = tk.Button(ctrl, text="Save as PNG", font=FONT_BODY,
                             bg=CLR_ACCENT, fg=CLR_TEXT, relief="flat",
                             padx=12, pady=4, cursor="hand2",
                             command=self._save_chart)
        save_btn.pack(side="left", padx=8)

        # Chart display area
        self.chart_area = _frame(self, bg=CLR_BG)
        self.chart_area.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        self._figures: dict[str, plt.Figure] = {}

    def populate(self, data: dict):
        for c in self._canvases:
            c.get_tk_widget().destroy()
        self._canvases.clear()
        self._figures.clear()

        plt.rcParams.update({
            "figure.facecolor":  CLR_SURFACE,
            "axes.facecolor":    CLR_SURFACE,
            "axes.edgecolor":    CLR_BORDER,
            "axes.labelcolor":   CLR_MUTED,
            "xtick.color":       CLR_MUTED,
            "ytick.color":       CLR_MUTED,
            "text.color":        CLR_TEXT,
            "grid.color":        CLR_BORDER,
            "grid.linewidth":    0.6,
            "font.family":       "sans-serif",
            "font.size":         9,
        })

        for name, builder in [
            ("Liquidity Ladder",      self._fig_ladder),
            ("Portfolio Composition", self._fig_composition),
            ("Stress NAV Impact",     self._fig_stress_nav),
            ("Redemption Heatmap",    self._fig_redemption_heatmap),
            ("Time-to-Liquidate",     self._fig_time_to_liq),
            ("Waterfall Schedule",    self._fig_waterfall),
        ]:
            try:
                self._figures[name] = builder(data)
            except Exception as _e:
                fig, ax = plt.subplots(figsize=(8, 4))
                fig.patch.set_facecolor(CLR_SURFACE)
                ax.set_facecolor(CLR_SURFACE)
                ax.text(0.5, 0.5,
                        f"Could not render '{name}':\n{_e}\n\n{traceback.format_exc()}",
                        ha="center", va="center", transform=ax.transAxes,
                        color="#e74c3c", fontsize=8, wrap=True,
                        family="monospace")
                ax.axis("off")
                self._figures[name] = fig

        self._show_selected()

    def _show_selected(self):
        for w in self.chart_area.winfo_children():
            w.destroy()

        name = self.chart_var.get()
        fig  = self._figures.get(name)
        if fig is None:
            return

        canvas = FigureCanvasTkAgg(fig, master=self.chart_area)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

        toolbar_frame = _frame(self.chart_area, bg=CLR_BG)
        toolbar_frame.pack(fill="x")
        NavigationToolbar2Tk(canvas, toolbar_frame)
        self._canvases.append(canvas)

    def _save_chart(self):
        name = self.chart_var.get()
        fig  = self._figures.get(name)
        if fig is None:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG Image", "*.png"), ("All Files", "*.*")],
            initialfile=name.lower().replace(" ", "_") + ".png",
        )
        if path:
            fig.savefig(path, dpi=150, bbox_inches="tight")
            messagebox.showinfo("Saved", f"Chart saved to:\n{path}")

    # ── Individual figure builders ──────────────────────────────────────

    def _fig_ladder(self, data: dict) -> plt.Figure:
        ld_n = data["ladder_normal"]
        ld_s = data["ladder_stress"]
        buckets = ld_n["bucket"].tolist()
        x = range(len(buckets))

        fig, ax = plt.subplots(figsize=(9, 4.5))
        w = 0.35
        bars_n = ax.bar([i - w/2 for i in x], ld_n["nav_pct"]*100, width=w,
                         label="Normal", color=CLR_ACCENT, alpha=0.85)
        bars_s = ax.bar([i + w/2 for i in x], ld_s["nav_pct"]*100, width=w,
                         label="Stress", color=CLR_RED, alpha=0.75)
        ax.set_xticks(list(x))
        ax.set_xticklabels(buckets)
        ax.set_ylabel("% NAV")
        ax.set_title("Liquidity Ladder — Normal vs Stress", pad=12)
        ax.legend(facecolor=CLR_SURFACE, edgecolor=CLR_BORDER)
        ax.grid(axis="y", linestyle="--", alpha=0.4)
        for bar in bars_n:
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                    f"{bar.get_height():.1f}%", ha="center", va="bottom",
                    fontsize=7.5, color=CLR_TEXT)
        for bar in bars_s:
            if bar.get_height() > 0:
                ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                        f"{bar.get_height():.1f}%", ha="center", va="bottom",
                        fontsize=7.5, color=CLR_RED)
        fig.tight_layout()
        return fig

    def _fig_composition(self, data: dict) -> plt.Figure:
        pos = data["position_buckets"]
        by_class = (pos.groupby("asset_class")["market_value_eur"]
                       .sum().sort_values(ascending=False))
        total = by_class.sum()
        pcts = by_class / total * 100

        colors = plt.cm.tab20.colors
        fig, ax = plt.subplots(figsize=(8, 5))
        wedges, texts, autotexts = ax.pie(
            pcts, labels=None, autopct=lambda p: f"{p:.1f}%" if p > 2 else "",
            colors=colors[:len(pcts)], startangle=90,
            wedgeprops={"linewidth": 0.5, "edgecolor": CLR_BORDER},
            pctdistance=0.80,
        )
        for t in autotexts:
            t.set_fontsize(7.5)
            t.set_color(CLR_BG)
        ax.legend(wedges, by_class.index.tolist(),
                  loc="center left", bbox_to_anchor=(1, 0.5),
                  facecolor=CLR_SURFACE, edgecolor=CLR_BORDER, fontsize=8)
        ax.set_title("Portfolio Composition by Asset Class", pad=12)
        fig.tight_layout()
        return fig

    def _fig_stress_nav(self, data: dict) -> plt.Figure:
        stress = data["stress_summary"]
        names  = stress["scenario_name"].tolist()
        impacts = (stress["nav_impact_pct"] * 100).tolist()
        colors = [CLR_RED if v < 0 else CLR_GREEN for v in impacts]

        fig, ax = plt.subplots(figsize=(9, 4.5))
        bars = ax.bar(names, impacts, color=colors, alpha=0.82, edgecolor=CLR_BORDER)
        ax.axhline(0, color=CLR_MUTED, linewidth=0.8)
        ax.set_ylabel("NAV Change (%)")
        ax.set_title("Stress Test — NAV Impact by Scenario", pad=12)
        ax.set_xticks(range(len(names)))
        ax.set_xticklabels(names, rotation=20, ha="right")
        ax.grid(axis="y", linestyle="--", alpha=0.4)
        for bar in bars:
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2,
                    h + (0.1 if h >= 0 else -0.3),
                    f"{h:+.1f}%", ha="center", va="bottom", fontsize=7.5, color=CLR_TEXT)
        fig.tight_layout()
        return fig

    def _fig_redemption_heatmap(self, data: dict) -> plt.Figure:
        redeem = data["redemption_summary"]
        scenarios = ["5%", "10%", "20%", "30%"]
        horizons  = ["T+1", "T+3", "T+7"]
        regimes   = ["normal", "stress"]

        fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
        for ax, regime in zip(axes, regimes):
            sub = redeem[redeem["regime"] == regime].copy()
            sub = sub.sort_values("scenario_pct")
            mat = np.zeros((len(scenarios), len(horizons)))
            for i, row in enumerate(sub.itertuples()):
                mat[i, 0] = 1 if row.can_meet_t1 else 0
                mat[i, 1] = 1 if row.can_meet_t3 else 0
                mat[i, 2] = 1 if row.can_meet_t7 else 0

            cmap = mcolors.LinearSegmentedColormap.from_list(
                "rg", [CLR_RED, CLR_YELLOW, CLR_GREEN])
            im = ax.imshow(mat, aspect="auto", cmap=cmap, vmin=0, vmax=1)
            ax.set_xticks(range(3))
            ax.set_xticklabels(horizons)
            ax.set_yticks(range(4))
            ax.set_yticklabels(scenarios)
            ax.set_title(f"{regime.capitalize()} Regime", pad=8)
            for ii in range(len(scenarios)):
                for jj in range(len(horizons)):
                    ax.text(jj, ii, "✓" if mat[ii, jj] == 1 else "✗",
                            ha="center", va="center", fontsize=13,
                            color=CLR_BG if mat[ii, jj] else CLR_TEXT)
        fig.suptitle("Redemption Coverage Heatmap", y=1.02)
        fig.tight_layout()
        return fig

    def _fig_time_to_liq(self, data: dict) -> plt.Figure:
        pos = data["position_buckets"]
        nav = data["liquidity_metrics"].total_nav_eur

        # Use fractional days (MV / daily_cap) so positions spread across the x-axis
        # rather than clustering at integer ceil values.
        sellable = (
            pos[~pos["is_locked"] & (pos["adv_30d"] > 0)]
            .copy()
        )
        sellable["_frac_days"] = (
            sellable["market_value_eur"].abs()
            / (sellable["adv_30d"] * MAX_ADV_PARTICIPATION)
        )
        sellable = sellable.sort_values("_frac_days")

        days_pts = [0.0]
        cum_pts  = [0.0]
        cumulative = 0.0
        for _, row in sellable.iterrows():
            cumulative += row["realisable_value"]
            days_pts.append(row["_frac_days"])
            cum_pts.append(cumulative / nav * 100)

        # Illiquid tail: locked + zero-ADV positions
        illiquid_val = pos[pos["is_locked"] | (pos["adv_30d"] <= 0)]["realisable_value"].sum()
        if illiquid_val > 0:
            tail_day = (days_pts[-1] + 60) if len(days_pts) > 1 else 60
            days_pts.append(tail_day)
            cum_pts.append((cumulative + illiquid_val) / nav * 100)

        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.plot(days_pts, cum_pts, color=CLR_ACCENT, linewidth=2, marker="o", markersize=3)
        for pct_lvl, color in [(50, CLR_YELLOW), (75, CLR_ACCENT2), (90, CLR_RED)]:
            ax.axhline(pct_lvl, color=color, linestyle="--", linewidth=0.9,
                       label=f"{pct_lvl}%")
        ax.set_xlabel("Days")
        ax.set_ylabel("Cumulative % NAV Liquidated")
        ax.set_title("Time-to-Liquidate Curve", pad=12)
        ax.set_xlim(left=0)
        ax.set_ylim(0, 105)
        ax.legend(facecolor=CLR_SURFACE, edgecolor=CLR_BORDER)
        ax.grid(linestyle="--", alpha=0.4)
        fig.tight_layout()
        return fig

    def _fig_waterfall(self, data: dict) -> plt.Figure:
        wf = data["waterfall"]
        sell_df = wf.sell_schedule_df()
        if sell_df.empty:
            fig, ax = plt.subplots(figsize=(6, 3))
            ax.text(0.5, 0.5, "No sell orders", ha="center", va="center",
                    transform=ax.transAxes, color=CLR_MUTED)
            return fig

        by_day = (sell_df.groupby("day")["net_proceeds_eur"]
                          .sum().reset_index())
        by_day["cumulative"] = by_day["net_proceeds_eur"].cumsum()

        fig, ax1 = plt.subplots(figsize=(9, 4.5))
        ax2 = ax1.twinx()
        ax1.bar(by_day["day"], by_day["net_proceeds_eur"] / 1e6,
                color=CLR_ACCENT, alpha=0.75, label="Daily Proceeds")
        ax2.plot(by_day["day"], by_day["cumulative"] / 1e6,
                 color=CLR_GREEN, linewidth=2, marker="o", markersize=4,
                 label="Cumulative")
        ax1.set_xlabel("Day")
        ax1.set_ylabel("Daily Proceeds (EUR M)", color=CLR_ACCENT)
        ax2.set_ylabel("Cumulative (EUR M)",     color=CLR_GREEN)
        ax1.set_title("Waterfall Schedule — Daily & Cumulative Proceeds", pad=12)
        ax1.axhline(0, color=CLR_MUTED, linewidth=0.5)
        lines1, lbls1 = ax1.get_legend_handles_labels()
        lines2, lbls2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, lbls1 + lbls2,
                   facecolor=CLR_SURFACE, edgecolor=CLR_BORDER)
        fig.tight_layout()
        return fig


# ---------------------------------------------------------------------------
# Risk Story Tab (Tab 6)
# ---------------------------------------------------------------------------

class RiskStoryTab(tk.Frame):
    """Narrative risk summary — auto-generated prose from the pipeline results."""

    def __init__(self, parent, app: "App"):
        super().__init__(parent, bg=CLR_BG)
        self.app = app
        self._build()

    def _build(self):
        hdr = _frame(self, bg=CLR_BG)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        _label(hdr, "Risk Story", font=FONT_TITLE, fg=CLR_TEXT, bg=CLR_BG).pack(side="left")

        btn_frame = _frame(hdr, bg=CLR_BG)
        btn_frame.pack(side="right")
        tk.Button(
            btn_frame, text="Copy Text", font=FONT_BODY,
            bg=CLR_SURFACE, fg=CLR_TEXT, relief="flat", padx=10, pady=4,
            cursor="hand2", activebackground=CLR_BORDER, activeforeground=CLR_TEXT,
            command=self._copy_text,
        ).pack(side="right")

        _label(
            self,
            "Auto-generated narrative synthesising all pipeline outputs for management reporting.",
            font=FONT_BODY, fg=CLR_MUTED, bg=CLR_BG,
        ).pack(anchor="w", padx=20, pady=(0, 10))

        card = _frame(self, bg=CLR_SURFACE,
                      highlightbackground=CLR_BORDER, highlightthickness=1)
        card.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        self._text = tk.Text(
            card,
            font=(FONT_FAMILY, 9),
            bg=CLR_SURFACE, fg=CLR_TEXT,
            insertbackground=CLR_TEXT,
            relief="flat",
            wrap="word",
            state="disabled",
            padx=16, pady=14,
            spacing1=2, spacing3=4,
        )
        vsb = ttk.Scrollbar(card, orient="vertical", command=self._text.yview)
        self._text.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._text.pack(side="left", fill="both", expand=True)

        # placeholder
        self._set_text("Run the analysis pipeline to generate the Risk Story narrative.")

    def _set_text(self, content: str):
        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        self._text.insert("1.0", content)
        self._text.config(state="disabled")

    def _copy_text(self):
        content = self._text.get("1.0", "end").strip()
        self.clipboard_clear()
        self.clipboard_append(content)

    def populate(self, data: dict):
        self._set_text(self._build_narrative(data))

    @staticmethod
    def _build_narrative(data: dict) -> str:
        lm   = data["liquidity_metrics"]
        st   = data["stress_summary"]
        rd   = data["redemption_summary"]
        wf   = data["waterfall"]
        port = data["portfolio"]

        # ── Regulatory status ────────────────────────────────────────────
        if lm.breach_flag:
            reg_status = "BREACH — T0+T1 liquidity has fallen below the 5% regulatory floor."
        elif lm.warning_flag:
            reg_status = "WARNING — T0+T1 liquidity is below the 10% caution threshold."
        else:
            reg_status = "COMPLIANT — all liquidity thresholds are within regulatory limits."

        # ── Stress ───────────────────────────────────────────────────────
        if not st.empty:
            worst_row = st.loc[st["nav_impact_pct"].idxmin()]
            worst_name = worst_row["scenario_name"]
            worst_nav  = worst_row["nav_impact_pct"] * 100
            worst_liq  = worst_row["liquid_pct_after"] * 100
            worst_days = worst_row["time_to_liquidate_days"]
            worst_met  = worst_row["can_meet_redemption"]
            n_scenarios = len(st)
            n_pass = int(st["can_meet_redemption"].sum())
        else:
            worst_name = "N/A"; worst_nav = 0.0; worst_liq = 0.0
            worst_days = 0.0; worst_met = False
            n_scenarios = 0; n_pass = 0

        # ── Redemption ───────────────────────────────────────────────────
        normal_rd = rd[rd["regime"] == "normal"] if "regime" in rd.columns else rd
        if not normal_rd.empty:
            t7_pass = int(normal_rd["can_meet_t7"].sum())
            t7_total = len(normal_rd)
            gate_pct = int(normal_rd["gate_triggered"].sum() / t7_total * 100) if t7_total else 0
        else:
            t7_pass = t7_total = 0; gate_pct = 0

        # ── Waterfall ────────────────────────────────────────────────────
        wf_raised  = wf.total_proceeds_eur
        wf_target  = wf.target_eur
        wf_met     = wf.target_met
        wf_days    = wf.days_to_target
        wf_impact  = wf.nav_impact_pct * 100
        wf_short   = wf.residual_shortfall_eur

        narrative = f"""LIQUIDITY RISK STORY
Fund: {port.fund_name}  |  Reporting Date: {port.reporting_date.date()}
Total NAV: EUR {lm.total_nav_eur:,.0f}
════════════════════════════════════════════════════════════════════════

1. REGULATORY STATUS
Outcome: {reg_status}

The fund's T0+T1 liquidity coverage ratio stands at {lm.lcr_t1*100:.1f}% of NAV, with T+3 \
at {lm.lcr_t3*100:.1f}% and T+7 at {lm.lcr_t7*100:.1f}%. Illiquid assets (>T+7) represent \
{lm.illiquid_pct*100:.1f}% of NAV. The portfolio can liquidate 50% of NAV in {_fmt_days(lm.days_to_50pct)}, \
75% in {_fmt_days(lm.days_to_75pct)}, and 90% in {_fmt_days(lm.days_to_90pct)}.

2. STRESS TESTING ({n_scenarios} SCENARIOS)
The most severe scenario is "{worst_name}", which produces a NAV impact of {worst_nav:+.1f}% \
and reduces T0+T1 liquidity to {worst_liq:.1f}% of stressed NAV. Under this scenario, the fund \
requires {worst_days:.1f} days to execute the target liquidation. Redemption coverage is \
{"achievable" if worst_met else "NOT achievable"} in the worst case.

Across all {n_scenarios} scenarios, {n_pass} out of {n_scenarios} pass the redemption coverage test.

3. REDEMPTION COVERAGE
Under the normal liquidity regime, {t7_pass} of {t7_total} redemption scenarios can be met \
within T+7. Gate mechanisms would be triggered in approximately {gate_pct}% of tested scenarios.

Concentration risk: the top-10 investor pool represents {lm.top10_concentration*100:.1f}% of NAV. \
The liquidity-to-concentration ratio is {lm.liquidity_vs_concentration:.2f}x, \
{"indicating adequate coverage" if lm.liquidity_vs_concentration >= 1.0 else "indicating a potential concentration risk"}.

4. LIQUIDATION WATERFALL (30% NAV TARGET UNDER SEVERE STRESS)
Target:   EUR {wf_target:,.0f}
Raised:   EUR {wf_raised:,.0f}
Met:      {"YES" if wf_met else "NO — SHORTFALL of EUR " + f"{wf_short:,.0f}"}
Duration: {wf_days:.1f} days
NAV hit:  {wf_impact:.1f}%

{"The fund can fully meet the 30% NAV redemption target under severe stress conditions." if wf_met
  else f"The fund faces a residual shortfall of EUR {wf_short:,.0f} — management action may be required."}

5. MANAGEMENT IMPLICATIONS
{"• No immediate regulatory escalation required." if not lm.breach_flag and not lm.warning_flag
  else "• ESCALATION: Regulatory threshold breach — notify board and regulator per AIFMD Art.16 / UCITS Art.40."}
• Monitor illiquid sleeve ({lm.illiquid_pct*100:.1f}% of NAV) for deterioration in secondary-market conditions.
• Stress results are based on {n_scenarios} ESMA-calibrated scenarios; next scheduled review: see Scenario_Metadata sheet.
• Run ID for audit trail: {getattr(data.get("_run_id", None), "__str__", lambda: "see Excel report")()}

────────────────────────────────────────────────────────────────────────
Generated by LRI Liquidity Risk Tool v1.0  |  UCITS / AIFMD compliant
"""
        return narrative


# ---------------------------------------------------------------------------
# Status bar
# ---------------------------------------------------------------------------

class StatusBar(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=CLR_HEADER_BG, height=28)
        self.pack_propagate(False)
        self._msg = tk.StringVar(value="Ready")
        self._lbl = tk.Label(self, textvariable=self._msg, font=FONT_BODY,
                             fg=CLR_MUTED, bg=CLR_HEADER_BG, anchor="w", padx=12)
        self._lbl.pack(side="left", fill="both", expand=True)
        self._progress = ttk.Progressbar(self, mode="indeterminate", length=120)

    def set(self, msg: str, busy: bool = False):
        self._msg.set(msg)
        if busy:
            self._progress.pack(side="right", padx=8)
            self._progress.start(10)
        else:
            self._progress.stop()
            self._progress.pack_forget()


# ---------------------------------------------------------------------------
# Main Application
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Liquidity Risk & Stress Testing Tool  |  v1.0")
        self.geometry("1280x820")
        self.minsize(1100, 720)
        self.configure(bg=CLR_BG)

        self._data: Optional[dict] = None
        self._has_run = False
        self._rerun_btn: Optional[tk.Button] = None
        self._build_ui()
        self.after(200, self._run_analysis)

    def _build_ui(self):
        self._build_header()
        self._build_toolbar()
        self._build_file_bar()
        self._build_notebook()

    def _build_header(self):
        header = _frame(self, bg=CLR_HEADER_BG)
        header.pack(fill="x")
        _label(header, "  LRI", font=(FONT_FAMILY, 12, "bold"),
               fg=CLR_ACCENT, bg=CLR_HEADER_BG).pack(side="left", pady=8)
        _label(header, "Liquidity Risk & Stress Testing Tool",
               font=(FONT_FAMILY, 10), fg=CLR_TEXT,
               bg=CLR_HEADER_BG).pack(side="left", padx=8)
        _label(header, "Luxembourg ManCo  |  UCITS / AIFMD",
               font=(FONT_FAMILY, 8), fg=CLR_MUTED,
               bg=CLR_HEADER_BG).pack(side="left", padx=0)

    def _build_toolbar(self):
        toolbar = _frame(self, bg=CLR_BG)
        toolbar.pack(fill="x", padx=16, pady=(6, 0))

        self.run_btn = tk.Button(
            toolbar, text="▶  Run Analysis", font=(FONT_FAMILY, 9, "bold"),
            bg=CLR_ACCENT, fg="white", relief="flat", padx=16, pady=6,
            cursor="hand2", command=self._run_analysis,
            activebackground="#3a7de0", activeforeground="white",
        )
        self.run_btn.pack(side="left", padx=(0, 8))

        self.export_btn = tk.Button(
            toolbar, text="⬇  Export Excel + JSON", font=FONT_BODY,
            bg=CLR_SURFACE, fg=CLR_TEXT, relief="flat", padx=14, pady=6,
            cursor="hand2", command=self._export,
            activebackground=CLR_BORDER, activeforeground=CLR_TEXT,
            state="disabled",
        )
        self.export_btn.pack(side="left", padx=(0, 8))

        self.charts_btn = tk.Button(
            toolbar, text="🖼  Save All Charts", font=FONT_BODY,
            bg=CLR_SURFACE, fg=CLR_TEXT, relief="flat", padx=14, pady=6,
            cursor="hand2", command=self._save_all_charts,
            activebackground=CLR_BORDER, activeforeground=CLR_TEXT,
            state="disabled",
        )
        self.charts_btn.pack(side="left", padx=(0, 8))

        _frame(toolbar, bg=CLR_BORDER, width=1).pack(side="left", fill="y",
                                                      padx=(8, 8), pady=4)

        self.fund_lbl = _label(toolbar, "No data loaded", font=FONT_BODY,
                                fg=CLR_MUTED, bg=CLR_BG)
        self.fund_lbl.pack(side="right", padx=8)

    def _build_file_bar(self):
        file_bar = _frame(self, bg=CLR_BG)
        file_bar.pack(fill="x", padx=16, pady=(2, 0))

        self._mvhol_var = tk.StringVar(value="")
        self._nav_var   = tk.StringVar(value="")
        self._mkt_var   = tk.StringVar(value="")

        tk.Button(file_bar, text="Upload Files…", font=FONT_BODY,
                  bg=CLR_ACCENT, fg="#ffffff",
                  relief="flat", padx=10, pady=4, cursor="hand2",
                  command=self._pick_files).pack(side="left", padx=(0, 10))

        self._files_lbl = _label(file_bar, "No files selected",
                                  font=(FONT_FAMILY, 8), fg=CLR_MUTED, bg=CLR_BG)
        self._files_lbl.pack(side="left", padx=(0, 10))

        # Portfolio selector — hidden until files are loaded
        self._portfolio_bar = _frame(self, bg=CLR_BG)
        _label(self._portfolio_bar, "Portfolio:", font=FONT_BODY,
               fg=CLR_MUTED, bg=CLR_BG).pack(side="left")
        self._portfolio_var = tk.StringVar(value="")
        self._portfolio_cb = ttk.Combobox(self._portfolio_bar,
                                          textvariable=self._portfolio_var,
                                          state="readonly", width=20, font=FONT_BODY)
        self._portfolio_cb.pack(side="left", padx=(4, 10))
        self._portfolio_cb.bind("<<ComboboxSelected>>", self._on_portfolio_selected)

        _label(file_bar, "  (or leave blank to auto-detect from Desktop)",
               font=(FONT_FAMILY, 7), fg=CLR_MUTED, bg=CLR_BG).pack(side="left", padx=4)

        self._separator = _frame(self, bg=CLR_BORDER, height=1)
        self._separator.pack(fill="x")

    def _build_notebook(self):
        style = ttk.Style()
        style.configure("Dark.TNotebook",
                        background=CLR_BG, tabmargins=[2, 4, 0, 0])
        style.configure("Dark.TNotebook.Tab",
                        background=CLR_SURFACE, foreground=CLR_MUTED,
                        font=(FONT_FAMILY, 9), padding=[14, 6],
                        bordercolor=CLR_BORDER)
        style.map("Dark.TNotebook.Tab",
                  background=[("selected", CLR_BG)],
                  foreground=[("selected", CLR_ACCENT)],
                  expand=[("selected", [1, 1, 1, 0])])

        self.nb = ttk.Notebook(self, style="Dark.TNotebook")
        self.nb.pack(fill="both", expand=True, padx=0, pady=0)

        self.tab_overview   = OverviewTab(self.nb, self)
        self.tab_dashboard  = DashboardTab(self.nb, self)
        self.tab_stress     = StressTab(self.nb, self)
        self.tab_redemption = RedemptionTab(self.nb, self)
        self.tab_waterfall  = WaterfallTab(self.nb, self)
        self.tab_charts     = ChartsTab(self.nb, self)
        self.tab_riskstory  = RiskStoryTab(self.nb, self)

        self.nb.add(self.tab_overview,   text="  Overview  ")
        self.nb.add(self.tab_dashboard,  text="  Dashboard  ")
        self.nb.add(self.tab_stress,     text="  Stress Tests  ")
        self.nb.add(self.tab_redemption, text="  Redemption  ")
        self.nb.add(self.tab_waterfall,  text="  Waterfall  ")
        self.nb.add(self.tab_charts,     text="  Charts  ")
        self.nb.add(self.tab_riskstory,  text="  Risk Story  ")

        self.status = StatusBar(self)
        self.status.pack(fill="x", side="bottom")

    # ── File picker helpers ──────────────────────────────────────────────

    def _pick_files(self):
        paths = filedialog.askopenfilenames(
            title="Select MVHOL and NAV CSV files",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not paths:
            return

        mvhol, nav, mkt = None, None, None
        for p in paths:
            name = Path(p).name.upper()
            if "MARKET_DATA" in name or "MARKET DATA" in name or name.startswith("MKT"):
                mkt = p
            elif ("MVHOL" in name or "MV_HOL" in name or "MVHOL" in name.replace("-", "").replace("_", "")
                  or "HOLDINGS" in name or "HOLDING" in name):
                mvhol = p
            elif "NAV" in name:
                nav = p

        # Fallback: if pattern matching fails, assign by position
        unmatched = [p for p in paths if p not in (mvhol, nav, mkt)]
        if not mvhol and not nav and len(unmatched) >= 2:
            mvhol, nav = unmatched[0], unmatched[1]
        elif not mvhol and len(unmatched) == 1:
            mvhol = unmatched[0]
        elif not nav and mvhol and len(unmatched) == 1:
            nav = unmatched[0]

        if mvhol:
            self._mvhol_var.set(mvhol)
        if nav:
            self._nav_var.set(nav)
        if mkt:
            self._mkt_var.set(mkt)

        selected = [Path(p).name for p in [mvhol, nav, mkt] if p]
        self._files_lbl.config(text="  ".join(selected) if selected else "No files selected")
        self._scan_portfolios()

    def _scan_portfolios(self):
        mv = self._mvhol_var.get().strip()
        if not mv:
            return
        try:
            codes = available_portfolio_codes(mv)
            if codes:
                self._portfolio_cb["values"] = codes
                self._portfolio_var.set(codes[0])
                # Reveal the portfolio row now that we have options
                self._portfolio_bar.pack(fill="x", padx=16, pady=(2, 4),
                                         before=self._separator)
            else:
                self._portfolio_bar.pack_forget()
        except Exception as exc:
            messagebox.showerror("Scan Error", str(exc))

    def _on_portfolio_selected(self, _=None):
        """Auto-run when the user picks a different portfolio from the combobox."""
        if self._has_run:
            self._rerun_analysis()
        else:
            self._run_analysis()

    # ── Pipeline runner ─────────────────────────────────────────────────

    def _run_analysis(self, rerun: bool = False):
        if rerun:
            self._rerun_btn.config(state="disabled")
        self.run_btn.config(state="disabled")
        self.status.set("Re-running analysis pipeline…" if rerun else "Running analysis pipeline…", busy=True)
        self._run_mvhol     = self._mvhol_var.get().strip() or None
        self._run_nav       = self._nav_var.get().strip() or None
        self._run_portfolio = self._portfolio_var.get().strip() or None
        threading.Thread(target=self._pipeline_thread, daemon=True).start()

    def _rerun_analysis(self):
        self._run_analysis(rerun=True)

    def _pipeline_thread(self):
        try:
            portfolio, mv, nv, mkt_path = self._load_portfolio()
            engines = self._run_engines(portfolio)
            self._update_status("Building portfolio overview…", True)
            overview_rows = self._build_overview_rows(mv, nv, engines["lm"], portfolio, mkt_path)

            self._data = {
                "portfolio":          portfolio,
                "liquidity_metrics":  engines["lm"],
                "ladder_normal":      engines["prof_n"].liquidity_ladder(),
                "ladder_stress":      engines["stressed_agg"],
                "position_buckets":   engines["prof_n"].position_buckets,
                "stress_summary":     engines["stress_df"],
                "redemption_summary": engines["redeem_all"],
                "waterfall":          engines["wf_result"],
                "overview":           overview_rows,
            }
            self._report_builder = ReportBuilder(portfolio, output_dir="output")
            self._report_builder.build()
            self.after(0, self._populate_ui)

        except Exception:
            tb = traceback.format_exc()
            self.after(0, lambda tb=tb: self._on_error(tb))

    def _load_portfolio(self):
        """Resolve file paths, load Portfolio, enrich with market data.
        Returns (portfolio, mv, nv, mkt_path)."""
        mv = nv = None
        if self._run_mvhol and self._run_nav:
            mv, nv = self._run_mvhol, self._run_nav
        else:
            _syn_dir = Path(__file__).parent / "data"
            _mv_files = sorted(_syn_dir.glob("HOLDINGS_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
            _nv_files = sorted(_syn_dir.glob("NAV_*.csv"),      key=lambda p: p.stat().st_mtime, reverse=True)
            if _mv_files and _nv_files:
                mv, nv = _mv_files[0], _nv_files[0]
                self.after(0, lambda m=mv, n=nv: (
                    self._mvhol_var.set(str(m)),
                    self._nav_var.set(str(n)),
                    self._scan_portfolios(),
                ))

        if mv and nv:
            portfolio = load_portfolio_from_csv(
                mv, nv, portfolio_code=self._run_portfolio or None
            )
            if self._run_portfolio is None:
                self.after(0, lambda pc=portfolio.fund_id: self._portfolio_var.set(pc))
        else:
            portfolio = build_sample_portfolio()

        mkt_path = Path(__file__).parent / "data" / "market_data_ALL.csv"
        if mkt_path.exists():
            enrich_portfolio_from_market_data(portfolio, mkt_path)

        return portfolio, mv, nv, mkt_path

    def _run_engines(self, portfolio) -> dict:
        """Run all analysis engines. Returns dict keyed by result name."""
        nav = portfolio.total_nav

        self._update_status("Liquidity profiling…", True)
        prof_n = LiquidityProfiler(portfolio, stress=False).run()

        self._update_status("Redemption scenarios…", True)
        prof_s_redeem = LiquidityProfiler(
            portfolio, stress=True, adv_stress_scalar=REDEMPTION_STRESS_ADV_SCALAR
        ).run()
        sim = RedemptionSimulator(
            portfolio, prof_n.position_buckets, prof_s_redeem.position_buckets
        )
        redeem_n = sim.run(stress=False)
        redeem_s = sim.run(stress=True)
        redeem_n["regime"] = "normal"
        redeem_s["regime"] = "stress"
        redeem_all = pd.concat([redeem_n, redeem_s], ignore_index=True)

        self._update_status("Stress engine…", True)
        engine = StressEngine(portfolio, STRESS_SCENARIOS)
        stress_results = engine.run_detail()
        stress_df = pd.DataFrame([r.to_dict() for r in stress_results])

        self._update_status("Waterfall simulation…", True)
        worst = next(
            (s for s in stress_results if "Severe" in s.scenario_name),
            stress_results[-1],
        )
        wf_engine = WaterfallEngine(portfolio, worst.position_detail, stress=True)
        wf_result = wf_engine.run(nav * 0.30)

        self._update_status("Building metrics…", True)
        lm = RiskMetricsBuilder(portfolio).build_liquidity_metrics()

        # Build stressed ladder from the worst scenario's shocked, ADV-compressed
        # position detail so that bucket migrations are reflected correctly.
        stressed_nav = worst.position_detail["market_value_eur"].sum()
        stressed_agg = (
            worst.position_detail
            .groupby("bucket")
            .agg(
                realisable_value_eur=("realisable_value", "sum"),
                market_value_eur=("market_value_eur", "sum"),
            )
            .reindex(BUCKET_ORDER, fill_value=0.0)
            .reset_index()
        )
        stressed_agg["nav_pct"] = (
            stressed_agg["market_value_eur"] / stressed_nav if stressed_nav > 0 else 0.0
        )
        stressed_agg["cumulative_nav_pct"] = stressed_agg["nav_pct"].cumsum()

        return {
            "prof_n":       prof_n,
            "redeem_all":   redeem_all,
            "stress_df":    stress_df,
            "wf_result":    wf_result,
            "lm":           lm,
            "stressed_agg": stressed_agg,
        }

    def _build_overview_rows(self, mv, nv, lm, portfolio, mkt_path) -> list:
        """Collect liquidity metrics for every portfolio in the holdings file."""
        rows: list = []
        if mv is not None:
            try:
                for code in available_portfolio_codes(mv):
                    try:
                        p = load_portfolio_from_csv(mv, nv, portfolio_code=code)
                        if mkt_path.exists():
                            enrich_portfolio_from_market_data(p, mkt_path)
                        m = RiskMetricsBuilder(p).build_liquidity_metrics()
                        rows.append({
                            "fund_id":       p.fund_id,
                            "fund_name":     p.fund_name,
                            "nav":           m.total_nav_eur,
                            "lcr_t1":        m.lcr_t1,
                            "lcr_t3":        m.lcr_t3,
                            "lcr_t7":        m.lcr_t7,
                            "illiquid_pct":  m.illiquid_pct,
                            "days_to_50pct": m.days_to_50pct,
                            "top10_conc":    m.top10_concentration,
                            "liq_conc":      m.liquidity_vs_concentration,
                            "warning":       m.warning_flag,
                            "breach":        m.breach_flag,
                        })
                    except Exception:
                        pass
            except Exception:
                pass
        if not rows:
            rows = [{
                "fund_id":       portfolio.fund_id,
                "fund_name":     portfolio.fund_name,
                "nav":           lm.total_nav_eur,
                "lcr_t1":        lm.lcr_t1,
                "lcr_t3":        lm.lcr_t3,
                "lcr_t7":        lm.lcr_t7,
                "illiquid_pct":  lm.illiquid_pct,
                "days_to_50pct": lm.days_to_50pct,
                "top10_conc":    lm.top10_concentration,
                "liq_conc":      lm.liquidity_vs_concentration,
                "warning":       lm.warning_flag,
                "breach":        lm.breach_flag,
            }]
        return rows

    def _update_status(self, msg: str, busy: bool = False):
        self.after(0, lambda: self.status.set(msg, busy))

    def _populate_ui(self):
        try:
            self._do_populate_ui()
        except Exception:
            self._on_error(traceback.format_exc())

    def _do_populate_ui(self):
        d = self._data
        fund = d["portfolio"]
        self.fund_lbl.config(
            text=f"{fund.fund_name}  |  {fund.reporting_date.date()}  "
                 f"|  NAV: EUR {fund.total_nav:,.0f}",
            fg=CLR_TEXT
        )
        self.tab_overview.populate(d["overview"])
        self.tab_dashboard.populate(d)
        self.tab_stress.populate(d)
        self.tab_redemption.populate(d)
        self.tab_waterfall.populate(d)
        self.tab_charts.populate(d)
        self.tab_riskstory.populate(d)

        self.export_btn.config(state="normal")
        self.charts_btn.config(state="normal")

        # After first run: replace button with "done" label + small re-run link
        if not self._has_run:
            self._has_run = True
            self.run_btn.config(
                text="✓  Analysis Complete", bg=CLR_GREEN, fg=CLR_BG,
                state="disabled", cursor="arrow",
            )
            self._rerun_btn = tk.Button(
                self.run_btn.master,
                text="Re-run ↺", font=(FONT_FAMILY, 8),
                bg=CLR_SURFACE, fg=CLR_MUTED, relief="flat", padx=8, pady=6,
                cursor="hand2", command=self._rerun_analysis,
                activebackground=CLR_BORDER, activeforeground=CLR_TEXT,
            )
            self._rerun_btn.pack(side="left", padx=(0, 8))
        else:
            self._rerun_btn.config(state="normal")

        n_stress = len(d.get("stress_summary", []))
        self.status.set(
            f"Analysis complete — {len(d['position_buckets'])} positions | "
            f"{n_stress} stress scenarios | 8 redemption scenarios",
            busy=False
        )

    def _on_error(self, tb: str):
        if self._has_run:
            self._rerun_btn.config(state="normal")
        else:
            self.run_btn.config(state="normal")
        # Extract just the last line (exception type + message) for the status bar
        last_line = tb.strip().splitlines()[-1] if tb.strip() else "Unknown error"
        self.status.set(f"Error: {last_line}", busy=False)
        messagebox.showerror("Pipeline Error", tb)

    # ── Export ─────────────────────────────────────────────────────────

    def _export(self):
        if self._report_builder is None:
            return
        try:
            out_dir = Path("output")
            self._report_builder.to_excel("liquidity_risk_report.xlsx")
            self._report_builder.to_json("liquidity_risk_report.json")
            messagebox.showinfo(
                "Export Complete",
                f"Files saved to:\n{out_dir.resolve()}\n\n"
                "• liquidity_risk_report.xlsx\n"
                "• liquidity_risk_report.json"
            )
        except Exception as e:
            messagebox.showerror("Export Error", str(e))

    def _save_all_charts(self):
        if self._data is None:
            return
        out_dir = Path("output/charts")
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, fig in self.tab_charts._figures.items():
            fname = out_dir / (name.lower().replace(" ", "_") + ".png")
            fig.savefig(fname, dpi=150, bbox_inches="tight")
        messagebox.showinfo(
            "Charts Saved",
            f"All charts saved to:\n{out_dir.resolve()}"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = App()
    app.mainloop()
