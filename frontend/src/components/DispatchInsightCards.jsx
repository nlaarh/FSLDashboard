import React, { useState, useMemo } from 'react'
import { clsx } from 'clsx'
import {
  Loader2, CheckCircle2, ChevronRight, X, Zap, Shield, Navigation,
  TrendingUp, AlertCircle, ArrowRight, Eye,
} from 'lucide-react'
import SALink from './SALink'
import { fetchHumanIntervention, fetchGpsDetail, fetchStatusDetail } from '../api'
import { InfoTip, DrillDown, MiniDonut, fmtMin } from './CommandCenterUtils'
import { SADetailRow } from './DispatchDrillDowns'

export function DispatchSplitCard({ data }) {
  const { no_human_count, no_human_pct, human_count, total, auto_count, auto_pct, manual_count, fleet_total } = data
  const [drillData, setDrillData] = useState(null)
  const [drillLoading, setDrillLoading] = useState(false)
  const [drillError, setDrillError] = useState(null)
  const [drillTab, setDrillTab] = useState(null) // null | 'manual' | 'auto' | 'platform_manual' | 'platform_auto'

  const openDrill = (tab) => {
    if (drillTab === tab) { setDrillTab(null); return }
    setDrillTab(tab)
    if (!drillData && !drillLoading) {
      setDrillLoading(true)
      fetchHumanIntervention()
        .then(setDrillData)
        .catch(e => setDrillError(e.message || 'Failed'))
        .finally(() => setDrillLoading(false))
    }
  }

  // Filter drill list based on active tab
  const drillList = useMemo(() => {
    if (!drillData) return []
    if (drillTab === 'manual') return drillData.human
    if (drillTab === 'auto') return drillData.auto
    if (drillTab === 'platform_manual') return drillData.human.filter(sa => sa.dispatch_method === 'Field Services')
    if (drillTab === 'platform_auto') return drillData.auto.filter(sa => sa.dispatch_method === 'Field Services')
    return []
  }, [drillData, drillTab])

  // Group by dispatcher for platform_manual tab
  const drillGrouped = useMemo(() => {
    if (drillTab !== 'platform_manual' || !drillList.length) return null
    const grouped = {}
    drillList.forEach(sa => {
      const d = sa.dispatcher || 'System'
      if (!grouped[d]) grouped[d] = []
      grouped[d].push(sa)
    })
    return Object.entries(grouped).sort((a, b) => b[1].length - a[1].length)
  }, [drillList, drillTab])

  const drillTitle = drillTab === 'platform_manual' ? `On-Platform Manual (${drillList.length})`
    : drillTab === 'platform_auto' ? `On-Platform Auto (${drillList.length})`
    : drillTab === 'manual' ? `Manual Dispatch (${drillData?.human_count ?? human_count})`
    : `Auto Dispatch (${drillData?.auto_count ?? no_human_count})`

  return (
    <div className={clsx('glass rounded-xl border border-slate-700/30 p-4 overflow-visible', drillTab && 'relative z-20')}>
      <div className="flex items-center gap-2 mb-3">
        <Zap className="w-4 h-4 text-emerald-400" />
        <span className="text-xs font-bold text-white uppercase tracking-wide">System vs Manual Dispatch</span>
        <InfoTip text={"Auto Dispatch % across ALL ERS calls today.\n\nAuto Dispatch = the SA went through its entire lifecycle without a human dispatcher (Membership User) making any status change in ServiceAppointmentHistory. This applies to both FSL Platform calls (fleet + on-platform contractors) and Towbook (off-platform garages).\n\nManual Dispatch = a dispatcher touched the SA at any point — initial manual assignment, reassignment after rejection/decline, etc.\n\nBreakdown:\n• FSL auto/manual = calls on the FSL platform (fleet trucks + on-platform contractor drivers)\n• Towbook auto/manual = calls sent to off-platform garages via Towbook\n\nHistorical avg: ~60% auto / ~40% manual (Jan–Mar 2026)."} />
        <span className="text-[10px] text-slate-500 ml-auto">{total} calls</span>
      </div>

      {/* Two donuts: Total (all channels) + On-Platform only */}
      <div className="grid grid-cols-2 gap-3">
        {/* All Channels — uses existing drill tab toggle */}
        <div className="flex flex-col items-center">
          <div className="text-[9px] text-slate-500 uppercase tracking-wide mb-1.5">All Channels</div>
          <MiniDonut pct={no_human_pct} size={56} stroke={6} autoColor="#10b981" manualColor="#334155" />
          <div className="w-full mt-2 space-y-0.5">
            <div className={clsx('flex items-center gap-1.5 rounded px-1 py-0.5 cursor-pointer hover:bg-slate-800/40',
              drillTab === 'auto' && 'bg-slate-800/40')}
              onClick={() => openDrill('auto')}>
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              <span className="text-[10px] text-slate-400 flex-1">Auto</span>
              <span className="text-xs font-bold text-white">{no_human_count}</span>
            </div>
            <div className={clsx('flex items-center gap-1.5 rounded px-1 py-0.5 cursor-pointer hover:bg-slate-800/40',
              drillTab === 'manual' && 'bg-slate-800/40')}
              onClick={() => openDrill('manual')}>
              <span className="w-2 h-2 rounded-full bg-amber-500" />
              <span className="text-[10px] text-slate-400 flex-1">Manual</span>
              <span className="text-xs font-bold text-white">{human_count}</span>
            </div>
          </div>
          <div className="text-[9px] text-slate-600 mt-1">{total} calls</div>
        </div>

        {/* On-Platform — Eye icon per row, drill-down renders full-width below grid */}
        <div className="flex flex-col items-center">
          <div className="text-[9px] text-slate-500 uppercase tracking-wide mb-1.5">On-Platform</div>
          <MiniDonut pct={auto_pct || 0} size={56} stroke={6} autoColor="#3b82f6" manualColor="#334155" />
          <div className="w-full mt-2 space-y-0.5">
            <div className={clsx('flex items-center gap-1.5 rounded px-1 py-0.5 cursor-pointer hover:bg-slate-800/40',
              drillTab === 'platform_auto' && 'bg-blue-600/20')}
              onClick={() => openDrill('platform_auto')}>
              <span className="w-2 h-2 rounded-full bg-blue-500" />
              <span className="text-[10px] text-slate-400 flex-1">Auto</span>
              <span className="text-xs font-bold text-white">{auto_count}</span>
              <Eye className={clsx('w-3 h-3', drillTab === 'platform_auto' ? 'text-blue-400' : 'text-slate-600')} />
            </div>
            <div className={clsx('flex items-center gap-1.5 rounded px-1 py-0.5 cursor-pointer hover:bg-slate-800/40',
              drillTab === 'platform_manual' && 'bg-amber-600/20')}
              onClick={() => openDrill('platform_manual')}>
              <span className="w-2 h-2 rounded-full bg-amber-500" />
              <span className="text-[10px] text-slate-400 flex-1">Manual</span>
              <span className="text-xs font-bold text-white">{manual_count}</span>
              <Eye className={clsx('w-3 h-3', drillTab === 'platform_manual' ? 'text-amber-400' : 'text-slate-600')} />
            </div>
          </div>
          <div className="text-[9px] text-slate-600 mt-1">{fleet_total} calls · Fleet + Contractor</div>
        </div>
      </div>

      {total === 0 && <div className="text-xs text-slate-600 text-center mt-3">No dispatches yet today</div>}

      {/* Drill-down panel */}
      {drillTab && (
        <div className="mt-3 pt-3 border-t border-slate-700/30 animate-in fade-in duration-200 -mx-4 px-4" style={{ minWidth: 600 }}>
          <div className="flex items-center gap-2 mb-2">
            <span className={clsx('text-[10px] font-semibold',
              drillTab?.includes('manual') ? 'text-amber-400' :
              drillTab?.includes('platform') ? 'text-blue-400' : 'text-emerald-400')}>
              {drillTitle}
            </span>
            <button onClick={() => setDrillTab(null)} className="ml-auto text-slate-600 hover:text-slate-400">
              <X className="w-3 h-3" />
            </button>
          </div>
          <div className="max-h-[450px] overflow-y-auto space-y-0.5 rounded-lg border border-slate-800/40 bg-slate-950/30 p-3">
            {drillLoading && <div className="flex items-center gap-2 text-xs text-slate-500 py-4 justify-center"><Loader2 className="w-4 h-4 animate-spin" /> Loading...</div>}
            {drillError && <div className="text-xs text-red-400 py-2 text-center">{drillError}</div>}
            {!drillLoading && drillList.length === 0 && <div className="text-xs text-slate-600 py-3 text-center">No calls</div>}

            {/* Grouped by dispatcher for on-platform manual */}
            {drillGrouped && drillGrouped.map(([dispatcher, sas]) => (
              <details key={dispatcher} className="group">
                <summary className="flex items-center gap-2 px-2.5 py-1.5 rounded cursor-pointer hover:bg-slate-800/40 text-[11px] list-none">
                  <ChevronRight className="w-3 h-3 text-slate-600 group-open:rotate-90 transition-transform shrink-0" />
                  <span className="text-amber-400 font-semibold">{dispatcher}</span>
                  <span className="text-slate-500 ml-auto">{sas.length} call{sas.length !== 1 ? 's' : ''}</span>
                </summary>
                <div className="ml-5 space-y-0.5 mt-0.5 mb-1">
                  {sas.map((item, j) => (
                    <div key={j} className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] bg-slate-900/40 rounded px-2.5 py-1.5">
                      {item.number ? <SALink number={item.number} style={{ fontFamily: 'monospace', fontSize: 10, width: 64, display: 'inline-block' }} /> : <span className="text-slate-500 font-mono w-16">—</span>}
                      {item.created_time && <span className="text-slate-600 w-14">{item.created_time}</span>}
                      <span className="text-slate-400 truncate">{item.work_type || '—'}</span>
                      <span className="text-slate-500 flex-1 truncate">{item.territory || '—'}</span>
                      {item.pta_delta != null && (
                        <span className={clsx('px-1.5 py-0.5 rounded text-[9px] font-bold whitespace-nowrap',
                          item.pta_delta > 0 ? 'bg-red-950/50 text-red-400' : 'bg-emerald-950/50 text-emerald-400'
                        )} title={`Promised: ${item.pta_min}m, Arrived: ${(item.pta_min || 0) + item.pta_delta}m`}>
                          {item.pta_delta > 0 ? `${item.pta_delta}m late` : item.pta_delta < 0 ? `${Math.abs(item.pta_delta)}m early` : 'on time'}
                        </span>
                      )}
                      <span className={clsx('px-1.5 py-0.5 rounded text-[8px] font-bold uppercase',
                        item.status === 'Completed' ? 'bg-emerald-950/50 text-emerald-400' :
                        item.status?.includes('Cancel') ? 'bg-red-950/50 text-red-400' :
                        'bg-slate-800 text-slate-400'
                      )}>{item.status || '—'}</span>
                    </div>
                  ))}
                </div>
              </details>
            ))}

            {/* Flat list for All Channels and On-Platform Auto */}
            {!drillGrouped && drillList.map((item, i) => (
              <div key={i}>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] bg-slate-900/40 rounded px-2.5 py-1.5">
                  {item.number
                    ? <SALink number={item.number} style={{ fontFamily: 'monospace', fontSize: 10, width: 64, display: 'inline-block' }} />
                    : <span className="text-slate-500 font-mono w-16">—</span>
                  }
                  {item.created_time && <span className="text-slate-600 w-14">{item.created_time}</span>}
                  <span className="text-slate-400 w-20 truncate">{item.work_type || '—'}</span>
                  <span className="text-slate-500 flex-1 truncate">{item.territory || '—'}</span>
                  {item.dispatcher && <span className="text-amber-400 text-[9px] truncate max-w-[100px]" title={item.dispatcher}>{item.dispatcher}</span>}
                  {item.ata_min != null && (
                    <span className={clsx('font-semibold whitespace-nowrap', item.ata_min <= 45 ? 'text-emerald-400' : 'text-amber-400')}>{item.ata_min}m ATA</span>
                  )}
                  <span className={clsx('px-1.5 py-0.5 rounded text-[8px] font-bold uppercase',
                    item.status === 'Completed' ? 'bg-emerald-950/50 text-emerald-400' :
                    item.status === 'Dispatched' ? 'bg-blue-950/50 text-blue-400' :
                    item.status?.includes('Cancel') ? 'bg-red-950/50 text-red-400' :
                    item.status === 'En Route' ? 'bg-amber-950/50 text-amber-400' :
                    'bg-slate-800 text-slate-400'
                  )}>{item.status || '—'}</span>
                  <span className={clsx('text-[8px] px-1 py-0.5 rounded',
                    item.dispatch_method === 'Field Services' ? 'bg-blue-950/40 text-blue-400' : 'bg-fuchsia-950/40 text-fuchsia-400'
                  )}>{item.dispatch_method === 'Field Services' ? 'FSL' : 'TB'}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export function TodayCalls({ ts, sp }) {
  const [selectedStatus, setSelectedStatus] = useState(null)
  const [detailData, setDetailData] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState(null)

  const handleClick = (statusKey) => {
    if (selectedStatus === statusKey) {
      setSelectedStatus(null)
      return
    }
    setSelectedStatus(statusKey)
    setDetailData(null)
    setDetailLoading(true)
    setDetailError(null)
    fetchStatusDetail(statusKey).then(d => setDetailData(d.calls))
      .catch(e => setDetailError(e.message || 'Failed'))
      .finally(() => setDetailLoading(false))
  }

  const pipeline = [
    { label: 'Dispatched', val: ts.Dispatched, color: 'text-blue-400', bg: 'bg-blue-500/20', ring: 'ring-blue-500/40' },
    { label: 'Accepted', val: ts.Accepted, color: 'text-sky-400', bg: 'bg-sky-500/20', ring: 'ring-sky-500/40' },
    { label: 'Assigned', val: ts.Assigned, color: 'text-violet-400', bg: 'bg-violet-500/20', ring: 'ring-violet-500/40' },
    { label: 'En Route', val: ts['En Route'], color: 'text-amber-400', bg: 'bg-amber-500/20', ring: 'ring-amber-500/40' },
    { label: 'On Location', val: ts['On Location'], color: 'text-cyan-400', bg: 'bg-cyan-500/20', ring: 'ring-cyan-500/40' },
  ]
  const outcomes = [
    { label: 'Completed', val: ts.Completed, color: 'text-emerald-400', bg: 'bg-emerald-500/20', ring: 'ring-emerald-500/40', status: 'Completed' },
    { label: 'Canceled', val: ts.Canceled, color: 'text-slate-500', bg: 'bg-slate-500/20', ring: 'ring-slate-500/40', status: 'Canceled' },
    { label: 'No-Show', val: ts['No-Show'], color: 'text-orange-400', bg: 'bg-orange-500/20', ring: 'ring-orange-500/40', status: 'No-Show' },
    { label: 'Unable', val: ts['Unable to Complete'], color: 'text-red-400', bg: 'bg-red-500/20', ring: 'ring-red-500/40', status: 'Unable to Complete' },
  ]

  const StatusTile = ({ s, statusKey }) => {
    const active = selectedStatus === statusKey
    return (
      <button onClick={() => s.val > 0 && handleClick(statusKey)}
        className={clsx('text-center rounded-lg py-1.5 transition-all',
          s.val > 0 ? 'cursor-pointer hover:ring-1' : 'cursor-default',
          active ? `${s.bg} ring-1 ${s.ring}` : 'bg-slate-800/30',
        )}>
        <div className={clsx('text-sm font-bold', s.color)}>{s.val}</div>
        <div className="text-[8px] text-slate-500 leading-tight">{s.label}</div>
      </button>
    )
  }

  return (<>
    <div className="text-[9px] text-slate-600 uppercase tracking-wider font-bold mb-1">Active Pipeline</div>
    <div className="grid grid-cols-5 gap-1.5 mb-1">
      {pipeline.map(s => <StatusTile key={s.label} s={s} statusKey={s.label} />)}
    </div>
    <div className="text-[9px] text-slate-600 uppercase tracking-wider font-bold mb-1 mt-2">Outcomes</div>
    <div className="grid grid-cols-4 gap-1.5">
      {outcomes.map(s => <StatusTile key={s.label} s={s} statusKey={s.status} />)}
    </div>
    {/* Full-width detail panel below the grids */}
    {selectedStatus && (
      <div className="mt-2 space-y-0.5 animate-in fade-in duration-200 max-h-[350px] overflow-y-auto rounded-lg border border-slate-800/40 bg-slate-950/30 p-2">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[10px] text-slate-400 font-medium">{selectedStatus}</span>
          <button onClick={() => setSelectedStatus(null)} className="text-slate-600 hover:text-slate-400 text-[10px]">Close</button>
        </div>
        {detailLoading && <div className="flex items-center gap-2 text-xs text-slate-500 py-4 justify-center"><Loader2 className="w-4 h-4 animate-spin" /> Loading...</div>}
        {detailError && <div className="text-xs text-red-400 py-2 text-center">{detailError}</div>}
        {detailData && detailData.length === 0 && !detailLoading && <div className="text-xs text-slate-600 py-3 text-center">No calls</div>}
        {detailData && detailData.map((item, i) => <SADetailRow key={i} item={item} />)}
      </div>
    )}
    {/* Fleet vs Contractor */}
    {sp && sp.total_completed > 0 && (
      <div className="mt-3 pt-3 border-t border-slate-800/60">
        <div className="flex justify-between text-[10px] mb-1">
          <span className="text-blue-400 font-medium">Fleet {sp.fleet_pct}%</span>
          <span className="text-slate-600">{sp.total_completed} completed</span>
          <span className="text-fuchsia-400 font-medium">Contractor {sp.contractor_pct}%</span>
        </div>
        <div className="h-3 rounded-full bg-slate-800 overflow-hidden flex">
          <div className="bg-blue-500" style={{ width: `${sp.fleet_pct}%` }} />
          <div className="bg-fuchsia-600" style={{ width: `${sp.contractor_pct}%` }} />
        </div>
      </div>
    )}
  </>)
}

export function GpsDriverRow({ item }) {
  const bucketColor = {
    fresh: 'bg-emerald-950/50 text-emerald-400',
    recent: 'bg-emerald-950/40 text-emerald-600',
    stale: 'bg-amber-950/50 text-amber-400',
    no_gps: 'bg-red-950/50 text-red-400',
  }
  const ageLabel = item.age_min != null
    ? item.age_min < 60 ? `${item.age_min}m ago` : `${Math.round(item.age_min / 60)}h ago`
    : 'Never'
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] bg-slate-900/40 rounded px-2.5 py-1.5">
      <span className="text-slate-300 w-32 truncate font-medium">{item.name}</span>
      {item.tech_id && <span className="text-slate-600 font-mono w-12">{item.tech_id}</span>}
      <span className={clsx('px-1.5 py-0.5 rounded text-[8px] font-bold uppercase', bucketColor[item.gps_bucket] || 'bg-slate-800 text-slate-400')}>
        {item.gps_bucket === 'no_gps' ? 'No GPS' : item.gps_bucket}
      </span>
      <span className={clsx('font-semibold',
        item.gps_bucket === 'fresh' ? 'text-emerald-400' :
        item.gps_bucket === 'recent' ? 'text-emerald-600' :
        item.gps_bucket === 'stale' ? 'text-amber-400' : 'text-red-400'
      )}>{ageLabel}</span>
      {item.last_update && <span className="text-slate-600">{item.last_update}</span>}
      {item.truck && <span className="w-full text-[9px] text-slate-600 truncate" title={item.truck}>{item.truck}</span>}
    </div>
  )
}

export function InsightStat({ label, auto, manual }) {
  return (
    <div className="text-center">
      <div className="text-[8px] text-slate-500 uppercase tracking-wider mb-0.5">{label}</div>
      <div className="flex items-center justify-center gap-1">
        <span className="text-[7px] text-indigo-400/70">Sys</span>
        <span className="text-[10px] font-bold text-indigo-400">{auto}</span>
      </div>
      <div className="flex items-center justify-center gap-1">
        <span className="text-[7px] text-amber-500/50">Dsp</span>
        <span className="text-[10px] font-medium text-amber-500/70">{manual}</span>
      </div>
    </div>
  )
}

export function SuggestionCard({ s }) {
  const config = {
    escalate:   { icon: AlertCircle, color: 'bg-red-950/40 border-red-800/30', iconColor: 'text-red-400', badge: 'ESCALATE' },
    reposition: { icon: Navigation,  color: 'bg-blue-950/40 border-blue-800/30', iconColor: 'text-blue-400', badge: 'REPOSITION' },
    surge:      { icon: TrendingUp,  color: 'bg-amber-950/40 border-amber-800/30', iconColor: 'text-amber-400', badge: 'SURGE' },
    coverage:   { icon: Shield,      color: 'bg-purple-950/40 border-purple-800/30', iconColor: 'text-purple-400', badge: 'COVERAGE' },
  }
  const c = config[s.type] || config.coverage
  const Icon = c.icon
  return (
    <div className={clsx('rounded-lg px-3 py-2.5 border text-xs', c.color)}>
      <div className="flex items-start gap-2">
        <Icon className={clsx('w-3.5 h-3.5 mt-0.5 shrink-0', c.iconColor)} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-0.5">
            <span className={clsx('text-[9px] font-bold uppercase tracking-wider', c.iconColor)}>{c.badge}</span>
            {s.priority === 'critical' && <span className="text-[8px] px-1 py-0.5 rounded bg-red-500/30 text-red-300 font-bold animate-pulse">URGENT</span>}
          </div>
          <div className="text-slate-300 leading-relaxed">
            {s.type === 'escalate' && s.call_number
              ? (() => {
                  // reason = "SA SA-718887 at 287 min -- PAST SLA"
                  // Split on the call_number so we can wrap it in SALink
                  const parts = s.reason.split(s.call_number)
                  return <>
                    {parts[0]}
                    <SALink number={s.call_number} style={{ fontSize: 'inherit', color: '#f87171', fontWeight: 700 }} />
                    {parts[1]}
                  </>
                })()
              : s.reason
            }
          </div>
          {s.type === 'reposition' && s.driver && (
            <div className="flex items-center gap-1 mt-1 text-blue-300">
              <ArrowRight className="w-3 h-3" />
              <span className="font-medium">{s.driver}</span>
              <span className="text-slate-500">→</span>
              <span>{s.to_zone}</span>
              <span className="text-slate-500">({s.distance_mi} mi)</span>
            </div>
          )}
          {s.type === 'escalate' && s.nearest_driver && (
            <div className="mt-1 text-slate-400">
              Nearest idle: <span className="text-emerald-400 font-medium">{s.nearest_driver}</span>
              {s.nearest_dist_mi && <span> ({s.nearest_dist_mi} mi)</span>}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
