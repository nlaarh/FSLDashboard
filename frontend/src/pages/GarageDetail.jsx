import { useState, useEffect, useCallback } from 'react'
import { useParams, Link, useSearchParams } from 'react-router-dom'
import { fetchSchedule, fetchSimulation } from '../api'
import ScheduleGrid from '../components/ScheduleGrid'
import MapView from '../components/MapView'
import GarageDashboard from '../components/GarageDashboard'
import { ArrowLeft, Calendar, BarChart3, Map, Loader2, ChevronLeft, ChevronRight } from 'lucide-react'

const TABS = [
  { key: 'schedule',  label: 'Schedule',    icon: Calendar },
  { key: 'dashboard', label: 'Dashboard',   icon: BarChart3 },
  { key: 'dispatch',  label: 'Dispatch Map', icon: Map },
]

import { getWeek as getWeekDates } from '../utils/dateHelpers'

export default function GarageDetail() {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  // Map old tab names to new
  const rawTab = searchParams.get('tab')
  const mappedTab = rawTab === 'scorecard' || rawTab === 'performance' ? 'dashboard' : rawTab
  const initialTab = TABS.find(t => t.key === mappedTab)?.key ?? 'schedule'
  const [tab, setTab] = useState(initialTab)
  const [schedule, setSchedule] = useState(null)
  const [simulation, setSimulation] = useState(null)
  const [loading, setLoading] = useState({})
  const [error, setError] = useState({})
  const [weekOffset, setWeekOffset] = useState(0)
  const [simDate] = useState(() => new Date().toISOString().split('T')[0])
  const [garageName, setGarageName] = useState(searchParams.get('name') || '')

  const week = getWeekDates(weekOffset)

  const loadSchedule = useCallback(() => {
    setLoading(p => ({ ...p, schedule: true }))
    setError(p => ({ ...p, schedule: null }))
    setSchedule(null)
    const endDate = week.end
    const end = new Date(endDate + 'T00:00:00')
    const start = new Date(end)
    start.setDate(start.getDate() - 27)
    const startDate = start.toISOString().split('T')[0]
    fetchSchedule(id, { weeks: 4, startDate, endDate })
      .then(data => setSchedule(data))
      .catch(e => setError(p => ({ ...p, schedule: e.message })))
      .finally(() => setLoading(p => ({ ...p, schedule: false })))
  }, [id, week.end])

  useEffect(() => { loadSchedule() }, [loadSchedule])

  const loadSimulation = useCallback(() => {
    setLoading(p => ({ ...p, simulation: true }))
    setError(p => ({ ...p, simulation: null }))
    setSimulation(null)
    fetchSimulation(id, simDate)
      .then(setSimulation)
      .catch(e => setError(p => ({ ...p, simulation: e.response?.data?.detail || e.message })))
      .finally(() => setLoading(p => ({ ...p, simulation: false })))
  }, [id, simDate])

  // Auto-load dispatch map when tab is selected
  useEffect(() => {
    if (tab === 'dispatch' && !simulation && !loading.simulation) {
      loadSimulation()
    }
  }, [tab])

  return (
    <div>
      {/* Header */}
      <div className="flex items-center gap-4 mb-6">
        <Link to="/garages" className="p-2 rounded-lg hover:bg-slate-800 transition-colors">
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
          <div className="flex items-center gap-3 mb-5">
            <button onClick={() => setWeekOffset(w => w - 1)}
              className="p-1.5 rounded-lg hover:bg-slate-800 transition-colors">
              <ChevronLeft className="w-5 h-5 text-slate-400" />
            </button>
            <div className="text-center min-w-[260px]">
              <div className="text-sm font-semibold text-white">
                {weekOffset === 0 ? 'This Week' : weekOffset === 1 ? 'Next Week' : weekOffset === -1 ? 'Last Week' : `Week of ${week.start}`}
              </div>
              <div className="text-xs text-slate-400">{week.label}</div>
            </div>
            <button onClick={() => setWeekOffset(w => w + 1)}
              className="p-1.5 rounded-lg hover:bg-slate-800 transition-colors">
              <ChevronRight className="w-5 h-5 text-slate-400" />
            </button>
            <button onClick={() => setWeekOffset(0)}
              className="px-3 py-1 text-xs text-slate-400 hover:text-white bg-slate-800 rounded-lg ml-2">
              Today
            </button>
          </div>
          {loading.schedule && <LoadingState text="Generating schedule from Salesforce data..." />}
          {error.schedule && <ErrorState msg={error.schedule} />}
          {schedule && <ScheduleGrid data={schedule} week={week} onGarageName={setGarageName} />}
        </>
      )}

      {/* Dashboard tab (merged scorecard + performance) */}
      {tab === 'dashboard' && (
        <GarageDashboard garageId={id} garageName={garageName} />
      )}

      {/* Dispatch tab */}
      {tab === 'dispatch' && (
        <div>
          {loading.simulation && <LoadingState text="Loading today's service appointments from Salesforce..." />}
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
