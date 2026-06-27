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
import { Loader2, DollarSign, Clock, BarChart2, Mail, Download, FileText, ArrowUp, ArrowDown, ExternalLink } from 'lucide-react'
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
  const [mcExpanded, setMcExpanded]   = useState(null)

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

  // Total revenue per driver = AAA billed (tow + battery) + member collected
  const driverTotal = (d) => (d.revenue || 0) + (d.battery_revenue || 0) + (d.member_collected || 0)
  const driverRph   = (d) => d.hours > 0 ? Math.round(driverTotal(d) / d.hours * 10) / 10 : 0

  // Revenue per Driver: top 20, direction toggleable
  const sortedByRev = sortRevDir === 'desc'
    ? drivers.slice(0, 20)
    : [...drivers].sort((a, b) => driverTotal(a) - driverTotal(b)).slice(0, 20)
  const maxRev = Math.max(...sortedByRev.map(d => driverTotal(d)), 1)

  // Revenue per Hour: sorted by rev/hour (total), direction toggleable
  const withHours = [...drivers.filter(d => d.hours > 0)]
    .sort((a, b) => sortRphDir === 'desc' ? driverRph(b) - driverRph(a) : driverRph(a) - driverRph(b))
  const maxRph = Math.max(...withHours.map(d => driverRph(d)), 1)

  const toggle = (name) => setExpanded(e => e === name ? null : name)

  // Member collected — only drivers with tow revenue (only tow WOs have over-mileage charges)
  const driversWithMC = drivers.filter(d => (d.member_collected || 0) > 0)
    .sort((a, b) => b.member_collected - a.member_collected)

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
          const allDrivers = [...drivers].sort((a, b) => ((b.revenue||0)+(b.battery_revenue||0)+(b.member_collected||0)) - ((a.revenue||0)+(a.battery_revenue||0)+(a.member_collected||0)))
          const fmt = v => v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
          const dRows = allDrivers.map(d => {
            const tot = (d.revenue||0)+(d.battery_revenue||0)+(d.member_collected||0)
            const rph = d.hours > 0 ? Math.round(tot / d.hours * 10) / 10 : 0
            return `<tr><td>${d.name}</td><td>${d.calls}</td>` +
              `<td style="text-align:right;color:#16a34a">$${fmt((d.revenue||0)+(d.battery_revenue||0))}</td>` +
              `<td style="text-align:right;color:#0284c7">$${fmt(d.member_collected||0)}</td>` +
              `<td style="text-align:right;font-weight:700">$${fmt(tot)}</td>` +
              `<td style="text-align:right">${d.hours > 0 ? d.hours + 'h' : '—'}</td>` +
              `<td style="text-align:right">${rph > 0 ? '$' + rph + '/h' : '—'}</td></tr>`
          }).join('')
          const totalAAA = (summary.total_attributed||0)+(summary.total_battery_revenue||0)
          const totalMC  = summary.total_member_collected||0
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
  <div class="card"><div class="clabel">AAA Revenue</div><div class="cval" style="color:#16a34a">$${fmt(totalAAA)}</div></div>
  <div class="card"><div class="clabel">Member Collected</div><div class="cval" style="color:#0284c7">$${fmt(totalMC)}</div></div>
  <div class="card"><div class="clabel">Total Revenue</div><div class="cval">$${fmt(totalAAA+totalMC)}</div></div>
  <div class="card"><div class="clabel">Active Drivers</div><div class="cval">${summary.total_drivers}</div></div>
  <div class="card"><div class="clabel">Total Calls</div><div class="cval">${(summary.total_calls||0).toLocaleString()}</div></div>
</div>
<div class="sec">Revenue per Driver</div>
<table><thead><tr><th>Driver</th><th>Calls</th><th style="text-align:right">AAA Revenue</th><th style="text-align:right">Member Collected</th><th style="text-align:right">Total</th><th style="text-align:right">Hours</th><th style="text-align:right">Rev/Hour</th></tr></thead><tbody>${dRows}</tbody></table>
<p class="note">Revenue = SA → WOLI → WO cost fields · Member Collected = over-mileage charges · Drop-Off SAs excluded</p>
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
      <div className="grid grid-cols-5 gap-4">
        <div className="glass rounded-xl p-4 border border-slate-700/30">
          <div className="flex items-center gap-1 text-[10px] text-slate-500 uppercase tracking-wider mb-1">
            AAA Revenue
            <InfoTip text={"HOW THIS IS CALCULATED:\n\nSum of billing WOLI cost fields (Basic + Plus + Premier + RV + Other) for all completed non-Drop-Off SAs — tow/light AND battery combined.\n\nPIPELINE: SA → ParentRecordId → WOLI → WO → sum cost fields\n\nDoes NOT include member-collected over-mileage charges (shown separately).\n\nWHY THIS ≠ INVOICE TOTAL: Invoices include calls billed in this period but completed before it (~7-day billing lag). No scale factor applied."} />
          </div>
          <div className="text-2xl font-black text-emerald-400">{fmtRevFull((summary.total_attributed || 0) + (summary.total_battery_revenue || 0))}</div>
          <div className="text-[10px] text-slate-600 mt-0.5">Tow + Battery · AAA billed</div>
        </div>
        <div className="glass rounded-xl p-4 border border-slate-700/30">
          <div className="flex items-center gap-1 text-[10px] text-slate-500 uppercase tracking-wider mb-1">
            Member Collected
            <InfoTip text={"HOW THIS IS CALCULATED:\n\nEst_Tow_Over_Mileage_Cost_to_Member1__c on the WorkOrder — the estimated cost billed directly to the member for tow over-mileage (distance beyond covered miles).\n\nNOTE: Only tow WorkOrders have this field. Battery, Lockout, Tire, and other call types do not generate member-collected charges."} />
          </div>
          <div className="text-2xl font-black text-sky-400">{fmtRevFull(summary.total_member_collected ?? 0)}</div>
          <div className="text-[10px] text-slate-600 mt-0.5">Member over-mileage</div>
        </div>
        <div className="glass rounded-xl p-4 border border-slate-700/30">
          <div className="flex items-center gap-1 text-[10px] text-slate-500 uppercase tracking-wider mb-1">
            Total Revenue
            <InfoTip text={"HOW THIS IS CALCULATED:\n\nTotal Revenue = AAA Revenue (tow + battery) + Member Collected (over-mileage).\n\nThis is the full economic value generated by drivers in this period regardless of who pays (AAA or member)."} />
          </div>
          <div className="text-2xl font-black text-white">{fmtRevFull((summary.total_attributed || 0) + (summary.total_battery_revenue || 0) + (summary.total_member_collected || 0))}</div>
          <div className="text-[10px] text-slate-600 mt-0.5">AAA + Member Collected</div>
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
            <InfoTip text={"HOW THIS IS CALCULATED:\n\nCount of all completed ServiceAppointments (SA) assigned to this garage's drivers in the selected period — all call types included.\n\nIncludes: Tow Pick-Up, Tow Drop-Off, Battery Jump Start, Tire Change, Lock-Out, Fuel Delivery, etc.\n\nTow Drop-Off is INCLUDED in this count (total activity) but EXCLUDED from all revenue figures.\n\nSOURCE: AssignedResource → ServiceAppointment WHERE Status = 'Completed' AND CreatedDate IN period"} />
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
            <InfoTip text={"HOW THIS IS CALCULATED:\n\nTotal Revenue per driver = AAA Revenue (tow + battery) + Member Collected (over-mileage).\n\nThis matches the Total column shown in the daily drill-down.\n\nPIPELINE:\n  AssignedResource → SA (Completed, non-Drop-Off)\n  → ParentRecordId → WOLI → WO → sum cost fields\n  + Est_Tow_Over_Mileage_Cost_to_Member1__c\n\nDeduplication: same WO counted once per driver.\nTop 20 by total revenue. Sorted descending.\n\nBAR COLORS: Blue = top 5 · Amber = 6–15 · Grey = 16–20\n\nClick a bar to expand daily breakdown."} />
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
                  subtitle={`${d.work_orders ?? d.calls} WOs`}
                  value={driverTotal(d)}
                  maxValue={maxRev}
                  barClass={i < 5 ? 'bg-brand-500' : i < 15 ? 'bg-amber-500' : 'bg-slate-500'}
                  labelRight={fmtRev(driverTotal(d))}
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
            <InfoTip text={"HOW THIS IS CALCULATED:\n\nRevenue per Hour = Total Revenue (tow + battery + member collected) ÷ Hours Worked\n\nSORTED: Descending by Revenue per Hour\n\nHOW HOURS ARE MEASURED:\n  Source: AssetHistory (Salesforce) — field ERS_Driver__c on ERS Truck assets\n  Login  = NewValue written  · Logout = OldValue cleared\n  Sessions capped at 16 h (forgotten logout guard)\n  Open sessions (no logout) discarded\n  ~955 ERS Trucks queried in parallel batches of 200\n\nDRIVERS NOT SHOWN: zero tracked hours excluded (can't divide). Still appear in Revenue per Driver chart.\n\nCOLOR THRESHOLDS: Green ≥ $100/h · Amber $60–$99/h · Red < $60/h\n\nNOTE: Depends on drivers logging truck time in Salesforce FSL app."} />
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
                  value={driverRph(d)}
                  maxValue={maxRph}
                  barClass={rphColor(driverRph(d))}
                  labelRight={`$${driverRph(d)}/h`}
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

      {/* Member Collected Revenue table */}
      {driversWithMC.length > 0 && (
        <div className="glass rounded-xl border border-sky-700/20 p-4">
          <div className="flex items-center gap-2 mb-4">
            <DollarSign className="w-4 h-4 text-sky-400" />
            <span className="text-sm font-semibold text-white">Member Collected Revenue</span>
            <InfoTip text={"HOW THIS IS CALCULATED:\n\nMember Collected = Est_Tow_Over_Mileage_Cost_to_Member1__c on the WorkOrder.\nThis is the estimated cost billed directly to the member for tow over-mileage (distance beyond covered miles).\n\nAAA Billed = sum of billing WOLI cost fields (Basic + Plus + Premier + RV + Other)\nTotal = AAA Billed + Member Collected\n\nNOTE: Only tow WorkOrders have an over-mileage member charge field. Battery, Lockout, Tire, and other call types do not have an equivalent field in Salesforce."} />
            <span className="text-[10px] text-slate-500 ml-auto">
              {driversWithMC.length} driver{driversWithMC.length !== 1 ? 's' : ''} with member charges
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="text-[11px] w-auto min-w-full">
              <colgroup>
                <col />
                <col className="w-32" />
                <col className="w-28" />
                <col className="w-28" />
                <col className="w-24" />
              </colgroup>
              <thead>
                <tr className="border-b border-slate-700/40">
                  <th className="text-left py-1.5 px-3 text-slate-500 font-medium">Driver</th>
                  <th className="text-right py-1.5 px-3 text-slate-500 font-medium whitespace-nowrap">Calls w/ Member Charge</th>
                  <th className="text-right py-1.5 px-3 text-emerald-600/80 font-medium whitespace-nowrap">AAA Billed (MC WOs)</th>
                  <th className="text-right py-1.5 px-3 text-sky-500/80 font-medium whitespace-nowrap">Member Collected</th>
                  <th className="text-right py-1.5 px-3 text-white font-medium whitespace-nowrap">Total</th>
                </tr>
              </thead>
              <tbody>
                {driversWithMC.map(d => {
                  const wos = d.member_wo_details ?? []
                  const isOpen = mcExpanded === d.name
                  const rowTotal = (d.member_aaa_billed ?? 0) + d.member_collected
                  return (
                    <>
                      <tr
                        key={d.name}
                        className={clsx(
                          'border-b border-slate-800/30 cursor-pointer select-none',
                          isOpen ? 'bg-slate-800/40' : 'hover:bg-slate-800/20'
                        )}
                        onClick={() => setMcExpanded(isOpen ? null : d.name)}
                      >
                        <td className="py-1.5 px-3 text-slate-300">
                          {wos.length > 0 && (
                            <span className="mr-1 text-slate-500">{isOpen ? '▾' : '▸'}</span>
                          )}
                          {d.name}
                        </td>
                        <td className="py-1.5 px-3 text-right text-slate-400">{wos.length}</td>
                        <td className="py-1.5 px-3 text-right text-emerald-400 font-medium whitespace-nowrap">{fmtRevFull(d.member_aaa_billed ?? 0)}</td>
                        <td className="py-1.5 px-3 text-right text-sky-400 font-medium whitespace-nowrap">{fmtRevFull(d.member_collected)}</td>
                        <td className="py-1.5 px-3 text-right text-white font-bold whitespace-nowrap">{fmtRevFull(rowTotal)}</td>
                      </tr>
                      {isOpen && wos.length > 0 && (
                        <tr key={`${d.name}-wos`} className="bg-slate-900/60">
                          <td colSpan={5} className="px-6 py-2">
                            <table className="text-[10px] w-auto min-w-[480px]">
                              <colgroup>
                                <col className="w-32" />
                                <col className="w-24" />
                                <col className="w-24" />
                                <col className="w-24" />
                                <col className="w-56" />
                                <col className="w-14" />
                              </colgroup>
                              <thead>
                                <tr className="border-b border-slate-700/30">
                                  <th className="text-left py-1 px-2 text-slate-500">Work Order</th>
                                  <th className="text-left py-1 px-2 text-slate-500">Date</th>
                                  <th className="text-right py-1 px-2 text-emerald-600/70">AAA Billed</th>
                                  <th className="text-right py-1 px-2 text-sky-500/70">Member Collected</th>
                                  <th className="text-left py-1 px-2 text-slate-500">Reason</th>
                                  <th className="py-1 px-2" />
                                </tr>
                              </thead>
                              <tbody>
                                {wos.map(w => (
                                  <tr key={w.wo_id} className="border-b border-slate-800/20 hover:bg-slate-800/20">
                                    <td className="py-1 px-2">
                                      <a href={w.sf_url} target="_blank" rel="noreferrer"
                                        className="text-blue-400 hover:text-blue-300 flex items-center gap-1 font-mono whitespace-nowrap"
                                        onClick={e => e.stopPropagation()}>
                                        {w.wo_number}
                                        <ExternalLink size={9} />
                                      </a>
                                    </td>
                                    <td className="py-1 px-2 text-slate-400 whitespace-nowrap">{w.date}</td>
                                    <td className="py-1 px-2 text-right text-emerald-400 whitespace-nowrap">{fmtRevFull(w.aaa_billed ?? 0)}</td>
                                    <td className="py-1 px-2 text-right text-sky-400 font-medium whitespace-nowrap">{fmtRevFull(w.amount)}</td>
                                    <td className="py-1 px-2 text-slate-400">{w.reason || 'Est. Tow Over-Mileage Cost to Member'}</td>
                                    <td className="py-1 px-2" />
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </td>
                        </tr>
                      )}
                    </>
                  )
                })}
              </tbody>
              <tfoot>
                <tr className="border-t border-slate-700/50">
                  <td className="py-2 px-3 text-slate-400 font-semibold">Total</td>
                  <td className="py-2 px-3 text-right text-slate-300 font-semibold">
                    {driversWithMC.reduce((s, d) => s + (d.member_wo_details?.length ?? 0), 0)} calls
                  </td>
                  <td className="py-2 px-3 text-right text-emerald-300 font-bold whitespace-nowrap">
                    {fmtRevFull(driversWithMC.reduce((s, d) => s + (d.member_aaa_billed ?? 0), 0))}
                  </td>
                  <td className="py-2 px-3 text-right text-sky-300 font-bold whitespace-nowrap">
                    {fmtRevFull(summary.total_member_collected ?? 0)}
                  </td>
                  <td className="py-2 px-3 text-right text-white font-bold whitespace-nowrap">
                    {fmtRevFull(
                      driversWithMC.reduce((s, d) => s + (d.member_aaa_billed ?? 0) + d.member_collected, 0)
                    )}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
          <div className="text-[9px] text-slate-600 mt-3 pt-2 border-t border-slate-800/40">
            Member Collected = Est_Tow_Over_Mileage_Cost_to_Member1__c on WorkOrder · Tow over-mileage only · No equivalent field exists for Battery/Lockout/Tire
          </div>
        </div>
      )}

      <div className="text-[9px] text-slate-700 text-center">
        Tow/Light revenue excludes Battery and Drop-Off SAs · Pipeline: SA → WOLI → WO → billing cost fields
      </div>
    </div>
  )
}
