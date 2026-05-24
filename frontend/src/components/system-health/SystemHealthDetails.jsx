import { Cloud, Cpu, Database, Download, ExternalLink, HardDrive, Loader2, Search } from 'lucide-react'
import { useState } from 'react'
import { clsx } from 'clsx'
import { adminSystemHealthBackup } from '../../api'

export default function SystemHealthDetails({ health, pin, onRefresh, setSuccess, setError }) {
  const [query, setQuery] = useState('')
  const envRows = (health.environment?.variables || []).filter((row) => {
    const q = query.trim().toLowerCase()
    if (!q) return true
    return row.name.toLowerCase().includes(q) || String(row.masked || '').toLowerCase().includes(q)
  })

  return (
    <div className="space-y-6">
      <BackupConsole health={health} pin={pin} onRefresh={onRefresh} setSuccess={setSuccess} setError={setError} />

      <EnvironmentExplorer
        rows={envRows}
        files={health.environment?.files || []}
        query={query}
        onQuery={setQuery}
      />
    </div>
  )
}

function BackupConsole({ health, pin, onRefresh, setSuccess, setError }) {
  const backups = health.backup_recovery?.items || []
  const azure = health.backup_recovery?.azure || {}
  const [backing, setBacking] = useState(false)

  async function runBackup() {
    setBacking(true)
    try {
      const result = await adminSystemHealthBackup(pin)
      setSuccess(`Backup created: ${result.result}`)
      setTimeout(() => setSuccess(''), 5000)
      if (onRefresh) await onRefresh()
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Backup failed'
      setError(msg)
      setTimeout(() => setError(''), 5000)
    } finally {
      setBacking(false)
    }
  }

  return (
    <div className="si-card-premium si-animate-enter p-6">
      <div className="flex flex-col gap-4 border-b border-slate-700/40 pb-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="flex items-center gap-1.5 text-[13px] font-bold uppercase tracking-wider text-indigo-300">
            <Database className="h-4 w-4" />
            Database Backup & Recovery Console
          </h3>
          <p className="mt-0.5 text-[11px] text-slate-500">
            Export all critical Postgres tables to Azure Blob (or local fallback). Destructive restore is intentionally not wired here.
          </p>
        </div>
        <button
          onClick={runBackup}
          disabled={backing}
          className="flex items-center gap-1.5 rounded-lg border border-indigo-400/30 bg-indigo-500/10 px-3.5 py-2 text-[12px] font-semibold text-indigo-300 transition hover:bg-indigo-500/20 disabled:opacity-50"
        >
          {backing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
          {backing ? 'Backing up…' : 'Create Backup Snapshot'}
        </button>
      </div>
      <div className="mt-4">
        <div className="mb-2 flex items-center justify-between gap-3">
          <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-500">
            <HardDrive className="h-3.5 w-3.5" />
            Existing Recovery Points
          </div>
          <span className="rounded border border-slate-700 bg-slate-800/30 px-2 py-0.5 text-[10px] text-slate-500">
            {backups.length} found
          </span>
        </div>
        {backups.length ? (
          <div className="overflow-hidden rounded-lg border border-slate-700/60">
            {backups.map((backup) => (
              <BackupRow key={backup.id || backup.name || backup.path} backup={backup} />
            ))}
          </div>
        ) : (
          <div className="rounded-lg border border-slate-700/60 bg-slate-950/30 p-4 text-[12px] text-slate-500">
            No backups found. Azure configured: {azure.configured ? 'yes' : 'no'}
            {azure.error ? ` — ${azure.error}` : ''}
            {' '}Click "Create Backup Snapshot" to generate one.
          </div>
        )}
      </div>
    </div>
  )
}

function BackupRow({ backup }) {
  const modified = backup.last_modified ? new Date(backup.last_modified).toLocaleString() : 'Unknown time'
  const size = formatBytes(backup.size_bytes)
  return (
    <div className="flex flex-col gap-3 border-b border-slate-800/70 bg-slate-950/30 px-4 py-3 last:border-b-0 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          {backup.source === 'Azure Blob' ? <Cloud className="h-4 w-4 text-sky-400" /> : <HardDrive className="h-4 w-4 text-emerald-400" />}
          <span className="truncate font-mono text-[11px] font-semibold text-slate-100">
            {backup.file_name || backup.name}
          </span>
        </div>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-slate-500">
          <span>{backup.source || 'Backup'}</span>
          <span>{modified}</span>
          <span>{size}</span>
          {backup.path && <span className="font-mono">{backup.path}</span>}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {backup.open_url && (
          <a
            href={backup.open_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 rounded-lg border border-indigo-400/25 bg-indigo-500/10 px-2.5 py-1.5 text-[11px] font-semibold text-indigo-300 transition hover:bg-indigo-500/20"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            Open
          </a>
        )}
        <span className="rounded border border-emerald-500/20 bg-emerald-500/10 px-2 py-1 text-[10px] font-bold uppercase text-emerald-400">
          Recoverable
        </span>
      </div>
    </div>
  )
}

function formatBytes(value) {
  const bytes = Number(value || 0)
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`
}

function EnvironmentExplorer({ rows, files, query, onQuery }) {
  return (
    <div className="si-card-premium si-animate-enter p-6">
      <div className="flex flex-col gap-4 border-b border-slate-700/40 pb-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="flex items-center gap-1.5 text-[13px] font-bold uppercase tracking-wider text-indigo-300">
            <Cpu className="h-4 w-4" />
            System Environment Configuration Explorer
          </h3>
          <p className="mt-0.5 text-[11px] text-slate-500">
            Securely view environment flags and configuration settings. Sensitive secrets are masked automatically.
          </p>
        </div>
        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-500/60" />
          <input
            type="text"
            placeholder="Search variables..."
            value={query}
            onChange={(event) => onQuery(event.target.value)}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/30 px-3 py-2 pl-9 text-[12px] font-medium text-slate-100 outline-none transition-colors placeholder:text-slate-500 focus:border-indigo-400/50 sm:w-60"
          />
        </div>
      </div>

      <div className="mt-4 max-h-[300px] overflow-x-auto overflow-y-auto">
        <table className="w-full text-left text-[12px]">
          <thead>
            <tr className="border-b border-slate-700 bg-slate-800/10 text-[10px] uppercase tracking-wide text-slate-500">
              <th className="px-4 py-2.5">Variable</th>
              <th className="px-4 py-2.5">Masked Value</th>
              <th className="px-4 py-2.5 text-right">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.name} className="border-b border-slate-700/50 transition hover:bg-slate-800/10">
                <td className="px-4 py-3 font-mono text-[11px] font-semibold text-slate-100">{row.name}</td>
                <td className="px-4 py-3 font-mono text-[11px] text-slate-500">{row.masked || 'Not configured'}</td>
                <td className="px-4 py-3 text-right">
                  <span className={clsx(
                    'rounded border px-2 py-0.5 text-[10px] font-bold uppercase',
                    row.configured ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400' : 'border-rose-500/20 bg-rose-500/10 text-rose-400',
                  )}>
                    {row.configured ? 'Configured' : 'Missing'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-2 md:grid-cols-2">
        {files.map((file) => (
          <div key={file.path} className="rounded-lg border border-slate-700 bg-slate-800/20 px-3 py-2 text-[11px]">
            <div className="font-mono text-slate-100">{file.path}</div>
            <div className={file.exists ? 'text-emerald-400' : 'text-slate-500'}>
              {file.exists ? `${file.keys_count} keys loaded` : 'File not found'}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
