import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchGarageLive } from '../../api'
import { pollWhileVisible } from '../../utils/pollWhileVisible'
import { REFRESH_MS } from './garageLiveModel'

const MSG = { 403: 'You do not have access to this garage.', 404: 'That garage was not found.', 503: 'Salesforce is busy. Try again in a moment.' }

/** One garage's live picture: read on open, then every 60 s while the browser tab is visible (the server shares one build per garage, so many
 *  viewers cost Salesforce nothing extra). A failed refresh keeps the last good picture and sets `stale`.
 *  Returns { data, error, stale, loading, receivedAt, reload }. */
export default function useGarageLive(garageId) {
  const [s, setS] = useState({ data: null, error: null, stale: false, loading: false, receivedAt: 0 })
  const seq = useRef(0)

  const load = useCallback(() => {
    if (!garageId) return Promise.resolve()
    const mine = ++seq.current
    return fetchGarageLive(garageId)
      .then(data => { if (mine === seq.current) setS({ data, error: null, stale: false, loading: false, receivedAt: Date.now() }) })
      .catch(e => { if (mine === seq.current) setS(p => ({ ...p, loading: false, stale: !!p.data, error: p.data ? null : (MSG[e?.response?.status] || e?.response?.data?.detail || 'This garage could not be loaded.') })) })
  }, [garageId])

  useEffect(() => {
    if (!garageId) { setS({ data: null, error: null, stale: false, loading: false, receivedAt: 0 }); return undefined }
    setS({ data: null, error: null, stale: false, loading: true, receivedAt: 0 })
    load()
    const stop = pollWhileVisible(load, REFRESH_MS)
    return () => { seq.current++; stop() }
  }, [garageId, load])

  return { ...s, reload: load }
}
