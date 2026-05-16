export default function EmptyState({ message = 'Upload CSV files and run an analysis to see results.' }) {
  return (
    <div className="flex flex-col items-center justify-center h-64" style={{ color: 'var(--text-muted)' }}>
      <svg className="mb-3 h-10 w-10" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
          d="M9 17v-2m3 2v-4m3 4v-6M4 20h16a1 1 0 001-1V5a1 1 0 00-1-1H4a1 1 0 00-1 1v14a1 1 0 001 1z" />
      </svg>
      <p className="text-sm">{message}</p>
    </div>
  )
}
