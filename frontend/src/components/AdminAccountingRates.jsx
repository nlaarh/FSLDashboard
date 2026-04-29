import { useState, useEffect, useCallback } from 'react'
import { Calculator, Save, Loader2, CheckCircle2, RotateCcw } from 'lucide-react'
import { adminGetAccountingRates, adminSetAccountingRate } from '../api'

const CATEGORY_ORDER = ['ER Miles Included', 'Tow Miles Included', 'Audit Thresholds', 'Time Caps']

export default function AdminAccountingRates({ pin }) {
  const [rates, setRates] = useState([])
  const [edits, setEdits] = useState({})   // code → edited value string
  const [saving, setSaving] = useState({}) // code → bool
  const [saved, setSaved] = useState({})   // code → bool
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await adminGetAccountingRates(pin)
      const list = Array.isArray(data) ? data : Object.values(data)
      setRates(list)
      // Reset edits to DB values on reload
      const initial = {}
      list.forEach(r => { initial[r.code] = String(r.value) })
      setEdits(initial)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [pin])

  useEffect(() => { load() }, [load])

  const save = async (code) => {
    const val = parseFloat(edits[code])
    if (isNaN(val)) return
    setSaving(s => ({ ...s, [code]: true }))
    setSaved(s => ({ ...s, [code]: false }))
    try {
      const updated = await adminSetAccountingRate(pin, code, val)
      setRates(prev => prev.map(r => r.code === code ? updated : r))
      setSaved(s => ({ ...s, [code]: true }))
      setTimeout(() => setSaved(s => ({ ...s, [code]: false })), 2500)
    } catch { /* ignore */ }
    finally { setSaving(s => ({ ...s, [code]: false })) }
  }

  const reset = (code) => {
    const r = rates.find(x => x.code === code)
    if (r) setEdits(e => ({ ...e, [code]: String(r.value) }))
  }

  // Group by category
  const byCategory = {}
  rates.forEach(r => {
    const cat = r.category || 'Other'
    if (!byCategory[cat]) byCategory[cat] = []
    byCategory[cat].push(r)
  })
  const categories = CATEGORY_ORDER.filter(c => byCategory[c])
  Object.keys(byCategory).forEach(c => { if (!categories.includes(c)) categories.push(c) })

  return (
    <div className="glass rounded-xl overflow-hidden">
      <div className="px-4 py-3 bg-slate-800/50 border-b border-slate-700/50 flex items-center gap-2">
        <Calculator className="w-4 h-4 text-amber-400" />
        <h2 className="text-sm font-semibold text-white">Accounting Reference Rates</h2>
        <span className="text-[10px] text-slate-500 ml-1">Included miles, audit thresholds, time caps</span>
        {loading && <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-500 ml-auto" />}
      </div>

      <div className="p-4 space-y-5">
        <p className="text-[11px] text-slate-500 leading-relaxed">
          These values drive the audit panel's pay/review/flag thresholds and the included-miles
          reference shown to auditors. Changes take effect immediately — no restart required.
          Values are stored in the local database and survive app restarts and deployments.
        </p>

        {categories.map(cat => (
          <div key={cat}>
            <div className="text-[10px] text-slate-500 uppercase tracking-wider font-bold mb-2">{cat}</div>
            <div className="space-y-2">
              {byCategory[cat].map(r => {
                const isDirty = edits[r.code] !== String(r.value)
                const isSaving = saving[r.code]
                const isSaved = saved[r.code]
                return (
                  <div key={r.code} className="flex items-center gap-3 rounded-lg bg-slate-900/40 px-3 py-2.5">
                    {/* Label + notes */}
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-medium text-slate-200">{r.label}</div>
                      <div className="text-[10px] text-slate-500 leading-snug">{r.notes}</div>
                    </div>

                    {/* Value input */}
                    <div className="flex items-center gap-1 flex-shrink-0">
                      <input
                        type="number"
                        value={edits[r.code] ?? r.value}
                        onChange={e => setEdits(prev => ({ ...prev, [r.code]: e.target.value }))}
                        className="w-20 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-white text-right
                                   focus:outline-none focus:ring-1 focus:ring-amber-500/40"
                        step={r.unit === '%' || r.unit === 'min' ? '1' : '0.5'}
                      />
                      <span className="text-[10px] text-slate-500 w-8">{r.unit}</span>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-1.5 flex-shrink-0">
                      {isDirty && !isSaved && (
                        <button onClick={() => reset(r.code)}
                          title="Reset to saved value"
                          className="p-1 text-slate-500 hover:text-slate-300 transition-colors">
                          <RotateCcw className="w-3 h-3" />
                        </button>
                      )}
                      <button
                        onClick={() => save(r.code)}
                        disabled={isSaving || (!isDirty && !isSaved)}
                        className="flex items-center gap-1 px-2.5 py-1 bg-amber-600 hover:bg-amber-500 disabled:opacity-40
                                   rounded text-[10px] font-semibold text-white transition-colors">
                        {isSaving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
                        Save
                      </button>
                      {isSaved && (
                        <span className="text-[10px] text-emerald-400 flex items-center gap-0.5">
                          <CheckCircle2 className="w-3 h-3" /> Saved
                        </span>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        ))}

        <p className="text-[10px] text-slate-600">
          Code key: er_included_* = included ER miles by coverage tier · tow_included_* = included tow miles ·
          mileage_pay_pct / mileage_review_pct = distance ratio thresholds · time_pay_pct = on-scene time ratio ·
          tl_flag_usd = toll amount triggering receipt note · e1_time_cap_min = E1 max minutes.
        </p>
      </div>
    </div>
  )
}
