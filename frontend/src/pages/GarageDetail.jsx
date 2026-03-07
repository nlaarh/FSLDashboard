import { useState, useEffect, useCallback } from 'react'
import { useParams, Link, useSearchParams } from 'react-router-dom'
import { fetchSchedule, fetchScorecard, fetchSimulation } from '../api'
import ScheduleGrid from '../components/ScheduleGrid'
import Scorecard from '../components/Scorecard'
import MapView from '../components/MapView'
import Performance from '../components/Performance'
import { ArrowLeft, Calendar, BarChart3, Map, Loader2, ChevronLeft, ChevronRight, TrendingUp } from 'lucide-react'

const TABS = [
  { key: 'schedule',    label: 'Schedule',    icon: Calendar },
  { key: 'scorecard',  label: 'Scorecard',   icon: BarChart3 },
  { key: 'performance', label: 'Performance', icon: TrendingUp },
  { key: 'dispatch',   label: 'Dispatch Map', icon: Map },
]

function getWeekDates(offset = 0) {
  const now = new Date()
  const day = now.getDay()
  const diffToMon = day === 0 ? -6 : 1 - day
  const monday = new Date(now)
  monday.setDate(now.getDate() + diffToMon + offset * 7)
  const sunday = new Date(monday)
  sunday.setDate(monday.getDate() + 6)
  const fmt = d => d.toISOString().split('T')[0]
  const label = d => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  return {
    start: fmt(monday),
    end: fmt(sunday),
    label: `${label(monday)} – ${label(sunday)}, ${monday.getFullYear()}`,
    offset,
  }
}

export default function GarageDetail() {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const initialTab = TABS.find(t => t.key === searchParams.get('tab'))?.key ?? 'schedule'
  const [tab, setTab] = useState(initialTab)
  const [schedule, setSchedule] = useState(null)
  const [scorecard, setScorecard] = useState(null)
  const [simulation, setSimulation] = useState(null)
  const [loading, setLoading] = useState({})
  const [error, setError] = useState({})
  const [weekOffset, setWeekOffset] = useState(0)
  const [simDate, setSimDate] = useState(() => {
    const d = new Date()
    d.setDate(d.getDate() - 1)
    return d.toISOString().split('T')[0]
  })
  const [garageName, setGarageName] = useState('')

  const week = getWeekDates(weekOffset)

  // Load schedule — recalculates whenever week changes
  const loadSchedule = useCallback(() => {
    setLoading(p => ({ ...p, schedule: true }))
    setError(p => ({ ...p, schedule: null }))
    setSchedule(null)
    // Pass a 4-week window ending on the selected week's Sunday
    const endDate = week.end
    // Calculate start: 4 weeks before the end date
    const end = new Date(endDate + 'T00:00:00')
    const start = new Date(end)
    start.setDate(start.getDate() - 27) // 4 weeks = 28 days, start is 27 days before end
    const startDate = start.toISOString().split('T')[0]
    fetchSchedule(id, { weeks: 4, startDate, endDate })
      .then(data => setSchedule(data))
      .catch(e => setError(p => ({ ...p, schedule: e.message })))
      .finally(() => setLoading(p => ({ ...p, schedule: false })))
  }, [id, week.end])

  useEffect(() => { loadSchedule() }, [loadSchedule])

  // Load scorecard when tab switches
  useEffect(() => {
    if (tab === 'scorecard' && !scorecard && !loading.scorecard) {
      setLoading(p => ({ ...p, scorecard: true }))
      setError(p => ({ ...p, scorecard: null }))
      fetchScorecard(id)
        .then(setScorecard)
        .catch(e => setError(p => ({ ...p, scorecard: e.message })))
        .finally(() => setLoading(p => ({ ...p, scorecard: false })))
    }
  }, [tab, id, scorecard, loading.scorecard])

  const loadSimulation = () => {
    setLoading(p => ({ ...p, simulation: true }))
    setError(p => ({ ...p, simulation: null }))
    setSimulation(null)
    fetchSimulation(id, simDate)
      .then(setSimulation)
      .catch(e => setError(p => ({ ...p, simulation: e.response?.data?.detail || e.message })))
      .finally(() => setLoading(p => ({ ...p, simulation: false })))
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center gap-4 mb-6">
        <Link to="/" className="p-2 rounded-lg hover:bg-slate-800 transition-colors">
          <ArrowLeft className="w-5 h-5 text-slate-400" />
        </Link>
        <div>
          <h1 className="text-2xl font-bold text-white">{garageName || 'Garage Detail'}</h1>
          <p className="text-sm text-slate-500 mt-0.5">Territory ID: {id}</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-slate-900 rounded-xl mb-6 w-fit">
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              tab === t.key
                ? 'bg-brand-600 text-white shadow-lg shadow-brand-600/20'
                : 'text-slate-400 hover:text-white hover:bg-slate-800'
            }`}
          >
            <t.icon className="w-4 h-4" />
            {t.label}
          </button>
        ))}
      </div>

      {/* Schedule tab */}
      {tab === 'schedule' && (
        <>
          {/* Week navigation */}
          <div className="flex items-center gap-3 mb-5">
            <button
              onClick={() => setWeekOffset(w => w - 1)}
              className="p-1.5 rounded-lg hover:bg-slate-800 transition-colors"
            >
              <ChevronLeft className="w-5 h-5 text-slate-400" />
            </button>
            <div className="text-center min-w-[260px]">
              <div className="text-sm font-semibold text-white">
                {weekOffset === 0 ? 'This Week' : weekOffset === 1 ? 'Next Week' : weekOffset === -1 ? 'Last Week' : `Week of ${week.start}`}
              </div>
              <div className="text-xs text-slate-400">{week.label}</div>
            </div>
            <button
              onClick={() => setWeekOffset(w => w + 1)}
              className="p-1.5 rounded-lg hover:bg-slate-800 transition-colors"
            >
              <ChevronRight className="w-5 h-5 text-slate-400" />
            </button>
            <button
              onClick={() => setWeekOffset(0)}
              className="px-3 py-1 text-xs text-slate-400 hover:text-white bg-slate-800 rounded-lg ml-2"
            >
              Today
            </button>
          </div>

          {loading.schedule && <LoadingState text="Generating schedule from Salesforce data..." />}
          {error.schedule && <ErrorState msg={error.schedule} />}
          {schedule && <ScheduleGrid data={schedule} week={week} onGarageName={setGarageName} />}
        </>
      )}

      {/* Scorecard tab */}
      {tab === 'scorecard' && (
        <>
          {loading.scorecard && <LoadingState text="Computing performance metrics..." />}
          {error.scorecard && <ErrorState msg={error.scorecard} />}
          {scorecard && <Scorecard data={scorecard} garageId={id} />}
        </>
      )}

      {/* Performance tab */}
      {tab === 'performance' && (
        <Performance garageId={id} garageName={garageName} />
      )}

      {/* Dispatch tab */}
      {tab === 'dispatch' && (
        <div>
          <div className="flex items-center gap-3 mb-4">
            <input
              type="date"
              value={simDate}
              onChange={e => setSimDate(e.target.value)}
              className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm
                         focus:outline-none focus:ring-2 focus:ring-brand-500/40"
            />
            <button
              onClick={loadSimulation}
              disabled={loading.simulation}
              className="px-4 py-2 bg-brand-600 hover:bg-brand-500 rounded-lg text-sm font-medium
                         transition-colors disabled:opacity-50 flex items-center gap-2"
            >
              {loading.simulation && <Loader2 className="w-4 h-4 animate-spin" />}
              {loading.simulation ? 'Loading...' : 'Get SAs'}
            </button>
            <span className="text-xs text-slate-500">Pick a date with SA data (try a weekday)</span>
          </div>
          {loading.simulation && <LoadingState text="Querying drivers, skills, and positions from Salesforce..." />}
          {error.simulation && <ErrorState msg={error.simulation} />}
          {simulation && <MapView data={simulation} />}
        </div>
      )}
    </div>
  )
}

function LoadingState({ text }) {
  return (
    <div className="flex items-center justify-center py-20 gap-3">
      <Loader2 className="w-6 h-6 animate-spin text-brand-400" />
      <span className="text-slate-400">{text}</span>
    </div>
  )
}

function ErrorState({ msg }) {
  return (
    <div className="rounded-xl bg-red-950/30 border border-red-800/30 p-4 text-red-300 text-sm">
      {msg}
    </div>
  )
}
