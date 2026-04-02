import { useState, useEffect, useMemo } from 'react'
import { clsx } from 'clsx'
import {
  BookOpen, ShieldCheck, AlertTriangle, CheckCircle2,
  XCircle, Loader2, Database, RefreshCw, Filter,
} from 'lucide-react'
import { fetchDataQuality, refreshDataQuality } from '../api'
import DictionaryTab, { DICTIONARY } from '../components/DataDictionaryTable'

// ── Severity badge ───────────────────────────────────────────────────────────

const SEV = {
  critical: { bg: 'bg-red-950/30', border: 'border-red-800/40', text: 'text-red-400', icon: XCircle, label: 'Critical' },
  warn:     { bg: 'bg-amber-950/20', border: 'border-amber-800/30', text: 'text-amber-400', icon: AlertTriangle, label: 'Warning' },
  ok:       { bg: 'bg-emerald-950/20', border: 'border-emerald-800/30', text: 'text-emerald-400', icon: CheckCircle2, label: 'OK' },
}

function SevBadge({ severity }) {
  const s = SEV[severity] || SEV.ok
  const Icon = s.icon
  return (
    <span className={clsx('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border', s.bg, s.border, s.text)}>
      <Icon className="w-3 h-3" />
      {s.label}
    </span>
  )
}

// ── Progress bar ─────────────────────────────────────────────────────────────

function QualityBar({ pct, severity }) {
  const color = severity === 'critical' ? 'bg-red-500' : severity === 'warn' ? 'bg-amber-500' : 'bg-emerald-500'
  return (
    <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
      <div className={clsx('h-full rounded-full transition-all', color)} style={{ width: `${Math.min(pct || 0, 100)}%` }} />
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────────

const TABS = [
  { key: 'dictionary', label: 'Field Dictionary', icon: BookOpen },
  { key: 'quality',    label: 'Data Quality Audit', icon: ShieldCheck },
]

export default function DataDictionary() {
  const [tab, setTab] = useState('dictionary')
  const [quality, setQuality] = useState(null)
  const [qLoading, setQLoading] = useState(false)
  const [qError, setQError] = useState(null)
  const [groupFilter, setGroupFilter] = useState('all')

  const totalFields = DICTIONARY.reduce((s, g) => s + g.fields.length, 0)

  // Load data quality when tab is selected
  useEffect(() => {
    if (tab === 'quality' && !quality && !qLoading) {
      setQLoading(true)
      setQError(null)
      fetchDataQuality()
        .then(setQuality)
        .catch(e => setQError(e.response?.data?.detail || e.message))
        .finally(() => setQLoading(false))
    }
  }, [tab])

  // ── Quality filter ──
  const qualityGroups = useMemo(() => {
    if (!quality) return []
    const groups = {}
    for (const f of quality.fields) {
      if (!groups[f.group]) groups[f.group] = []
      groups[f.group].push(f)
    }
    return Object.entries(groups).map(([name, fields]) => ({ name, fields }))
  }, [quality])

  const filteredQuality = useMemo(() => {
    if (groupFilter === 'all') return qualityGroups
    if (groupFilter === 'issues') {
      return qualityGroups.map(g => ({
        ...g,
        fields: g.fields.filter(f => f.severity !== 'ok'),
      })).filter(g => g.fields.length > 0)
    }
    return qualityGroups.filter(g => g.name === groupFilter)
  }, [qualityGroups, groupFilter])

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <Database className="w-6 h-6 text-brand-400" />
            Data Dictionary & Quality
          </h1>
          <p className="text-slate-500 text-xs mt-0.5">
            {totalFields} fields across {DICTIONARY.length} groups — every Salesforce field used in this app
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-slate-900 rounded-xl mb-6 w-fit">
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={clsx(
              'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all',
              tab === t.key
                ? 'bg-brand-600 text-white shadow-lg shadow-brand-600/20'
                : 'text-slate-400 hover:text-white hover:bg-slate-800'
            )}
          >
            <t.icon className="w-4 h-4" />
            {t.label}
            {t.key === 'quality' && quality?.summary && (
              <span className={clsx('ml-1 px-1.5 py-0.5 rounded-full text-[9px] font-bold',
                quality.summary.critical_issues > 0 ? 'bg-red-500 text-white' : 'bg-emerald-500 text-white')}>
                {quality.summary.critical_issues > 0 ? `${quality.summary.critical_issues} issues` : 'OK'}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ═══ DICTIONARY TAB ══════════════════════════════════════════════════════ */}
      {tab === 'dictionary' && <DictionaryTab />}

      {/* ═══ DATA QUALITY TAB ════════════════════════════════════════════════════ */}
      {tab === 'quality' && (
        <div>
          {/* Loading */}
          {qLoading && (
            <div className="flex items-center justify-center py-20 gap-3">
              <Loader2 className="w-6 h-6 animate-spin text-brand-400" />
              <span className="text-slate-400">Auditing field quality across {'>'}28 days of data...</span>
            </div>
          )}

          {/* Error */}
          {qError && !qLoading && (
            <div className="rounded-xl bg-red-950/30 border border-red-800/30 p-4 text-red-300 text-sm">
              Failed to load data quality: {qError}
            </div>
          )}

          {/* Results */}
          {quality && !qLoading && (
            <>
              {/* Summary cards */}
              <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-5">
                <div className="glass rounded-xl p-4">
                  <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Period</div>
                  <div className="text-sm font-bold text-white">{quality.period}</div>
                  {quality.refreshed_at && (
                    <div className="text-[9px] text-slate-600 mt-1">Refreshed: {quality.refreshed_at}</div>
                  )}
                </div>
                <div className="glass rounded-xl p-4">
                  <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Total SAs</div>
                  <div className="text-lg font-bold text-white">{quality.total_sas?.toLocaleString()}</div>
                  <div className="text-[10px] text-slate-500">{quality.completed_sas?.toLocaleString()} completed</div>
                </div>
                <div className={clsx('glass rounded-xl p-4', quality.summary.critical_issues > 0 && 'border border-red-800/30')}>
                  <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Critical Issues</div>
                  <div className={clsx('text-lg font-bold', quality.summary.critical_issues > 0 ? 'text-red-400' : 'text-emerald-400')}>
                    {quality.summary.critical_issues}
                  </div>
                </div>
                <div className="glass rounded-xl p-4">
                  <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Warnings</div>
                  <div className={clsx('text-lg font-bold', quality.summary.warnings > 0 ? 'text-amber-400' : 'text-slate-500')}>
                    {quality.summary.warnings}
                  </div>
                </div>
                <div className="glass rounded-xl p-4">
                  <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Healthy</div>
                  <div className="text-lg font-bold text-emerald-400">{quality.summary.healthy}</div>
                  <div className="text-[10px] text-slate-500">of {quality.summary.total_fields_checked} checked</div>
                </div>
              </div>

              {/* Critical issues callout */}
              {quality.summary.critical_issues > 0 && (
                <div className="mb-5 p-4 rounded-xl border border-red-800/30 bg-red-950/10">
                  <div className="flex items-center gap-2 mb-2">
                    <XCircle className="w-4 h-4 text-red-400" />
                    <span className="text-xs font-bold text-red-300 uppercase tracking-wide">
                      {quality.summary.critical_issues} Critical Data Quality Issue{quality.summary.critical_issues > 1 ? 's' : ''}
                    </span>
                  </div>
                  <div className="text-xs text-red-300/80">
                    {quality.summary.critical_field_names.join(', ')} — these affect core metrics like response time and SLA rates.
                  </div>
                </div>
              )}

              {/* Filter bar */}
              <div className="flex items-center gap-2 mb-4">
                <Filter className="w-3.5 h-3.5 text-slate-500" />
                <div className="flex gap-1 flex-wrap">
                  {[
                    { key: 'all', label: 'All Fields' },
                    { key: 'issues', label: 'Issues Only' },
                    ...qualityGroups.map(g => ({ key: g.name, label: g.name })),
                  ].map(f => (
                    <button
                      key={f.key}
                      onClick={() => setGroupFilter(f.key)}
                      className={clsx(
                        'px-2.5 py-1 rounded-lg text-[10px] font-medium transition-all',
                        groupFilter === f.key
                          ? 'bg-brand-600/30 text-brand-300 border border-brand-500/30'
                          : 'text-slate-500 hover:text-white hover:bg-slate-800 border border-transparent'
                      )}
                    >
                      {f.label}
                    </button>
                  ))}
                </div>
                <button
                  onClick={() => { setQuality(null); setQLoading(true); setQError(null); refreshDataQuality().then(setQuality).catch(e => setQError(e.response?.data?.detail || e.message)).finally(() => setQLoading(false)) }}
                  disabled={qLoading}
                  className="ml-auto flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[10px] text-slate-500 hover:text-white hover:bg-slate-800 transition-all disabled:opacity-50"
                >
                  <RefreshCw className={clsx('w-3 h-3', qLoading && 'animate-spin')} />
                  {qLoading ? 'Refreshing...' : 'Refresh from Salesforce'}
                </button>
              </div>

              {/* Quality cards by group */}
              <div className="space-y-4">
                {filteredQuality.map(group => (
                  <div key={group.name} className="glass rounded-xl overflow-hidden">
                    <div className="px-5 py-3 border-b border-slate-800/60">
                      <h3 className="text-sm font-semibold text-slate-200">{group.name}</h3>
                    </div>
                    <div className="divide-y divide-slate-800/30">
                      {group.fields.map(f => (
                        <div key={f.field} className={clsx('px-5 py-4', f.severity === 'critical' && 'bg-red-950/5')}>
                          <div className="flex items-start gap-4">
                            {/* Left: field info */}
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-1.5">
                                <span className="font-semibold text-white text-sm">{f.label}</span>
                                <SevBadge severity={f.severity} />
                              </div>
                              <div className="font-mono text-[11px] text-brand-300/70 mb-2">{f.field}</div>
                              <div className="text-xs text-slate-400 leading-relaxed mb-3">{f.description}</div>

                              {/* Issues */}
                              <div className="text-xs text-slate-300 bg-slate-800/40 rounded-lg px-3 py-2 mb-2">
                                <span className="text-slate-500 font-medium">Issues: </span>
                                {f.issues}
                              </div>

                              {/* Impact */}
                              <div className="text-xs text-slate-400">
                                <span className="text-slate-500 font-medium">Impact on metrics: </span>
                                {f.impact}
                              </div>
                            </div>

                            {/* Right: stats */}
                            <div className="w-48 shrink-0 space-y-2">
                              <div className="flex justify-between items-baseline">
                                <span className="text-[10px] text-slate-500">Populated</span>
                                <span className={clsx('text-sm font-bold', f.pct >= 90 ? 'text-emerald-400' : f.pct >= 70 ? 'text-amber-400' : 'text-red-400')}>
                                  {f.pct != null ? `${f.pct}%` : 'N/A'}
                                </span>
                              </div>
                              <QualityBar pct={f.pct} severity={f.severity} />
                              <div className="text-[10px] text-slate-600">
                                {f.populated?.toLocaleString()} of {f.total?.toLocaleString()} records
                              </div>

                              {/* Detail breakdown if available */}
                              {f.detail && f.detail.breakdown && (
                                <div className="pt-2 border-t border-slate-800/40 space-y-1">
                                  {Object.entries(f.detail.breakdown).map(([k, v]) => (
                                    <div key={k} className="flex justify-between text-[10px]">
                                      <span className="text-slate-500">{k}</span>
                                      <span className="text-slate-400">{v?.toLocaleString()}</span>
                                    </div>
                                  ))}
                                </div>
                              )}
                              {f.detail && f.detail.usable != null && (
                                <div className="pt-2 border-t border-slate-800/40 space-y-1 text-[10px]">
                                  <div className="flex justify-between">
                                    <span className="text-slate-500">Usable values</span>
                                    <span className="text-emerald-400 font-bold">{f.detail.usable?.toLocaleString()}</span>
                                  </div>
                                  <div className="flex justify-between">
                                    <span className="text-slate-500">Invalid (0 / 999+)</span>
                                    <span className="text-red-400">{f.detail.sentinel_zero_or_999?.toLocaleString()}</span>
                                  </div>
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>

              {filteredQuality.length === 0 && (
                <div className="text-center py-16 text-slate-600 text-sm">No fields match this filter.</div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
