import { useMemo, useState } from 'react'
import { Lock, RotateCcw } from 'lucide-react'
import StickyMatrix from './StickyMatrix'
import { diffFeatures } from '../utils/matrixDiff'
import { saveAccessFeatures } from '../api'

/** Features (rows) x roles (columns). One tab per group so the grid never gets long. */
export default function AdminFeatureMatrix({ matrix, onSaved, group, onGroup }) {
  const original = useMemo(() => Object.fromEntries(matrix.features.map(f => [f.key, f.roles])), [matrix])
  const [edited, setEdited] = useState({})            // key -> roles, only for rows touched
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState(null)

  const rolesOf = f => edited[f.key] || f.roles
  const changes = diffFeatures(original, edited)
  const groups = [...new Set(matrix.features.map(f => f.group))]
  const current = groups.includes(group) ? group : groups[0]
  const rows = matrix.features.filter(f => f.group === current)

  // Every click, drag and select-all arrives here as a list of "set this cell to this value".
  const setCells = updates => setEdited(e => {
    const next = { ...e }
    for (const { row, col, value } of updates) {
      const roles = next[row.key] || row.f.roles
      if (roles.includes(col.key) !== value) next[row.key] = value ? [...roles, col.key] : roles.filter(r => r !== col.key)
    }
    return next
  })

  const save = async () => {
    setSaving(true); setMessage(null)
    try {
      // Back to the code default = remove the stored row.
      const body = Object.fromEntries(Object.entries(changes).map(([k, roles]) => {
        const f = matrix.features.find(x => x.key === k)
        const isDefault = roles.length === f.default_roles.length && roles.every(r => f.default_roles.includes(r))
        return [k, isDefault ? null : roles]
      }))
      const next = await saveAccessFeatures(body)
      setEdited({})
      setMessage({ text: `Saved ${Object.keys(body).length} feature${Object.keys(body).length === 1 ? '' : 's'}. Takes effect within about 30 seconds on every server.` })
      onSaved(next)
    } catch (e) {
      setMessage({ error: true, text: e.response?.data?.detail || 'Save failed' })
    } finally { setSaving(false) }
  }

  const header = f => (
    <div className="flex items-center gap-2">
      {f.locked && <Lock className="w-3 h-3 text-slate-500 flex-shrink-0" title={f.lock_reason} />}
      <div className="min-w-0">
        <div className="text-slate-200 font-medium">{f.label}</div>
        <div className="text-[10px] text-slate-500 truncate" title={f.locked ? f.lock_reason : f.description}>{f.locked ? f.lock_reason : f.description}</div>
      </div>
      {!f.locked && edited[f.key] && (
        <button onClick={() => setEdited(e => ({ ...e, [f.key]: f.default_roles }))} title="Reset to the code default" className="ml-auto text-slate-500 hover:text-white">
          <RotateCcw className="w-3 h-3" />
        </button>
      )}
    </div>
  )

  const getCell = ({ f }, c) => {
    const denied = f.warning && c.key === 'contractor'
    const on = rolesOf(f).includes(c.key)
    return {
      on, changed: on !== f.roles.includes(c.key), label: `${f.label} for ${c.key}`,
      disabled: f.locked || c.key === 'superadmin' || !!denied,
      title: denied ? f.warning : c.key === 'superadmin' ? 'Superadmin always keeps access' : f.locked ? f.lock_reason : undefined,
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {groups.map(g => (
          <button key={g} onClick={() => onGroup(g)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium ${g === current ? 'bg-brand-600/20 text-brand-300' : 'bg-slate-800/60 text-slate-400 hover:text-white'}`}>
            {g} <span className="text-[10px] text-slate-500 ml-1">{matrix.features.filter(f => f.group === g).length}</span>
          </button>
        ))}
      </div>
      {matrix.fallback && <div className="text-xs text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">The access tables are not installed or unreadable, so everyone is on the built-in defaults and Save is unavailable.</div>}
      <StickyMatrix columns={matrix.roles.map(r => ({ key: r, label: r }))} rows={rows.map(f => ({ key: f.key, header: header(f), muted: f.locked, f }))}
        getCell={getCell} onSet={setCells} changeCount={Object.keys(changes).length}
        onSave={save} onCancel={() => { setEdited({}); setMessage(null) }} saving={saving} message={message} />
    </div>
  )
}
