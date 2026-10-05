import { useState } from 'react'
import { Search } from 'lucide-react'
import ReplayPanel from './ReplayPanel'

/** Work Order tab: type a work order or SA number and replay that one call. Nothing else. */
export default function WorkOrderReplayTab({ q, onChange }) {
  const [text, setText] = useState(q || '')
  const submit = e => { e.preventDefault(); onChange(text.trim()) }
  return (
    <div className="space-y-3">
      <form onSubmit={submit} className="glass rounded-xl p-3 flex items-center gap-2">
        <Search className="w-4 h-4 text-slate-400" />
        <input value={text} onChange={e => setText(e.target.value)} placeholder="Work order or SA number, e.g. 05173612 or SA-1074304"
          className="flex-1 bg-transparent text-sm text-white placeholder:text-slate-500 focus:outline-none" />
        <button type="submit" className="px-4 py-1.5 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-xs font-medium">Replay</button>
      </form>
      {q ? <ReplayPanel q={q} /> : <div className="glass rounded-xl p-8 text-center text-sm text-slate-400">Type a work order or SA number to watch what happened to the call.</div>}
    </div>
  )
}
