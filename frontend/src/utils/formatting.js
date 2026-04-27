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

// ── WOA / Accounting helpers ─────────────────────────────────────────────────

export function productCode(product) {
  if (!product) return ''
  return (product.split(/[\s\-]/)[0] || product).toUpperCase()
}

export function formatQty(qty, product) {
  if (qty == null || qty === '') return '--'
  const code = productCode(product)
  const n = Number(qty)
  if (['ER', 'TW'].includes(code)) return `${n % 1 === 0 ? n : n.toFixed(2)} mi`
  if (['E1', 'E2'].includes(code)) return `${n} min`
  return `$${n.toFixed(2)}`
}
