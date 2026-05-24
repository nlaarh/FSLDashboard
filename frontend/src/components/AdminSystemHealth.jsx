import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertCircle, Loader2, RefreshCw, ShieldCheck } from 'lucide-react'
import { adminSystemHealth, adminSystemHealthPing } from '../api'
import SystemHealthDetails from './system-health/SystemHealthDetails'
import SystemHealthTopology from './system-health/SystemHealthTopology'
import { StatusBadge, normalizeStatus } from './system-health/systemHealthUi'

const INITIAL_LOGS = [
  'Initializing tactical system health dashboard...',
  'Secure connection established with node controller.',
]

export default function AdminSystemHealth({ pin }) {
  const [health, setHealth] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [logs, setLogs] = useState(INITIAL_LOGS)
  const [pinging, setPinging] = useState({})
  const [lastUpdated, setLastUpdated] = useState(null)

  const appendLog = useCallback((message) => {
    const stamp = new Date().toLocaleTimeString()
    setLogs((items) => [`[${stamp}] ${message}`, ...items].slice(0, 60))
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await adminSystemHealth(pin)
      setHealth(data)
      setLastUpdated(new Date())
      setLogs((items) => [...(data.logs || []), ...items].slice(0, 60))
      appendLog(`System health queried: status matches ${normalizeStatus(data.status).toUpperCase()}`)
    } catch (err) {
      const message = err.response?.data?.detail || err.message || 'System health query failed'
      setError(message)
      appendLog(`[ERROR] Failed to query health: ${message}`)
    } finally {
      setLoading(false)
    }
  }, [appendLog, pin])

  useEffect(() => {
    load()
  }, [load])

  const counts = useMemo(() => {
    const items = Object.values(health?.services || {})
    return {
      online: items.filter((item) => normalizeStatus(item.status) === 'online').length,
      degraded: items.filter((item) => normalizeStatus(item.status) === 'degraded').length,
      offline: items.filter((item) => normalizeStatus(item.status) === 'offline').length,
    }
  }, [health])

  async function pingNode(serviceKey) {
    setPinging((prev) => ({ ...prev, [serviceKey]: true }))
    appendLog(`Sending safe health request to ${serviceKey.toUpperCase()} node...`)
    try {
      const result = await adminSystemHealthPing(pin, serviceKey)
      appendLog(`Reply from ${serviceKey.toUpperCase()} node: ${result.message} status=${normalizeStatus(result.status).toUpperCase()} live_ping=${result.live_ping}`)
      await load()
    } catch (err) {
      const message = err.response?.data?.detail || err.message || 'Ping failed'
      appendLog(`[WARN] Request failed for ${serviceKey.toUpperCase()} node: ${message}`)
    } finally {
      setPinging((prev) => ({ ...prev, [serviceKey]: false }))
    }
  }

  if (loading && !health) {
    return (
      <div className="flex h-[40vh] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-indigo-300" />
      </div>
    )
  }

  if (!health) {
    return (
      <div className="si-card-premium flex items-center gap-3 border-rose-500/20 p-5 text-rose-400">
        <AlertCircle className="h-5 w-5" />
        <div>
          <p className="text-sm font-semibold">System health failed to load.</p>
          <p className="text-xs">{error}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="si-card-premium si-animate-enter overflow-hidden p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 className="flex items-center gap-2 text-[15px] font-bold uppercase tracking-wider text-slate-100">
              <ShieldCheck className="h-5 w-5 text-indigo-300" />
              FSLPulse Tactical System Health
            </h2>
            <p className="mt-1 text-[12px] text-slate-500">
              No automatic paid-provider pings. Salesforce, Google Maps, OpenAI, GitHub, AgentMail, and Azure show configured status until a safe manual check is requested.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={health.status} />
            <span className="rounded-lg border border-slate-700 bg-slate-800/30 px-3 py-2 text-[11px] text-slate-500">
              Last updated: {lastUpdated ? lastUpdated.toLocaleString() : new Date(health.timestamp).toLocaleString()}
            </span>
            <button
              onClick={() => load()}
              disabled={loading}
              className="flex items-center gap-1.5 rounded-lg border border-indigo-400/30 bg-indigo-500/10 px-3.5 py-2 text-[12px] font-semibold text-indigo-300 transition hover:bg-indigo-500/20 disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-3 gap-3">
          <HudStat label="Online" value={counts.online} tone="text-emerald-400" />
          <HudStat label="Degraded" value={counts.degraded} tone="text-amber-400" />
          <HudStat label="Offline" value={counts.offline} tone="text-rose-400" />
        </div>
      </div>

      <SystemHealthTopology
        health={health}
        logs={logs}
        loading={loading}
        pinging={pinging}
        onRefresh={() => load()}
        onPing={(serviceKey) => pingNode(serviceKey)}
      />

      <SystemHealthDetails health={health} pin={pin} onRefresh={load} setSuccess={setSuccess} setError={setError} />

      {success && <Toast tone="success" message={success} />}
      {error && <Toast tone="error" message={error} />}
    </div>
  )
}

function HudStat({ label, value, tone }) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800/20 p-3">
      <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`mt-1 text-2xl font-bold tabular-nums ${tone}`}>{value}</p>
    </div>
  )
}

function Toast({ tone, message }) {
  return (
    <div className={`flex items-center gap-2 rounded-lg px-4 py-2.5 text-[13px] font-medium ${tone === 'success' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'}`}>
      {tone === 'success' ? <ShieldCheck className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
      {message}
    </div>
  )
}
