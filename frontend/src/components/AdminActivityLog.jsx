import { useState, useEffect } from 'react'
import { Activity, Clock, User, Globe, RefreshCw, AlertTriangle } from 'lucide-react'
import { adminGetActivityLog, adminGetActivityStats } from '../api'
import { clsx } from 'clsx'

export default function AdminActivityLog({ pin }) {
  const [logs, setLogs] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(false)
  const [limit, setLimit] = useState(50)

  const load = () => {
    setLoading(true)
    Promise.all([
      adminGetActivityLog(pin, limit),
      adminGetActivityStats(pin),
    ]).then(([l, s]) => { setLogs(l); setStats(s) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [pin, limit])

  const durationColor = (ms) => {
    if (ms == null) return 'text-slate-600'
    if (ms < 500) return 'text-emerald-400'
    if (ms < 2000) return 'text-blue-400'
    if (ms < 5000) return 'text-amber-400'
    return 'text-red-400'
  }

  const statusColor = (code) => {
    if (!code) return 'text-slate-600'
    if (code < 300) return 'text-emerald-400'
    if (code < 400) return 'text-amber-400'
    return 'text-red-400'
  }

  return (
    <div className="glass rounded-xl overflow-hidden">
      <div className="px-4 py-3 bg-slate-800/50 border-b border-slate-700/50 flex items-center gap-2">
        <Activity className="w-4 h-4 text-brand-400" />
        <h2 className="text-sm font-semibold text-white">Activity Log</h2>
        {stats && (
          <div className="ml-2 flex items-center gap-3 text-[10px] text-slate-500">
            <span>{stats.last_24h} today</span>
            <span>{stats.unique_users} users</span>
            {stats.slow_queries > 0 && (
              <span className="text-amber-400 flex items-center gap-0.5">
                <AlertTriangle className="w-3 h-3" /> {stats.slow_queries} slow
              </span>
            )}
          </div>
        )}
        <div className="ml-auto flex items-center gap-2">
          <select value={limit} onChange={e => setLimit(+e.target.value)}
            className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-[10px] text-slate-400">
            <option value={50}>Last 50</option>
            <option value={100}>Last 100</option>
            <option value={500}>Last 500</option>
          </select>
          <button onClick={load} disabled={loading}
            className="p-1.5 rounded-lg hover:bg-slate-700 text-slate-500 hover:text-white transition">
            <RefreshCw className={clsx('w-3.5 h-3.5', loading && 'animate-spin')} />
          </button>
        </div>
      </div>

      <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
        <table className="w-full text-[11px]">
          <thead className="sticky top-0 bg-slate-900">
            <tr className="text-slate-500 border-b border-slate-800">
              <th className="text-left py-2 px-3 font-medium">Time</th>
              <th className="text-left py-2 px-3 font-medium">User</th>
              <th className="text-left py-2 px-3 font-medium">Endpoint</th>
              <th className="text-center py-2 px-3 font-medium">Status</th>
              <th className="text-right py-2 px-3 font-medium">Duration</th>
              <th className="text-left py-2 px-3 font-medium">IP</th>
            </tr>
          </thead>
          <tbody>
            {logs.map(l => (
              <tr key={l.id} className={clsx('border-b border-slate-800/30 hover:bg-slate-800/20',
                l.duration_ms > 5000 && 'bg-red-950/10')}>
                <td className="py-1.5 px-3 text-slate-500 font-mono whitespace-nowrap">
                  {l.timestamp?.replace('T', ' ').substring(5, 19)}
                </td>
                <td className="py-1.5 px-3 text-slate-300">
                  {l.user || <span className="text-slate-600">anon</span>}
                </td>
                <td className="py-1.5 px-3 text-slate-400 font-mono truncate max-w-[300px]" title={l.endpoint}>
                  <span className="text-slate-600 mr-1">{l.method}</span>
                  {l.endpoint}
                </td>
                <td className={clsx('py-1.5 px-3 text-center font-bold', statusColor(l.status_code))}>
                  {l.status_code || '—'}
                </td>
                <td className={clsx('py-1.5 px-3 text-right font-mono', durationColor(l.duration_ms))}>
                  {l.duration_ms != null ? (l.duration_ms > 1000 ? `${(l.duration_ms / 1000).toFixed(1)}s` : `${Math.round(l.duration_ms)}ms`) : '—'}
                </td>
                <td className="py-1.5 px-3 text-slate-600 font-mono">{l.ip || '—'}</td>
              </tr>
            ))}
            {logs.length === 0 && (
              <tr><td colSpan={6} className="py-8 text-center text-slate-600">No activity logged yet</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
