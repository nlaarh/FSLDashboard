import { useEffect, useMemo, useState } from 'react'
import { fetchFeatures } from '../../api'
import { loadStoryExtras } from '../reportcard/prefetch'
import { contactMarks } from './contactMarks'

/** Member calls, texts and the driver's other jobs for one call. Starts only once the story is on screen (`ready`),
 *  so it never slows the first picture. extras: undefined = loading, null = not available (flag off, so no request is made, or an error),
 *  otherwise the /api/call-story/extras answer. marks = contactMarks(steps, extras), ready for the stage's icons. */
export default function useReplayExtras(q, ready, steps) {
  const [extras, setExtras] = useState(undefined)
  useEffect(() => {
    setExtras(undefined)
    if (!q || !ready) return undefined
    let live = true
    fetchFeatures().then(f => (f.replay_member_contact === true ? loadStoryExtras(q) : { status: 0 })).then(({ status, data }) => live && setExtras(status === 200 ? data : null)).catch(() => live && setExtras(null))
    return () => { live = false }
  }, [q, ready])
  const marks = useMemo(() => contactMarks(steps, extras), [steps, extras])
  return { extras, marks }
}
