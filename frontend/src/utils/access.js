import { useEffect, useState } from 'react'

// What the signed-in user may see: the `features` list from /api/auth/me (computed from all of their roles).
// null means "not loaded yet" and is treated as allowed, so menus do not flash empty; the server still enforces.
let _me = null
export const loadMe = () => {
  if (!_me) _me = fetch('/api/auth/me').then(r => (r.ok ? r.json() : {})).catch(() => ({})).then(d => { if (!d.features) _me = null; return d })
  return _me
}

export const can = (features, key) => features === null || features === undefined || features.includes(key)

export function useFeatures() {
  const [features, setFeatures] = useState(null)
  useEffect(() => { loadMe().then(d => setFeatures(d.features || null)) }, [])
  return features
}

// Staff landing pages in menu order: where to send someone who opens a page they may not use.
export const HOME_PAGES = [
  ['page.command_center', '/'], ['page.garages', '/garages'], ['page.sa_watchlist', '/sa-watchlist'], ['page.queue', '/queue'],
  ['page.forecast', '/forecast'], ['page.accounting', '/accounting'], ['page.reporting', '/reporting'], ['page.help', '/help'],
]
export const homePath = features => HOME_PAGES.find(([k]) => can(features, k))?.[1] ?? null
