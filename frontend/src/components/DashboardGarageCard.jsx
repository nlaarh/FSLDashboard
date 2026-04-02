/**
 * DashboardGarageCard.jsx
 *
 * Extracted from Dashboard.jsx:
 * - statusMeta, color helpers
 * - MiniBar, COL_DEFS, Th, QuickActions, ExpandedRow, Stat
 * - AlertStrip, KPI
 *
 * These are the building-block components used by the Dashboard table.
 */

import { Fragment } from 'react'
import { clsx } from 'clsx'
import {
  Calendar, BarChart3, Map,
  AlertTriangle, Clock, CheckCircle2, ChevronUp, ChevronDown,
  ChevronRight, X, Phone, MapPin, Users,
} from 'lucide-react'

// ── Color helpers ─────────────────────────────────────────────────────────────

export const statusMeta = {
  critical: { label: 'Critical',   border: 'border-l-red-500',    bg: 'bg-red-500',     text: 'text-red-400',    dim: 'bg-red-950/20'   },
  behind:   { label: 'Behind',     border: 'border-l-amber-400',  bg: 'bg-amber-400',   text: 'text-amber-400',  dim: 'bg-amber-950/15' },
  good:     { label: 'Good',       border: 'border-l-emerald-500',bg: 'bg-emerald-500', text: 'text-emerald-400',dim: ''                },
  inactive: { label: 'No Data',    border: 'border-l-slate-700',  bg: 'bg-slate-600',   text: 'text-slate-500',  dim: ''                },
}

export function respColor(v) {
  if (v == null) return 'text-slate-600'
  return v <= 45 ? 'text-emerald-400' : v <= 70 ? 'text-amber-400' : 'text-red-400'
}
export function compColor(v) {
  if (v == null) return 'text-slate-600'
  return v >= 90 ? 'text-emerald-400' : v >= 75 ? 'text-amber-400' : 'text-red-400'
}
export function waitColor(v) {
  if (!v) return 'text-slate-600'
  return v > 90 ? 'text-red-400 font-bold' : v > 45 ? 'text-amber-400 font-semibold' : 'text-slate-400'
}


// ── Mini bar ──────────────────────────────────────────────────────────────────
export function MiniBar({ pct, color }) {
  return (
    <div className="mt-0.5 w-14 h-1 bg-slate-800 rounded-full overflow-hidden">
      <div className={clsx('h-full rounded-full', color)} style={{ width: `${Math.min(pct || 0, 100)}%` }} />
    </div>
  )
}

// ── Column definitions (for ? tooltips) ──────────────────────────────────────
export const COL_DEFS = {
  name:          'ServiceTerritory.Name — the garage/territory name in Salesforce.',
  city:          'ServiceTerritory.City — city from the territory address.',
  open:          'COUNT(ServiceAppointment.Id) WHERE ServiceAppointment.Status IN (\'Dispatched\',\'Assigned\') AND ServiceAppointment.ServiceTerritoryId = this garage AND ServiceAppointment.CreatedDate = today. These are SAs still waiting for a driver.',
  total:         'COUNT(ServiceAppointment.Id) WHERE ServiceAppointment.ServiceTerritoryId = this garage AND ServiceAppointment.CreatedDate = today. Includes all statuses.',
  completion:    'COUNT(ServiceAppointment.Status = \'Completed\') / Total * 100. Uses ServiceAppointment.Status to identify completed calls.',
  pct_primary:   '1st Call Completion: calls where ServiceAppointment.ERS_Spotting_Number__c = 1 (rank 1 = primary in ERS_Territory_Priority_Matrix__c zone chain). completion = COUNT(Status = \'Completed\') / COUNT(ERS_Spotting_Number__c = 1) * 100.',
  pct_secondary: '2nd+ Call Completion: calls where ServiceAppointment.ERS_Spotting_Number__c > 1 (backup — received after primary declined via cascade). completion = COUNT(Status = \'Completed\') / COUNT(ERS_Spotting_Number__c > 1) * 100.',
  avg_pta:       'AVG(ServiceAppointment.ERS_PTA__c) WHERE ServiceAppointment.ERS_PTA__c > 0 AND ServiceAppointment.ERS_PTA__c < 999 AND ServiceAppointment.CreatedDate = today. ERS_PTA__c = minutes promised to the member at dispatch.',
  resp_time:     'AVG(ServiceAppointment.ActualStartTime - ServiceAppointment.CreatedDate) in minutes, for Completed SAs today. Includes both Field Services and Towbook dispatches.',
  max_wait:      'MAX(NOW() - ServiceAppointment.CreatedDate) WHERE ServiceAppointment.Status IN (\'Dispatched\',\'Assigned\'). Longest current wait among open SAs — high values = stuck/delayed call.',
}

// ── Sort header ───────────────────────────────────────────────────────────────
export function Th({ label, col, sort, onSort, activeDef, setActiveDef, right = false }) {
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
            <button onClick={() => setActiveDef(null)} className="text-slate-400 hover:text-white text-xs shrink-0">&times;</button>
          </div>
          <div className="text-[11px] text-slate-300 leading-relaxed break-words">{def}</div>
        </div>
      )}
    </th>
  )
}

// ── Quick-action row ──────────────────────────────────────────────────────────
export function QuickActions({ id, name, onNav }) {
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
export function ExpandedRow({ row, onNav, onClose }) {
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
                value={row.avg_pta ? `${row.avg_pta} min` : '\u2014'}
                color={row.avg_pta && row.avg_pta <= 60 ? 'text-emerald-400' : row.avg_pta && row.avg_pta <= 90 ? 'text-amber-400' : 'text-red-400'}
                sub="Promised to member" />
              <Stat label="Avg ATA"
                value={row.resp_time ? `${row.resp_time} min` : '\u2014'}
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

export function Stat({ label, value, color = 'text-white', sub }) {
  return (
    <div>
      <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-0.5">{label}</div>
      <div className={clsx('text-lg font-bold', color)}>{value}</div>
      {sub && <div className={clsx('text-[10px] mt-0.5', color === 'text-red-400' ? 'text-red-400' : 'text-slate-500')}>{sub}</div>}
    </div>
  )
}

// ── Alert strip ───────────────────────────────────────────────────────────────
export function AlertStrip({ rows, onNav }) {
  const urgent = rows.filter(r => r.status === 'critical' || r.status === 'behind').slice(0, 6)
  if (urgent.length === 0) return null
  return (
    <div className="mb-4 p-3 rounded-xl border border-amber-800/30 bg-amber-950/10">
      <div className="flex items-center gap-2 mb-2.5">
        <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
        <span className="text-xs font-bold text-amber-300 uppercase tracking-wide">
          {urgent.filter(r => r.status === 'critical').length} Critical &middot;{' '}
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
export function KPI({ label, value, sub, icon: Icon, color = 'text-white', urgent }) {
  return (
    <div className={clsx(
      'rounded-xl p-4 border',
      urgent ? 'bg-red-950/20 border-red-800/30' : 'bg-slate-800/40 border-slate-700/30'
    )}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</span>
        {Icon && <Icon className="w-3.5 h-3.5 text-slate-600" />}
      </div>
      <div className={clsx('text-2xl font-black', color)}>{value ?? '\u2014'}</div>
      {sub && <div className="text-[11px] text-slate-500 mt-0.5">{sub}</div>}
    </div>
  )
}
