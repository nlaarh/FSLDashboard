import { useEffect, useRef, useState } from 'react'
import { Check, Loader2, Save, Undo2 } from 'lucide-react'
import { bulkValue, rectCells } from '../utils/matrixSelect'
import { confirmLeave, isInternalNavClick, setUnsaved } from '../utils/unsavedGuard'

/**
 * A checkbox grid with a sticky header row and a sticky first column, and one Save / Cancel bar.
 *   columns: [{ key, label }]   rows: [{ key, header: node, muted }]
 *   getCell(row, col) -> { on, disabled, title, changed, extra }
 *   onSet([{ row, col, value }]) is called for every click, drag, shift-click and select-all.
 * One click ticks a cell; press and drag (or shift-click) ticks or unticks a run; the check button at the end of
 * a row header or on top of a column header ticks the whole row or column.
 */
export default function StickyMatrix({ columns, rows, getCell, onSet, changeCount, onSave, onCancel, saving, message, emptyText = 'Nothing to show.', firstColWidth = 260 }) {
  const drag = useRef(null)     // { anchor:{r,c}, value }
  const last = useRef(null)     // last clicked cell, for shift-click
  const [skipNote, setSkipNote] = useState('')

  useEffect(() => {
    const stop = () => { drag.current = null }
    window.addEventListener('mouseup', stop)
    return () => window.removeEventListener('mouseup', stop)
  }, [])

  // Leaving with unsaved edits asks first: reload/close (browser prompt) and clicks on in-app links (BrowserRouter has no blocker).
  // Sidebar buttons and sub-tabs call confirmLeave() themselves. The browser Back button is not guarded.
  useEffect(() => {
    setUnsaved(changeCount)
    if (!changeCount) return
    const warn = e => { e.preventDefault(); e.returnValue = '' }
    const clickGuard = e => {
      if (isInternalNavClick(e.target.closest?.('a'), e) && !confirmLeave()) { e.preventDefault(); e.stopPropagation() }
    }
    window.addEventListener('beforeunload', warn)
    document.addEventListener('click', clickGuard, true)
    return () => { window.removeEventListener('beforeunload', warn); document.removeEventListener('click', clickGuard, true); setUnsaved(0) }
  }, [changeCount])

  // Locked cells are skipped. Cells blocked because of a restricted role are counted and reported, never silently changed.
  const apply = (cells, value) => {
    const all = cells.map(({ r, c }) => ({ r, c, cell: getCell(rows[r], columns[c]) }))
    const restricted = new Set(all.filter(x => x.cell.restricted && value).map(x => x.r))
    setSkipNote(restricted.size ? `Skipped ${restricted.size} user${restricted.size === 1 ? '' : 's'} with restricted roles` : '')
    onSet(all.filter(x => !x.cell.disabled).map(({ r, c }) => ({ row: rows[r], col: columns[c], value })))
  }

  const down = (e, r, c) => {
    if (e.button !== 0) return
    e.preventDefault()
    if (getCell(rows[r], columns[c]).disabled) { if (getCell(rows[r], columns[c]).restricted) apply([{ r, c }], true); return }
    const value = !getCell(rows[r], columns[c]).on
    if (e.shiftKey && last.current) apply(rectCells(last.current, { r, c }), value)
    else { apply([{ r, c }], value); drag.current = { anchor: { r, c }, value } }
    last.current = { r, c }
  }
  const enter = (r, c) => { if (drag.current) apply(rectCells(drag.current.anchor, { r, c }), drag.current.value) }
  const key = (e, r, c) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); if (!getCell(rows[r], columns[c]).disabled) apply([{ r, c }], !getCell(rows[r], columns[c]).on) } }

  const allBtn = (cells, label, className) => (
    <button type="button" onClick={() => apply(cells.map(x => ({ r: x.r, c: x.c })), bulkValue(cells.map(x => ({ ...x, ...getCell(rows[x.r], columns[x.c]) }))))}
      title={label} aria-label={label} className={`text-slate-600 hover:text-brand-300 ${className}`}><Check className="w-3 h-3" /></button>
  )

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 min-h-[34px]">
        <span className={`text-xs font-medium min-w-[110px] ${changeCount ? 'text-amber-300' : 'text-slate-500'}`}>
          {changeCount ? `${changeCount} unsaved change${changeCount === 1 ? '' : 's'}` : 'No changes'}
        </span>
        <button onClick={onSave} disabled={!changeCount || saving}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-xs font-semibold disabled:opacity-40 disabled:cursor-not-allowed">
          {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}Save
        </button>
        <button onClick={() => { setSkipNote(''); onCancel() }} disabled={!changeCount || saving}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium disabled:opacity-40">
          <Undo2 className="w-3.5 h-3.5" />Cancel
        </button>
        {skipNote && <span className="text-xs text-amber-300">{skipNote}</span>}
        {message && <span className={`text-xs ${message.error ? 'text-red-400' : 'text-emerald-400'}`}>{message.text}</span>}
        <span className="ml-auto text-[10px] text-slate-600">Click, or drag across cells. Shift-click for a range. The check buttons tick a whole row or column.</span>
      </div>
      <div className="overflow-auto rounded-xl border border-slate-700/50 select-none" style={{ maxHeight: 'calc(100vh - 300px)' }} data-testid="sticky-matrix">
        <table className="text-xs border-separate border-spacing-0 min-w-full">
          <thead>
            <tr>
              <th className="sticky top-0 left-0 z-30 bg-slate-900 border-b border-r border-slate-700/50 px-3 py-2" style={{ minWidth: firstColWidth, width: firstColWidth }} />
              {columns.map((c, ci) => (
                <th key={c.key} className="sticky top-0 z-20 bg-slate-900 border-b border-slate-700/50 px-0.5 py-1.5 text-slate-400 font-semibold align-bottom" title={c.title || c.label}>
                  {/* Rotated so all 14 roles fit without sideways scrolling; the full name is the tooltip. */}
                  <div className="flex flex-col items-center gap-1">
                    {rows.length > 0 && allBtn(rows.map((_, r) => ({ r, c: ci })), `Tick or untick ${c.label} for every row shown`, '')}
                    <span className="whitespace-nowrap text-[11px]" style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}>{c.label}</span>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={columns.length + 1} className="px-3 py-6 text-center text-slate-500">{emptyText}</td></tr>}
            {rows.map((row, r) => (
              <tr key={row.key} className={row.muted ? 'opacity-60' : 'hover:bg-slate-800/30'}>
                <th className="sticky left-0 z-10 bg-slate-900 border-b border-r border-slate-800 px-3 py-1.5 text-left font-normal" style={{ minWidth: firstColWidth, width: firstColWidth }}>
                  <div className="flex items-center gap-2"><div className="flex-1 min-w-0">{row.header}</div>
                    {allBtn(columns.map((_, c) => ({ r, c })), 'Tick or untick every role in this row', '')}</div>
                </th>
                {columns.map((col, c) => {
                  const cell = getCell(row, col)
                  return (
                    <td key={col.key} className="border-b border-slate-800 px-0.5 py-1 text-center" onMouseEnter={() => enter(r, c)}>
                      <span className="inline-flex items-center gap-0.5">
                        <span role="checkbox" aria-checked={cell.on} aria-disabled={cell.disabled} aria-label={cell.label} tabIndex={cell.disabled ? -1 : 0} title={cell.title}
                          onMouseDown={e => down(e, r, c)} onKeyDown={e => key(e, r, c)}
                          className={`w-5 h-5 rounded border flex items-center justify-center ${cell.disabled ? 'opacity-40' : 'cursor-pointer'} ${cell.on ? 'bg-brand-500 border-brand-400' : 'bg-slate-900 border-slate-600'} ${cell.changed ? 'ring-2 ring-amber-400' : ''}`}>
                          {cell.on && <Check className="w-3 h-3 text-white" />}
                        </span>
                        {cell.extra}
                      </span>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
