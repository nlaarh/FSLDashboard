import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { BookOpen, Loader2, AlertTriangle, Search } from 'lucide-react'
import { fetchCallStory, fetchReportCardStatus } from '../api'
import StoryHeader from '../components/callstory/StoryHeader'
import StoryVerdict from '../components/callstory/StoryVerdict'
import SegmentStrip from '../components/callstory/SegmentStrip'
import MatrixLadder from '../components/callstory/MatrixLadder'
import StoryTimeline from '../components/callstory/StoryTimeline'
import SmsSummary from '../components/callstory/SmsSummary'

const POLL_MS = 3000
const POLL_LIMIT_MS = 3 * 60 * 1000

function Message({ icon: Icon = AlertTriangle, tone = 'text-slate-400', children }) {
  return (
    <div className="glass rounded-xl p-8 flex flex-col items-center gap-3 text-center">
      <Icon className={`w-6 h-6 ${tone}`} />
      <div className="text-sm text-slate-300 max-w-lg">{children}</div>
    </div>
  )
}

/** Call Story: type a call, see what happened and why (call-story-architecture 7.4). URL is the source of truth. */
export default function CallStory() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') || ''
  const sa = params.get('sa') || ''
  const [input, setInput] = useState(q)
  const [state, setState] = useState({ phase: 'idle' })
  const [highlight, setHighlight] = useState([])
  const pollRef = useRef(null)

  const go = (next) => {
    const p = new URLSearchParams()
    if (next.q) p.set('q', next.q)
    if (next.sa) p.set('sa', next.sa)
    setParams(p)
  }

  const load = useCallback(async () => {
    setState({ phase: 'loading' })
    const { status, data } = await fetchCallStory(q, { sa }).catch(e => ({ status: 0, data: { detail: e.message } }))
    if (status === 200) setState({ phase: 'ready', story: data })
    else if (status === 404 && data?.status === 'not_found') setState({ phase: 'error', error: `No call found for "${q}".` })
    else if (status === 404 || status === 403) setState({ phase: 'error', error: 'Call Story is not available for your account.' })
    else if (status === 409 && data?.status === 'ambiguous') setState({ phase: 'ambiguous', candidates: data.candidates })
    else setState({ phase: 'error', error: data?.detail || `Could not load the story (${status || 'network'})` })
  }, [q, sa])

  useEffect(() => {
    setInput(q)
    if (q) load()
    else setState({ phase: 'idle' })
    return () => clearInterval(pollRef.current)
  }, [q, sa, load])

  const afterBuild = (building) => {
    if (!building) return load()
    const v = state.story.verdict.build, t0 = Date.now()
    clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      const { data } = await fetchReportCardStatus(v.territory_id, v.date).catch(() => ({ data: null }))
      if (data?.status === 'ready' || data?.status === 'failed' || Date.now() - t0 > POLL_LIMIT_MS) {
        clearInterval(pollRef.current)
        load()                                       // re-composes from the cached call: no new Salesforce reads
      }
    }, POLL_MS)
  }

  const story = state.story
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2">
          <BookOpen className="w-5 h-5 text-brand-400" />
          <h1 className="text-lg font-semibold text-white">Call Story</h1>
        </div>
        <form onSubmit={e => { e.preventDefault(); input.trim() && go({ q: input.trim() }) }} className="flex items-center gap-2">
          <input value={input} onChange={e => setInput(e.target.value)} placeholder="SA#, WO#, call key or source call ID"
            className="bg-slate-900 border border-slate-700 rounded-lg text-sm px-3 py-1.5 w-80 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500/40" />
          <button type="submit" className="px-3 py-1.5 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-xs font-medium flex items-center gap-1">
            <Search className="w-3.5 h-3.5" />Show story
          </button>
        </form>
        {story && (
          <span className="text-[10px] text-slate-500 ml-auto">
            {story.meta.cache === 'hit' ? 'From cache' : `${story.meta.sf_calls} Salesforce reads`}
            {story.meta.snapshot_used ? ` · garage-day ${story.meta.snapshot_used.date} built` : ' · garage-day not built'}
            {` · rules ${story.meta.rules_version} / ${story.meta.verdict_rules_version}`}
          </span>
        )}
      </div>

      {state.phase === 'idle' && <Message icon={BookOpen}>Type an SA number, work order number, call key or source call ID to see every step of the call, who acted, where it got stuck and why.</Message>}
      {state.phase === 'loading' && <Message icon={Loader2} tone="text-brand-400 animate-spin">Reading Salesforce (about 3 s)…</Message>}
      {state.phase === 'error' && <Message tone="text-rose-400">{state.error}</Message>}
      {state.phase === 'ambiguous' && (
        <Message>
          <div>That number matches more than one call. Which one?</div>
          <div className="flex justify-center gap-2 mt-3">
            {state.candidates.map(c => (
              <button key={c.wo_number} onClick={() => go({ q: c.wo_number })}
                className="px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-white text-xs">
                {c.type === 'wo' ? 'Work order' : 'Source call ID'} → WO {c.wo_number}
              </button>
            ))}
          </div>
        </Message>
      )}

      {state.phase === 'ready' && story && (story.status === 'no_service_appointment'
        ? <Message>This work order has no service appointment.</Message>
        : (<>
          <StoryHeader story={story} onPickLeg={n => go({ q, sa: n })} />
          <StoryVerdict story={story} onHighlight={setHighlight} onRebuilt={afterBuild} />
          <SegmentStrip segments={story.segments} highlight={highlight} onHighlight={setHighlight} />
          <MatrixLadder ladder={story.header.matrix_ladder} grid={story.header.grid?.name} />
          <StoryTimeline events={story.events} sms={story.sms} highlight={highlight} />
          <SmsSummary sms={story.sms} />
          {story.data_notes.length > 0 && (
            <div className="glass rounded-xl p-4 space-y-1">
              <div className="text-[10px] uppercase tracking-wide text-slate-500">Data notes</div>
              {story.data_notes.map((n, i) => <div key={i} className="text-[12px] text-slate-400">• {n.text}</div>)}
            </div>
          )}
        </>))}
    </div>
  )
}
