import { useState } from 'react'

const FILES = [
  {
    label: 'Holdings CSV',
    required: true,
    naming: 'Any name ending in .csv — e.g. HOLDINGS_20260101120000.csv',
    delimiter: 'Semicolon ( ; )',
    decimal: 'European format — comma as decimal, period as thousands separator (e.g. 1.234.567,89)',
    columns: [
      { name: 'Portfolio Code', required: true,  example: 'AL-A',            notes: 'Identifies which portfolio the row belongs to' },
      { name: 'Date',           required: true,  example: '01/05/2026',       notes: 'Reporting date — day-first format (DD/MM/YYYY)' },
      { name: 'ISIN',           required: false, example: 'DE0001102549',     notes: 'Security identifier; use CASH-EUR for cash rows' },
      { name: 'Security Name',  required: false, example: 'BUND 2030',        notes: 'Used to infer asset class and bond maturity' },
      { name: 'Currency',       required: false, example: 'EUR',              notes: 'Position currency; defaults to EUR if missing' },
      { name: 'Market Value in Base Currency', required: true, example: '1.234.567,00', notes: 'EUR market value — European decimal format' },
      { name: 'PriceFactor',    required: false, example: '0,01',             notes: '0.01 = bond (quoted as % of par), 1.0 = equity/ETF' },
      { name: 'Exchange rate',  required: false, example: '1,0823',           notes: 'FX rate to base currency; defaults to 1 if missing' },
      { name: 'Product Code',   required: false, example: 'FTFDAX',           notes: 'Used to detect futures / options' },
      { name: 'CustomSecurityCode', required: false, example: 'CASH-EUR',     notes: 'Fallback identifier when ISIN is absent' },
      { name: 'Exposure (base)',required: false, example: '-500.000,00',      notes: 'Notional for derivatives; used when Market Value = 0' },
    ],
  },
  {
    label: 'NAV CSV',
    required: true,
    naming: 'Any name ending in .csv — e.g. NAV_20260101120000.csv',
    delimiter: 'Semicolon ( ; )',
    decimal: 'European format',
    columns: [
      { name: 'PortfolioCode  (or "Portfolio Code" / "Fund Code")', required: true,  example: 'AL-A',           notes: 'Must match the codes in the Holdings file' },
      { name: 'TotalAssets  (or "NAV" / "Total NAV" / "Amount")',   required: true,  example: '125.000.000,00', notes: 'Total fund NAV — used to compute position weights' },
    ],
    notes: 'Column names are matched case-insensitively. Any recognised synonym is accepted.',
  },
  {
    label: 'Market Data CSV (optional)',
    required: false,
    naming: 'Any name ending in .csv',
    delimiter: 'Comma ( , )',
    decimal: 'Standard (period as decimal)',
    columns: [
      { name: 'isin',               required: true,  example: 'DE0001102549', notes: 'Must match ISINs in the Holdings file' },
      { name: 'portfolio',          required: false, example: 'AL-A',         notes: 'If present, rows are matched to the correct fund' },
      { name: 'asset_class_hint',   required: false, example: 'government_bond', notes: 'Overrides the inferred asset class' },
      { name: 'adv_30d_eur',        required: false, example: '30000000',     notes: '30-day average daily volume in EUR' },
      { name: 'bid_ask_spread_bps', required: false, example: '4',            notes: 'Bid-ask spread in basis points' },
      { name: 'modified_duration',  required: false, example: '4.5',          notes: 'Modified duration (bonds only)' },
      { name: 'convexity',          required: false, example: '0.25',         notes: 'Convexity (bonds only)' },
      { name: 'beta',               required: false, example: '0.9',          notes: 'Equity beta (equities only)' },
      { name: 'fx_rate_to_eur',     required: false, example: '1.0823',       notes: 'FX rate to EUR' },
    ],
    notes: 'All columns except isin are optional. Missing values fall back to asset-class defaults.',
  },
]

const ASSET_CLASSES = [
  { value: 'cash',              adv: '1,000,000,000+', spread: '0 bps' },
  { value: 'government_bond',   adv: '30,000,000',     spread: '4 bps' },
  { value: 'ig_corporate_bond', adv: '5,000,000',      spread: '20 bps' },
  { value: 'hy_corporate_bond', adv: '1,000,000',      spread: '100 bps' },
  { value: 'listed_equity',     adv: '10,000,000',     spread: '2 bps' },
  { value: 'etf',               adv: '10,000,000',     spread: '15 bps' },
  { value: 'future',            adv: '200,000,000',    spread: '3 bps' },
  { value: 'option',            adv: '10,000,000',     spread: '25 bps' },
  { value: 'money_market',      adv: '50,000,000',     spread: '1 bps' },
  { value: 'structured_credit', adv: '500,000',        spread: '60 bps' },
  { value: 'real_estate',       adv: '0 (illiquid)',   spread: '200 bps' },
  { value: 'private_equity',    adv: '0 (illiquid)',   spread: '300 bps' },
]

export default function InfoModal() {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState(0)

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title="File format reference"
        style={{ color: 'var(--text-secondary)', border: '1px solid var(--border)', background: 'var(--bg-panel)' }}
        className="rounded-full w-7 h-7 text-sm font-bold flex items-center justify-center hover:opacity-80 transition-opacity shrink-0"
      >
        i
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: 'rgba(0,0,0,0.5)' }}
          onClick={(e) => e.target === e.currentTarget && setOpen(false)}
        >
          <div className="rounded-xl shadow-2xl flex flex-col w-full max-w-4xl max-h-[85vh]"
            style={{ background: 'var(--bg-panel)', color: 'var(--text-primary)', border: '1px solid var(--border)' }}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 shrink-0"
              style={{ borderBottom: '1px solid var(--border)' }}>
              <h2 className="font-semibold text-base">File Format Reference</h2>
              <button onClick={() => setOpen(false)}
                style={{ color: 'var(--text-secondary)' }}
                className="text-xl leading-none hover:opacity-70 cursor-pointer">×</button>
            </div>

            {/* Tabs */}
            <div className="flex gap-1 px-6 pt-3 shrink-0">
              {[...FILES.map(f => f.label), 'Asset Class Defaults'].map((t, i) => (
                <button key={i} onClick={() => setTab(i)}
                  style={tab === i
                    ? { background: 'var(--text-accent)', color: '#fff' }
                    : { background: 'var(--bg-surface)', color: 'var(--text-secondary)', border: '1px solid var(--border)' }
                  }
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors cursor-pointer whitespace-nowrap">
                  {t}
                </button>
              ))}
            </div>

            {/* Body */}
            <div className="overflow-auto flex-1 px-6 py-4">
              {tab < FILES.length ? (
                <FileTab file={FILES[tab]} />
              ) : (
                <AssetDefaultsTab />
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function FileTab({ file }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 text-sm">
        <Meta label="Required" value={file.required ? 'Yes' : 'No (optional)'} />
        <Meta label="Delimiter" value={file.delimiter} />
        <Meta label="Decimal format" value={file.decimal} />
        <Meta label="Naming" value={file.naming} />
      </div>

      {file.notes && (
        <p className="text-xs rounded-lg px-3 py-2"
          style={{ background: 'var(--bg-surface)', color: 'var(--text-secondary)' }}>
          {file.notes}
        </p>
      )}

      <table className="w-full text-xs border-collapse">
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
            <th className="text-left py-2 pr-4 font-semibold w-56">Column name</th>
            <th className="text-left py-2 pr-4 font-semibold w-20">Required</th>
            <th className="text-left py-2 pr-4 font-semibold w-32">Example</th>
            <th className="text-left py-2 font-semibold">Notes</th>
          </tr>
        </thead>
        <tbody>
          {file.columns.map((col) => (
            <tr key={col.name} style={{ borderBottom: '1px solid var(--border)' }}>
              <td className="py-2 pr-4 font-mono" style={{ color: 'var(--text-accent)' }}>{col.name}</td>
              <td className="py-2 pr-4" style={{ color: col.required ? 'var(--text-primary)' : 'var(--text-secondary)' }}>
                {col.required ? 'Yes' : 'No'}
              </td>
              <td className="py-2 pr-4 font-mono" style={{ color: 'var(--text-secondary)' }}>{col.example}</td>
              <td className="py-2" style={{ color: 'var(--text-secondary)' }}>{col.notes}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AssetDefaultsTab() {
  return (
    <div className="space-y-3">
      <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
        When no Market Data CSV is provided, these defaults are used. Supply a Market Data CSV to override per-position.
      </p>
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
            <th className="text-left py-2 pr-6 font-semibold">Asset class</th>
            <th className="text-left py-2 pr-6 font-semibold">Default ADV (EUR)</th>
            <th className="text-left py-2 font-semibold">Default bid-ask spread</th>
          </tr>
        </thead>
        <tbody>
          {ASSET_CLASSES.map((ac) => (
            <tr key={ac.value} style={{ borderBottom: '1px solid var(--border)' }}>
              <td className="py-2 pr-6 font-mono" style={{ color: 'var(--text-accent)' }}>{ac.value}</td>
              <td className="py-2 pr-6" style={{ color: 'var(--text-secondary)' }}>{ac.adv}</td>
              <td className="py-2" style={{ color: 'var(--text-secondary)' }}>{ac.spread}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Meta({ label, value }) {
  return (
    <div className="rounded-lg px-3 py-2" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
      <div className="text-xs font-semibold mb-0.5" style={{ color: 'var(--text-secondary)' }}>{label}</div>
      <div className="text-xs" style={{ color: 'var(--text-primary)' }}>{value}</div>
    </div>
  )
}
