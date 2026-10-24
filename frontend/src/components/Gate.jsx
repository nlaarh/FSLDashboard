import { Navigate, useLocation } from 'react-router-dom'
import { can, homePath } from '../utils/access'

/** Shows `children` when the user has the feature (or any of them); otherwise sends them to their first allowed page. */
export default function Gate({ feature, features, children }) {
  const { pathname } = useLocation()
  const keys = Array.isArray(feature) ? feature : [feature]
  if (keys.some(k => can(features, k))) return children
  const home = homePath(features)
  if (home && home !== pathname) return <Navigate to={home} replace />
  return <div className="p-10 text-center text-sm text-slate-400">You do not have access to any page yet. Ask an administrator.</div>
}
