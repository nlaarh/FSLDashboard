import { useEffect, useMemo, useRef, useState } from 'react'
import { Search, ChevronDown, Loader2 } from 'lucide-react'
import { filterGarages } from './garageLiveModel'

/** A searchable garage picker: type any part of the name, arrow keys + Enter or one click. The caller remembers the choice. */
export default function GaragePicker({ garages, loading, value, onPick, autoOpen }) {
  const [open, setOpen] = useState(!!autoOpen)
  const [q, setQ] = useState('')
  const [hi, setHi] = useState(0)
  const box = useRef(null), input = useRef(null)
  const current = garages?.find(g => g.id === value)
  const list = useMemo(() => filterGarages(garages, q), [garages, q])

  useEffect(() => { setHi(0) }, [q])
  useEffect(() => { if (open) input.current?.focus() }, [open])
  useEffect(() => {
    const off = e => { if (!box.current?.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', off)
    return () => document.removeEventListener('mousedown', off)
  }, [])

  const pick = g => { if (!g) return; setOpen(false); setQ(''); onPick(g.id) }
  const onKey = e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setHi(h => Math.min(list.length - 1, h + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHi(h => Math.max(0, h - 1)) }
    else if (e.key === 'Enter') { e.preventDefault(); pick(list[hi]) }
    else if (e.key === 'Escape') setOpen(false)
  }

  return (
    <div ref={box} className="relative w-full sm:w-[360px]">
      <button type="button" onClick={() => setOpen(o => !o)} aria-haspopup="listbox" aria-expanded={open}
        className="w-full flex items-center gap-2 rounded-lg border border-slate-600 bg-slate-800 hover:bg-slate-700 text-left px-3 py-2 min-h-[40px]">
        {loading ? <Loader2 className="w-4 h-4 animate-spin text-slate-400" /> : <Search className="w-4 h-4 text-slate-400" />}
        <span className="flex-1 truncate text-sm font-semibold text-white">{current?.name || (value ? 'Garage' : 'Choose a garage…')}</span>
        <ChevronDown className="w-4 h-4 text-slate-400" />
      </button>
      {open && (
        <div className="absolute z-[1300] mt-1 w-full rounded-lg border border-slate-600 bg-slate-900 shadow-2xl">
          <input ref={input} value={q} onChange={e => setQ(e.target.value)} onKeyDown={onKey} placeholder="Type a garage name or number"
            className="w-full bg-transparent border-b border-slate-700 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-500" aria-label="Search garages" />
          <ul role="listbox" className="max-h-72 overflow-y-auto py-1">
            {list.map((g, n) => (
              <li key={g.id} role="option" aria-selected={g.id === value}>
                <button type="button" onMouseEnter={() => setHi(n)} onClick={() => pick(g)}
                  className={`w-full text-left px-3 py-1.5 text-sm flex justify-between gap-3 ${n === hi ? 'bg-sky-600/30 text-white' : 'text-slate-200'} ${g.id === value ? 'font-bold' : ''}`}>
                  <span className="truncate">{g.name}</span>
                  <span className="text-xs text-slate-500 shrink-0">{g.city || ''}</span>
                </button>
              </li>))}
            {list.length === 0 && <li className="px-3 py-3 text-sm text-slate-500">{loading ? 'Loading garages…' : 'No garage matches that.'}</li>}
          </ul>
        </div>)}
    </div>
  )
}
