import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import AdminFeatureMatrix from './AdminFeatureMatrix'
import AdminUserRoleMatrix from './AdminUserRoleMatrix'
import { fetchAccessMatrix } from '../api'
import { confirmLeave } from '../utils/unsavedGuard'

const VIEWS = [['features', 'Features by role'], ['users', 'Users by role']]

/** Admin > Access: who can use what. Superadmin only. */
export default function AdminAccess() {
  const [params, setParams] = useSearchParams()
  const view = params.get('view') === 'users' ? 'users' : 'features'
  const group = params.get('group') || ''
  const [matrix, setMatrix] = useState(null)
  const [error, setError] = useState('')

  const load = useCallback(() => fetchAccessMatrix().then(setMatrix).catch(e => setError(e.response?.data?.detail || 'Could not load access settings')), [])
  useEffect(() => { load() }, [load])

  const setParam = (k, v) => setParams(p => { p.set(k, v); return p }, { replace: true })

  if (error) return <div className="glass rounded-xl p-4 text-sm text-red-400">{error}</div>
  if (!matrix) return <Loader2 className="w-5 h-5 animate-spin text-slate-500" />

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-bold text-white">Access</h2>
        <p className="text-xs text-slate-500 mt-0.5">Tick what each role can use, or which roles each person holds. One Save per screen. Locked rows are fixed in code.</p>
      </div>
      <div className="flex gap-1 border-b border-slate-800">
        {VIEWS.map(([k, label]) => (
          <button key={k} onClick={() => confirmLeave() && setParam('view', k)}
            className={`px-3 py-2 text-xs font-semibold border-b-2 ${view === k ? 'border-brand-500 text-brand-300' : 'border-transparent text-slate-500 hover:text-slate-300'}`}>{label}</button>
        ))}
      </div>
      {view === 'features'
        ? <AdminFeatureMatrix matrix={matrix} onSaved={setMatrix} group={group} onGroup={g => setParam('group', g)} />
        : <AdminUserRoleMatrix matrix={matrix} onSaved={load} />}
    </div>
  )
}
