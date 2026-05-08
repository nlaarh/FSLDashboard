/**
 * GarageRevenueDrivers.jsx — "Revenue per Driver" tab in Garage Dashboard
 *
 * Two side-by-side charts:
 *   Left  — Revenue per driver (top 20 horizontal bars, sorted by revenue)
 *   Right — Revenue per hour (all tracked drivers, colour-coded)
 *
 * Click any driver row → inline drill-down:
 *   - Daily breakdown table  (date | calls by type | hours | revenue)
 *   - Call-type summary table (type | count | revenue | avg/call)
 */

import { useState, useEffect } from 'react'
import { Loader2, DollarSign, Clock, BarChart2, Mail, Download, FileText, ArrowUp, ArrowDown } from 'lucide-react'
import { clsx } from 'clsx'
import { fetchDriverRevenue, exportDriverRevenue, emailDriverRevenue } from '../api'
import { InfoTip } from './CommandCenterUtils'
import DriverDrillDown, { fmtRevFull } from './GarageRevenueDriverDrillDown'

// ── Colour helpers ────────────────────────────────────────────────────────────

const rphColor = (rph) =>
  rph >= 100 ? 'bg-emerald-500' :
  rph >= 60  ? 'bg-amber-500'  : 'bg-red-500'

const rphText = (rph) =>
  rph >= 100 ? 'text-emerald-400' :
  rph >= 60  ? 'text-amber-400'   : 'text-red-400'

const fmtRev = (v) => v >= 1000 ? `$${(v / 1000).toFixed(1)}K` : `$${Math.round(v)}`

// ── Horizontal bar (reusable) ─────────────────────────────────────────────────

function HBar({ label, value, maxValue, barClass, labelRight, subtitle, onClick, active }) {
  const pct = maxValue > 0 ? Math.min((value / maxValue) * 100, 100) : 0
  return (
    <div
      className={clsx(
        'flex items-center gap-2 px-2 py-1 rounded-lg cursor-pointer transition-colors',
        active ? 'bg-brand-600/15 border border-brand-500/30' : 'hover:bg-slate-800/40'
      )}
      onClick={onClick}
    >
      {/* Name */}
      <div className="w-36 shrink-0 text-right">
        <span className="text-[11px] text-slate-300 truncate block">{label}</span>
        {subtitle && <span className="text-[9px] text-slate-600">{subtitle}</span>}
      </div>
      {/* Bar */}
      <div className="flex-1 h-4 bg-slate-800/60 rounded overflow-hidden">
        <div className={clsx('h-full rounded', barClass)} style={{ width: `${pct}%` }} />
      </div>
      {/* Value */}
      <div className="w-16 text-right shrink-0 text-[11px] font-semibold text-slate-200">
        {labelRight}
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function GarageRevenueDrivers({ garageId, startDate, endDate, garageName = '', refreshKey = 0 }) {
  const [data, setData]         = useState(null)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)
  const [expanded, setExpanded] = useState(null)
  const [sortRevDir, setSortRevDir]   = useState('desc')   // asc | desc
  const [sortRphDir, setSortRphDir]   = useState('desc')
  const [emailOpen, setEmailOpen]     = useState(false)
  const [emailTo, setEmailTo]         = useState('')
  const [emailSending, setEmailSending] = useState(false)
  const [emailSent, setEmailSent]     = useState(false)
  const [exporting, setExporting]     = useState(false)

  useEffect(() => {
    if (!startDate || !endDate) return
    setLoading(true); setData(null); setError(null); setExpanded(null)
    fetchDriverRevenue(garageId, startDate, endDate, refreshKey > 0)
      .then(setData)
      .catch(e => setError(e?.response?.data?.detail || 'Failed to load revenue data'))
      .finally(() => setLoading(false))
  }, [garageId, startDate, endDate, refreshKey])

  if (loading) return (
    <div className="flex flex-col items-center justify-center py-24 gap-4">
      <Loader2 className="w-8 h-8 animate-spin text-brand-400" />
      <span className="text-slate-400 text-sm">Loading driver revenue from Salesforce…</span>
      <span className="text-slate-600 text-xs">First load may take 30–60 s (hours + billing pipeline). Cached after that.</span>
    </div>
  )
  if (error) return (
    <div className="rounded-xl bg-red-950/30 border border-red-800/30 p-4 text-red-300 text-sm">{error}</div>
  )
  if (!data) return null

  const { drivers, summary } = data
  const note = summary?.note

  if (note || !drivers?.length) return (
    <div className="rounded-xl bg-slate-900/50 border border-slate-700/30 p-8 text-center">
      <BarChart2 className="w-10 h-10 text-slate-600 mx-auto mb-3" />
      <div className="text-slate-400 text-sm">{note || 'No driver data for this period.'}</div>
      <div className="text-slate-600 text-xs mt-1">Revenue is attributed from completed SAs in this period. Fleet and On-Platform Contractor drivers show individual names; Towbook garages appear as a single aggregate entry with no hours data.</div>
    </div>
  )

  // Revenue per Driver: top 20, direction toggleable
  const sortedByRev = sortRevDir === 'desc'
    ? drivers.slice(0, 20)
    : [...drivers].sort((a, b) => a.revenue - b.revenue).slice(0, 20)
  const maxRev = Math.max(...sortedByRev.map(d => d.revenue), 1)

  // Revenue per Hour: sorted by rev/hour, direction toggleable
  const withHours = [...drivers.filter(d => d.hours > 0)]
    .sort((a, b) => sortRphDir === 'desc' ? b.rev_per_hour - a.rev_per_hour : a.rev_per_hour - b.rev_per_hour)
  const maxRph = Math.max(...withHours.map(d => d.rev_per_hour), 1)

  // Battery chart: all drivers with battery calls, sorted by battery revenue desc
  const battDrivers = [...drivers.filter(d => d.battery_calls > 0)].sort((a, b) => b.battery_revenue - a.battery_revenue).slice(0, 20)
  const maxBattRev  = Math.max(...battDrivers.map(d => d.battery_revenue), 1)

  const toggle = (name) => setExpanded(e => e === name ? null : name)

  return (
    <div className="space-y-6">

      {/* Export toolbar */}
      <div className="flex items-center justify-end gap-2">
        <div className="relative">
          <button onClick={() => { setEmailOpen(!emailOpen); setEmailSent(false) }}
            className={clsx('flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-medium border rounded-lg transition',
              emailOpen ? 'text-blue-400 bg-blue-900/30 border-blue-500/40' : 'text-blue-300 bg-blue-900/20 hover:bg-blue-800/30 border-blue-700/40')}>
            <Mail className="w-3.5 h-3.5" />Email Report
          </button>
          {emailOpen && (
            <div className="absolute top-full right-0 mt-1 bg-slate-800 border border-slate-700 rounded-lg p-3 shadow-xl z-20 w-72">
              {emailSent ? <div className="text-emerald-400 text-xs font-medium text-center py-2">Sent!</div> : (
                <div className="flex gap-2">
                  <input type="email" value={emailTo} onChange={e => setEmailTo(e.target.value)}
                    placeholder="recipient@email.com"
                    className="flex-1 bg-slate-900 border border-slate-700 rounded-md px-2.5 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-blue-500/50"
                    onKeyDown={e => { if (e.key === 'Enter' && emailTo) { setEmailSending(true); emailDriverRevenue(garageId, emailTo, startDate, endDate, garageName).then(() => { setEmailSent(true); setTimeout(() => { setEmailOpen(false); setEmailSent(false) }, 2000) }).catch(err => alert(err.response?.data?.detail || 'Failed')).finally(() => setEmailSending(false)) } }} />
                  <button disabled={emailSending || !emailTo}
                    onClick={() => { setEmailSending(true); emailDriverRevenue(garageId, emailTo, startDate, endDate, garageName).then(() => { setEmailSent(true); setTimeout(() => { setEmailOpen(false); setEmailSent(false) }, 2000) }).catch(err => alert(err.response?.data?.detail || 'Failed')).finally(() => setEmailSending(false)) }}
                    className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 text-white text-xs font-medium rounded-md transition">
                    {emailSending ? '...' : 'Send'}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
        <button onClick={() => {
          const allDrivers = [...drivers].sort((a, b) => b.revenue - a.revenue)
          const fmt = v => v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
          const dRows = allDrivers.map(d =>
            `<tr><td>${d.name}</td><td>${d.calls}</td>` +
            `<td style="text-align:right;color:#16a34a">$${fmt(d.revenue)}</td>` +
            `<td style="text-align:right;color:#b45309">$${fmt(d.battery_revenue||0)}</td>` +
            `<td style="text-align:right">${d.hours > 0 ? d.hours + 'h' : '—'}</td>` +
            `<td style="text-align:right">${d.rev_per_hour > 0 ? '$' + d.rev_per_hour + '/h' : '—'}</td></tr>`
          ).join('')
          const bRows = [...drivers].filter(d => d.battery_calls > 0)
            .sort((a, b) => b.battery_revenue - a.battery_revenue)
            .map(d => `<tr><td>${d.name}</td><td style="text-align:right">${d.battery_calls}</td><td style="text-align:right;color:#b45309">$${fmt(d.battery_revenue||0)}</td></tr>`).join('')
          const w = window.open('', '_blank')
          w.document.write(`<!DOCTYPE html><html><head><title>${garageName} Driver Revenue</title>
<style>
  body{margin:32px;font-family:Arial,Helvetica,sans-serif;background:#fff;color:#111;font-size:12px}
  h2{margin:0 0 4px;font-size:16px}p.sub{color:#64748b;font-size:11px;margin:0 0 20px}
  .cards{display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap}
  .card{border:1px solid #e2e8f0;border-radius:6px;padding:10px 16px;min-width:130px}
  .clabel{font-size:9px;color:#94a3b8;text-transform:uppercase;letter-spacing:.5px;margin-bottom:3px}
  .cval{font-size:16px;font-weight:900}
  .sec{font-size:11px;font-weight:700;margin:20px 0 6px;color:#1e293b}
  table{width:100%;border-collapse:collapse}
  th{background:#f8fafc;padding:6px 10px;text-align:left;color:#64748b;border-bottom:2px solid #e2e8f0;font-size:10px;text-transform:uppercase;white-space:nowrap}
  td{padding:5px 10px;border-bottom:1px solid #f1f5f9;white-space:nowrap}
  tr:nth-child(even){background:#fafafa}
  .note{font-size:9px;color:#94a3b8;border-top:1px solid #e2e8f0;padding-top:12px;margin-top:20px}
  @media print{@page{margin:18mm}body{font-size:11px}}
</style></head><body>
<h2>${garageName} — Driver Revenue Report</h2>
<p class="sub">${startDate} to ${endDate}</p>
<div class="cards">
  <div class="card"><div class="clabel">Tow/Light Revenue</div><div class="cval" style="color:#16a34a">$${fmt(summary.total_attributed||0)}</div></div>
  <div class="card"><div class="clabel">Battery Revenue</div><div class="cval" style="color:#b45309">$${fmt(summary.total_battery_revenue||0)}</div></div>
  <div class="card"><div class="clabel">Active Drivers</div><div class="cval">${summary.total_drivers}</div></div>
  <div class="card"><div class="clabel">Total Calls</div><div class="cval">${(summary.total_calls||0).toLocaleString()}</div></div>
</div>
<div class="sec">Revenue per Driver</div>
<table><thead><tr><th>Driver</th><th>Calls</th><th style="text-align:right">Tow/Light Rev</th><th style="text-align:right">Battery Rev</th><th style="text-align:right">Hours</th><th style="text-align:right">Rev/Hour</th></tr></thead><tbody>${dRows}</tbody></table>
${bRows ? `<div class="sec">Battery Revenue per Driver</div><table><thead><tr><th>Driver</th><th style="text-align:right">Battery Calls</th><th style="text-align:right">Battery Revenue</th></tr></thead><tbody>${bRows}</tbody></table>` : ''}
<p class="note">Revenue = SA → WOLI → WO → Total_Amount_Invoiced__c · Battery excluded from Tow/Light · Drop-Off SAs excluded from revenue</p>
</body></html>`)
          w.document.close(); setTimeout(() => w.print(), 300)
        }} className="flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-medium border rounded-lg transition text-slate-300 bg-slate-800/60 hover:bg-slate-700/60 border-slate-700/40">
          <FileText className="w-3.5 h-3.5" />PDF
        </button>
        <button disabled={exporting}
          onClick={() => { setExporting(true); exportDriverRevenue(garageId, startDate, endDate, garageName); setTimeout(() => setExporting(false), 5000) }}
          className={clsx('flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-medium border rounded-lg transition',
            exporting ? 'text-amber-400 bg-amber-900/20 border-amber-700/40 cursor-wait' : 'text-slate-300 bg-slate-800/60 hover:bg-slate-700/60 border-slate-700/40')}>
          {exporting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
          {exporting ? 'Generating...' : 'Export Excel'}
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-4">
        <div className="glass rounded-xl p-4 border border-slate-700/30">
          <div className="flex items-center gap-1 text-[10px] text-slate-500 uppercase tracking-wider mb-1">
            Tow/Light Revenue
            <InfoTip text={"HOW THIS IS CALCULATED:\n\nSum of Total_Amount_Invoiced__c for WorkOrders where a driver completed a non-battery Pick-Up SA in the period.\n\nPIPELINE: SA → ParentRecordId → WorkOrderLineItem → WorkOrderId → all billing WOLIs → sum(Total_Amount_Invoiced__c)\n\nEXCLUDED from this figure:\n  • Tow Drop-Off SAs (revenue credited to Pick-Up only)\n  • Battery Jump Start SAs (shown separately in Battery Revenue card)\n\nWHY THIS ≠ INVOICE TOTAL:\nInvoices include calls billed in this period but completed before it (~7-day billing lag) and cancelled-but-billed calls. No scale factor applied."} />
          </div>
          <div className="text-2xl font-black text-emerald-400">{fmtRevFull(summary.total_attributed)}</div>
          <div className="text-[10px] text-slate-600 mt-0.5">Excl. Battery · billing WOLIs</div>
        </div>
        <div className="glass rounded-xl p-4 border border-slate-700/30">
          <div className="flex items-center gap-1 text-[10px] text-slate-500 uppercase tracking-wider mb-1">
            Battery Revenue
            <InfoTip text={"HOW THIS IS CALCULATED:\n\nSame pipeline as Tow/Light Revenue but for Battery Jump Start SAs only.\n\nPIPELINE: Battery SA → ParentRecordId → WOLI → WO → sum(Total_Amount_Invoiced__c)\n\nBattery calls are separated from tow/light revenue because they have a different billing profile and volume pattern. See the Battery Revenue per Driver chart below.\n\nNOTE: Battery Drop-Off SAs (if any) are excluded the same way as Tow Drop-Off."} />
          </div>
          <div className="text-2xl font-black text-amber-400">{fmtRevFull(summary.total_battery_revenue ?? 0)}</div>
          <div className="text-[10px] text-slate-600 mt-0.5">Battery Jump Start only</div>
        </div>
        <div className="glass rounded-xl p-4 border border-slate-700/30">
          <div className="flex items-center gap-1 text-[10px] text-slate-500 uppercase tracking-wider mb-1">
            Active Drivers
            <InfoTip text={"HOW THIS IS CALCULATED:\n\nCount of On-Platform Contractor drivers who completed at least one ServiceAppointment in this period.\n\nFILTERS APPLIED:\n  • ERS_Driver_Type__c = 'On-Platform Contractor Driver'\n  • ServiceResource.IsActive = true (inactive/terminated drivers excluded)\n  • Status = 'Completed' on the SA\n\nNOTE: Fleet drivers have no individual billing attribution in Salesforce. This tab is specific to On-Platform Contractor garages."} />
          </div>
          <div className="text-2xl font-black text-white">{summary.total_drivers}</div>
          <div className="text-[10px] text-slate-600 mt-0.5">On-Platform Contractor</div>
        </div>
        <div className="glass rounded-xl p-4 border border-slate-700/30">
          <div className="flex items-center gap-1 text-[10px] text-slate-500 uppercase tracking-wider mb-1">
            Total Calls
            <InfoTip text={"HOW THIS IS CALCULATED:\n\nCount of all completed ServiceAppointments (SA) assigned to this garage's drivers in the selected period — all call types included.\n\nIncludes: Tow Pick-Up, Tow Drop-Off, Battery Jump Start, Tire Change, Lock-Out, Fuel Delivery, etc.\n\nTow Drop-Off is INCLUDED in this count (total activity) but EXCLUDED from all revenue figures. Battery is counted here and shown in its own revenue chart.\n\nSOURCE: AssignedResource → ServiceAppointment WHERE Status = 'Completed' AND CreatedDate IN period"} />
          </div>
          <div className="text-2xl font-black text-white">{summary.total_calls?.toLocaleString()}</div>
          <div className="text-[10px] text-slate-600 mt-0.5">All types incl. Drop-Off</div>
        </div>
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-2 gap-6">

        {/* ── Left: Revenue per driver ──────────────────────────────── */}
        <div className="glass rounded-xl border border-slate-700/30 p-4">
          <div className="flex items-center gap-2 mb-4">
            <DollarSign className="w-4 h-4 text-emerald-400" />
            <span className="text-sm font-semibold text-white">Revenue per Driver</span>
            <InfoTip text={"HOW THIS IS CALCULATED:\n\nFor each driver: sum of Total_Amount_Invoiced__c for Tow/Light call WOs only (Battery excluded — see chart below).\n\nPIPELINE:\n  AssignedResource → SA (Completed, non-Drop-Off, non-Battery)\n  → ParentRecordId → WOLI → WO → sum(Total_Amount_Invoiced__c)\n\nDeduplication: same WO counted once per driver.\nTop 20 by revenue. Sorted descending.\n\nBAR COLORS: Blue = top 5 · Amber = 6–15 · Grey = 16–20\n\nClick a bar to expand daily breakdown."} />
            <button onClick={() => setSortRevDir(d => d === 'desc' ? 'asc' : 'desc')}
              title={sortRevDir === 'desc' ? 'Switch to lowest first' : 'Switch to highest first'}
              className="ml-1 p-0.5 rounded hover:bg-slate-700/50 text-slate-500 hover:text-slate-300 transition">
              {sortRevDir === 'desc' ? <ArrowDown className="w-3 h-3" /> : <ArrowUp className="w-3 h-3" />}
            </button>
            <span className="text-[10px] text-slate-500 ml-auto">Top {sortedByRev.length} of {drivers.length}</span>
          </div>
          <div className="space-y-0.5">
            {sortedByRev.map((d, i) => (
              <div key={d.name}>
                <HBar
                  label={d.name}
                  subtitle={`${d.calls} calls`}
                  value={d.revenue}
                  maxValue={maxRev}
                  barClass={i < 5 ? 'bg-brand-500' : i < 15 ? 'bg-amber-500' : 'bg-slate-500'}
                  labelRight={fmtRev(d.revenue)}
                  active={expanded === d.name}
                  onClick={() => toggle(d.name)}
                />
                {expanded === d.name && (
                  <div className="mx-2 mb-2 mt-1 rounded-lg bg-slate-900/60 border border-slate-700/30 px-3">
                    <DriverDrillDown
                      garageId={garageId}
                      driverName={d.name}
                      startDate={startDate}
                      endDate={endDate}
                    />
                  </div>
                )}
              </div>
            ))}
          </div>
          <div className="text-[9px] text-slate-600 mt-3 pt-2 border-t border-slate-800/40">
            Click a driver to expand daily breakdown
          </div>
        </div>

        {/* ── Right: Revenue per hour ───────────────────────────────── */}
        <div className="glass rounded-xl border border-slate-700/30 p-4">
          <div className="flex items-center gap-2 mb-3">
            <Clock className="w-4 h-4 text-amber-400" />
            <span className="text-sm font-semibold text-white">Revenue per Hour</span>
            <InfoTip text={"HOW THIS IS CALCULATED:\n\nRevenue per Hour = Tow/Light Revenue ÷ Hours Worked  (Battery excluded from revenue numerator)\n\nSORTED: Descending by Revenue per Hour\n\nHOW HOURS ARE MEASURED:\n  Source: AssetHistory (Salesforce) — field ERS_Driver__c on ERS Truck assets\n  Login  = NewValue written  · Logout = OldValue cleared\n  Sessions capped at 16 h (forgotten logout guard)\n  Open sessions (no logout) discarded\n  ~955 ERS Trucks queried in parallel batches of 200\n\nDRIVERS NOT SHOWN: zero tracked hours excluded (can't divide). Still appear in Revenue per Driver chart.\n\nCOLOR THRESHOLDS: Green ≥ $100/h · Amber $60–$99/h · Red < $60/h\n\nNOTE: Depends on drivers logging truck time in Salesforce FSL app."} />
            <button onClick={() => setSortRphDir(d => d === 'desc' ? 'asc' : 'desc')}
              title={sortRphDir === 'desc' ? 'Switch to lowest first' : 'Switch to highest first'}
              className="ml-1 p-0.5 rounded hover:bg-slate-700/50 text-slate-500 hover:text-slate-300 transition">
              {sortRphDir === 'desc' ? <ArrowDown className="w-3 h-3" /> : <ArrowUp className="w-3 h-3" />}
            </button>
            <span className="text-[10px] text-slate-500 ml-auto">{withHours.length} tracked</span>
          </div>
          {/* Legend */}
          <div className="flex gap-3 mb-3">
            {[['bg-emerald-500','≥ $100/h'],['bg-amber-500','$60–$99/h'],['bg-red-500','< $60/h']].map(([cls, lbl]) => (
              <div key={lbl} className="flex items-center gap-1">
                <div className={clsx('w-2 h-2 rounded-full', cls)} />
                <span className="text-[9px] text-slate-500">{lbl}</span>
              </div>
            ))}
          </div>
          <div className="space-y-0.5 overflow-y-auto max-h-[520px] pr-1">
            {withHours.map(d => (
              <div key={d.name}>
                <HBar
                  label={d.name}
                  subtitle={`${d.shift_days}d / ${d.hours}h`}
                  value={d.rev_per_hour}
                  maxValue={maxRph}
                  barClass={rphColor(d.rev_per_hour)}
                  labelRight={`$${d.rev_per_hour}/h`}
                  active={expanded === d.name}
                  onClick={() => toggle(d.name)}
                />
                {expanded === d.name && (
                  <div className="mx-2 mb-2 mt-1 rounded-lg bg-slate-900/60 border border-slate-700/30 px-3">
                    <DriverDrillDown
                      garageId={garageId}
                      driverName={d.name}
                      startDate={startDate}
                      endDate={endDate}
                    />
                  </div>
                )}
              </div>
            ))}
          </div>
          <div className="text-[9px] text-slate-600 mt-3 pt-2 border-t border-slate-800/40">
            Hours = AssetHistory login/logout · sessions capped 16 h · open sessions discarded
          </div>
        </div>
      </div>

      {/* Battery Revenue per Driver chart */}
      {battDrivers.length > 0 && (
        <div className="glass rounded-xl border border-amber-700/20 p-4">
          <div className="flex items-center gap-2 mb-4">
            <span className="text-base">🔋</span>
            <span className="text-sm font-semibold text-white">Battery Revenue per Driver</span>
            <InfoTip text={"HOW THIS IS CALCULATED:\n\nFor each driver: sum of Total_Amount_Invoiced__c for Battery Jump Start WOs only.\n\nPIPELINE:\n  AssignedResource → SA (Completed, WorkType contains 'Battery')\n  → ParentRecordId → WOLI → WO → sum(Total_Amount_Invoiced__c)\n\nSame deduplication rule: same WO counted once per driver.\nSorted descending by battery revenue.\n\nWHY SEPARATE FROM TOW/LIGHT:\nBattery calls have a different rate and different billing profile. Mixing them with tow revenue distorts per-driver comparisons. This chart isolates battery-specific revenue contribution."} />
            <span className="text-[10px] text-slate-500 ml-auto">
              {battDrivers.length} drivers · {fmtRevFull(summary.total_battery_revenue ?? 0)} total
            </span>
          </div>
          <div className="grid grid-cols-2 gap-6">
            <div className="space-y-0.5">
              {battDrivers.map(d => (
                <div key={d.name}>
                  <HBar
                    label={d.name}
                    subtitle={`${d.battery_calls} battery call${d.battery_calls !== 1 ? 's' : ''}`}
                    value={d.battery_revenue}
                    maxValue={maxBattRev}
                    barClass="bg-amber-500"
                    labelRight={fmtRev(d.battery_revenue)}
                    active={expanded === `batt_${d.name}`}
                    onClick={() => setExpanded(e => e === `batt_${d.name}` ? null : `batt_${d.name}`)}
                  />
                  {expanded === `batt_${d.name}` && (
                    <div className="mx-2 mb-2 mt-1 rounded-lg bg-slate-900/60 border border-slate-700/30 px-3">
                      <DriverDrillDown
                        garageId={garageId}
                        driverName={d.name}
                        startDate={startDate}
                        endDate={endDate}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
            <div className="text-[11px] text-slate-500 space-y-2 pt-1">
              <div className="font-semibold text-slate-400 text-[10px] uppercase tracking-wider mb-3">Top battery earners</div>
              {battDrivers.slice(0, 5).map((d, i) => (
                <div key={d.name} className="flex items-center gap-2">
                  <span className="text-[10px] text-slate-600 w-4">{i + 1}.</span>
                  <span className="text-slate-300 flex-1 truncate">{d.name}</span>
                  <span className="text-amber-400 font-semibold">{fmtRevFull(d.battery_revenue)}</span>
                  <span className="text-slate-600 text-[10px]">({d.battery_calls} calls)</span>
                </div>
              ))}
            </div>
          </div>
          <div className="text-[9px] text-slate-600 mt-3 pt-2 border-t border-slate-800/40">
            Battery revenue = SA → WOLI → WO → Total_Amount_Invoiced__c · Battery Jump Start type only · Drop-Off excluded
          </div>
        </div>
      )}

      <div className="text-[9px] text-slate-700 text-center">
        Tow/Light revenue excludes Battery and Drop-Off SAs · Battery revenue shown separately above · Pipeline: SA → WOLI → WO → Total_Amount_Invoiced__c
      </div>
    </div>
  )
}
