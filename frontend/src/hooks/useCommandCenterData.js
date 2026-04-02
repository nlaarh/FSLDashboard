import { useState, useEffect, useCallback } from 'react'
import { fetchCommandCenter, lookupSA, fetchMapGrids, fetchMapDrivers, fetchMapWeather, fetchOpsGarages, fetchOpsBrief, fetchSchedulerInsights, fetchGpsHealth } from '../api'
import { getMapConfig } from '../mapStyles'

const REFRESH_MS = 60 * 1000

export default function useCommandCenterData() {
  // ── Map style
  const [mapConfig, setMapConfig] = useState(getMapConfig)
  useEffect(() => {
    const handler = () => setMapConfig(getMapConfig())
    window.addEventListener('mapStyleChanged', handler)
    return () => window.removeEventListener('mapStyleChanged', handler)
  }, [])

  // ── Core data
  const [data, setData] = useState(null)
  const [brief, setBrief] = useState(null)
  const [loading, setLoading] = useState(true)
  const [briefLoading, setBriefLoading] = useState(true)
  const [error, setError] = useState(null)
  const [hours, setHours] = useState(4)
  const [lastRefresh, setLastRefresh] = useState(null)
  const [countdown, setCountdown] = useState(60)

  // ── Panel state
  const [panelTab, setPanelTab] = useState('ops')
  const [viewMode, setViewMode] = useState('insights')
  const [panelOpen, setPanelOpen] = useState(true)
  const [focusCenter, setFocusCenter] = useState(null)

  // ── SA lookup
  const [saQuery, setSaQuery] = useState('')
  const [saResult, setSaResult] = useState(null)
  const [saLoading, setSaLoading] = useState(false)
  const [saError, setSaError] = useState(null)

  // ── Map layers
  const [layers, setLayers] = useState({ grid: false, drivers: true, weather: false, activeSAs: true, garages: false, towbook: false })
  const [grids, setGrids] = useState(null)
  const [allDrivers, setAllDrivers] = useState([])
  const [mapWeather, setMapWeather] = useState([])
  const [allGarages, setAllGarages] = useState([])
  const [layerLoading, setLayerLoading] = useState({})

  // ── Scheduler insights + GPS health
  const [schedulerData, setSchedulerData] = useState(null)
  const [gpsHealth, setGpsHealth] = useState(null)

  // ── Filters
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [showSADots, setShowSADots] = useState(true)
  const [saStatusFilter, setSaStatusFilter] = useState('open')

  const load = useCallback(() => {
    setLoading(true)
    setBriefLoading(true)
    setError(null)
    fetchCommandCenter(hours)
      .then(d => {
        // Only update state if data actually changed — prevents map blink on refresh
        setData(prev => {
          if (prev && JSON.stringify(prev.territories?.map(t => t.id + t.total + t.status)) ===
                       JSON.stringify(d.territories?.map(t => t.id + t.total + t.status))) {
            // Territories unchanged — update summary/hourly without re-rendering map
            return { ...prev, summary: d.summary, hourly_volume: d.hourly_volume, fleet: d.fleet }
          }
          return d
        })
        setLastRefresh(new Date()); setCountdown(60)
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
    fetchOpsBrief()
      .then(d => setBrief(prev => {
        if (prev && JSON.stringify(prev.fleet) === JSON.stringify(d.fleet)) {
          return { ...prev, ...d }
        }
        return d
      }))
      .catch(e => console.error('Ops brief fetch failed:', e))
      .finally(() => setBriefLoading(false))
  }, [hours])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    const iv = setInterval(load, REFRESH_MS)
    return () => clearInterval(iv)
  }, [load])
  // Scheduler insights — always fetched fresh (no cache), loaded when user visits page
  const loadScheduler = useCallback(() => {
    fetchSchedulerInsights().then(setSchedulerData).catch(() => {})
    fetchGpsHealth().then(setGpsHealth).catch(() => {})
  }, [])
  useEffect(() => { loadScheduler() }, [loadScheduler])
  useEffect(() => {
    const t = setInterval(() => setCountdown(c => Math.max(0, c - 1)), 1000)
    return () => clearInterval(t)
  }, [])

  // ── Layer lazy-loading
  useEffect(() => {
    if (!layers.grid || grids !== null) return
    setLayerLoading(l => ({ ...l, grid: true }))
    fetchMapGrids().then(d => { setGrids(d); setLayerLoading(l => ({ ...l, grid: false })) }).catch(() => setLayerLoading(l => ({ ...l, grid: false })))
  }, [layers.grid])
  useEffect(() => {
    if (!layers.drivers || allDrivers.length > 0) return
    setLayerLoading(l => ({ ...l, drivers: true }))
    fetchMapDrivers().then(d => { setAllDrivers(d); setLayerLoading(l => ({ ...l, drivers: false })) }).catch(() => setLayerLoading(l => ({ ...l, drivers: false })))
  }, [layers.drivers])
  useEffect(() => {
    if (!layers.weather || mapWeather.length > 0) return
    setLayerLoading(l => ({ ...l, weather: true }))
    fetchMapWeather().then(d => { setMapWeather(d); setLayerLoading(l => ({ ...l, weather: false })) }).catch(() => setLayerLoading(l => ({ ...l, weather: false })))
  }, [layers.weather])
  useEffect(() => {
    if ((!layers.garages && !layers.towbook) || allGarages.length > 0) return
    setLayerLoading(l => ({ ...l, garages: true }))
    fetchOpsGarages().then(d => { setAllGarages(d); setLayerLoading(l => ({ ...l, garages: false })) }).catch(() => setLayerLoading(l => ({ ...l, garages: false })))
  }, [layers.garages, layers.towbook])

  const searchSA = () => {
    if (!saQuery.trim()) return
    setSaLoading(true); setSaError(null); setSaResult(null)
    lookupSA(saQuery.trim())
      .then(r => { setSaResult(r); if (r.sa.lat && r.sa.lon) setFocusCenter([r.sa.lat, r.sa.lon]) })
      .catch(e => setSaError(e.response?.data?.detail || e.message))
      .finally(() => setSaLoading(false))
  }
  const clearSA = () => { setSaResult(null); setSaError(null); setSaQuery('') }

  const territories = data?.territories || []
  const summary = data?.summary || {}
  const fleet = brief?.fleet || {}
  const demand = brief?.demand || {}
  const suggestions = brief?.suggestions || []
  const openCalls = brief?.open_calls || []
  const atRisk = brief?.at_risk || []
  const zones = brief?.zones || []

  const filtered = territories.filter(t => {
    if (statusFilter !== 'all' && t.status !== statusFilter) return false
    if (search && !t.name.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  // Build idle driver set for map highlighting
  const idleDriverIds = new Set((fleet.idle_drivers || []).map(d => d.id))

  return {
    mapConfig, data, brief, loading, briefLoading, error, hours, setHours,
    lastRefresh, countdown, load,
    panelTab, setPanelTab, viewMode, setViewMode, panelOpen, setPanelOpen,
    focusCenter, setFocusCenter,
    saQuery, setSaQuery, saResult, setSaResult, saLoading, setSaLoading,
    saError, setSaError, searchSA, clearSA,
    layers, setLayers, grids, allDrivers, mapWeather, allGarages, layerLoading,
    schedulerData, gpsHealth, loadScheduler,
    search, setSearch, statusFilter, setStatusFilter,
    showSADots, setShowSADots, saStatusFilter, setSaStatusFilter,
    territories, summary, fleet, demand, suggestions, openCalls, atRisk, zones,
    filtered, idleDriverIds,
  }
}
