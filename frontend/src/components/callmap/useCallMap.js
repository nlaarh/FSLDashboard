import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchCallMap } from '../../api'

export const REFRESH_MS = 60_000
const MSG = { 403: 'You do not have access to this view.', 404: 'That call was not found.', 503: 'Salesforce is busy. Try again in a moment.' }

/** The call map's data: loaded on open, then re-read every 60 s while the view is open AND the browser tab is visible (the server
 *  caches each call for 60 s, so many viewers share one read). A failed refresh keeps the last good picture and sets `stale`.
 *  Returns { data, error, stale, loading, reload }. */
export default function useCallMap(saId, hints) {
  const [s, setS] = useState({ data: null, error: null, stale: false, loading: true })
  const hintsRef = useRef(hints)
  hintsRef.current = hints
  const lastAt = useRef(0)

  const load = useCallback(() => {
    lastAt.current = Date.now()
    return fetchCallMap(saId, hintsRef.current)
      .then(data => setS({ data, error: null, stale: false, loading: false }))
      .catch(e => setS(p => ({ data: p.data, loading: false, stale: !!p.data,
        error: p.data ? null : (MSG[e?.response?.status] || e?.response?.data?.detail || 'The call map could not be loaded.') })))
  }, [saId])

  useEffect(() => {
    setS({ data: null, error: null, stale: false, loading: true })
    load()
    const tick = () => { if (document.visibilityState === 'visible') load() }
    const timer = setInterval(tick, REFRESH_MS)
    const onVis = () => { if (document.visibilityState === 'visible' && Date.now() - lastAt.current >= REFRESH_MS) load() }
    document.addEventListener('visibilitychange', onVis)
    return () => { clearInterval(timer); document.removeEventListener('visibilitychange', onVis) }
  }, [saId, load])

  return { ...s, reload: load }
}
