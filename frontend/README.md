# Liquidity Risk Tool — React Frontend

A React + Vite + TailwindCSS v4 web application for interactive liquidity risk analytics. Real-time portfolio analysis, stress testing, waterfall simulation, and AIFMD II Liquidity Management Tools configuration.

## Quick Start

### Install dependencies
```bash
npm install
```

### Development server
```bash
npm run dev
```

Opens [http://localhost:5173](http://localhost:5173) in your browser (HMR enabled).

### Production build
```bash
npm run build
```

Outputs to `dist/`.

### Preview production build
```bash
npm run preview
```

## Project Structure

```
frontend/
├── src/
│   ├── pages/                      # Tab/page components
│   │   ├── AllPortfolios.jsx       # Cross-portfolio comparison table
│   │   ├── Dashboard.jsx           # Fund summary, KPIs, liquidity ladder
│   │   ├── StressTests.jsx         # Per-scenario NAV impact analysis
│   │   ├── Waterfall.jsx           # Forced sell-down schedule
│   │   ├── Charts.jsx              # 7-chart matplotlib library
│   │   ├── Leverage.jsx            # AIFMD II Art.15 gross leverage KPIs
│   │   ├── Redemption.jsx          # Coverage matrix, scenario analysis
│   │   └── LMTSimulator.jsx        # AIFMD II LMT configuration & impact dashboard
│   ├── components/                 # Shared React components
│   │   ├── KPICard.jsx             # Metric display with tooltip support
│   │   ├── MetricTooltip.jsx       # Contextual help tooltips
│   │   ├── EmptyState.jsx          # No data placeholder
│   │   ├── CoverageTable.jsx       # Liquidity coverage ratio matrix
│   │   └── ...                     # Theme, sidebar, layout components
│   ├── AnalysisContext.jsx         # Global state (useAnalysis hook)
│   ├── theme.js                    # Colour tokens (light/dark/Bloomberg Terminal)
│   ├── App.jsx                     # Main router and nav
│   └── index.css                   # TailwindCSS directives
├── package.json
└── vite.config.js
```

## Global State — AnalysisContext

The `useAnalysis()` hook provides:

```javascript
const {
  data,              // { normal_buckets, stress_buckets, position_detail, ... }
  runId,             // Current run UUID
  portfolio,         // Selected portfolio (for multi-portfolio runs)
  loading,           // Boolean — true while run is in progress
  error,             // Error message if run failed
  simResults,        // LMT simulation results (populated by LMT Simulator)
  setSimResults,     // Update LMT simulation results
} = useAnalysis();
```

State is initialized by uploading portfolio CSV files via the sidebar and clicking **Run Analysis**. The backend executes the full 8-step pipeline and returns results to the frontend.

## Pages

### All Portfolios
Cross-portfolio comparison table with NAV, LCR T+1/T+3/T+7, illiquid %, concentration ratio, days-to-liquidate, leverage ratio, and unified regulatory status badge for every fund.

### Dashboard
Fund-level summary: name, reporting date, 6 LCR KPI cards (T+1/T+3/T+7 normal & stressed), liquidity ladder chart (normal vs stressed bars), and detailed positions table with bucket badges and concentration flags.

### Stress Tests
Per-scenario NAV impact: equity/credit/rate loss components, liquid % before/after shock, days-to-liquidate. Expandable scenario config panel shows all ESMA parameters (equity shock, spread widening, rate shift, etc.). Sortable results table.

### Waterfall
Forced liquidation KPIs: target cash, gross proceeds, residual shortfall, NAV impact. Day-by-day proceeds chart by settlement bucket. Sell-order table shows execution sequence, haircuts applied, and net proceeds per position.

### Charts
7-chart matplotlib gallery:
1. Liquidity ladder — normal vs stressed (stacked bar)
2. Redemption heatmap — coverage % by scenario and horizon
3. Stress NAV impact — loss % per scenario
4. Time-to-liquidate — cumulative % NAV liquidated over days
5. Portfolio composition — donut chart by asset class
6. Waterfall cumulative proceeds — line chart over days
7. Concentration scatter — weight vs market value per position

### LMT Simulator
Interactive AIFMD II Liquidity Management Tools configurator and impact dashboard.

**Left panel — Tool Configurator:**
- **Always Available:** Suspension and Side Pockets (informational cards)
- **Quantitative Tools:** Gate, Notice Period Extension, Redemptions in Kind — each with toggle + parameter inputs
- **Anti-Dilution Tools:** Redemption Fee, Swing Pricing, Dual Pricing, ADL — each with toggle + parameter inputs
- AIFMD II compliance strip: count of selected tools, prohibition warning (swing pricing + dual pricing), Run Simulation button

**Right panel — Impact Dashboard:**
- **Coverage Table:** Per scenario (5/10/20/30% redemption), shows baseline vs configured shortfall, delta, and days-to-clear. Colour-coded (green/amber/red) by coverage change.
- **Investor Cost Summary:** Total bps charged (fee + swing factor + dual spread + ADL)
- **Recommendation Card:** Auto-generated guidance on coverage improvement and tool selection

When a simulation completes, `simResults` is populated and fed into the Redemption page's comparison table.

### Leverage
AIFMD II Article 15 gross leverage KPIs — gross method (CDR 231/2013 Art.7) and loan origination AIF detection (≥50% NAV in loans, 5% risk retention, 20% borrower concentration).

### Redemption
Liquidity coverage matrix across 4 redemption sizes (5/10/20/30%) and 3 time horizons (T+1/T+3/T+7) for both normal and worst-case (Severe Combined) scenarios. When `simResults` are populated by the LMT Simulator, this table compares baseline vs configured coverage side-by-side.

## Theme Switching

Three theme modes (toggle in top nav):
- **Light** — white background, dark text
- **Dark** — dark background, light text
- **Bloomberg Terminal** — green-on-black, monospace font

All charts, tables, and KPI cards are theme-aware via `theme.js` colour tokens. CSS is generated at build time by TailwindCSS; no runtime theme switching overhead.

## Building & Deploying

### Build for production
```bash
npm run build
```

Outputs minified assets to `dist/` for static hosting.

### Environment variables
Backend API URL is configured in `AnalysisContext.jsx`:
```javascript
const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:8080/api';
```

Set `REACT_APP_API_URL` environment variable at build time for different deployments.

### Hosting
Deploy the `dist/` folder to any static host (Vercel, Netlify, S3 + CloudFront, etc.). Backend API must be accessible from the frontend's origin (CORS-enabled).

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `react` | ^18 | UI framework |
| `vite` | ^5 | Build tool, dev server, HMR |
| `tailwindcss` | ^4.0 | Styling |
| `chart.js` | ^4 | Charts (line, bar, heatmap) |
| `react-chartjs-2` | ^5 | React wrapper for Chart.js |
| `axios` | ^1 | HTTP client for API calls |

## Development Notes

- **HMR** is enabled by default; code changes auto-refresh in the browser
- **ESLint** rules are configured in `vite.config.js` but not strict (warnings only)
- **No React Compiler:** Not enabled due to dev/build performance impact (see `vite.config.js` comment)
- **TailwindCSS v4:** Uses new CSS-first configuration; see `tailwind.config.js` for asset class colour mappings and breakpoints
- **API errors** are caught and displayed via the `error` state in `AnalysisContext`; user sees a red error banner
- **Loading states** show a spinner or skeleton loader while the backend is running

---

**Documentation:** See [../README.md](../README.md) for full system architecture, regulatory alignment, and theoretical background.
