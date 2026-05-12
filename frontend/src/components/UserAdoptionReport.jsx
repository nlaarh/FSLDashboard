import { useEffect, useMemo, useState } from 'react'
import { Activity, Clock, Loader2, RefreshCw, Users, ChevronUp, ChevronDown } from 'lucide-react'
import { fetchUserAdoptionReport } from '../api'

const fmtDateTime = (epoch) => {
  if (!epoch) return '—'
  return new Date(epoch * 1000).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

const fmtDuration = (minutes) => {
  const mins = Math.max(0, Math.round(minutes || 0))
  if (mins < 60) return `${mins}m`
  const hours = Math.floor(mins / 60)
  const rem = mins % 60
  return rem ? `${hours}h ${rem}m` : `${hours}h`
}

function Stat({ label, value, icon: Icon, tone = 'text-slate-200' }) {
  return (
    <div className="glass rounded-xl border border-slate-700/50 p-4">
      <div className="flex items-center gap-2 text-slate-500 text-xs font-semibold uppercase tracking-wider">
        <Icon className="w-4 h-4" />
        {label}
      </div>
      <div className={`mt-2 text-2xl font-bold ${tone}`}>{value}</div>
    </div>
  )
}

export default function UserAdoptionReport() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [sortCol, setSortCol] = useState('name')
  const [sortDir, setSortDir] = useState('asc')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      setData(await fetchUserAdoptionReport())
    } catch (e) {
      setError(e.response?.data?.detail || 'Unable to load user adoption report')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleSort = (col) => {
    if (sortCol === col) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortCol(col)
      setSortDir(col === 'name' || col === 'role' ? 'asc' : 'desc')
    }
  }

  const rows = data?.rows || []

  const { stats, sortedRows } = useMemo(() => {
    const activeUsers = rows.filter(r => r.active)
    const loggedIn = rows.filter(r => r.status === 'logged_in')
    const adopted = rows.filter(r => r.session_count > 0)
    const minutes = rows.reduce((sum, r) => sum + (r.minutes_this_month || 0), 0)

    // Augment rows with computed avg_min for sorting
    const augmented = rows.map(r => ({
      ...r,
      avg_min: r.session_count > 0 ? r.minutes_this_month / r.session_count : -1,
      status_sort: r.status === 'logged_in' ? 0 : 1,
    }))

    const sorted = [...augmented].sort((a, b) => {
      let va = a[sortCol], vb = b[sortCol]
      if (va == null) va = typeof vb === 'number' ? -Infinity : ''
      if (vb == null) vb = typeof va === 'number' ? -Infinity : ''
      if (typeof va === 'number' && typeof vb === 'number') {
        return sortDir === 'asc' ? va - vb : vb - va
      }
      const sa = String(va).toLowerCase(), sb = String(vb).toLowerCase()
      return sortDir === 'asc' ? sa.localeCompare(sb) : sb.localeCompare(sa)
    })

    return {
      stats: {
        users: activeUsers.length,
        loggedIn: loggedIn.length,
        adopted: adopted.length,
        adoptionPct: activeUsers.length ? Math.round(adopted.length / activeUsers.length * 100) : 0,
        minutes,
      },
      sortedRows: sorted,
    }
  }, [rows, sortCol, sortDir])

  if (loading) {
    return (
      <div className="glass rounded-xl border border-slate-700/50 h-48 flex items-center justify-center gap-3 text-slate-400">
        <Loader2 className="w-6 h-6 animate-spin" />
        <span className="text-sm">Loading user adoption…</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="glass rounded-xl border border-red-500/30 p-6 text-red-400 text-sm">
        {error}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Stat label="Active Users" value={stats.users} icon={Users} />
        <Stat label="Logged In Now" value={stats.loggedIn} icon={Activity} tone="text-emerald-400" />
        <Stat label="Adopted This Month" value={`${stats.adoptionPct}%`} icon={RefreshCw} tone="text-brand-400" />
        <Stat label="Time This Month" value={fmtDuration(stats.minutes)} icon={Clock} tone="text-amber-300" />
      </div>

      <div className="glass rounded-xl border border-slate-700/50 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-700/50 flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-slate-200">User Adoption</p>
            <p className="text-xs text-slate-500 mt-0.5">
              Current month only · generated {fmtDateTime(data?.generated_at)}
            </p>
          </div>
          <button
            onClick={load}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-slate-600/50 text-slate-300 hover:bg-slate-800/60 transition-all">
            <RefreshCw className="w-3.5 h-3.5" />Refresh
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-slate-700/50 bg-slate-900/50">
                {[
                  { key: 'name',               label: 'User',             align: 'left'   },
                  { key: 'status_sort',         label: 'Status',           align: 'center' },
                  { key: 'last_login',          label: 'Last Login',       align: 'center' },
                  { key: 'last_seen',           label: 'Last Active',      align: 'center' },
                  { key: 'session_count',       label: 'Sessions',         align: 'center' },
                  { key: 'minutes_this_month',  label: 'Time This Month',  align: 'center' },
                  { key: 'avg_min',             label: 'Avg Session',      align: 'center' },
                ].map(({ key, label, align }) => (
                  <th
                    key={key}
                    onClick={() => handleSort(key)}
                    className={`px-3 py-2 text-${align} text-xs font-semibold text-slate-400 uppercase tracking-wider cursor-pointer select-none hover:text-slate-200 transition-colors`}>
                    <span className="inline-flex items-center gap-0.5">
                      {label}
                      {sortCol === key
                        ? sortDir === 'asc'
                          ? <ChevronUp className="w-3 h-3 text-brand-400" />
                          : <ChevronDown className="w-3 h-3 text-brand-400" />
                        : <ChevronDown className="w-3 h-3 text-slate-700" />
                      }
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedRows.map((row, i) => {
                const avgMin = row.session_count > 0 ? row.minutes_this_month / row.session_count : null
                const isOnline = row.status === 'logged_in'
                return (
                  <tr key={row.username} className={`border-b border-slate-800/50 hover:bg-slate-800/30 ${i % 2 ? 'bg-slate-900/20' : ''}`}>
                    <td className="px-3 py-2">
                      <div className="font-medium text-slate-200">{row.name || row.username}</div>
                      <div className="text-[11px] text-slate-500">
                        {row.role}{row.department ? ` · ${row.department}` : ''}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-center">
                      {isOnline ? (
                        <div>
                          <span className="px-2 py-0.5 rounded text-[10px] font-bold border bg-emerald-500/10 text-emerald-400 border-emerald-500/20">
                            Online
                          </span>
                          {row.active_since && (
                            <div className="text-[10px] text-slate-500 mt-0.5">since {fmtDateTime(row.active_since)}</div>
                          )}
                        </div>
                      ) : (
                        <span className="px-2 py-0.5 rounded text-[10px] font-bold border bg-slate-700/30 text-slate-500 border-slate-700/40">
                          Offline
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-center text-slate-300 text-xs">{fmtDateTime(row.last_login)}</td>
                    <td className="px-3 py-2 text-center text-slate-300 text-xs">{fmtDateTime(row.last_seen)}</td>
                    <td className="px-3 py-2 text-center text-slate-300">{row.session_count || '—'}</td>
                    <td className="px-3 py-2 text-center font-semibold text-slate-200">
                      {row.minutes_this_month > 0 ? fmtDuration(row.minutes_this_month) : '—'}
                    </td>
                    <td className="px-3 py-2 text-center text-slate-400 text-xs">
                      {avgMin !== null ? fmtDuration(avgMin) : '—'}
                    </td>
                  </tr>
                )
              })}
              {rows.length === 0 && (
                <tr><td colSpan={7} className="py-8 text-center text-slate-600">No users found</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
