import React, { useState, useMemo } from 'react'
import { clsx } from 'clsx'
import {
  Loader2, RefreshCw, CheckCircle2, AlertTriangle,
  ChevronRight, MapPin, Clock, FileText,
  X, Truck, Zap, Shield, Navigation, Users, TrendingUp, AlertCircle, ArrowRight,
  BarChart3, XCircle, ThumbsDown, Activity, Eye
} from 'lucide-react'
import SALink from './SALink'
import { fetchHumanIntervention, fetchGpsDetail, fetchReassignmentDetail, fetchDispatcherDetail, fetchDriverDetail, fetchCancelDetail, fetchDeclineDetail, fetchStatusDetail, fetchCapacityDetail, fetchClosestDriverDetail } from '../api'
import { InfoTip, DrillDown, MiniDonut, fmtMin } from './CommandCenterUtils'
import TrendsView, { MonthTrendsView } from './TrendsView'
import SatisfactionView from './SatisfactionView'
import SatisfactionScorecard from './SatisfactionScorecard'
import { SADetailRow, BounceDetailRow, ClosestDriverDetailRow } from './DispatchDrillDowns'
import { DispatchSplitCard, TodayCalls, GpsDriverRow, InsightStat, SuggestionCard } from './DispatchInsightCards'

// Re-export for external consumers
export { SuggestionCard } from './DispatchInsightCards'
export { SADetailRow, BounceDetailRow, ClosestDriverDetailRow } from './DispatchDrillDowns'
export { DispatchSplitCard, TodayCalls, GpsDriverRow, InsightStat } from './DispatchInsightCards'

export default function DispatchInsightsFullView({ data, gpsHealth, ccData, onViewOnMap }) {
  const [insightsTab, setInsightsTab] = useState('today') // today | trends
  const { auto_count, manual_count, towbook_count, auto_pct, no_human_count, no_human_pct, human_count, towbook_auto_count, towbook_human_count, auto_avg_response, manual_avg_response, auto_avg_speed, manual_avg_speed, auto_sla, manual_sla, auto_closest_pct, auto_closest_eval, auto_extra_miles, auto_wrong, manual_closest_pct, manual_closest_eval, manual_extra_miles, manual_wrong, towbook_closest_pct, towbook_closest_eval, towbook_extra_miles, towbook_wrong, total_extra_miles, dispatchers, total, fleet_total } = data
  const fg = ccData?.fleet_gps
  const ts = ccData?.today_status
  const sp = ccData?.today_split
  const lb = ccData?.fleet_leaderboard
  const ra = ccData?.reassignment
  const cb = ccData?.cancel_breakdown
  const db = ccData?.decline_breakdown
  const fu = ccData?.fleet_utilization
  const hv = ccData?.hourly_volume
  const overCap = (ccData?.territories || []).filter(t =>
      (t.capacity === 'over' || t.capacity === 'busy')
      && !t.name.startsWith('000')
      && !/SPOT/i.test(t.name)
    )
    .sort((a, b) => {
      const scoreA = (a.open || 0) * Math.max(a.max_wait || 1, 1)
      const scoreB = (b.open || 0) * Math.max(b.max_wait || 1, 1)
      return scoreB - scoreA
    })

  return (
    <div className="w-full h-full bg-slate-950 overflow-y-auto pt-2 pb-6 px-6">
      {/* ── Tab Bar ── */}
      <div className="max-w-5xl mx-auto mb-4 space-y-2">
        {/* Primary tabs */}
        <div className="flex items-center gap-1">
          {[['today', 'Today'], ['trends', 'Monthly Trend'], ['satisfaction', 'Satisfaction Scores']].map(([key, label]) => (
            <button key={key} onClick={() => setInsightsTab(key)}
              className={clsx('px-4 py-1.5 rounded-lg text-xs font-semibold transition-all',
                insightsTab === key
                  ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30'
                  : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800/40'
              )}>{label}</button>
          ))}
        </div>
        {/* Month tabs — only show when Monthly Trend or a month is active */}
        {(insightsTab === 'trends' || insightsTab.startsWith('month-')) && <div className="flex items-center gap-1 pl-1">
          <span className="text-[10px] text-slate-600 mr-1">{new Date().getFullYear()}</span>
          {(() => {
            const now = new Date()
            const currentMonth = now.getMonth() // 0-based
            const tabs = []
            for (let m = 0; m <= currentMonth; m++) {
              const key = `month-${now.getFullYear()}-${String(m + 1).padStart(2, '0')}`
              const label = new Date(now.getFullYear(), m, 1).toLocaleDateString('en-US', { month: 'short' })
              tabs.push(
                <button key={key} onClick={() => setInsightsTab(key)}
                  className={clsx('px-3 py-1 rounded-md text-[11px] font-medium transition-all',
                    insightsTab === key
                      ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30'
                      : 'text-slate-600 hover:text-slate-300 hover:bg-slate-800/40'
                  )}>{label}</button>
              )
            }
            return tabs
          })()}
        </div>}
      </div>

      {insightsTab === 'trends' && <TrendsView />}
      {insightsTab === 'satisfaction' && <SatisfactionView />}
      {insightsTab.startsWith('month-') && <MonthTrendsView month={insightsTab.slice(6)} />}

      {insightsTab === 'today' && <div className="max-w-5xl mx-auto space-y-6">

        {/* ── Row 1: Dispatch Split + Closest Driver + Stats ── */}
        <div className="grid grid-cols-3 gap-4">
          {/* No Human Intervention — primary metric */}
          <DispatchSplitCard data={data} />

          {/* Hourly Volume */}
          <div className="glass rounded-xl border border-slate-700/30 p-4">
            <div className="flex items-center gap-2 mb-3">
              <BarChart3 className="w-4 h-4 text-sky-400" />
              <span className="text-xs font-bold text-white uppercase tracking-wide">Hourly Volume</span>
              <InfoTip text={"WHAT: Call volume by hour today (Eastern Time).\n\nShows when calls are coming in so you can spot peak hours and staffing gaps.\n\nPeak hours are highlighted. If peaks don't align with your shift coverage, you may need to adjust driver start times.\n\nGOAL: Smooth coverage across peak hours. No hour should have 3x the average without extra drivers available."} />
            </div>
            {hv && hv.length > 0 ? (<>
              {(() => {
                const maxCount = Math.max(...hv.map(h => h.count), 1)
                const nowHour = new Date().getHours()
                const filtered = hv.filter(h => h.hour >= 6 && h.hour <= 23)
                return (
                  <div className="flex items-end gap-px h-24">
                    {filtered.map(h => {
                      const pct = Math.max(h.count / maxCount * 100, 2)
                      const isPeak = h.count >= maxCount * 0.7
                      const isCurrent = h.hour === nowHour
                      return (
                        <div key={h.hour} className="flex-1 flex flex-col items-center justify-end h-full group relative">
                          <div className={clsx('w-full rounded-t-sm transition-colors',
                            isCurrent ? 'bg-sky-400' : isPeak ? 'bg-sky-500/80' : 'bg-slate-700/60'
                          )} style={{ height: `${pct}%` }} />
                          {h.hour % 3 === 0 && (
                            <span className="text-[7px] text-slate-600 mt-0.5">
                              {h.hour > 12 ? `${h.hour - 12}p` : h.hour === 0 ? '12a' : h.hour === 12 ? '12p' : `${h.hour}a`}
                            </span>
                          )}
                          <div className="absolute bottom-full mb-1 bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5 text-[9px] text-white whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10">
                            {h.hour > 12 ? `${h.hour - 12}:00 PM` : h.hour === 0 ? '12:00 AM' : h.hour === 12 ? '12:00 PM' : `${h.hour}:00 AM`}: {h.count} calls
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )
              })()}
              <div className="flex justify-between text-[9px] text-slate-600 mt-1">
                <span>Total: {hv.reduce((s, h) => s + h.count, 0)} calls</span>
                <span>Peak: {Math.max(...hv.map(h => h.count))}</span>
              </div>
            </>) : (
              <div className="text-xs text-slate-600 text-center py-6">No hourly data yet</div>
            )}
          </div>

          {/* Performance Stats */}
          <div className="glass rounded-xl border border-slate-700/30 p-4">
            <div className="flex items-center gap-2 mb-3">
              <TrendingUp className="w-4 h-4 text-cyan-400" />
              <span className="text-xs font-bold text-white uppercase tracking-wide">System vs Dispatcher</span>
              <InfoTip text={"HOW TO READ THIS CARD:\n\nCompares System (auto-scheduler) vs Dispatcher (human) side by side on 3 metrics. Blue row = System, Orange row = Dispatcher. Lower is better for time metrics, higher is better for SLA %.\n\n• Avg Response: Average time from call creation to driver arriving on scene (ATA). This is how long the member waited.\n• Sched ETA: Average time from call creation to the scheduled arrival window. How far out was the appointment set.\n• 45-min SLA: % of calls where the driver arrived within 45 minutes (AAA's standard).\n\nFleet calls only (Towbook excluded).\n\nGOAL: System should match or beat Dispatcher on all 3 metrics. If Dispatcher is faster, the scheduler may need tuning."} />
            </div>
            <table className="w-full text-center border-separate" style={{ borderSpacing: '0 4px' }}>
              <thead>
                <tr>
                  <th className="w-16" />
                  <th className="text-[9px] text-slate-500 uppercase tracking-wider font-medium pb-1">
                    Avg Response<InfoTip text={"WHAT: Average time a member waits from calling AAA to the driver arriving on scene.\n\nHOW: For each completed call: ActualStartTime (driver marked 'On Location' in Towbook) minus CreatedDate (call entered Salesforce). Averaged across all completed calls.\n\nGOAL: Under 45 minutes. This is the #1 member experience metric."} />
                  </th>
                  <th className="text-[9px] text-slate-500 uppercase tracking-wider font-medium pb-1">
                    Sched ETA<InfoTip text={"WHAT: How quickly a call gets a scheduled arrival window.\n\nHOW: SchedStartTime minus CreatedDate. Measures how far out the scheduled appointment is from creation.\n\nGOAL: Lower is better — means calls are being scheduled with short ETAs."} />
                  </th>
                  <th className="text-[9px] text-slate-500 uppercase tracking-wider font-medium pb-1">
                    45-min SLA<InfoTip text={"WHAT: % of calls where the driver arrived within 45 minutes.\n\nHOW: If (ActualStartTime - CreatedDate) ≤ 45 min, it passes.\n\nGOAL: AAA standard is 45 min. Higher % = better. Below 80% is a red flag."} />
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="text-[9px] text-indigo-400/60 font-medium text-left">System</td>
                  <td className="text-sm font-bold text-indigo-400">{auto_avg_response != null ? `${auto_avg_response}m` : '—'}</td>
                  <td className="text-sm font-bold text-indigo-400">{auto_avg_speed != null ? `${auto_avg_speed}m` : '—'}</td>
                  <td className="text-sm font-bold text-indigo-400">{auto_sla != null ? `${auto_sla}%` : '—'}</td>
                </tr>
                <tr>
                  <td className="text-[9px] text-amber-500/50 font-medium text-left">Dispatcher</td>
                  <td className="text-sm font-bold text-amber-500/80">{manual_avg_response != null ? `${manual_avg_response}m` : '—'}</td>
                  <td className="text-sm font-bold text-amber-500/80">{manual_avg_speed != null ? `${manual_avg_speed}m` : '—'}</td>
                  <td className="text-sm font-bold text-amber-500/80">{manual_sla != null ? `${manual_sla}%` : '—'}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Row 2: On-Shift Driver GPS + Today's Calls + Fleet vs Contractor ── */}
        <div className="grid grid-cols-3 gap-4">
          {/* On-Shift Driver GPS Health */}
          <div className="glass rounded-xl border border-slate-700/30 p-4">
            <div className="flex items-center gap-2 mb-3">
              <Truck className="w-4 h-4 text-blue-400" />
              <span className="text-xs font-bold text-white uppercase tracking-wide">GPS Status</span>
              <InfoTip text={"Fleet + On-Platform Contractor drivers only (Towbook excluded).\n\nVisible: GPS reported in the last hour — scheduler can locate them.\nRecently active: GPS reported 1-4 hours ago — still usable.\n\nDrivers with no GPS activity in 4+ hours are considered off-shift and not shown.\n\nThe scheduler needs live GPS to pick the closest driver. Without it, assignments are based on territory only → longer ETAs.\n\nUpdates every 5 minutes."} />
            </div>
            {fg ? (<>
              {fg.on_shift > 0 ? (<>
                <div className="space-y-2 mb-3">
                  <div className="flex items-center gap-3">
                    <div className="w-2 h-2 rounded-full bg-emerald-500 flex-shrink-0" />
                    <span className="text-sm text-white">
                      <span className="font-bold text-emerald-400">{fg.visible}</span> driver{fg.visible !== 1 ? 's' : ''} visible to the scheduler right now
                    </span>
                  </div>
                  {fg.recent > 0 && (
                    <div className="flex items-center gap-3">
                      <div className="w-2 h-2 rounded-full bg-amber-500 flex-shrink-0" />
                      <span className="text-sm text-white">
                        <span className="font-bold text-amber-400">{fg.recent}</span> recently active (1-4h ago)
                      </span>
                    </div>
                  )}
                </div>
                <div className="h-2.5 rounded-full bg-slate-800 overflow-hidden flex mb-2">
                  {fg.visible > 0 && <div className="bg-emerald-500" style={{ width: `${100*fg.visible/fg.on_shift}%` }} />}
                  {fg.recent > 0 && <div className="bg-amber-500" style={{ width: `${100*fg.recent/fg.on_shift}%` }} />}
                </div>
                <DrillDown
                  fetchFn={() => fetchGpsDetail('all').then(d => d.drivers)}
                  renderRow={(item, j) => <GpsDriverRow key={j} item={item} />}
                  emptyMsg="No drivers found">
                  <div className="text-[10px] text-slate-500">
                    {fg.on_shift} on-shift · {fg.total_roster} in roster · Updated every 5 min
                  </div>
                </DrillDown>
              </>) : (
                <div className="text-sm text-slate-500 py-4">No drivers with active GPS right now</div>
              )}
            </>) : (
              <div className="text-xs text-slate-600 text-center py-6">Loading...</div>
            )}
          </div>

          {/* Today's Calls */}
          <div className="glass rounded-xl border border-slate-700/30 p-4">
            <div className="flex items-center gap-2 mb-3">
              <FileText className="w-4 h-4 text-cyan-400" />
              <span className="text-xs font-bold text-white uppercase tracking-wide">Today's Calls</span>
              <span className="text-sm font-bold text-white ml-auto">{ts?.total || 0}</span>
              <InfoTip text={"WHAT: All roadside calls created today broken into pipeline stages and outcomes.\n\nPIPELINE (active calls):\n• Dispatched — Call entered, waiting for driver assignment\n• Accepted — Driver accepted, preparing to leave\n• Assigned — Driver assigned, not yet en route\n• En Route — Driver traveling to member\n• On Location — Driver arrived, working on site\n\nOUTCOMES (finished calls):\n• Completed — Service finished successfully\n• Canceled — Call canceled by member or dispatcher\n• No-Show — Driver arrived but member not present\n• Unable — Driver couldn't complete the service\n\nTow Drop-Offs excluded (second leg of a tow, not a new call)."} />
            </div>
            {ts ? (<TodayCalls ts={ts} sp={sp} />) : (
              <div className="text-xs text-slate-600 text-center py-6">No call data yet</div>
            )}
          </div>

          {/* Fleet ATA Leaderboard */}
          <div className="glass rounded-xl border border-slate-700/30 p-4">
            <div className="flex items-center gap-2 mb-3">
              <TrendingUp className="w-4 h-4 text-emerald-400" />
              <span className="text-xs font-bold text-white uppercase tracking-wide">Fleet ATA Today</span>
              <InfoTip text={"WHAT: Which fleet drivers are fastest and slowest today.\n\nHOW: For each fleet driver's completed calls today, we calculate their average ATA (time from call creation to driver on scene). Then rank all drivers.\n\nFastest: Top 3 drivers with the lowest average ATA.\nSlowest: Bottom 3 drivers with the highest average ATA.\nThe number in parentheses is how many calls that driver completed.\n\nGOAL: Identifies top performers and drivers who may need route optimization or are covering difficult areas."} />
            </div>
            {lb && (lb.top?.length > 0 || lb.bottom?.length > 0) ? (<>
              {lb.top?.length > 0 && (
                <div className="mb-3">
                  <div className="text-[9px] text-emerald-500/70 uppercase tracking-wider mb-1">Fastest</div>
                  {lb.top.map((d, i) => (
                    <DrillDown key={i}
                      fetchFn={() => fetchDriverDetail(d.name).then(r => r.calls)}
                      renderRow={(item) => <SADetailRow item={item} />}
                      emptyMsg="No calls found">
                      <div className="flex items-center justify-between text-xs py-0.5">
                        <span className="text-slate-300 truncate mr-2">{d.name}</span>
                        <span className="text-emerald-400 font-semibold whitespace-nowrap">{d.avg_ata}m <span className="text-slate-600 font-normal">({d.calls})</span></span>
                      </div>
                    </DrillDown>
                  ))}
                </div>
              )}
              {lb.bottom?.length > 0 && (
                <div>
                  <div className="text-[9px] text-red-500/70 uppercase tracking-wider mb-1">Slowest</div>
                  {lb.bottom.map((d, i) => (
                    <DrillDown key={i}
                      fetchFn={() => fetchDriverDetail(d.name).then(r => r.calls)}
                      renderRow={(item) => <SADetailRow item={item} />}
                      emptyMsg="No calls found">
                      <div className="flex items-center justify-between text-xs py-0.5">
                        <span className="text-slate-300 truncate mr-2">{d.name}</span>
                        <span className="text-red-400 font-semibold whitespace-nowrap">{d.avg_ata}m <span className="text-slate-600 font-normal">({d.calls})</span></span>
                      </div>
                    </DrillDown>
                  ))}
                </div>
              )}
            </>) : (
              <div className="text-xs text-slate-600 text-center py-6">No completed fleet calls yet</div>
            )}
          </div>
        </div>

        {/* ── Row 3: Reassignment Cost ── */}
        <div className={clsx('glass rounded-xl p-4', ra && ra.total_bounces > 0 ? 'border border-red-800/30 bg-red-950/10' : 'border border-slate-700/30')}>
          <div className="flex items-center gap-2 mb-3">
            <RefreshCw className="w-4 h-4 text-red-400" />
            <span className="text-xs font-bold text-white uppercase tracking-wide">Time Lost to Reassignments</span>
            <InfoTip text={"WHAT: Total time lost today because calls had to be reassigned — a driver or garage didn't respond within 10 minutes, so the system moved it to someone else.\n\nHOW: We track every driver/garage assignment change in Salesforce history. Each 10+ minute gap between assignments = wasted time for the member.\n\nClick to see all affected calls with the full assignment history."} />
          </div>
          {!ra && <div className="text-xs text-slate-600 text-center py-2">Loading...</div>}
          {ra && ra.total_bounces === 0 && (
            <div className="text-xs text-emerald-400/70 text-center py-2">No reassignment delays today</div>
          )}
          {ra && ra.total_bounces > 0 && (
            <DrillDown
              fetchFn={() => fetchReassignmentDetail().then(d => d.bounces)}
              renderRow={(item) => <BounceDetailRow item={item} />}
              emptyMsg="No bounce details available">
              <div className="cursor-pointer hover:bg-slate-800/30 rounded-lg px-2 py-1 -mx-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-baseline gap-2">
                    <span className="text-2xl font-bold text-red-400">{ra.hours_lost}h</span>
                    <span className="text-xs text-slate-500">lost to reassignments</span>
                  </div>
                  <div className="text-xs text-slate-500">{ra.affected_calls} calls · {ra.total_bounces} bounces</div>
                </div>
                {ra.by_channel && (
                  <div className="flex gap-4 mt-2">
                    {[
                      { key: 'fleet', label: 'Fleet', color: 'text-blue-400' },
                      { key: 'contractor', label: 'On-Platform', color: 'text-indigo-400' },
                      { key: 'towbook', label: 'Towbook', color: 'text-fuchsia-400' },
                    ].map(ch => {
                      const s = ra.by_channel[ch.key]
                      if (!s || s.bounces === 0) return null
                      return (
                        <div key={ch.key} className="text-[10px]">
                          <span className={clsx('font-semibold', ch.color)}>{ch.label}</span>
                          <span className="text-slate-500 ml-1">{s.hours_lost}h · {s.calls} calls</span>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            </DrillDown>
          )}
        </div>

        {/* ── Row 4: Dispatchers + Capacity Alerts ── */}
        <div className="grid grid-cols-2 gap-4">
          {/* Top Dispatchers */}
          <div className="glass rounded-xl border border-slate-700/30 p-4">
            <div className="flex items-center gap-2 mb-3">
              <Users className="w-4 h-4 text-amber-400" />
              <span className="text-xs font-bold text-white uppercase tracking-wide">Top Dispatchers</span>
              <InfoTip text={"WHAT: Which dispatchers are manually assigning the most fleet calls today.\n\nHOW: When a call's dispatch method is not 'Field Services' (auto-scheduler), it was manually assigned. We look at who last modified the assignment to identify the dispatcher.\n\nGOAL: High manual counts may indicate the auto-scheduler isn't covering enough, or that dispatchers are overriding system assignments."} />
            </div>
            {dispatchers && dispatchers.length > 0 ? (
              <div className="space-y-0.5">
                {dispatchers.map((d, i) => (
                  <DrillDown key={i}
                    fetchFn={() => fetchDispatcherDetail(d.name).then(r => r.calls)}
                    renderRow={(item) => (
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] bg-slate-900/40 rounded px-2.5 py-1.5">
                        {item.number
                          ? <SALink number={item.number} style={{ fontFamily: 'monospace', fontSize: 10, width: 64, display: 'inline-block' }} />
                          : <span className="text-slate-500 font-mono w-16">—</span>
                        }
                        {item.dispatched_at && <span className="text-blue-400 w-16">{item.dispatched_at}</span>}
                        <span className="text-slate-400 w-20 truncate">{item.work_type || '—'}</span>
                        <span className="text-slate-500 flex-1 truncate">{item.territory || '—'}</span>
                        {item.ata_min != null && <span className={clsx('font-semibold whitespace-nowrap', item.ata_min <= 45 ? 'text-emerald-400' : 'text-amber-400')}>{item.ata_min}m ATA</span>}
                        <span className={clsx('px-1.5 py-0.5 rounded text-[8px] font-bold uppercase',
                          item.status === 'Completed' ? 'bg-emerald-950/50 text-emerald-400' :
                          item.status === 'Dispatched' ? 'bg-blue-950/50 text-blue-400' :
                          item.status?.includes('Cancel') ? 'bg-red-950/50 text-red-400' :
                          'bg-slate-800 text-slate-400'
                        )}>{item.status || '—'}</span>
                      </div>
                    )}
                    emptyMsg="No calls found">
                    <div className="flex items-center justify-between text-xs py-1 border-b border-slate-800/30 last:border-0">
                      <span className="text-slate-300">{d.name}</span>
                      <span className="text-white font-bold">{d.count}</span>
                    </div>
                  </DrillDown>
                ))}
              </div>
            ) : (
              <div className="text-xs text-slate-600 text-center py-6">No manual dispatches yet</div>
            )}
          </div>

          {/* Capacity Alerts */}
          <div className="glass rounded-xl border border-slate-700/30 p-4">
            <div className="flex items-center gap-2 mb-3">
              <AlertCircle className="w-4 h-4 text-red-400" />
              <span className="text-xs font-bold text-white uppercase tracking-wide">Capacity Alerts</span>
              <InfoTip text={"WHAT: Garages struggling with call volume right now.\n\nFleet garages: flagged when open calls outnumber GPS-active drivers (open/drv ratio).\nContractor garages (ⓒ): flagged by open call count + wait time, since their real driver count isn't tracked in Salesforce.\n\nOver = significantly overloaded. Busy = near capacity.\n\nGOAL: No garage should stay 'Over' for long."} />
            </div>
            {overCap.length > 0 ? (
              <div className="space-y-1.5">
                {overCap.slice(0, 8).map(t => (
                  <DrillDown key={t.id}
                    fetchFn={() => fetchCapacityDetail(t.name).then(d => d.calls)}
                    renderRow={(item, j) => <SADetailRow key={j} item={item} />}>
                    <div className="flex items-center gap-2 text-xs">
                      <span className={clsx('px-1.5 py-0.5 rounded text-[8px] font-bold uppercase',
                        t.capacity === 'over' ? 'bg-red-950/60 text-red-400' : 'bg-amber-950/50 text-amber-400'
                      )}>{t.capacity === 'over' ? 'Over' : 'Busy'}</span>
                      <span className="text-slate-300 truncate flex-1">{t.name}{t.is_contractor ? ' ⓒ' : ''}</span>
                      <span className="text-slate-500 whitespace-nowrap">
                        {t.is_contractor
                          ? `${t.open} open${t.max_wait ? ` · ${t.max_wait}m wait` : ''}`
                          : `${t.open} open / ${t.avail_drivers} drv`}
                      </span>
                    </div>
                  </DrillDown>
                ))}
              </div>
            ) : (
              <div className="text-xs text-emerald-400/70 text-center py-6">All garages within capacity</div>
            )}
          </div>
        </div>

        {/* ── Row 5: Cancellation Breakdown + Decline Reasons ── */}
        <div className="grid grid-cols-2 gap-4">
          {/* Cancellation Breakdown */}
          <div className="glass rounded-xl border border-slate-700/30 p-4">
            <div className="flex items-center gap-2 mb-3">
              <XCircle className="w-4 h-4 text-orange-400" />
              <span className="text-xs font-bold text-white uppercase tracking-wide">Cancel Reasons</span>
              <InfoTip text={"WHY calls are being canceled today.\n\n• 'Member Could Not Wait' = member gave up waiting → response time too slow. This is the #1 actionable cancel.\n• 'Member Got Going' = self-resolved (flat fixed, car started). Not your fault.\n• 'Facility Initiated' = garage canceled the call. Investigate why.\n• 'Duplicate Call' = double entry, ignore.\n\nGOAL: Keep 'Could Not Wait' < 3% of total calls. High rate = members are abandoning."} />
              <span className="text-sm font-bold text-orange-400 ml-auto">{cb?.total || 0}</span>
            </div>
            {cb && cb.total > 0 ? (
              <div className="space-y-1.5">
                {cb.reasons.map((r, i) => {
                  const isCnw = r.reason.toLowerCase().includes('could not wait')
                  return (
                    <DrillDown key={i}
                      fetchFn={() => fetchCancelDetail(r.reason).then(d => d.calls)}
                      renderRow={(item, j) => <SADetailRow key={j} item={item} />}>
                      <div className="flex items-center gap-2 text-xs">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between mb-0.5">
                            <span className={clsx('truncate', isCnw ? 'text-red-400 font-medium' : 'text-slate-300')}>{r.reason}</span>
                            <span className={clsx('font-bold ml-2 whitespace-nowrap', isCnw ? 'text-red-400' : 'text-slate-400')}>{r.count} <span className="text-slate-600 font-normal">({r.pct}%)</span></span>
                          </div>
                          <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
                            <div className={clsx('h-full rounded-full', isCnw ? 'bg-red-500' : 'bg-orange-600/60')}
                                 style={{ width: `${r.pct}%` }} />
                          </div>
                        </div>
                      </div>
                    </DrillDown>
                  )
                })}
              </div>
            ) : (
              <div className="text-xs text-emerald-400/70 text-center py-6">No cancellations today</div>
            )}
          </div>

          {/* Decline/Rejection Reasons */}
          <div className="glass rounded-xl border border-slate-700/30 p-4">
            <div className="flex items-center gap-2 mb-3">
              <ThumbsDown className="w-4 h-4 text-rose-400" />
              <span className="text-xs font-bold text-white uppercase tracking-wide">Decline Reasons</span>
              <InfoTip text={"WHY garages are declining assigned calls today.\n\n• 'End of Shift' = timing gap. Garage closed but still getting calls.\n• 'Meal/Break' = driver unavailable temporarily.\n• 'Out of Area' = routing problem. Call sent to wrong zone.\n• 'Truck not capable' = skill mismatch. Battery truck sent to tow call.\n• 'Towbook Decline' = external contractor refusing work.\n\nEach decline adds ~10 min delay (call cascades to next garage).\nGOAL: Reduce declines by fixing routing and shift alignment."} />
              <span className="text-sm font-bold text-rose-400 ml-auto">{db?.total || 0}</span>
            </div>
            {db && db.total > 0 ? (
              <div className="space-y-1.5">
                {db.reasons.map((r, i) => (
                  <DrillDown key={i}
                    fetchFn={() => fetchDeclineDetail(r.reason).then(d => d.calls)}
                    renderRow={(item, j) => <SADetailRow key={j} item={item} />}>
                    <div className="flex items-center gap-2 text-xs">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between mb-0.5">
                          <span className="text-slate-300 truncate">{r.reason}</span>
                          <span className="text-slate-400 font-bold ml-2 whitespace-nowrap">{r.count} <span className="text-slate-600 font-normal">({r.pct}%)</span></span>
                        </div>
                        <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
                          <div className="h-full rounded-full bg-rose-600/60" style={{ width: `${r.pct}%` }} />
                        </div>
                      </div>
                    </div>
                  </DrillDown>
                ))}
              </div>
            ) : (
              <div className="text-xs text-emerald-400/70 text-center py-6">No declines today</div>
            )}
          </div>
        </div>

        {/* ── Row 6: Fleet Utilization ── */}
        <div className="glass rounded-xl border border-slate-700/30 p-4">
          <div className="flex items-center gap-2 mb-3">
            <Activity className="w-4 h-4 text-violet-400" />
            <span className="text-xs font-bold text-white uppercase tracking-wide">Fleet Utilization</span>
            <InfoTip text={"WHAT: How much of your on-shift fleet is currently busy vs idle.\n\nOn Shift = drivers logged into a truck (Asset). Busy = on an active SA (Dispatched/Assigned/In Progress/En Route/On Location).\n\nBroken down by tier:\n• Tow = can do tow + light service + battery\n• Light = tire/lockout/fuel/winch + battery\n• Battery = battery-only trucks\n\nGOAL: 60-80% utilization is healthy. Below 50% = overstaffed. Above 90% = no capacity buffer for surges."} />
          </div>
          {fu && fu.total_on_shift > 0 ? (<>
            {/* Big gauge */}
            <div className="flex items-center gap-4 mb-3">
              <div className="relative w-20 h-20">
                <svg viewBox="0 0 36 36" className="w-20 h-20 -rotate-90">
                  <circle cx="18" cy="18" r="14" fill="none" stroke="#1e293b" strokeWidth="4" />
                  <circle cx="18" cy="18" r="14" fill="none"
                    stroke={fu.utilization_pct >= 90 ? '#ef4444' : fu.utilization_pct >= 60 ? '#a78bfa' : '#22c55e'}
                    strokeWidth="4" strokeDasharray={`${fu.utilization_pct * 0.88} 88`} strokeLinecap="round" />
                </svg>
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className={clsx('text-lg font-bold',
                    fu.utilization_pct >= 90 ? 'text-red-400' : fu.utilization_pct >= 60 ? 'text-violet-400' : 'text-emerald-400'
                  )}>{fu.utilization_pct}%</span>
                </div>
              </div>
              <div className="flex-1 space-y-1">
                <div className="flex justify-between text-xs">
                  <span className="text-slate-500">On Shift</span>
                  <span className="text-white font-bold">{fu.total_on_shift}</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-slate-500">Busy</span>
                  <span className="text-violet-400 font-bold">{fu.total_busy}</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-slate-500">Idle</span>
                  <span className="text-emerald-400 font-bold">{fu.total_on_shift - fu.total_busy}</span>
                </div>
              </div>
            </div>
            {/* Tier breakdown */}
            <div className="border-t border-slate-800/50 pt-2 space-y-1">
              {['tow', 'light', 'battery'].map(tier => {
                const t = fu.by_tier?.[tier]
                if (!t || t.on_shift === 0) return null
                const pct = Math.round(100 * t.busy / Math.max(t.on_shift, 1))
                return (
                  <div key={tier} className="flex items-center gap-2 text-[10px]">
                    <span className="text-slate-500 w-12 uppercase font-medium">{tier}</span>
                    <div className="flex-1 h-2 rounded-full bg-slate-800 overflow-hidden">
                      <div className={clsx('h-full rounded-full',
                        pct >= 90 ? 'bg-red-500' : pct >= 60 ? 'bg-violet-500' : 'bg-emerald-500'
                      )} style={{ width: `${pct}%` }} />
                    </div>
                    <span className="text-slate-400 w-16 text-right">{t.busy}/{t.on_shift} <span className="text-slate-600">({pct}%)</span></span>
                  </div>
                )
              })}
            </div>
          </>) : (
            <div className="text-xs text-slate-600 text-center py-6">No drivers on shift yet</div>
          )}
        </div>

        <div className="text-[10px] text-slate-600 text-center">
          Fleet · {data.is_fallback ? 'Last 24h' : 'Today'} · 2m auto-refresh
        </div>
      </div>}
    </div>
  )
}
