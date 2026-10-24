import { useEffect, useMemo, useState } from 'react'
import { Search, Star, X } from 'lucide-react'
import StickyMatrix from './StickyMatrix'
import Paginator from './Paginator'
import { blockedReason, diffUsers, makePrimary, setUserRole, userRoleList } from '../utils/matrixDiff'
import { ROLE_STYLE } from '../constants/users'
import { fetchAccessUsers, saveAccessUsers } from '../api'

const PAGE_SIZE = 25

/** Users (rows) x roles (columns). Ticked = the user holds the role; the star marks the primary role. Pending changes survive paging and search. */
export default function AdminUserRoleMatrix({ matrix, onSaved }) {
  const [page, setPage] = useState(0)
  const [q, setQ] = useState('')
  const [data, setData] = useState({ total: 0, users: [] })
  const [error, setError] = useState('')
  const [original, setOriginal] = useState({})      // username -> {primary, extra} as last loaded
  const [edited, setEdited] = useState({})          // username -> {primary, extra}, only users touched
  const [selName, setSelName] = useState(null)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState(null)

  useEffect(() => {
    const t = setTimeout(() => {
      fetchAccessUsers({ page: page + 1, page_size: PAGE_SIZE, q }).then(d => {
        setData(d); setError('')
        setOriginal(o => ({ ...o, ...Object.fromEntries(d.users.map(u => [u.username, { primary: u.primary, extra: u.extra }])) }))
      }).catch(e => setError(e.response?.data?.detail || 'Could not load users'))
    }, q ? 250 : 0)
    return () => clearTimeout(t)
  }, [page, q])

  const stateOf = u => edited[u.username] || original[u.username] || { primary: u.primary, extra: u.extra }
  const changes = diffUsers(original, edited)
  const exclusive = matrix.exclusive_roles

  const update = (u, fn) => setEdited(e => ({ ...e, [u.username]: fn(e[u.username] || original[u.username] || { primary: u.primary, extra: u.extra }) }))
  // Every click, drag and select-all arrives here as a list of "set this cell to this value".
  const setCells = updates => setEdited(e => {
    const next = { ...e }
    for (const { row, col, value } of updates) {
      const u = row.u
      const cur = next[u.username] || original[u.username] || { primary: u.primary, extra: u.extra }
      const after = setUserRole(cur, col.key, value, exclusive)
      if (after !== cur) next[u.username] = after
    }
    return next
  })

  const save = async () => {
    setSaving(true); setMessage(null)
    try {
      await saveAccessUsers(changes)
      setOriginal(o => ({ ...o, ...Object.fromEntries(changes.map(c => [c.username, { primary: c.primary, extra: c.extra }])) }))
      setEdited({})
      setMessage({ text: `Saved ${changes.length} user${changes.length === 1 ? '' : 's'}.` })
      onSaved()
    } catch (e) {
      setMessage({ error: true, text: e.response?.data?.detail || 'Save failed' })
    } finally { setSaving(false) }
  }

  const getCell = ({ u }, c) => {
    const st = stateOf(u)
    const on = userRoleList(st).includes(c.key)
    const isPrimary = st.primary === c.key
    const reason = blockedReason(st, c.key, exclusive)
    return {
      on, label: `${u.username} ${c.key}`, disabled: !!reason || isPrimary, restricted: !!reason,
      changed: on !== userRoleList(original[u.username] || st).includes(c.key),
      title: reason || (isPrimary ? 'Primary role. Tick another role and click its star to change it.' : undefined),
      extra: on && (
        <button disabled={isPrimary} onClick={() => update(u, x => makePrimary(x, c.key))} title={isPrimary ? 'Primary role' : 'Make this the primary role'}
          aria-label={isPrimary ? `${c.key} is primary` : `Make ${c.key} primary`}>
          <Star className={`w-3 h-3 ${isPrimary ? 'text-amber-400 fill-amber-400' : 'text-slate-600 hover:text-amber-300'}`} />
        </button>
      ),
    }
  }

  const header = u => {
    const st = stateOf(u)
    return (
      <button onClick={() => setSelName(u.username)} className="text-left w-full" title="Show everything this person can do">
        <div className={`font-medium truncate ${u.active ? 'text-slate-200' : 'text-slate-500 line-through'}`}>{u.name || u.username}</div>
        <div className="flex items-center gap-1 mt-0.5">
          <span className={`px-1.5 py-px rounded border text-[10px] font-medium ${ROLE_STYLE[st.primary] || 'bg-slate-500/10 text-slate-400 border-slate-500/20'}`}>{st.primary}</span>
          {st.extra.length > 0 && <span className="text-[10px] text-slate-500" title={st.extra.join(', ')}>+{st.extra.length}</span>}
        </div>
      </button>
    )
  }

  // The panel only shows a user who is in the list on screen; search or paging away clears it.
  const selUser = data.users.find(u => u.username === selName)
  // Effective access is never stored per user: the union of the features of all their roles (from matrix 2).
  const effective = useMemo(() => {
    if (!selUser) return null
    const roles = userRoleList(edited[selUser.username] || original[selUser.username] || selUser)
    const allowed = matrix.features.filter(f => f.roles.some(r => roles.includes(r) && !(r === 'contractor' && f.warning)))
    const groups = [...new Set(allowed.map(f => f.group))].map(g => [g, allowed.filter(f => f.group === g).map(f => f.label)])
    return { roles, groups }
  }, [selUser, edited, original, matrix])

  return (
    <div>
      <div className="space-y-3">
        <div className="relative w-72">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-slate-500" />
          <input value={q} onChange={e => { setQ(e.target.value); setPage(0) }} placeholder="Search name or username"
            className="w-full pl-8 pr-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-xs text-white focus:outline-none focus:ring-2 focus:ring-brand-500/40" />
        </div>
        {error && <div className="text-xs text-red-400">{error}</div>}
        <StickyMatrix columns={matrix.roles.map(r => ({ key: r, label: r }))} rows={data.users.map(u => ({ key: u.username, header: header(u), muted: !u.active, u }))}
          firstColWidth={200} getCell={getCell} onSet={setCells} changeCount={changes.length} onSave={save} onCancel={() => { setEdited({}); setMessage(null) }}
          saving={saving} message={message} emptyText="No users match." />
        <Paginator page={page} setPage={setPage} total={data.total} pageSize={PAGE_SIZE} />
      </div>
      {/* Slide-over, so the matrix keeps the full width and every role column stays visible. */}
      {effective && (
        <aside className="fixed top-14 right-0 bottom-0 w-80 z-40 glass border-l border-slate-700/50 p-4 text-xs overflow-auto shadow-2xl">
          <div className="flex items-center mb-2">
            <div className="font-semibold text-white">Effective access</div>
            <button onClick={() => setSelName(null)} aria-label="Close" className="ml-auto text-slate-500 hover:text-white"><X className="w-4 h-4" /></button>
          </div>
          <div className="space-y-2">
            <div className="text-slate-300 font-medium">{selUser.name || selUser.username}</div>
            <div className="text-slate-400">Roles: {effective.roles.join(', ')}</div>
            <div className="text-slate-600">Read-only: everything this person can do, from all their roles.</div>
            {edited[selUser.username] && <div className="text-amber-300">Includes your unsaved changes.</div>}
            {effective.groups.map(([g, labels]) => (
              <div key={g}>
                <div className="text-[10px] uppercase tracking-wide text-slate-500 mt-2">{g}</div>
                <ul className="list-disc ml-4 text-slate-300 space-y-0.5">{labels.map(l => <li key={l}>{l}</li>)}</ul>
              </div>
            ))}
          </div>
        </aside>
      )}
    </div>
  )
}
