import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ClipboardCheck, PlayCircle, Loader2, AlertTriangle, Hammer, RefreshCw } from 'lucide-react'
import { fetchReportCard, fetchReportCardStatus, buildReportCard, fetchFeatures } from '../api'
import { loadReplay, loadCallFlags } from '../components/reportcard/prefetch'
import ReportCardPickers from '../components/reportcard/ReportCardPickers'
import DaySummary from '../components/reportcard/DaySummary'
import DayGantt from '../components/reportcard/DayGantt'
import CallPanel from '../components/reportcard/CallPanel'
import AiFindings from '../components/reportcard/AiFindings'
import GarageReplay, { BuildingPreview } from '../components/reportcard/GarageReplay'
import WorkOrderReplayTab from '../components/woreplay/WorkOrderReplayTab'

const TABS = [['day', 'Day']]                                            // the Report Card page: grading only. Replay has its own page and permission.
const REPLAY_TABS = [['replay', 'Garage'], ['wo', 'Work Order']]   // the "Replay" menu page: replay only, no grading

const POLL_MS = 1500   // the building page fills in as the build publishes the day's calls
const POLL_LIMIT_MS = 3 * 60 * 1000

function Message({ icon: Icon = AlertTriangle, tone = 'text-slate-400', children }) {
  return (
    <div className="glass rounded-xl p-8 flex flex-col items-center gap-3 text-center">
      <Icon className={`w-6 h-6 ${tone}`} />
      <div className="text-sm text-slate-300 max-w-lg">{children}</div>
    </div>
  )
}

/** Scheduler Report Card — Day view (architecture.md section 2). URL is the source of truth. */
export default function SchedulerReportCard({ view = 'report-card' }) {
  const isReplay = view === 'replay'
  const tabs = isReplay ? REPLAY_TABS : TABS
  // Replay is for administrators and executives only: the server refuses everyone else, and this tells them why instead of showing an empty page
  const [canReplay, setCanReplay] = useState(null)   // null = still checking
  useEffect(() => {
    if (!isReplay) return
    fetch('/api/auth/me').then(r => r.json()).then(d => setCanReplay((d.features || []).includes('scheduler.replay'))).catch(() => setCanReplay(false))
  }, [isReplay])
  const [params, setParams] = useSearchParams()
  const garage = params.get('garage') || ''
  const date = params.get('date') || ''
  const saNumber = params.get('sa') || ''
  const tab = tabs.some(([k]) => k === params.get('tab')) ? params.get('tab') : tabs[0][0]
  const q = params.get('q') || ''
  const rules = params.get('rules') || ''          // '' = server default (r2: original PTA)
  const [state, setState] = useState({ phase: 'idle' })
  const [highlight, setHighlight] = useState(null)   // { key, ids: Set of SA ids } dims everything else
  const pollRef = useRef(null)
  const [callStory, setCallStory] = useState(false)
  useEffect(() => { fetchFeatures().then(f => setCallStory(f.call_story === true)).catch(() => {}) }, [])

  const setUrl = useCallback(next => {
    const p = new URLSearchParams()
    if (next.garage) p.set('garage', next.garage)
    if (next.date) p.set('date', next.date)
    if (next.sa) p.set('sa', next.sa)
    const tb = next.tab ?? tab
    if (tb !== tabs[0][0]) p.set('tab', tb)
    const qq = next.q ?? q
    if (qq && tb === 'wo') p.set('q', qq)
    const r = next.rules ?? rules
    if (r) p.set('rules', r)
    setParams(p, { replace: !!next.sa || !next.date })
  }, [setParams, rules, tab, q])

  const stopPoll = () => { clearInterval(pollRef.current); pollRef.current = null }

  const autoBuilt = useRef('')   // the garage-day we already started a build for
  const load = useCallback(async () => {
    stopPoll()
    setState({ phase: 'loading' })
    // Replay page: start the map and list-detail requests now, alongside the day request, instead of after it
    if (isReplay && tab === 'replay' && garage && date) { loadReplay(garage, date); loadCallFlags(garage, date) }
    try {
      const { status, data } = await fetchReportCard(garage, date, rules)
      if (status === 200) setState({ phase: 'ready', data })
      else if (status === 409 && data?.status === 'rules_unavailable') setState({ phase: 'rules_unavailable', info: data })
      else if (status === 202) startPoll(data.started_at)
      else if (status === 404 && data?.status === 'not_built') {
        // Nothing to click: picking the garage and day starts the build and the page opens when it is ready.
        // Once per garage-day, so a failed build shows its error instead of retrying in a loop.
        const key = `${garage}:${date}`
        if (autoBuilt.current !== key) { autoBuilt.current = key; build() } else setState({ phase: 'not_built' })
      }
      else if (status === 409) setState({ phase: 'failed', error: data?.error })
      else if (status === 404 || status === 403) setState({ phase: 'unavailable' })
      else setState({ phase: 'error', error: data?.detail || `Unexpected response ${status}` })
    } catch (e) {
      setState({ phase: 'error', error: e.message })
    }
  }, [garage, date, rules]) // eslint-disable-line react-hooks/exhaustive-deps

  const startPoll = startedAt => {
    stopPoll()
    const t0 = Date.now()
    setState({ phase: 'building', startedAt })
    pollRef.current = setInterval(async () => {
      if (Date.now() - t0 > POLL_LIMIT_MS) {
        stopPoll()
        setState({ phase: 'error', error: 'Still building after 3 minutes. Check back shortly.' })
        return
      }
      const { data } = await fetchReportCardStatus(garage, date).catch(() => ({ data: null }))
      if (data?.status === 'building' && data.preview) setState(s => (s.phase === 'building' ? { ...s, preview: data.preview, stage: data.stage } : s))
      if (data?.status === 'ready') load()
      else if (data?.status === 'failed') { stopPoll(); setState({ phase: 'failed', error: data.error }) }
    }, POLL_MS)
  }

  const build = async (force = false) => {
    setState({ phase: 'loading' })
    const { status, data } = await buildReportCard(garage, date, force).catch(e => ({ status: 0, data: { detail: e.message } }))
    if (status === 202) startPoll(data.started_at)
    else if (status === 200) load()
    else setState({ phase: 'error', error: data?.detail || `Build failed to start (${status})` })
  }

  useEffect(() => {
    setHighlight(null)
    if (garage && date) load()
    else setState({ phase: 'idle' })
    return stopPoll
  }, [garage, date, rules, load])

  const data = state.data
  const phase = tab === 'wo' ? 'wo' : state.phase   // the Work Order tab needs no garage or day
  const selected = data?.sas.find(s => s.number === saNumber) || null
  const selectSa = id => {
    const sa = data.sas.find(s => s.id === id)
    setUrl({ garage, date, sa: sa && sa.number !== saNumber ? sa.number : '' })
  }

  if (isReplay && canReplay === false) return <div className="space-y-4"><Message icon={PlayCircle}>Replay is available to administrators and executives only.</Message></div>
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2">
          {isReplay ? <PlayCircle className="w-5 h-5 text-brand-400" /> : <ClipboardCheck className="w-5 h-5 text-brand-400" />}
          <h1 className="text-lg font-semibold text-white">{isReplay ? 'Replay' : 'Scheduler Report Card'}</h1>
        </div>
        <ReportCardPickers garage={garage} date={date} onChange={setUrl} />
        {tab === 'day' && (
          <label className="flex items-center gap-2 text-xs text-slate-400"
            title="PTA is the arrival time promised to the member. If the garage or Towbook changes it later (say from 90 to 120 minutes), a late call can look on time. 'The original promise' judges lateness against what the member was first told. This only changes the grading on the Day tab.">
            Judge lateness against
            <select value={rules || 'r2'} onChange={e => setUrl({ garage, date, rules: e.target.value === 'r2' ? '' : e.target.value })}
              className="bg-slate-900 border border-slate-700 rounded-lg text-xs px-2 py-2 text-white focus:outline-none focus:ring-2 focus:ring-brand-500/40">
              <option value="r2">the original promise</option>
              <option value="r1">the final promise (after changes)</option>
            </select>
          </label>
        )}
        {data && (
          <span className="text-[10px] text-slate-500 ml-auto">
            Built {new Date(data.snapshot.built_at).toLocaleString('en-US', { timeZone: 'America/New_York' })} ET
            · rules {data.snapshot.rules_version} · {data.snapshot.completeness.sf_calls} Salesforce reads
            {data.snapshot.provisional && <span className="ml-2 text-amber-300">Provisional: built within 24 h of the day</span>}
          </span>
        )}
      </div>

      {phase === 'idle' && <Message icon={ClipboardCheck}>{isReplay ? 'Pick a garage and a past day to replay it: where the drivers were and what happened to each work order.' : 'Pick a garage and a past day to see how the scheduler did, driver by driver.'}</Message>}
      {phase === 'loading' && <Message icon={Loader2} tone="text-brand-400 animate-spin">Loading…</Message>}
      {phase === 'unavailable' && <Message>The Scheduler Report Card is not available for your account.</Message>}
      {phase === 'error' && <Message tone="text-rose-400">{state.error}</Message>}
      {phase === 'not_built' && (
        <Message icon={Hammer} tone="text-brand-400">
          <div>This day has not been built yet. Building reads Salesforce once (about a minute); after that the report opens instantly.</div>
          <button onClick={() => build()} className="mt-3 px-4 py-1.5 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-xs font-medium">Build report</button>
        </Message>
      )}
      {phase === 'building' && (state.preview && isReplay && tab === 'replay'
        ? <BuildingPreview preview={state.preview} stage={state.stage} garage={garage} date={date} startedAt={state.startedAt} />
        : (
          <Message icon={Loader2} tone="text-brand-400 animate-spin">
            <div>Reading this day from Salesforce… it opens by itself when ready (about a minute the first time, instant after that).</div>
            <div className="mt-1 text-xs text-slate-500">started {state.startedAt ? new Date(state.startedAt).toLocaleTimeString() : 'just now'}</div>
          </Message>
        ))}
      {phase === 'rules_unavailable' && (
        <Message icon={RefreshCw} tone="text-amber-300">
          <div>{state.info.error}</div>
          <div className="flex justify-center gap-2 mt-3">
            <button onClick={() => build(true)} className="px-4 py-1.5 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-xs font-medium">Rebuild this day</button>
            {state.info.available.includes('r1') && (
              <button onClick={() => setUrl({ garage, date, rules: 'r1' })} className="px-4 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-white text-xs">View under r1 (final PTA)</button>
            )}
          </div>
        </Message>
      )}
      {phase === 'failed' && (
        <Message tone="text-rose-400">
          <div>The build failed: {state.error || 'unknown error'}</div>
          <button onClick={() => build()} className="mt-3 px-4 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-white text-xs inline-flex items-center gap-1.5">
            <RefreshCw className="w-3.5 h-3.5" />Retry
          </button>
        </Message>
      )}

      {tabs.length > 1 && (
        <div className="flex gap-1 border-b border-slate-700/60" role="tablist">
          {tabs.filter(([k]) => k !== 'wo' || callStory).map(([k, label]) => (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => setUrl({ garage, date, sa: saNumber, tab: k, q })}
              className={`px-4 py-2 text-xs font-medium -mb-px border-b-2 transition-colors ${
                tab === k ? 'border-brand-500 text-white' : 'border-transparent text-slate-400 hover:text-white'}`}>{label}</button>
          ))}
        </div>
      )}

      {state.phase === 'ready' && data && tab === 'replay' && (
        <GarageReplay data={data} garage={garage} date={date} selectedSa={selected?.id} onSelectSa={selectSa} callStory={callStory} />
      )}

      {tab === 'wo' && callStory && (
        <WorkOrderReplayTab q={q} onChange={v => setUrl({ garage, date, tab: 'wo', q: v })} />
      )}

      {state.phase === 'ready' && data && tab === 'day' && (<>
        {data.snapshot.day_mode !== 'fsl' && (
          <div className="glass rounded-xl px-4 py-2 text-xs text-amber-300">
            {data.snapshot.day_mode === 'towbook'
              ? 'Towbook day: workload only. Towbook calls are not graded as scheduler decisions.'
              : `Mixed day: ${data.snapshot.channel_summary.by_channel.towbook || 0} Towbook calls are excluded from grading.`}
          </div>
        )}
        <DaySummary data={data} filter={highlight?.key} onFilter={code => setHighlight(code
          ? { key: code, ids: new Set(data.sas.filter(s => s.verdict?.code === code).map(s => s.id)) } : null)} />
        <AiFindings garage={garage} date={date} rules={rules} activeKey={highlight?.key}
          onHighlight={(key, numbers) => setHighlight(key && highlight?.key !== key
            ? { key, ids: new Set(data.sas.filter(s => numbers.includes(s.number)).map(s => s.id)) } : null)}
          onOpenSa={number => setUrl({ garage, date, sa: number })} />
        <div className="flex gap-4 items-start">
          <div className="flex-1 min-w-0">
            <DayGantt data={data} highlight={highlight?.ids} selectedSa={selected?.id} onSelect={selectSa} />
          </div>
          {selected && (
            <div className="w-96 shrink-0 sticky top-20">
              <CallPanel sa={selected} catalog={data.verdict_catalog} callStory={callStory} onClose={() => setUrl({ garage, date })} />
            </div>
          )}
        </div>
      </>)}
    </div>
  )
}
