// One place that knows whether a screen has unsaved edits, so every way of leaving can ask first.
let unsaved = 0
export const setUnsaved = n => { unsaved = n }
export const hasUnsaved = () => unsaved > 0

const ask = msg => (typeof globalThis.confirm === 'function' ? globalThis.confirm(msg) : true)

/** True when it is fine to leave: nothing unsaved, or the user agreed. `confirmFn` is injectable for tests. */
export const confirmLeave = (confirmFn = ask) => !unsaved || confirmFn('You have unsaved changes. Leave and lose them?')

/** Is this click on a link that leaves the current screen inside the app? */
export function isInternalNavClick(anchor, e = {}) {
  if (!anchor || e.defaultPrevented || e.button > 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return false
  const href = anchor.getAttribute?.('href') || ''
  return href.startsWith('/') && !href.startsWith('//') && anchor.getAttribute('target') !== '_blank'
}
