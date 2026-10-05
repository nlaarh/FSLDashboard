/**
 * Refresh data every `ms` milliseconds, but ONLY while the page is actually in front of someone.
 *
 *   - Tab in the background, window minimised or screen locked (document.hidden): no calls at all.
 *   - Computer asleep: timers do not run; when it wakes, the next timer fires once (no burst of catch-up calls).
 *   - Coming back: if the data on screen is older than `ms`, refresh at once; otherwise wait out the rest of the interval.
 *   - While visible it behaves like setInterval(fn, ms): the same cadence.
 *
 * `fn` is expected to have been run once already by the caller (the mount-time load). Returns stop().
 * Each refresh costs Salesforce calls on the server; a forgotten background tab used to keep that going all night.
 */
export function pollWhileVisible(fn, ms) {
  let timer = null
  let last = Date.now()
  let stopped = false

  const fire = () => {
    if (stopped || document.hidden) return              // hidden: stay quiet; the visibility handler re-arms us
    last = Date.now()
    try { fn() } catch { /* the caller's fn handles its own errors, as it did under setInterval */ }
    timer = setTimeout(fire, ms)
  }
  const onVisibility = () => {
    clearTimeout(timer)
    if (stopped || document.hidden) return
    const age = Date.now() - last
    timer = setTimeout(fire, age >= ms ? 0 : ms - age)  // stale -> now; fresh -> the rest of the interval
  }

  document.addEventListener('visibilitychange', onVisibility)
  timer = setTimeout(fire, ms)
  return () => {
    stopped = true
    clearTimeout(timer)
    document.removeEventListener('visibilitychange', onVisibility)
  }
}
