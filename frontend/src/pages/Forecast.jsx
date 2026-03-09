import { useState, useEffect } from 'react'
import { fetchForecast, fetchGarages } from '../api'
import {
  Loader2, Cloud, Sun, Snowflake, CloudRain, Wind, Thermometer,
  Users, TrendingUp, ChevronDown, BarChart3, Calendar,
} from 'lucide-react'
import { clsx } from 'clsx'

const SEVERITY_COLORS = {
  Clear:    'text-emerald-400',
  Mild:     'text-blue-400',
  Moderate: 'text-amber-400',
  Severe:   'text-orange-400',
  Extreme:  'text-red-400',
}

const SEVERITY_BG = {
  Clear:    'bg-emerald-950/20 border-emerald-800/20',
  Mild:     'bg-blue-950/20 border-blue-800/20',
  Moderate: 'bg-amber-950/20 border-amber-800/20',
  Severe:   'bg-orange-950/20 border-orange-800/20',
  Extreme:  'bg-red-950/20 border-red-800/20',
}

function WeatherIcon({ severity, className = 'w-5 h-5' }) {
  if (severity === 'Extreme' || severity === 'Severe') return <Snowflake className={clsx(className, 'text-blue-300')} />
  if (severity === 'Moderate') return <CloudRain className={clsx(className, 'text-amber-400')} />
  if (severity === 'Mild') return <Cloud className={clsx(className, 'text-slate-400')} />
  return <Sun className={clsx(className, 'text-yellow-400')} />
}

export default function Forecast() {
  const [garages, setGarages] = useState([])
  const [selectedGarage, setSelectedGarage] = useState(null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [weeks, setWeeks] = useState(8)

  // Load garages for selector
  useEffect(() => {
    fetchGarages()
      .then(g => {
        setGarages(g)
        if (g.length && !selectedGarage) setSelectedGarage(g[0])
      })
      .catch(e => { console.error('Failed to load garages for forecast:', e); setError(e.message || 'Failed to load garages') })
  }, [])

  // Load forecast when garage changes
  useEffect(() => {
    if (!selectedGarage) return
    setLoading(true)
    setError(null)
    fetchForecast(selectedGarage.id, weeks)
      .then(setData)
      .catch(e => setError(e.response?.data?.detail || e.message))
      .finally(() => setLoading(false))
  }, [selectedGarage, weeks])

  const forecast = data?.forecast || []
  const model = data?.model || {}

  // Find peak day
  const peakDay = forecast.reduce((max, d) => d.adjusted_volume > (max?.adjusted_volume || 0) ? d : max, null)

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Demand Forecast</h1>
          <p className="text-sm text-slate-500 mt-0.5">16-day volume prediction using DOW patterns + weather</p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={selectedGarage?.id || ''}
            onChange={e => setSelectedGarage(garages.find(g => g.id === e.target.value))}
            className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm
                       focus:outline-none focus:ring-2 focus:ring-brand-500/40 text-white"
          >
            {garages.map(g => (
              <option key={g.id} value={g.id}>{g.name}</option>
            ))}
          </select>
          <select value={weeks} onChange={e => setWeeks(Number(e.target.value))}
            className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm
                       focus:outline-none focus:ring-2 focus:ring-brand-500/40 text-white">
            <option value={4}>4-week history</option>
            <option value={8}>8-week history</option>
            <option value={12}>12-week history</option>
          </select>
        </div>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-20 gap-3">
          <Loader2 className="w-6 h-6 animate-spin text-brand-400" />
          <span className="text-slate-400">Building demand forecast...</span>
        </div>
      )}

      {error && (
        <div className="rounded-xl bg-red-950/30 border border-red-800/30 p-4 text-red-300 text-sm">{error}</div>
      )}

      {data && !loading && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="glass rounded-xl p-4 border border-slate-700/30">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Peak Day</div>
              <div className="text-lg font-black text-white">{peakDay?.day_of_week} {peakDay?.date?.slice(5)}</div>
              <div className="text-xs text-slate-500">{peakDay?.adjusted_volume} calls expected</div>
            </div>
            <div className="glass rounded-xl p-4 border border-slate-700/30">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Peak Driver Need</div>
              <div className="text-lg font-black text-brand-400">{peakDay?.driver_needs.peak_total}</div>
              <div className="text-xs text-slate-500">{peakDay?.driver_needs.peak_tow} tow + {peakDay?.driver_needs.peak_batt_light} batt/light</div>
            </div>
            <div className="glass rounded-xl p-4 border border-slate-700/30">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Weather Alerts</div>
              <div className="text-lg font-black text-amber-400">
                {forecast.filter(d => d.weather.severity === 'Severe' || d.weather.severity === 'Extreme').length}
              </div>
              <div className="text-xs text-slate-500">severe/extreme days</div>
            </div>
            <div className="glass rounded-xl p-4 border border-slate-700/30">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Avg Volume</div>
              <div className="text-lg font-black text-white">
                {forecast.length ? Math.round(forecast.reduce((s, d) => s + d.adjusted_volume, 0) / forecast.length) : 0}
              </div>
              <div className="text-xs text-slate-500">calls/day</div>
            </div>
          </div>

          {/* DOW averages */}
          {model.dow_averages && (
            <div className="glass rounded-xl p-5">
              <h3 className="font-semibold text-slate-200 mb-3 flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-brand-400" />
                Day-of-Week Pattern ({model.weeks_analyzed} weeks)
              </h3>
              <div className="flex gap-2">
                {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map(d => {
                  const vol = model.dow_averages[d] || 0
                  const maxVol = Math.max(...Object.values(model.dow_averages))
                  const pct = maxVol > 0 ? (vol / maxVol) * 100 : 0
                  return (
                    <div key={d} className="flex-1 text-center">
                      <div className="h-20 flex items-end justify-center mb-1">
                        <div className="w-full max-w-[40px] bg-brand-600/60 rounded-t-md transition-all"
                          style={{ height: `${Math.max(pct, 5)}%` }} />
                      </div>
                      <div className="text-xs font-bold text-white">{vol}</div>
                      <div className="text-[10px] text-slate-500">{d}</div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* 16-day cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {forecast.map((day, i) => {
              const isToday = i === 0
              const severity = day.weather.severity
              return (
                <div key={day.date}
                  className={clsx('rounded-xl p-4 border transition-all',
                    isToday ? 'bg-brand-950/30 border-brand-700/40' : SEVERITY_BG[severity])}>

                  {/* Date header */}
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <div className="text-sm font-bold text-white">
                        {isToday ? 'Today' : day.day_of_week}
                        <span className="text-slate-500 font-normal ml-1.5">{day.date.slice(5)}</span>
                      </div>
                      <div className={clsx('text-[10px] font-medium', SEVERITY_COLORS[severity])}>
                        {severity}
                      </div>
                    </div>
                    <WeatherIcon severity={severity} />
                  </div>

                  {/* Weather details */}
                  <div className="flex gap-3 text-[10px] text-slate-400 mb-3">
                    <span className="flex items-center gap-1">
                      <Thermometer className="w-3 h-3" />
                      {day.weather.temp_min_f ?? '?'}–{day.weather.temp_max_f ?? '?'}°F
                    </span>
                    {day.weather.snow_in > 0 && (
                      <span className="flex items-center gap-1 text-blue-400">
                        <Snowflake className="w-3 h-3" /> {day.weather.snow_in}"
                      </span>
                    )}
                    {day.weather.wind_max_mph > 20 && (
                      <span className="flex items-center gap-1">
                        <Wind className="w-3 h-3" /> {day.weather.wind_max_mph}mph
                      </span>
                    )}
                  </div>

                  {/* Volume */}
                  <div className="mb-2">
                    <div className="flex items-baseline gap-1.5">
                      <span className="text-xl font-black text-white">{day.adjusted_volume}</span>
                      <span className="text-xs text-slate-500">calls</span>
                    </div>
                    {day.weather_multiplier > 1 && (
                      <div className="text-[10px] text-amber-400">
                        +{Math.round((day.weather_multiplier - 1) * 100)}% weather impact (base: {day.base_volume})
                      </div>
                    )}
                  </div>

                  {/* Driver needs */}
                  <div className="bg-slate-900/50 rounded-lg p-2 mt-2">
                    <div className="text-[10px] text-slate-500 font-semibold mb-1">Peak Staffing ({day.driver_needs.peak_block})</div>
                    <div className="flex gap-3 text-xs">
                      <span className="text-blue-400 font-medium">{day.driver_needs.peak_tow} tow</span>
                      <span className="text-purple-400 font-medium">{day.driver_needs.peak_batt_light} B/L</span>
                      <span className="text-white font-bold ml-auto">{day.driver_needs.peak_total} total</span>
                    </div>
                  </div>

                  {/* Confidence */}
                  <div className={clsx('text-[10px] mt-2',
                    day.confidence === 'high' ? 'text-emerald-500' : day.confidence === 'medium' ? 'text-amber-500' : 'text-red-500')}>
                    {day.confidence} confidence
                  </div>
                </div>
              )
            })}
          </div>

          {/* Model info */}
          <div className="text-[10px] text-slate-600 text-center">
            Model: {model.weeks_analyzed}-week DOW average × weather severity multiplier.
            Multipliers: Clear 1.0x, Mild 1.05x, Moderate 1.1x, Severe 1.25x, Extreme 1.4x
          </div>
        </>
      )}
    </div>
  )
}
