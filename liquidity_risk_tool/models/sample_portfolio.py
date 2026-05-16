"""
Realistic sample Luxembourg UCITS fund portfolio (mixed asset, ~EUR 500M NAV).
Reflects a typical balanced fund with investment-grade bias.
"""
import pandas as pd
from .position import Position, ShareClass, Portfolio


def build_sample_portfolio() -> Portfolio:
    share_classes = [
        ShareClass("Class A (Retail)",        100.42, 1_804_420, notice_period_days=0, redemption_frequency="daily"),
        ShareClass("Class I (Institutional)", 150.18, 1_082_652, notice_period_days=2, redemption_frequency="daily"),
        ShareClass("Class R (Reserved)",      200.05,   180_442, notice_period_days=5, redemption_frequency="weekly"),
    ]

    positions = [
        # ── CASH & MONEY MARKET ──────────────────────────────────────────
        Position("CASH001", "EUR Cash Account",          "cash",              25_000_000,  0, "EUR", 1.0, adv_30d=1e12, bid_ask_spread_bps=0),
        Position("MM001",   "BNP Paribas CP 3M",         "money_market",      15_000_000,  0, "EUR", 1.0, adv_30d=15_000_000, bid_ask_spread_bps=1),
        Position("MM002",   "LVMH Commercial Paper 1M",  "money_market",      10_000_000,  0, "EUR", 1.0, adv_30d=10_000_000, bid_ask_spread_bps=1),

        # ── GOVERNMENT BONDS ────────────────────────────────────────────
        Position("XS001",   "Bund 2.5% 2030",            "government_bond",   30_000_000,  0, "EUR", 1.0, adv_30d=50_000_000, bid_ask_spread_bps=2,  duration=4.8,  credit_spread_bps=0,   rating="AAA", is_government=True),
        Position("XS002",   "OAT 3.0% 2032",             "government_bond",   20_000_000,  0, "EUR", 1.0, adv_30d=40_000_000, bid_ask_spread_bps=3,  duration=6.2,  credit_spread_bps=45,  rating="AA",  is_government=True),
        Position("XS003",   "BTP Italy 4.0% 2029",       "government_bond",   15_000_000,  0, "EUR", 1.0, adv_30d=35_000_000, bid_ask_spread_bps=4,  duration=3.7,  credit_spread_bps=185, rating="BBB+",is_government=True),
        Position("US001",   "US Treasury 4.25% 2031",    "government_bond",   10_000_000,  0, "USD", 1.08, adv_30d=80_000_000, bid_ask_spread_bps=1,  duration=5.1,  credit_spread_bps=0,   rating="AAA", is_government=True),

        # ── IG CORPORATE BONDS ──────────────────────────────────────────
        Position("XS010",   "Volkswagen 3.5% 2028",      "ig_corporate_bond", 12_000_000,  0, "EUR", 1.0, adv_30d=8_000_000,  bid_ask_spread_bps=12, duration=3.2,  credit_spread_bps=120, rating="BBB+"),
        Position("XS011",   "Total Energies 3.0% 2031",  "ig_corporate_bond", 10_000_000,  0, "EUR", 1.0, adv_30d=7_000_000,  bid_ask_spread_bps=10, duration=5.4,  credit_spread_bps=85,  rating="A-"),
        Position("XS012",   "Siemens 2.75% 2027",        "ig_corporate_bond",  8_000_000,  0, "EUR", 1.0, adv_30d=6_000_000,  bid_ask_spread_bps=9,  duration=2.9,  credit_spread_bps=70,  rating="A"),
        Position("XS013",   "Enel 4.0% 2030",            "ig_corporate_bond",  7_000_000,  0, "EUR", 1.0, adv_30d=5_500_000,  bid_ask_spread_bps=14, duration=4.1,  credit_spread_bps=145, rating="BBB"),
        Position("XS014",   "Sanofi 2.5% 2029",          "ig_corporate_bond",  6_000_000,  0, "EUR", 1.0, adv_30d=5_000_000,  bid_ask_spread_bps=8,  duration=3.8,  credit_spread_bps=60,  rating="AA-"),

        # ── HY CORPORATE BONDS ──────────────────────────────────────────
        Position("XS020",   "Altice France 8.0% 2027",   "hy_corporate_bond",  5_000_000,  0, "EUR", 1.0, adv_30d=2_000_000,  bid_ask_spread_bps=60, duration=1.8,  credit_spread_bps=650, rating="B+"),
        Position("XS021",   "Softbank 6.5% 2029",        "hy_corporate_bond",  4_000_000,  0, "USD", 1.08, adv_30d=1_800_000, bid_ask_spread_bps=75, duration=2.6,  credit_spread_bps=480, rating="BB-"),
        Position("XS022",   "Loxam 7.25% 2028",          "hy_corporate_bond",  3_000_000,  0, "EUR", 1.0, adv_30d=1_200_000,  bid_ask_spread_bps=90, duration=2.2,  credit_spread_bps=580, rating="B"),

        # ── STRUCTURED CREDIT ───────────────────────────────────────────
        Position("XS030",   "CLO AAA Tranche 2022-3",    "structured_credit",  8_000_000,  0, "EUR", 1.0, adv_30d=1_500_000,  bid_ask_spread_bps=25, duration=2.5,  credit_spread_bps=170, rating="AAA"),
        Position("XS031",   "CMBS Senior 2021-1",        "structured_credit",  5_000_000,  0, "EUR", 1.0, adv_30d=800_000,    bid_ask_spread_bps=40, duration=4.2,  credit_spread_bps=250, rating="AA"),

        # ── LISTED EQUITIES ─────────────────────────────────────────────
        Position("FR0000131104", "BNP Paribas",          "listed_equity",     18_000_000,  0, "EUR", 1.0, adv_30d=120_000_000, bid_ask_spread_bps=5, beta=1.20),
        Position("DE0007164600", "SAP SE",               "listed_equity",     22_000_000,  0, "EUR", 1.0, adv_30d=90_000_000,  bid_ask_spread_bps=4, beta=0.85),
        Position("FR0000120271", "Total Energies",       "listed_equity",     16_000_000,  0, "EUR", 1.0, adv_30d=110_000_000, bid_ask_spread_bps=4, beta=0.95),
        Position("NL0000009165", "Heineken",             "listed_equity",     12_000_000,  0, "EUR", 1.0, adv_30d=60_000_000,  bid_ask_spread_bps=5, beta=0.70),
        Position("CH0012221716", "ABB Ltd",              "listed_equity",     10_000_000,  0, "CHF", 1.02, adv_30d=55_000_000, bid_ask_spread_bps=6, beta=1.05),
        Position("GB0031348658", "Diageo",               "listed_equity",      9_000_000,  0, "GBP", 1.17, adv_30d=75_000_000, bid_ask_spread_bps=4, beta=0.60),
        Position("US5949181045", "Microsoft",            "listed_equity",     20_000_000,  0, "USD", 1.08, adv_30d=400_000_000, bid_ask_spread_bps=2, beta=0.90),
        Position("US0231351067", "Amazon",               "listed_equity",     15_000_000,  0, "USD", 1.08, adv_30d=350_000_000, bid_ask_spread_bps=2, beta=1.10),

        # ── ETFs ────────────────────────────────────────────────────────
        Position("IE00B4L5Y983", "iShares Core MSCI World", "etf",           20_000_000,  0, "USD", 1.08, adv_30d=250_000_000, bid_ask_spread_bps=3, beta=1.00),
        Position("LU0290358497", "Xtrackers Euro Stoxx 50", "etf",           12_000_000,  0, "EUR", 1.0,  adv_30d=80_000_000,  bid_ask_spread_bps=3, beta=1.00),

        # ── PRIVATE / ILLIQUID ───────────────────────────────────────────
        Position("PE001",   "EQT Infrastructure VI",    "private_equity",    10_000_000,  0, "EUR", 1.0, adv_30d=0, is_locked=True, lock_expiry_days=730),
        Position("HF001",   "Bridgewater All Weather",  "hedge_fund",         8_000_000,  0, "USD", 1.08, adv_30d=0, is_locked=True, lock_expiry_days=90),
        Position("RE001",   "CBRE Pan-Euro RE Fund",    "real_estate",         7_000_000,  0, "EUR", 1.0, adv_30d=0, is_locked=True, lock_expiry_days=365),
    ]

    return Portfolio(
        fund_name="LRI Balanced Income SICAV",
        fund_id="LU0123456789",
        reporting_date=pd.Timestamp("2026-05-04"),
        share_classes=share_classes,
        positions=positions,
        top_10_investor_concentration=0.38,
    )
