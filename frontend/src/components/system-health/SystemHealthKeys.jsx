import { useCallback, useEffect, useState } from 'react'
import { clsx } from 'clsx'
import { ExternalLink, KeyRound, Loader2, RefreshCw } from 'lucide-react'
import { adminSystemKeys, adminSystemKeysCheck } from '../../api'

const STATUS = {
  ok:      { label: 'Working',      cls: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400' },
  broken:  { label: 'Not working',  cls: 'border-rose-500/30 bg-rose-500/10 text-rose-400' },
  missing: { label: 'Not set',      cls: 'border-amber-500/30 bg-amber-500/10 text-amber-400' },
  unknown: { label: 'Not checked',  cls: 'border-slate-600 bg-slate-800/40 text-slate-400' },
}

// Admin → System Health → Keys: does each outside key still work, and where to fix it.
export default function SystemHealthKeys({ pin }) {
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async (fn) => {
    setBusy(true)
    setError('')
    try {
      setData(await fn(pin))
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Could not load key status')
    } finally {
      setBusy(false)
    }
  }, [pin])

  useEffect(() => { load(adminSystemKeys) }, [load])

  const results = data?.results || []
  const broken = results.filter((r) => r.status === 'broken')

  return (
    <div className="space-y-6">
      <div className="si-card-premium p-5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="flex items-center gap-1.5 text-[13px] font-bold uppercase tracking-wider text-indigo-300">
              <KeyRound className="h-4 w-4" /> Keys
            </h3>
            <p className="mt-1 text-[12px] text-slate-500">
              Each key is tested every hour. Admins get an email when one stops working.
              {data?.checked_at && <> Last check: {new Date(data.checked_at).toLocaleString()}{data.site ? ` on ${data.site}` : ''}.</>}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {data?.vault_url && <LinkButton href={data.vault_url}>Open Key Vault</LinkButton>}
            <button
              onClick={() => load(adminSystemKeysCheck)}
              disabled={busy}
              className="flex items-center gap-1.5 rounded-lg border border-indigo-400/30 bg-indigo-500/10 px-3.5 py-2 text-[12px] font-semibold text-indigo-300 transition hover:bg-indigo-500/20 disabled:opacity-50"
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              Check now
            </button>
          </div>
        </div>
        {error && <p className="mt-3 text-[12px] text-rose-400">{error}</p>}
        {broken.length > 0 && data?.restart_url && (
          <p className="mt-3 rounded-lg border border-rose-500/20 bg-rose-500/5 p-3 text-[12px] text-rose-300">
            To fix: open the key below, save a new value in the vault, then{' '}
            <a href={data.restart_url} target="_blank" rel="noopener noreferrer" className="underline">restart the live site</a>
            {' '}so it picks up the new value.
          </p>
        )}

        <div className="mt-4 divide-y divide-slate-700/40 rounded-lg border border-slate-700/40">
          {!data && busy && <div className="p-4 text-[12px] text-slate-500">Loading…</div>}
          {data && results.length === 0 && (
            <div className="p-4 text-[12px] text-slate-500">No check has run yet. Press “Check now”.</div>
          )}
          {results.map((r) => <KeyRow key={r.id} row={r} />)}
        </div>
      </div>

      <div className="si-card-premium p-5">
        <h3 className="text-[13px] font-bold uppercase tracking-wider text-indigo-300">Where everything lives</h3>
        <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2">
          {(data?.addresses || []).map((a) => (
            <a key={a.url} href={a.url} target="_blank" rel="noopener noreferrer"
               className="flex items-center justify-between gap-3 rounded-lg border border-slate-700/40 px-3 py-2 text-[12px] transition hover:bg-slate-800/50">
              <span className="text-slate-200">{a.label}</span>
              <span className="flex min-w-0 items-center gap-1 text-slate-500">
                <span className="truncate font-mono text-[10px]">{a.url.replace(/^https:\/\//, '').slice(0, 48)}</span>
                <ExternalLink className="h-3 w-3 shrink-0" />
              </span>
            </a>
          ))}
        </div>
      </div>
    </div>
  )
}

function KeyRow({ row }) {
  const s = STATUS[row.status] || STATUS.unknown
  return (
    <div className="flex flex-col gap-2 p-3 lg:flex-row lg:items-start lg:justify-between">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className={clsx('rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase', s.cls)}>{s.label}</span>
          <span className="text-[13px] font-semibold text-slate-100">{row.label}</span>
        </div>
        <p className={clsx('mt-1 text-[12px]', row.status === 'ok' ? 'text-slate-500' : 'text-slate-300')}>{row.message}</p>
        {row.status !== 'ok' && <p className="mt-0.5 text-[11px] text-slate-500">If it stays broken: {row.impact}</p>}
      </div>
      <div className="flex shrink-0 flex-wrap gap-1.5">
        {row.secrets.map((sec) => (
          <a key={sec.env} href={sec.url} target="_blank" rel="noopener noreferrer" title={`Edit ${sec.vault_name} in the Key Vault`}
             className="flex items-center gap-1 rounded border border-slate-700 px-2 py-1 font-mono text-[10px] text-slate-400 transition hover:bg-slate-800 hover:text-slate-100">
            {sec.vault_name} <ExternalLink className="h-3 w-3" />
          </a>
        ))}
      </div>
    </div>
  )
}

function LinkButton({ href, children }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer"
       className="flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/40 px-3.5 py-2 text-[12px] font-semibold text-slate-200 transition hover:bg-slate-800">
      {children} <ExternalLink className="h-3.5 w-3.5" />
    </a>
  )
}
