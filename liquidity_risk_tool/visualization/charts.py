"""
Visualization Module
--------------------
Produces the standard chart pack used in fund risk reports.

Charts produced
---------------
1.  Liquidity Ladder (stacked bar, normal vs stress)
2.  Redemption Coverage Heatmap (scenario × horizon)
3.  Stress Test NAV Impact (waterfall / grouped bar)
4.  Time-to-Liquidate Curve (cumulative proceeds over days)
5.  Asset Allocation Donut (by asset class & bucket)
6.  Stress Liquidity Comparison (before/after stress per scenario)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec

from ..config.settings import BUCKET_ORDER, MAX_ADV_PARTICIPATION


# ---------------------------------------------------------------------------
# Palette aligned with typical risk-report styling
# ---------------------------------------------------------------------------
BUCKET_COLORS = {
    "T+0":   "#1a7abf",
    "T+1":   "#4db3e6",
    "T+3":   "#f0a500",
    "T+7":   "#e07b39",
    ">T+7":  "#c0392b",
}
STRESS_COLOR  = "#c0392b"
NORMAL_COLOR  = "#2980b9"
ACCENT_COLOR  = "#27ae60"


def _fmt_eur(x, _=None) -> str:
    if abs(x) >= 1e9:
        return f"€{x/1e9:.1f}B"
    if abs(x) >= 1e6:
        return f"€{x/1e6:.0f}M"
    return f"€{x:,.0f}"


class ChartPack:

    def __init__(self, output_dir: str = "output/charts"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        plt.rcParams.update({
            "font.family":  "sans-serif",
            "font.size":    9,
            "axes.spines.top":    False,
            "axes.spines.right":  False,
            "figure.dpi":   150,
        })

    # ------------------------------------------------------------------
    # 1. Liquidity Ladder
    # ------------------------------------------------------------------

    def plot_liquidity_ladder(
        self,
        normal_ladder: pd.DataFrame,
        stress_ladder: pd.DataFrame,
        fund_name: str = "",
        save: bool = True,
    ) -> plt.Figure:
        fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=False)
        fig.suptitle(f"{fund_name} — Liquidity Ladder (Normal vs Stress)", fontweight="bold")

        for ax, ladder, title in zip(axes, [normal_ladder, stress_ladder], ["Normal Regime", "Stress Regime"]):
            colors = [BUCKET_COLORS[b] for b in ladder["bucket"]]
            bars = ax.bar(ladder["bucket"], ladder["nav_pct"] * 100, color=colors, edgecolor="white", linewidth=0.5)
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
            ax.set_title(title, pad=8)
            ax.set_xlabel("Liquidity Bucket")
            ax.set_ylabel("% of NAV")
            for bar, val in zip(bars, ladder["nav_pct"] * 100):
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.3,
                    f"{val:.1f}%",
                    ha="center", va="bottom", fontsize=8,
                )
            # Cumulative line
            ax2 = ax.twinx()
            ax2.plot(
                ladder["bucket"],
                ladder["cumulative_nav_pct"] * 100,
                color="#2c3e50", marker="o", linewidth=2, markersize=5,
            )
            ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
            ax2.set_ylabel("Cumulative %", color="#2c3e50")
            ax2.tick_params(axis="y", labelcolor="#2c3e50")
            ax2.set_ylim(0, 115)

        plt.tight_layout()
        if save:
            p = self.output_dir / "01_liquidity_ladder.png"
            fig.savefig(p, bbox_inches="tight")
        return fig

    # ------------------------------------------------------------------
    # 2. Redemption Coverage Heatmap
    # ------------------------------------------------------------------

    def plot_redemption_heatmap(
        self, redemption_df: pd.DataFrame, save: bool = True
    ) -> plt.Figure:
        fig, axes = plt.subplots(1, 2, figsize=(12, 4))
        fig.suptitle("Redemption Coverage — Normal vs Stress Regime", fontweight="bold")

        for ax, regime in zip(axes, ["normal", "stress"]):
            sub = redemption_df[redemption_df["regime"] == regime].copy()
            sub["scenario_label"] = (sub["scenario_pct"] * 100).astype(int).astype(str) + "%"

            matrix = sub[["scenario_label", "can_meet_t1", "can_meet_t3", "can_meet_t7"]].set_index("scenario_label")
            matrix.columns = ["T+1", "T+3", "T+7"]

            colors = matrix.map(lambda x: ACCENT_COLOR if x else STRESS_COLOR)
            ax.set_xlim(0, len(matrix.columns))
            ax.set_ylim(0, len(matrix))
            ax.set_xticks(np.arange(len(matrix.columns)) + 0.5)
            ax.set_xticklabels(matrix.columns)
            ax.set_yticks(np.arange(len(matrix)) + 0.5)
            ax.set_yticklabels(matrix.index[::-1])

            for i, row_label in enumerate(reversed(matrix.index)):
                for j, col_label in enumerate(matrix.columns):
                    val = matrix.loc[row_label, col_label]
                    color = ACCENT_COLOR if val else STRESS_COLOR
                    ax.add_patch(mpatches.FancyBboxPatch(
                        (j + 0.05, i + 0.05), 0.9, 0.9,
                        boxstyle="round,pad=0.05", color=color, alpha=0.85,
                    ))
                    ax.text(j + 0.5, i + 0.5, "✓" if val else "✗",
                            ha="center", va="center", fontsize=14,
                            color="white", fontweight="bold")

            ax.set_title(f"{regime.capitalize()} Regime", pad=8)
            ax.set_xlabel("Settlement Horizon")
            ax.set_ylabel("Redemption Rate")
            ax.spines[:].set_visible(False)
            ax.tick_params(length=0)

        plt.tight_layout()
        if save:
            p = self.output_dir / "02_redemption_heatmap.png"
            fig.savefig(p, bbox_inches="tight")
        return fig

    # ------------------------------------------------------------------
    # 3. Stress Test NAV Impact
    # ------------------------------------------------------------------

    def plot_stress_nav_impact(
        self, stress_df: pd.DataFrame, save: bool = True
    ) -> plt.Figure:
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        fig.suptitle("Stress Test Results", fontweight="bold")

        scenarios = stress_df["scenario_name"]
        nav_impacts = stress_df["nav_impact_pct"] * 100
        liquid_after = stress_df["liquid_pct_after"] * 100

        # NAV impact
        ax = axes[0]
        bar_colors = [STRESS_COLOR if v < -5 else "#e07b39" if v < -2 else NORMAL_COLOR for v in nav_impacts]
        bars = ax.barh(scenarios, nav_impacts, color=bar_colors, edgecolor="white")
        ax.axvline(0, color="black", linewidth=0.8)
        ax.set_xlabel("NAV Impact (%)")
        ax.set_title("NAV Impact per Scenario")
        for bar, val in zip(bars, nav_impacts):
            ax.text(
                val - 0.1 if val < 0 else val + 0.1,
                bar.get_y() + bar.get_height() / 2,
                f"{val:.1f}%",
                ha="right" if val < 0 else "left",
                va="center", fontsize=8,
            )

        # Liquidity under stress
        ax = axes[1]
        x = np.arange(len(scenarios))
        liquid_before = stress_df["liquid_pct_before"] * 100
        w = 0.35
        ax.bar(x - w/2, liquid_before, width=w, label="Before Stress", color=NORMAL_COLOR, alpha=0.85)
        ax.bar(x + w/2, liquid_after,  width=w, label="After Stress",  color=STRESS_COLOR, alpha=0.85)
        ax.axhline(10, color="orange", linestyle="--", linewidth=1, label="Warning (10%)")
        ax.axhline(5,  color=STRESS_COLOR,  linestyle=":",  linewidth=1, label="Breach (5%)")
        ax.set_xticks(x)
        ax.set_xticklabels(scenarios, rotation=15, ha="right", fontsize=7)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
        ax.set_ylabel("Liquid (T0+T1) % NAV")
        ax.set_title("Liquidity Profile Before/After Stress")
        ax.legend(fontsize=7, loc="upper right")

        plt.tight_layout()
        if save:
            p = self.output_dir / "03_stress_nav_impact.png"
            fig.savefig(p, bbox_inches="tight")
        return fig

    # ------------------------------------------------------------------
    # 4. Time-to-Liquidate Curve
    # ------------------------------------------------------------------

    def plot_time_to_liquidate(
        self,
        profile: pd.DataFrame,
        nav: float,
        save: bool = True,
    ) -> plt.Figure:
        """Plots cumulative liquidation proceeds vs. calendar day."""
        sellable = (
            profile[~profile["is_locked"] & (profile["adv_30d"] > 0)]
            .copy()
            .sort_values("days_to_liquidate")
        )

        days_col, proceeds_col = [], []
        cumulative = 0.0
        for _, pos in sellable.iterrows():
            adv_cap = pos["adv_30d"] * MAX_ADV_PARTICIPATION
            days = pos["market_value_eur"] / adv_cap
            cumulative += pos["realisable_value"]
            days_col.append(days)
            proceeds_col.append(cumulative / nav * 100)

        # Add illiquid tail
        illiquid_val = profile[profile["is_locked"] | (profile["adv_30d"] <= 0)]["realisable_value"].sum()
        days_col.append(days_col[-1] + 60 if days_col else 60)
        proceeds_col.append((cumulative + illiquid_val) / nav * 100)

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(days_col, proceeds_col, color=NORMAL_COLOR, linewidth=2.5, marker=".", markersize=4)
        ax.axhline(50, linestyle="--", color="gray",         linewidth=1, label="50% threshold")
        ax.axhline(75, linestyle="--", color="#f0a500",      linewidth=1, label="75% threshold")
        ax.axhline(90, linestyle="--", color=STRESS_COLOR,   linewidth=1, label="90% threshold")
        ax.fill_between(days_col, proceeds_col, alpha=0.12, color=NORMAL_COLOR)
        ax.set_xlabel("Calendar Days")
        ax.set_ylabel("% of NAV Liquidated")
        ax.set_title("Time-to-Liquidate Curve (Normal Regime)", fontweight="bold")
        ax.legend(fontsize=8)
        ax.set_xlim(left=0)
        ax.set_ylim(0, 105)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))

        plt.tight_layout()
        if save:
            p = self.output_dir / "04_time_to_liquidate.png"
            fig.savefig(p, bbox_inches="tight")
        return fig

    # ------------------------------------------------------------------
    # 5. Portfolio Composition Donut
    # ------------------------------------------------------------------

    def plot_portfolio_composition(
        self,
        profile: pd.DataFrame,
        nav: float,
        save: bool = True,
    ) -> plt.Figure:
        fig, axes = plt.subplots(1, 2, figsize=(12, 5))
        fig.suptitle("Portfolio Composition", fontweight="bold")

        # By asset class
        ac_data = (
            profile.groupby("asset_class")["market_value_eur"]
            .sum()
            .sort_values(ascending=False)
        )
        cmap = plt.cm.get_cmap("tab20", len(ac_data))
        axes[0].pie(
            ac_data.values,
            labels=[f"{k}\n({v/nav*100:.1f}%)" for k, v in ac_data.items()],
            colors=[cmap(i) for i in range(len(ac_data))],
            startangle=90,
            pctdistance=0.85,
            wedgeprops={"linewidth": 0.5, "edgecolor": "white"},
        )
        axes[0].set_title("By Asset Class")

        # By bucket
        bucket_data = (
            profile.groupby("bucket")["realisable_value"]
            .sum()
            .reindex(BUCKET_ORDER, fill_value=0)
        )
        bcolors = [BUCKET_COLORS[b] for b in bucket_data.index]
        axes[1].pie(
            bucket_data.values,
            labels=[f"{k}\n({v/nav*100:.1f}%)" for k, v in bucket_data.items()],
            colors=bcolors,
            startangle=90,
            wedgeprops={"linewidth": 0.5, "edgecolor": "white"},
        )
        axes[1].set_title("By Liquidity Bucket (Realisable)")

        plt.tight_layout()
        if save:
            p = self.output_dir / "05_portfolio_composition.png"
            fig.savefig(p, bbox_inches="tight")
        return fig

    # ------------------------------------------------------------------
    # 6. Waterfall Sell Schedule
    # ------------------------------------------------------------------

    def plot_waterfall_schedule(
        self,
        sell_schedule: pd.DataFrame,
        target_eur: float,
        save: bool = True,
    ) -> plt.Figure:
        if sell_schedule.empty:
            return None

        daily = (
            sell_schedule.groupby("day")
            .agg(net_proceeds=("net_proceeds_eur", "sum"))
            .reset_index()
        )
        daily["cumulative"] = daily["net_proceeds"].cumsum()

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.bar(daily["day"], daily["net_proceeds"] / 1e6, color=NORMAL_COLOR, alpha=0.8, label="Daily Proceeds")
        ax2 = ax.twinx()
        ax2.plot(daily["day"], daily["cumulative"] / 1e6, color=STRESS_COLOR, marker="o", linewidth=2, label="Cumulative")
        ax2.axhline(target_eur / 1e6, color="black", linestyle="--", linewidth=1.5, label=f"Target €{target_eur/1e6:.0f}M")

        ax.set_xlabel("Calendar Day")
        ax.set_ylabel("Daily Net Proceeds (€M)")
        ax2.set_ylabel("Cumulative Proceeds (€M)", color=STRESS_COLOR)
        ax2.tick_params(axis="y", labelcolor=STRESS_COLOR)
        ax.set_title("Liquidation Waterfall — Sell Schedule", fontweight="bold")

        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines1 + lines2, labels1 + labels2, loc="lower right", fontsize=8)

        plt.tight_layout()
        if save:
            p = self.output_dir / "06_waterfall_schedule.png"
            fig.savefig(p, bbox_inches="tight")
        return fig

