# Refinitiv / LSEG Workspace Integration

This directory contains the market data extractor that pulls live data from
LSEG Workspace (formerly Refinitiv Eikon) via its local proxy API.

> **Note:** The live demo at [https://liquidity-risk-stress-testing.onrender.com](https://liquidity-risk-stress-testing.onrender.com)
> does **not** use Refinitiv data. All demo data is synthetically generated and
> contains no real ISINs, market values, or licensed content.
> The code in this directory is provided for users who have their own LSEG Workspace licence.

## Setup

1. Open **LSEG Workspace** on your machine (the proxy runs on `localhost:9000`).
2. Set your app key as an environment variable:

   ```bash
   # Linux / macOS
   export REFINITIV_APP_KEY=your_app_key_here

   # Windows PowerShell
   $env:REFINITIV_APP_KEY = "your_app_key_here"
   ```

   Your app key is available in the Workspace App Studio at
   `https://apd.refinitiv.com/apps/AppDeveloperPortal/` (requires login).

3. Install dependencies (pandas, requests are sufficient — no `eikon` library needed):

   ```bash
   pip install pandas requests openpyxl
   ```

## Usage

```bash
# Fetch all portfolios from a holdings file → data/real/market_data_ALL.csv
python integrations/refinitiv/fetch_market_data.py --mvhol path/to/HOLDINGS_YYYYMMDD.csv

# Fetch a single portfolio to a custom output path
python integrations/refinitiv/fetch_market_data.py \
    --mvhol path/to/HOLDINGS_YYYYMMDD.csv \
    --portfolio MY-FUND \
    --out data/real/my_fund_market_data.csv
```

## Data Restrictions

**Outputs of this script are Refinitiv/LSEG licensed data.**

- Do **not** commit output CSVs to version control.
- Do **not** share outputs publicly or embed them in examples.
- Keep all outputs in `data/real/` (covered by `.gitignore`).
- The script code itself is safe to commit; credentials must remain in env vars only.

For the public demo, synthetic data is used instead — no licence required:

```bash
python data/generate_synthetic_data.py
```
