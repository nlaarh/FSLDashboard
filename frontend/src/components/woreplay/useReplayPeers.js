import { useEffect, useMemo, useState } from 'react'
import { loadStoryPeers } from '../reportcard/prefetch'
import { peerMoments } from './peerNotes'

/** The other qualified, on-shift drivers when the call was given (and accepted). Read from the day snapshot on the server (no Salesforce call),
 *  started only once `ready`. peers: undefined = loading, null = unavailable; moments = peerMoments(peers) for the stage. */
export default function useReplayPeers(q, ready) {
  const [peers, setPeers] = useState(undefined)
  useEffect(() => {
    setPeers(undefined)
    if (!q || !ready) return undefined
    let live = true
    loadStoryPeers(q).then(({ status, data }) => live && setPeers(status === 200 ? data : null)).catch(() => live && setPeers(null))
    return () => { live = false }
  }, [q, ready])
  const moments = useMemo(() => peerMoments(peers), [peers])
  return { peers, moments }
}
