# Public Repository Upload Policy

This document governs what may and may not be committed to the public GitHub
repository for the Liquidity Risk & Stress Testing Tool.

---

## ALLOWED — Safe to commit

| Category | Examples |
|---|---|
| Core engine code | `liquidity_risk_tool/engines/*.py` |
| Models and data loaders | `liquidity_risk_tool/models/*.py` |
| Reporting and visualization | `liquidity_risk_tool/reporting/*.py`, `liquidity_risk_tool/visualization/*.py` |
| Configuration (no secrets) | `liquidity_risk_tool/config/settings.py` |
| CLI entry point | `main.py` |
| Tkinter GUI | `ui-tk/gui.py` |
| FastAPI backend | `backend/` |
| React frontend source | `frontend/src/` |
| Refinitiv extractor **code** | `integrations/refinitiv/fetch_market_data.py` |
| Synthetic data generator | `data/generate_synthetic_data.py` |
| Synthetic sample data | `data/sample/*.csv`, `data/sample/*.xlsx` |
| Tests | `tests/` |
| Documentation | `README.md`, `MODEL.md`, `*.md` |
| Package manifest | `requirements.txt`, `package.json`, `package-lock.json` |
| Schema examples (no real values) | `*.schema.json` |
| Docker / CI config | `Dockerfile`, `.dockerignore`, `.github/` |

---

## FORBIDDEN — Must never be committed

### 1. Refinitiv / LSEG Licensed Data

Refinitiv data is subject to the LSEG Terms of Use. Committing it — even
partially or in transformed form — violates those terms and creates legal risk.

| Forbidden | Why |
|---|---|
| `data/market_data_ALL.csv` | Output of Refinitiv API fetch |
| `data/market_data_ERRORS.csv` | Derived from Refinitiv fetch |
| `data/market_data_cache.csv` | Cache of Refinitiv data |
| `data/zero_coupon_yields.xlsx` | Fetched via Refinitiv RICs (USZCY*=FBNY) |
| Any file with Refinitiv RIC codes as data values | Constitutes licensed data |
| `REFINITIV_APP_KEY` or any credentials | Security risk |

**Rule:** If a file was produced by `fetch_market_data.py` or by querying any
Refinitiv/LSEG API, it may not be committed. This applies even if the values
happen to be publicly available elsewhere.

### 2. Real Portfolio / Client Data

| Forbidden | Why |
|---|---|
| Real MVHOL holdings files (`MVHOL_ALT_*.csv`) | Proprietary position data |
| Real NAV files (`NAV_ALT_*.csv`) | Proprietary fund data |
| Any file containing real ISIN + market value pairs | Client confidential |
| Internal fund codes, portfolio names | Proprietary |
| Any file from `data/real/` | Reserved for local real-data workflows |

### 3. Generated Reports and Outputs

Reports contain processed views of real or synthetic data. Only synthetic
outputs may be committed, and only if they are explicitly labeled as synthetic.

| Forbidden | Why |
|---|---|
| `output/liquidity_risk_report.xlsx` | May reflect real portfolio state |
| `output/liquidity_risk_report.json` | Same |
| `output/charts/*.png` | Same |
| `liquidity_risk_tool/output/` | Same |

### 4. Credentials and Secrets

| Forbidden | Examples |
|---|---|
| API keys | `REFINITIV_APP_KEY`, any `_APP_KEY` literal |
| Personal file paths | `C:\Users\Eden Carbonell\...` |
| `.env` files | Any `.env` or `secrets.py` |

---

## Pre-commit Checklist

Before pushing a commit, verify:

- [ ] No files in `data/` except `data/sample/` and `data/generate_synthetic_data.py`
- [ ] No `*.xlsx` or `*.csv` outside of `data/sample/`
- [ ] No hardcoded API keys or personal paths in any Python file
- [ ] `output/` is empty or gitignored
- [ ] `integrations/refinitiv/.env` is gitignored (it is — see `.gitignore`)
- [ ] `git status` shows no unintended staged data files

---

## Public Demo Data

The repository ships with a synthetic data generator that produces structurally
identical but entirely fictional data:

```bash
python data/generate_synthetic_data.py
```

Outputs land in `data/sample/` and are safe to commit. All values are randomly
generated and contain no real ISINs, market values, or client information.
