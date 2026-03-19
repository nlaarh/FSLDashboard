import { useState, useEffect, useMemo, useCallback, useRef, Fragment } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchGarages, fetchOpsTerritories } from '../api'
import { clsx } from 'clsx'
import {
  Search, Calendar, BarChart3, Map,
  AlertTriangle, Clock, CheckCircle2, ChevronUp, ChevronDown,
  Activity, Flame, RefreshCw, ChevronRight, X,
  Phone, MapPin, Zap, Circle, Users,
} from 'lucide-react'

// ── Color helpers ─────────────────────────────────────────────────────────────

const statusMeta = {
  critical: { label: 'Critical',   border: 'border-l-red-500',    bg: 'bg-red-500',     text: 'text-red-400',    dim: 'bg-red-950/20'   },
  behind:   { label: 'Behind',     border: 'border-l-amber-400',  bg: 'bg-amber-400',   text: 'text-amber-400',  dim: 'bg-amber-950/15' },
  good:     { label: 'Good',       border: 'border-l-emerald-500',bg: 'bg-emerald-500', text: 'text-emerald-400',dim: ''                },
  inactive: { label: 'No Data',    border: 'border-l-slate-700',  bg: 'bg-slate-600',   text: 'text-slate-500',  dim: ''                },
}

function respColor(v) {
  if (v == null) return 'text-slate-600'
  return v <= 45 ? 'text-emerald-400' : v <= 70 ? 'text-amber-400' : 'text-red-400'
}
function compColor(v) {
  if (v == null) return 'text-slate-600'
  return v >= 90 ? 'text-emerald-400' : v >= 75 ? 'text-amber-400' : 'text-red-400'
}
function waitColor(v) {
  if (!v) return 'text-slate-600'
  return v > 90 ? 'text-red-400 font-bold' : v > 45 ? 'text-amber-400 font-semibold' : 'text-slate-400'
}


// ── Mini bar ──────────────────────────────────────────────────────────────────
function MiniBar({ pct, color }) {
  return (
    <div className="mt-0.5 w-14 h-1 bg-slate-800 rounded-full overflow-hidden">
      <div className={clsx('h-full rounded-full', color)} style={{ width: `${Math.min(pct || 0, 100)}%` }} />
    </div>
  )
}

// ── Column definitions (for ? tooltips) ──────────────────────────────────────
const COL_DEFS = {
  name:          'ServiceTerritory.Name — the garage/territory name in Salesforce.',
  city:          'ServiceTerritory.City — city from the territory address.',
  open:          'COUNT(ServiceAppointment.Id) WHERE ServiceAppointment.Status IN (\'Dispatched\',\'Assigned\') AND ServiceAppointment.ServiceTerritoryId = this garage AND ServiceAppointment.CreatedDate = today. These are SAs still waiting for a driver.',
  total:         'COUNT(ServiceAppointment.Id) WHERE ServiceAppointment.ServiceTerritoryId = this garage AND ServiceAppointment.CreatedDate = today. Includes all statuses.',
  completion:    'COUNT(ServiceAppointment.Status = \'Completed\') ÷ Total × 100. Uses ServiceAppointment.Status to identify completed calls.',
  pct_primary:   '1st Call Completion: calls where ServiceAppointment.ERS_Spotting_Number__c = 1 (rank 1 = primary in ERS_Territory_Priority_Matrix__c zone chain). completion = COUNT(Status = \'Completed\') ÷ COUNT(ERS_Spotting_Number__c = 1) × 100.',
  pct_secondary: '2nd+ Call Completion: calls where ServiceAppointment.ERS_Spotting_Number__c > 1 (backup — received after primary declined via cascade). completion = COUNT(Status = \'Completed\') ÷ COUNT(ERS_Spotting_Number__c > 1) × 100.',
  avg_pta:       'AVG(ServiceAppointment.ERS_PTA__c) WHERE ServiceAppointment.ERS_PTA__c > 0 AND ServiceAppointment.ERS_PTA__c < 999 AND ServiceAppointment.CreatedDate = today. ERS_PTA__c = minutes promised to the member at dispatch.',
  resp_time:     'AVG(ServiceAppointment.ActualStartTime − ServiceAppointment.CreatedDate) in minutes, for Completed SAs today. Includes both Field Services and Towbook dispatches.',
  max_wait:      'MAX(NOW() − ServiceAppointment.CreatedDate) WHERE ServiceAppointment.Status IN (\'Dispatched\',\'Assigned\'). Longest current wait among open SAs — high values = stuck/delayed call.',
}

// ── Sort header ───────────────────────────────────────────────────────────────
function Th({ label, col, sort, onSort, activeDef, setActiveDef, right = false }) {
  const active = sort.col === col
  const def = COL_DEFS[col]
  const showDef = activeDef === col
  return (
    <th className={clsx(
        'px-3 py-3 text-[10px] font-semibold uppercase tracking-wider cursor-pointer select-none whitespace-nowrap relative',
        'hover:text-slate-200 transition-colors',
        right ? 'text-right' : 'text-left',
        active ? 'text-brand-400' : 'text-slate-500'
      )}>
      <span onClick={() => onSort(col)}>
        {label}
        {active
          ? sort.dir === 'asc'
            ? <ChevronUp   className="inline w-3 h-3 ml-0.5 -mt-0.5" />
            : <ChevronDown className="inline w-3 h-3 ml-0.5 -mt-0.5" />
          : <span className="inline-block w-3 ml-0.5" />}
      </span>
      {def && (
        <button onClick={e => { e.stopPropagation(); setActiveDef(showDef ? null : col) }}
          className="ml-1 w-3.5 h-3.5 rounded-full bg-slate-700/60 hover:bg-slate-600 text-slate-500 hover:text-white
                     text-[8px] font-bold inline-flex items-center justify-center transition-colors align-middle"
          title="How this is calculated">?</button>
      )}
      {showDef && def && (
        <div className="absolute top-full left-0 z-50 w-56 max-w-[90vw] bg-slate-800 border border-slate-600/50 rounded-xl p-3 shadow-xl mt-1 whitespace-normal break-words overflow-hidden"
          onClick={e => e.stopPropagation()}>
          <div className="flex items-center justify-between mb-1 gap-2">
            <span className="text-[10px] font-bold text-brand-400 uppercase truncate">{label}</span>
            <button onClick={() => setActiveDef(null)} className="text-slate-400 hover:text-white text-xs shrink-0">✕</button>
          </div>
          <div className="text-[11px] text-slate-300 leading-relaxed break-words">{def}</div>
        </div>
      )}
    </th>
  )
}

// ── Quick-action row ──────────────────────────────────────────────────────────
function QuickActions({ id, name, onNav }) {
  const btns = [
    { icon: Calendar,  label: 'Schedule',  tab: 'schedule'  },
    { icon: BarChart3, label: 'Dashboard', tab: 'dashboard' },
    { icon: Map,       label: 'Map',       tab: 'dispatch'  },
  ]
  return (
    <div className="flex gap-1 justify-end">
      {btns.map(b => (
        <button key={b.tab}
          onClick={e => { e.stopPropagation(); onNav(id, b.tab, name) }}
          className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium
                     text-slate-400 hover:text-white hover:bg-brand-600/30 hover:border-brand-500/40
                     border border-transparent transition-all whitespace-nowrap">
          <b.icon className="w-3 h-3 shrink-0" />
          {b.label}
        </button>
      ))}
    </div>
  )
}

// ── Expanded row detail ───────────────────────────────────────────────────────
function ExpandedRow({ row, onNav, onClose }) {
  return (
    <tr className="bg-slate-900/80">
      <td colSpan={12} className="px-4 pb-4 pt-2">
        <div className="flex items-start gap-6">

          {/* Status + location */}
          <div className="min-w-[140px]">
            <div className={clsx('text-xs font-bold mb-1', statusMeta[row.status]?.text)}>
              {statusMeta[row.status]?.label}
            </div>
            {row.city && (
              <div className="flex items-center gap-1 text-xs text-slate-500">
                <MapPin className="w-3 h-3" />{row.city}{row.state ? `, ${row.state}` : ''}
              </div>
            )}
            <div className="text-xs text-slate-600 mt-1">{row.total} SAs today</div>
          </div>

          {/* Live stats grid */}
          {row.hasLive ? (
            <div className="grid grid-cols-5 gap-4 flex-1">
              <Stat label="Open Now"    value={row.open}
                color={row.open > 5 ? 'text-red-400' : row.open > 0 ? 'text-amber-400' : 'text-slate-400'} />
              <Stat label="Completed Today" value={`${row.completed} / ${row.total}`}
                color="text-slate-300" />
              <Stat label="Avg PTA (Promise)"
                value={row.avg_pta ? `${row.avg_pta} min` : '—'}
                color={row.avg_pta && row.avg_pta <= 60 ? 'text-emerald-400' : row.avg_pta && row.avg_pta <= 90 ? 'text-amber-400' : 'text-red-400'}
                sub="Promised to member" />
              <Stat label="Avg ATA"
                value={row.resp_time ? `${row.resp_time} min` : '—'}
                color={respColor(row.resp_time)}
                sub={row.resp_source === 'ata' ? `Actual (${row.ata_sample} calls)` : 'Estimated (PTA)'} />
            </div>
          ) : (
            <div className="text-xs text-slate-600 flex-1 flex items-center">
              No activity in the last 24 hours
            </div>
          )}

          {/* Navigation */}
          <div className="flex flex-col gap-1.5 min-w-[130px]">
            {[
              { icon: Calendar,   label: 'View Schedule',    tab: 'schedule'     },
              { icon: BarChart3,  label: 'Dashboard',         tab: 'dashboard'    },
              { icon: Map,        label: 'Dispatch Map',      tab: 'dispatch'     },
            ].map(b => (
              <button key={b.tab}
                onClick={e => { e.stopPropagation(); onNav(row.id, b.tab, row.name) }}
                className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs font-medium
                           text-slate-400 hover:text-white hover:bg-slate-700 transition-all text-left">
                <b.icon className="w-3.5 h-3.5 shrink-0" />{b.label}
              </button>
            ))}
          </div>

          <button onClick={onClose}
            className="text-slate-600 hover:text-slate-400 transition-colors mt-0.5">
            <X className="w-4 h-4" />
          </button>
        </div>
      </td>
    </tr>
  )
}

function Stat({ label, value, color = 'text-white', sub }) {
  return (
    <div>
      <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-0.5">{label}</div>
      <div className={clsx('text-lg font-bold', color)}>{value}</div>
      {sub && <div className={clsx('text-[10px] mt-0.5', color === 'text-red-400' ? 'text-red-400' : 'text-slate-500')}>{sub}</div>}
    </div>
  )
}

// ── Alert strip ───────────────────────────────────────────────────────────────
function AlertStrip({ rows, onNav }) {
  const urgent = rows.filter(r => r.status === 'critical' || r.status === 'behind').slice(0, 6)
  if (urgent.length === 0) return null
  return (
    <div className="mb-4 p-3 rounded-xl border border-amber-800/30 bg-amber-950/10">
      <div className="flex items-center gap-2 mb-2.5">
        <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
        <span className="text-xs font-bold text-amber-300 uppercase tracking-wide">
          {urgent.filter(r => r.status === 'critical').length} Critical ·{' '}
          {urgent.filter(r => r.status === 'behind').length} Behind — Needs Attention
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        {urgent.map(r => (
          <div key={r.id}
            className={clsx(
              'flex items-center gap-2 px-3 py-2 rounded-lg border text-xs cursor-pointer',
              'hover:bg-slate-800/60 transition-colors',
              r.status === 'critical'
                ? 'bg-red-950/30 border-red-800/40'
                : 'bg-amber-950/20 border-amber-800/30'
            )}
            onClick={() => onNav(r.id, 'dashboard', r.name)}>
            <span className={clsx('w-2 h-2 rounded-full shrink-0',
              r.status === 'critical' ? 'bg-red-500' : 'bg-amber-400')} />
            <span className="font-semibold text-white max-w-[160px] truncate">{r.name}</span>
            {r.avg_pta != null && (
              <span className={r.avg_pta <= 60 ? 'text-emerald-400' : r.avg_pta <= 90 ? 'text-amber-400' : 'text-red-400'}>PTA {r.avg_pta}m</span>
            )}
            {r.max_wait > 60 && (
              <span className="text-red-400 font-semibold">{r.max_wait} min wait!</span>
            )}
            <ChevronRight className="w-3 h-3 text-slate-600" />
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Summary KPI tiles ─────────────────────────────────────────────────────────
function KPI({ label, value, sub, icon: Icon, color = 'text-white', urgent }) {
  return (
    <div className={clsx(
      'rounded-xl p-4 border',
      urgent ? 'bg-red-950/20 border-red-800/30' : 'bg-slate-800/40 border-slate-700/30'
    )}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</span>
        {Icon && <Icon className="w-3.5 h-3.5 text-slate-600" />}
      </div>
      <div className={clsx('text-2xl font-black', color)}>{value ?? '—'}</div>
      {sub && <div className="text-[11px] text-slate-500 mt-0.5">{sub}</div>}
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

const SORT_DEF = {
  status: 'asc', name: 'asc', city: 'asc',
  open: 'desc', total: 'desc', completion: 'asc',
  avg_pta: 'desc', resp_time: 'desc', pct_primary: 'desc', pct_secondary: 'desc', max_wait: 'desc',
}
const STATUS_RANK = { critical: 0, behind: 1, good: 2, inactive: 3 }

export default function Dashboard() {
  const [garages,    setGarages]    = useState([])
  const [ccData,     setCcData]     = useState(null)
  const [garLoading, setGarLoading] = useState(true)
  const [ccLoading,  setCcLoading]  = useState(false)
  const [garError,   setGarError]   = useState(null)
  const [ccError,    setCcError]    = useState(null)
  const [search,     setSearch]     = useState('')
  const [sort,       setSort]       = useState({ col: 'status', dir: 'asc' })
  const [expanded,   setExpanded]   = useState(null)   // garage id
  const [activeDef,  setActiveDef]  = useState(null)   // which column tooltip is open
  const [lastUpdate, setLastUpdate] = useState(null)
  const navigate = useNavigate()
  const refreshRef = useRef(null)

  // ── Fetch garages (independent) ─────────────────────────────────────────────
  useEffect(() => {
    setGarLoading(true)
    setGarError(null)
    fetchGarages()
      .then(setGarages)
      .catch(e => setGarError(e.message))
      .finally(() => setGarLoading(false))
  }, [])

  // ── Fetch live data (independent, can retry) ─────────────────────────────────
  const loadLive = useCallback(() => {
    setCcLoading(true)
    setCcError(null)
    fetchOpsTerritories()
      .then(data => { setCcData(data); setLastUpdate(new Date()); setCcError(null) })
      .catch(e => { console.error('Live data fetch failed:', e); setCcError(e.message || 'Failed to load live data') })
      .finally(() => setCcLoading(false))
  }, [])

  useEffect(() => { loadLive() }, [loadLive])

  // Auto-refresh every 2 min
  useEffect(() => {
    refreshRef.current = setInterval(loadLive, 120_000)
    return () => clearInterval(refreshRef.current)
  }, [loadLive])

  // ── Merge ────────────────────────────────────────────────────────────────────
  const rows = useMemo(() => {
    const ccByT = {}
    if (ccData) for (const t of ccData.territories) ccByT[t.id] = t
    return garages.map(g => {
      const live = ccByT[g.id] ?? null
      return {
        ...g,
        status:       live?.status            ?? 'inactive',
        open:         live?.open              ?? 0,
        total:        live?.total             ?? 0,
        completed:    live?.completed         ?? 0,
        completion:   live?.completion_rate   ?? null,
        avg_pta:      live?.avg_pta           ?? null,
        avg_ata:      live?.avg_ata           ?? null,
        pta_sample:   live?.pta_sample_size   ?? 0,
        ata_sample:   live?.ata_sample_size   ?? 0,
        resp_time:    live?.resp_time         ?? null,
        resp_source:  live?.resp_source       ?? null,
        avg_wait:     live?.avg_wait          ?? 0,
        max_wait:     live?.max_wait          ?? 0,
        avail_drivers: live?.avail_drivers    ?? null,
        capacity:     live?.capacity          ?? null,
        pct_primary:  live?.pct_primary_completion  ?? null,
        primary_n:    live?.primary_total    ?? 0,
        pct_secondary: live?.pct_secondary_completion ?? null,
        secondary_n:  live?.secondary_total  ?? 0,
        hasLive:      !!live,
      }
    })
  }, [garages, ccData])

  // ── Sort + filter ─────────────────────────────────────────────────────────────
  const sorted = useMemo(() => {
    const q = search.toLowerCase()
    const filtered = rows.filter(r =>
      !q || r.name?.toLowerCase().includes(q) || r.city?.toLowerCase().includes(q)
    )
    return [...filtered].sort((a, b) => {
      let av, bv
      if (sort.col === 'status') { av = STATUS_RANK[a.status] ?? 9; bv = STATUS_RANK[b.status] ?? 9 }
      else if (sort.col === 'name' || sort.col === 'city') { av = (a[sort.col] ?? ''); bv = (b[sort.col] ?? '') }
      else { av = a[sort.col] ?? -1; bv = b[sort.col] ?? -1 }
      const cmp = typeof av === 'string' ? av.localeCompare(bv) : av - bv
      return sort.dir === 'asc' ? cmp : -cmp
    })
  }, [rows, search, sort])

  function onSort(col) {
    setSort(prev => prev.col === col
      ? { col, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
      : { col, dir: SORT_DEF[col] ?? 'asc' }
    )
  }

  const onNav = (id, tab, name) => navigate(`/garage/${id}?tab=${tab}${name ? '&name=' + encodeURIComponent(name) : ''}`)

  // ── Summary ───────────────────────────────────────────────────────────────────
  const active   = rows.filter(r => r.hasLive)
  const critical = active.filter(r => r.status === 'critical').length
  const behind   = active.filter(r => r.status === 'behind').length
  const totalOpen= active.reduce((s, r) => s + r.open, 0)
  const maxWait  = active.reduce((m, r) => Math.max(m, r.max_wait), 0)
  const avgComp  = active.length
    ? Math.round(active.reduce((s, r) => s + (r.completion ?? 0), 0) / active.length)
    : null
  const ptaVals  = active.map(r => r.avg_pta).filter(Boolean)
  const fleetPta = ptaVals.length ? Math.round(ptaVals.reduce((s, v) => s + v, 0) / ptaVals.length) : null
  const overCap  = active.filter(r => r.capacity === 'over').length
  const busyCap  = active.filter(r => r.capacity === 'busy').length

  const minAgo = lastUpdate
    ? Math.round((new Date() - lastUpdate) / 60000)
    : null

  return (
    <div>
      {/* ── Header ────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-2xl font-bold text-white">Garage Operations</h1>
          <p className="text-slate-500 text-xs mt-0.5">
            {garages.length} territories
            {lastUpdate && ` · Live data updated ${minAgo === 0 ? 'just now' : `${minAgo}m ago`}`}
          </p>
        </div>
        <button onClick={loadLive} disabled={ccLoading}
          className="flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700
                     text-slate-400 hover:text-white text-xs font-medium transition-all disabled:opacity-50">
          <RefreshCw className={clsx('w-3.5 h-3.5', ccLoading && 'animate-spin')} />
          {ccLoading ? 'Refreshing…' : 'Refresh Live'}
        </button>
      </div>

      {/* ── Summary KPIs ──────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-4">
        <KPI label="Active Today" value={active.length}
          sub={`of ${garages.length} territories`} icon={Activity} />
        <KPI label="Critical" value={critical}
          sub={critical > 0 ? 'Need immediate action' : 'All clear'}
          color={critical > 0 ? 'text-red-400' : 'text-emerald-400'}
          icon={Flame} urgent={critical > 0} />
        <KPI label="Behind" value={behind}
          sub="Slow but not critical"
          color={behind > 0 ? 'text-amber-400' : 'text-slate-500'}
          icon={AlertTriangle} />
        <KPI label="Open Right Now" value={totalOpen}
          sub="across all territories" icon={Phone}
          color={totalOpen > 20 ? 'text-red-400' : 'text-white'} />
        <KPI label="Over Capacity" value={overCap > 0 ? `${overCap} garage${overCap > 1 ? 's' : ''}` : 'None'}
          sub={busyCap > 0 ? `${busyCap} more busy` : 'All garages staffed'}
          color={overCap > 0 ? 'text-red-400' : 'text-emerald-400'}
          icon={Users} urgent={overCap > 0} />
        <KPI label="Fleet Avg PTA" value={fleetPta != null ? `${fleetPta} min` : '—'}
          sub="Avg promise to member"
          color={fleetPta && fleetPta <= 60 ? 'text-emerald-400' : fleetPta && fleetPta <= 90 ? 'text-amber-400' : 'text-red-400'}
          icon={Clock} />
      </div>

      {/* ── Live data error banner ────────────────────────────────────── */}
      {ccError && !ccLoading && (
        <div className="mb-4 px-4 py-2.5 rounded-xl border border-amber-800/30 bg-amber-950/10 flex items-center gap-2">
          <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
          <span className="text-xs text-amber-300">Live data temporarily unavailable</span>
          <span className="text-[10px] text-slate-500 ml-1">— garage list still shown from last load</span>
        </div>
      )}

      {/* ── Alerts ────────────────────────────────────────────────────── */}
      {!garLoading && <AlertStrip rows={sorted} onNav={onNav} />}

      {/* ── Search ────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 mb-3">
        <div className="relative max-w-xs flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
          <input value={search} onChange={e => { setSearch(e.target.value); setExpanded(null) }}
            placeholder="Search garage or city…"
            className="w-full pl-9 pr-4 py-2 bg-slate-900 border border-slate-700 rounded-xl text-sm
                       placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-brand-500/40 transition-all" />
        </div>
        {garError && (
          <div className="text-xs text-red-400 flex items-center gap-1">
            <AlertTriangle className="w-3.5 h-3.5" />
            Failed to load garages: {garError}
          </div>
        )}
        <div className="ml-auto text-[10px] text-slate-600 text-right">
          Click row to expand · Click icon to open tab directly
        </div>
      </div>

      {/* ── Table ─────────────────────────────────────────────────────── */}
      <div className="glass rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800">
                <th className="w-2 px-0" />{/* status border */}
                <th className="px-1 py-3 text-[10px] font-semibold uppercase tracking-wider text-slate-500 text-right w-5">#</th>
                <Th label="Garage"     col="name"         sort={sort} onSort={onSort} activeDef={activeDef} setActiveDef={setActiveDef} />
                <Th label="City"       col="city"         sort={sort} onSort={onSort} activeDef={activeDef} setActiveDef={setActiveDef} />
                <Th label="Open"       col="open"         sort={sort} onSort={onSort} activeDef={activeDef} setActiveDef={setActiveDef} />
                <Th label="Today"      col="total"        sort={sort} onSort={onSort} activeDef={activeDef} setActiveDef={setActiveDef} />
                <Th label="Done %"     col="completion"   sort={sort} onSort={onSort} activeDef={activeDef} setActiveDef={setActiveDef} />
                <Th label="1st Call %" col="pct_primary"  sort={sort} onSort={onSort} activeDef={activeDef} setActiveDef={setActiveDef} />
                <Th label="2nd+ Call %" col="pct_secondary" sort={sort} onSort={onSort} activeDef={activeDef} setActiveDef={setActiveDef} />
                <Th label="Avg PTA"    col="avg_pta"      sort={sort} onSort={onSort} activeDef={activeDef} setActiveDef={setActiveDef} />
                <Th label="Avg ATA"    col="resp_time"    sort={sort} onSort={onSort} activeDef={activeDef} setActiveDef={setActiveDef} />
                <Th label="Max Wait"   col="max_wait"     sort={sort} onSort={onSort} activeDef={activeDef} setActiveDef={setActiveDef} />
                <th className="px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-slate-500 text-right">
                  Actions
                </th>
              </tr>
            </thead>

            <tbody className="divide-y divide-slate-800/40">

              {/* Loading skeletons */}
              {garLoading && [...Array(10)].map((_, i) => (
                <tr key={i}>
                  <td className="w-1 py-3 bg-slate-700/30" />
                  <td className="px-2 py-3"><div className="skeleton h-3 rounded w-4" /></td>
                  {[...Array(10)].map((__, j) => (
                    <td key={j} className="px-3 py-3.5">
                      <div className={clsx('skeleton h-3.5 rounded', j === 0 ? 'w-40' : 'w-16')} />
                    </td>
                  ))}
                </tr>
              ))}

              {!garLoading && sorted.map((r, idx) => {
                const sm = statusMeta[r.status] || statusMeta.inactive
                const isExpanded = expanded === r.id

                return (
                  <Fragment key={r.id}>
                    <tr onClick={() => setExpanded(isExpanded ? null : r.id)}
                      className={clsx(
                        'cursor-pointer transition-colors group',
                        isExpanded
                          ? 'bg-slate-800/70'
                          : 'hover:bg-slate-800/40',
                      )}>

                      {/* Status left border */}
                      <td className={clsx('w-1 p-0 border-l-2', sm.border)} />
                      <td className="px-1 py-2 align-top text-[10px] text-slate-500 text-right">{idx + 1}</td>

                      {/* Name */}
                      <td className="px-3 py-3 align-top">
                        <div className="font-semibold text-white text-sm leading-tight max-w-[280px] truncate flex items-center gap-1.5">
                          {r.name}
                          {r.primary_zones > 0 && (
                            <span className="shrink-0 px-1.5 py-0.5 rounded text-[8px] font-bold uppercase tracking-wide bg-emerald-950/40 text-emerald-400 border border-emerald-800/30">Primary</span>
                          )}
                          {!r.primary_zones && r.secondary_zones > 0 && (
                            <span className="shrink-0 px-1.5 py-0.5 rounded text-[8px] font-bold uppercase tracking-wide bg-amber-950/40 text-amber-400 border border-amber-800/30">Secondary</span>
                          )}
                          {r.capacity === 'over' && (
                            <span className="shrink-0 px-1.5 py-0.5 rounded text-[8px] font-bold uppercase tracking-wide bg-red-950/60 text-red-400 border border-red-800/30 animate-pulse">Over Cap</span>
                          )}
                          {r.capacity === 'busy' && (
                            <span className="shrink-0 px-1.5 py-0.5 rounded text-[8px] font-bold uppercase tracking-wide bg-amber-950/50 text-amber-400 border border-amber-800/30">Busy</span>
                          )}
                        </div>
                        <div className={clsx('text-[10px] font-medium mt-0.5 h-3.5', sm.text)}>
                          {r.status === 'critical' ? '⚠ Needs attention' : r.status === 'behind' ? 'Falling behind' : '\u00A0'}
                        </div>
                      </td>

                      {/* City */}
                      <td className="px-3 py-3 align-top text-xs text-slate-500 whitespace-nowrap">
                        {r.city ?? '—'}
                      </td>

                      {/* Open */}
                      <td className="px-3 py-3 align-top">
                        {r.hasLive
                          ? <div>
                              <span className={clsx(
                                'inline-flex items-center justify-center min-w-[1.5rem] h-6 px-1.5 rounded-full text-xs font-bold',
                                r.open > 5  ? 'bg-red-950/60 text-red-300 ring-1 ring-red-700/40' :
                                r.open > 0  ? 'bg-amber-950/50 text-amber-300' :
                                              'text-slate-600'
                              )}>{r.open}</span>
                              {r.avail_drivers != null && (
                                <div className="text-[10px] text-slate-600 mt-0.5">{r.avail_drivers} drv</div>
                              )}
                            </div>
                          : <span className="text-slate-700 text-xs">—</span>}
                      </td>

                      {/* Total today */}
                      <td className="px-3 py-3 align-top text-slate-300 font-medium">
                        {r.hasLive ? r.total : <span className="text-slate-700 text-xs">—</span>}
                      </td>

                      {/* Completion % */}
                      <td className="px-3 py-3 align-top">
                        {r.completion != null
                          ? <div>
                              <span className={clsx('font-bold', compColor(r.completion))}>
                                {r.completion}%
                              </span>
                              <MiniBar pct={r.completion}
                                color={r.completion >= 90 ? 'bg-emerald-500' : r.completion >= 75 ? 'bg-amber-500' : 'bg-red-500'} />
                            </div>
                          : <span className="text-slate-700 text-xs">—</span>}
                      </td>

                      {/* 1st Call % (primary) */}
                      <td className="px-3 py-3 align-top">
                        <div className="font-bold leading-tight">
                          {r.pct_primary != null
                            ? <span className={r.pct_primary >= 80 ? 'text-emerald-400' : r.pct_primary >= 60 ? 'text-amber-400' : 'text-red-400'}>
                                {r.pct_primary}%
                              </span>
                            : <span className="text-slate-700 text-xs">—</span>}
                        </div>
                        <div className="text-[10px] text-slate-600 h-3.5">{r.primary_n ? `${r.primary_n} calls` : '\u00A0'}</div>
                      </td>

                      {/* 2nd+ Call % (secondary) */}
                      <td className="px-3 py-3 align-top">
                        <div className="font-bold leading-tight">
                          {r.pct_secondary != null
                            ? <span className={r.pct_secondary >= 80 ? 'text-emerald-400' : r.pct_secondary >= 60 ? 'text-amber-400' : 'text-red-400'}>
                                {r.pct_secondary}%
                              </span>
                            : <span className="text-slate-700 text-xs">—</span>}
                        </div>
                        <div className="text-[10px] text-slate-600 h-3.5">{r.secondary_n ? `${r.secondary_n} calls` : '\u00A0'}</div>
                      </td>

                      {/* Avg PTA (Promise) */}
                      <td className="px-3 py-3 align-top">
                        <div className="font-bold leading-tight">
                          {r.avg_pta != null
                            ? <span className={r.avg_pta <= 60 ? 'text-emerald-400' : r.avg_pta <= 90 ? 'text-amber-400' : 'text-red-400'}>
                                {r.avg_pta} min
                              </span>
                            : <span className="text-slate-700 text-xs">—</span>}
                        </div>
                        <div className="text-[10px] text-slate-600 h-3.5">{r.pta_sample ? `${r.pta_sample} promised` : '\u00A0'}</div>
                      </td>

                      {/* Avg ATA (actual response time) */}
                      <td className="px-3 py-3 align-top">
                        <div className="font-bold leading-tight">
                          {r.resp_time != null
                            ? <span className={respColor(r.resp_time)}>
                                {r.resp_time} min
                              </span>
                            : <span className="text-slate-700 text-xs">—</span>}
                        </div>
                        <div className="text-[10px] text-slate-600 h-3.5">
                          {r.resp_time != null
                            ? (r.resp_source === 'ata' ? `actual (${r.ata_sample})` : 'est. (PTA)')
                            : '\u00A0'}
                        </div>
                      </td>

                      {/* Max wait */}
                      <td className="px-3 py-3 align-top">
                        <div className="font-bold leading-tight">
                          {r.max_wait > 0
                            ? <span className={waitColor(r.max_wait)}>{r.max_wait} min</span>
                            : <span className="text-slate-700 text-xs">—</span>}
                        </div>
                        <div className="h-3.5">{'\u00A0'}</div>
                      </td>

                      {/* Quick actions */}
                      <td className="px-3 py-3 align-top" onClick={e => e.stopPropagation()}>
                        <QuickActions id={r.id} name={r.name} onNav={onNav} />
                      </td>
                    </tr>

                    {/* Expanded row */}
                    {isExpanded && (
                      <ExpandedRow row={r} onNav={onNav}
                        onClose={() => setExpanded(null)} />
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Empty state */}
        {!garLoading && sorted.length === 0 && (
          <div className="text-center py-16 text-slate-600 text-sm">
            {search ? 'No garages match your search.' : garError ? 'Failed to load garages.' : 'No garages found.'}
          </div>
        )}

        {/* Footer */}
        {!garLoading && sorted.length > 0 && (
          <div className="px-4 py-2.5 border-t border-slate-800/60 flex items-center justify-between">
            <span className="text-[10px] text-slate-600">
              {sorted.length} of {garages.length} garages
              {!ccData && !ccLoading && ' · Live data unavailable'}
            </span>
            <div className="flex items-center gap-4 text-[10px] text-slate-600">
              {[
                { color: 'bg-red-500',    label: 'Critical'    },
                { color: 'bg-amber-400',  label: 'Behind'      },
                { color: 'bg-emerald-500',label: 'On track'    },
                { color: 'bg-slate-600',  label: 'No activity' },
              ].map(s => (
                <span key={s.label} className="flex items-center gap-1.5">
                  <span className={clsx('w-1.5 h-4 rounded-sm inline-block', s.color)} />
                  {s.label}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
