/**
 * Shared number/percentage formatting — used across dashboard components.
 */

export function pct(n, d) {
  return d > 0 ? Math.round(100 * n / d * 10) / 10 : 0
}

export function round(n, decimals = 1) {
  const f = Math.pow(10, decimals)
  return Math.round(n * f) / f
}

export function formatNumber(n) {
  return (n ?? 0).toLocaleString()
}
