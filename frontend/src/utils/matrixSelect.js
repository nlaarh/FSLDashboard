// Bulk-tick helpers for the Access matrices (pure, so they can be tested).

/** Cells in the rectangle between two corners: [{ r, c }] with row and column indexes. */
export function rectCells(a, b) {
  const out = []
  for (let r = Math.min(a.r, b.r); r <= Math.max(a.r, b.r); r++)
    for (let c = Math.min(a.c, b.c); c <= Math.max(a.c, b.c); c++) out.push({ r, c })
  return out
}

/** Value a "select all" toggle should apply: untick everything if every editable cell is already ticked, else tick all. */
export function bulkValue(cells) {
  const editable = cells.filter(x => !x.disabled)
  return editable.length > 0 && !editable.every(x => x.on)
}
