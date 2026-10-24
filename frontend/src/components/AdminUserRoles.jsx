import { useEffect, useState } from 'react'
import { Loader2, Star } from 'lucide-react'
import { clsx } from 'clsx'
import { blockedReason, toggleUserRole } from '../utils/matrixDiff'
import { ROLE_STYLE } from '../constants/users'
import { fetchAccessMatrix, fetchAccessUsers } from '../api'

/** Roles for one person inside the Edit window. The main role is the Role box above; every other role is one click on or off.
 *  Nothing is saved here: "Save changes" in the window saves the roles together with the rest. */
export default function AdminUserRoles({ username, primary, state, setState }) {
  const [matrix, setMatrix] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let live = true
    Promise.all([fetchAccessMatrix(), fetchAccessUsers({ page: 1, page_size: 10, q: username })]).then(([m, d]) => {
      if (!live) return
      const row = d.users.find(u => u.username === username)
      if (!row) { setError('Could not find this person in the access list'); return }
      setMatrix(m)
      setState({ original: row.extra, extra: row.extra })
    }).catch(e => live && setError(e.response?.data?.detail || 'Could not load roles'))
    return () => { live = false }
  }, [username, setState])

  if (error) return <div className="text-xs text-red-400">{error}</div>
  if (!matrix || !state) return <Loader2 className="w-4 h-4 animate-spin text-slate-500" />

  const person = { primary, extra: state.extra.filter(r => r !== primary) }
  const changed = person.extra.length !== state.original.length || person.extra.some(r => !state.original.includes(r))

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex items-baseline gap-2">
        <h4 className="text-xs font-semibold text-white">Roles</h4>
        <span className="text-[11px] text-slate-500">Click a role to add it or remove it. The main role is the Role box above.</span>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {matrix.roles.map(r => {
          const isPrimary = r === primary
          const on = isPrimary || person.extra.includes(r)
          const reason = blockedReason(person, r, matrix.exclusive_roles)
          return (
            <button key={r} type="button" disabled={isPrimary || !!reason}
              title={isPrimary ? 'Main role. Change it in the Role box above.' : reason || (on ? 'Click to remove this role' : 'Click to add this role')}
              onClick={() => setState(s => ({ ...s, extra: toggleUserRole(person, r, matrix.exclusive_roles).extra }))}
              className={clsx('inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-xs font-medium transition disabled:cursor-not-allowed',
                on ? (ROLE_STYLE[r] || 'bg-brand-500/10 text-brand-300 border-brand-500/30') : 'border-dashed border-slate-700 text-slate-500 hover:border-slate-500 hover:text-slate-300',
                !on && reason && 'opacity-40')}>
              {isPrimary ? <Star className="h-3 w-3 fill-amber-400 text-amber-400" /> : <span aria-hidden>{on ? '✓' : '+'}</span>}
              {r}
            </button>
          )
        })}
      </div>
      {changed && <div className="mt-2 text-[11px] text-amber-300">Role changes are not saved yet. Press Save changes.</div>}
    </section>
  )
}
