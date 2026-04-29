import { useState, useEffect, Fragment } from 'react'
import { Activity, CheckCircle, AlertTriangle, XCircle, RefreshCw } from 'lucide-react'
import { adminGetOptimizerSyncAudit } from '../api'

const STATUS_ICON = {
  success: <CheckCircle size={13} className="text-green-400" />,
  partial: <AlertTriangle size={13} className="text-yellow-400" />,
  failed: <XCircle size={13} className="text-red-400" />,
  running: <RefreshCw size={13} className="text-blue-400 animate-spin" />,
}

const STATUS_COLOR = {
  success: 'text-green-400',
  partial: 'text-yellow-400',
  failed: 'text-red-400',
  running: 'text-blue-400',
}

function fmtTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

export default function AdminOptimizerSync() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(null)

  const load = async () => {
    setLoading(true)
    try {
      const data = await adminGetOptimizerSyncAudit(50)
      setRows(data)
    } catch {
      // silently ignore — sync may not be running yet
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  return (
    <div className="glass rounded-xl overflow-hidden">
      <div className="px-4 py-3 bg-slate-800/50 border-b border-slate-700/50 flex items-center gap-2">
        <Activity className="w-4 h-4 text-brand-400" />
        <h2 className="text-sm font-semibold text-white">Optimizer Sync Audit</h2>
        <button
          onClick={load}
          className="ml-auto flex items-center gap-1 text-xs text-gray-400 hover:text-white transition-colors"
        >
          <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      <div className="p-4">
        {loading && rows.length === 0 ? (
          <div className="text-xs text-gray-500 text-center py-4">Loading sync history…</div>
        ) : rows.length === 0 ? (
          <div className="text-xs text-gray-500 text-center py-4">
            No sync records yet. The optimizer sync starts automatically with the server.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-white/10 text-right">
                  <th className="text-left pb-1.5 pr-3 font-medium">Time</th>
                  <th className="text-left pb-1.5 pr-3 font-medium">Status</th>
                  <th className="pb-1.5 pr-3 font-medium">Found</th>
                  <th className="pb-1.5 pr-3 font-medium">Stored</th>
                  <th className="pb-1.5 pr-3 font-medium">Skipped</th>
                  <th className="pb-1.5 pr-3 font-medium">Failed</th>
                  <th className="pb-1.5 pr-3 font-medium">Verdicts</th>
                  <th className="pb-1.5 font-medium">Duration</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => (
                  <Fragment key={r.id}>
                    <tr
                      className={`border-b border-white/5 transition-colors ${r.error_detail ? 'cursor-pointer hover:bg-white/5' : ''}`}
                      onClick={() => r.error_detail && setExpanded(expanded === r.id ? null : r.id)}
                    >
                      <td className="py-1.5 pr-3 text-gray-400 whitespace-nowrap">{fmtTime(r.started_at)}</td>
                      <td className="py-1.5 pr-3">
                        <span className="flex items-center gap-1">
                          {STATUS_ICON[r.status] ?? <AlertTriangle size={13} className="text-gray-500" />}
                          <span className={STATUS_COLOR[r.status] ?? 'text-gray-400'}>{r.status}</span>
                          {r.error_detail && (
                            <span className="text-[10px] text-gray-600 ml-1">▼</span>
                          )}
                        </span>
                      </td>
                      <td className="py-1.5 pr-3 text-right text-gray-300">{r.runs_found ?? '—'}</td>
                      <td className="py-1.5 pr-3 text-right text-green-400">{r.runs_inserted ?? '—'}</td>
                      <td className="py-1.5 pr-3 text-right text-gray-500">{r.runs_skipped ?? '—'}</td>
                      <td className="py-1.5 pr-3 text-right text-red-400">{r.runs_failed > 0 ? r.runs_failed : '—'}</td>
                      <td className="py-1.5 pr-3 text-right text-gray-400">
                        {r.verdicts_inserted != null ? r.verdicts_inserted.toLocaleString() : '—'}
                      </td>
                      <td className="py-1.5 text-right text-gray-500">
                        {r.duration_ms != null ? `${(r.duration_ms / 1000).toFixed(1)}s` : '—'}
                      </td>
                    </tr>
                    {expanded === r.id && r.error_detail && (
                      <tr>
                        <td colSpan={8} className="py-2 px-3 bg-red-950/30">
                          <div className="text-[11px] text-red-300 font-mono break-all">{r.error_detail}</div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
