import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { MapContainer, TileLayer, Marker, Popup, Tooltip, Polyline, useMap } from 'react-leaflet'
import { Loader2, RefreshCw, AlertCircle, Search, MapPinOff } from 'lucide-react'
import { truckIcon, customerIcon, dropoffIcon } from '../../mapIcons'

// UNRELEASED — rendered only when the backend `contractor_dispatch` flag is on.
// Live map of a contractor's own active calls and the drivers running them.
// Customer pins and driver pins use deliberately different marks.

const CENTER = [42.9, -78.8]      // Western/Central NY

// How often the map re-polls for driver positions. Note DRIVER_GPS_MAX_AGE_MIN
// (30 min, server-side) is what decides whether a truck is drawn at all — this
// only controls how quickly a moving truck's pin catches up.
const REFRESH_MS = 60000

// Route colours. Green = the truck's run to the stranded member; blue = the tow
// onward to the shop, matching the drop-off pin's own tint so the eye pairs the
// line with the destination it ends at.
const LEG_TO_BREAKDOWN = '#34d399'
const LEG_TO_DROPOFF   = '#7dd3fc'

const TRUCK_TONE = {
  'En Route': 'closest', 'On Location': 'assigned_closest', 'In Progress': 'assigned_closest',
  'Dispatched': 'dispatched', 'Accepted': 'dispatched', 'Assigned': 'eligible',
}

const clock = iso => iso
  ? new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  : ''

/** Pans the map when the user picks a row. */
function FlyTo({ target }) {
  const map = useMap()
  useEffect(() => {
    if (target) map.flyTo(target, 15, { duration: 0.9 })
  }, [target, map])
  return null
}

/** One labelled line inside a hover tooltip. Renders nothing when empty. */
const Row = ({ k, v }) => v
  ? <div><span style={{ color: '#94a3b8' }}>{k}</span> <span style={{ color: '#e2e8f0' }}>{v}</span></div>
  : null

export default function ContractorMap() {
  const [tab, setTab] = useState('calls')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [target, setTarget] = useState(null)
  const [selected, setSelected] = useState(null)
  const [q, setQ] = useState('')

  const [unavailable, setUnavailable] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [updatedAt, setUpdatedAt] = useState(null)

  // Driver GPS moves constantly, so the map polls once a minute. Each poll costs
  // three SOQL queries and nothing here is cached server-side, so the pins are as
  // fresh as Salesforce itself — but that also means an idle tab would burn API
  // quota for nothing. Hence: skip while hidden, never stack overlapping requests.
  const inFlight = useRef(false)

  const load = useCallback(() => {
    if (inFlight.current) return   // a slow poll must not queue another behind it
    inFlight.current = true
    setRefreshing(true)
    setErr('')
    fetch('/api/contractor/map')
      .then(async r => {
        // 403 = off-platform garage: not an error to retry, a feature that
        // does not apply. Surface the server's wording, not "HTTP 403".
        if (r.status === 403) {
          const d = await r.json().catch(() => ({}))
          setUnavailable(d.detail || 'The live map is available to on-platform garages only.')
          return null
        }
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(d => { if (d) { setUnavailable(''); setData(d); setUpdatedAt(new Date()) } })
      .catch(e => setErr(e.message || 'Failed to load'))
      .finally(() => { inFlight.current = false; setRefreshing(false); setLoading(false) })
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    const t = setInterval(() => { if (!document.hidden) load() }, REFRESH_MS)
    // Coming back to a backgrounded tab, the pins on screen are as old as the
    // time away. Refresh at once rather than showing stale trucks until the
    // next tick.
    const onVisible = () => { if (!document.hidden) load() }
    document.addEventListener('visibilitychange', onVisible)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', onVisible) }
  }, [load])

  const calls = data?.calls || []
  const drivers = data?.drivers || []

  const filt = useCallback(list => {
    const s = q.trim().toLowerCase()
    if (!s) return list
    return list.filter(x => JSON.stringify(x).toLowerCase().includes(s))
  }, [q])

  const shownCalls = useMemo(() => filt(calls), [filt, calls])
  const shownDrivers = useMemo(() => filt(drivers), [filt, drivers])

  // Marker instances, keyed the same way as `selected` ("c:<id>" / "d:<name>"),
  // so picking a row can open that exact popup.
  const markers = useRef({})

  const pick = (lat, lon, key) => {
    if (lat == null || lon == null) return
    setTarget([lat, lon])
    setSelected(key)
  }

  // Open the picked marker's popup once the fly-to has settled, so the row
  // click lands you on a pin that is both highlighted and already labelled.
  useEffect(() => {
    if (!selected) return
    const t = setTimeout(() => markers.current[selected]?.openPopup(), 950)
    return () => clearTimeout(t)
  }, [selected, target])

  // Street route for whichever call is selected. Fetched on demand rather than
  // with the map payload: it is one routing call per click, and most clicks
  // never happen. A failed or slow route just leaves the lines undrawn — the
  // public OSRM server has no SLA, so it must never block the map.
  const [route, setRoute] = useState(null)
  useEffect(() => {
    if (!selected?.startsWith('c:')) { setRoute(null); return }
    const saId = selected.slice(2)
    let cancelled = false
    setRoute(null)
    fetch(`/api/contractor/route?sa_id=${encodeURIComponent(saId)}`)
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (!cancelled) setRoute(d) })
      .catch(() => { /* no line is better than an error toast */ })
    // A second click before the first resolves must not paint the old route.
    return () => { cancelled = true }
  }, [selected])

  if (unavailable) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-92px)] px-6">
        <div className="max-w-md text-center">
          <MapPinOff size={30} className="mx-auto text-slate-600 mb-3" />
          <div className="text-slate-200 font-medium mb-1">Live map not available</div>
          <div className="text-sm text-slate-500">{unavailable}</div>
          <div className="text-xs text-slate-600 mt-3">
            Your calls are dispatched through Towbook, which does not report driver
            location to this system. Use the Dispatch board to track your work.
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-[calc(100vh-92px)]">
      {/* ── left rail ─────────────────────────────────────────────── */}
      <div className="w-[420px] flex-shrink-0 border-r border-slate-800 flex flex-col bg-slate-950">
        <div className="p-3 border-b border-slate-800">
          <div className="flex items-center gap-2 mb-2">
            <div className="flex rounded-lg border border-slate-700 overflow-hidden">
              {['calls', 'drivers'].map(t => (
                <button key={t} onClick={() => setTab(t)}
                  className={`px-4 py-1.5 text-sm font-medium capitalize transition-all ${
                    tab === t ? 'bg-brand-600 text-white' : 'text-slate-400 hover:text-white hover:bg-slate-800'
                  }`}>
                  {t} <span className="opacity-60">({t === 'calls' ? calls.length : drivers.length})</span>
                </button>
              ))}
            </div>
            {updatedAt && (
              <span className="ml-auto text-[10px] text-slate-500 tabular-nums" title="Map refreshes every minute">
                updated {clock(updatedAt.toISOString())}
              </span>
            )}
            <button onClick={load} title="Refresh now"
              className={`${updatedAt ? '' : 'ml-auto'} p-2 rounded-lg border border-slate-700 text-slate-400 hover:text-white hover:bg-slate-800`}>
              <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
            </button>
          </div>
          <div className="relative">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
            <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search…"
              className="w-full bg-slate-900 border border-slate-700 rounded-lg pl-8 pr-3 py-1.5
                         text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-brand-500" />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {err && (
            <div className="flex items-center gap-2 text-sm text-red-300 bg-red-500/10 m-3
                            border border-red-500/25 rounded-lg px-3 py-2">
              <AlertCircle size={14} /> {err}
            </div>
          )}
          {loading && !data ? (
            <div className="flex items-center gap-2 text-slate-500 text-sm py-10 justify-center">
              <Loader2 size={16} className="animate-spin" /> Loading…
            </div>
          ) : tab === 'calls' ? (
            shownCalls.length === 0
              ? <div className="text-center text-slate-500 text-sm py-12">No active calls.</div>
              : shownCalls.map(c => (
                <button key={c.sa_id} onClick={() => pick(c.lat, c.lon, `c:${c.sa_id}`)}
                  className={`w-full text-left px-4 py-3 border-b border-slate-800/60 transition-all ${
                    selected === `c:${c.sa_id}` ? 'bg-brand-600/10' : 'hover:bg-slate-900'
                  }`}>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-slate-500 tabular-nums">{c.sa_number}</span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded border border-slate-600/40
                                     bg-slate-700/30 text-slate-300">{c.status}</span>
                    {c.is_dropoff && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded border border-sky-500/40
                                       bg-sky-500/10 text-sky-300">drop-off</span>
                    )}
                    {c.eta && <span className="ml-auto text-xs text-slate-500">ETA {clock(c.eta)}</span>}
                  </div>
                  <div className="text-slate-100 font-medium text-sm mt-0.5 truncate">
                    {c.vehicle || c.work_type}
                  </div>
                  <div className="text-xs text-slate-400 truncate">{c.address}</div>
                  <div className="text-xs text-slate-500 truncate mt-0.5">
                    {c.work_type}
                    {c.driver ? ` · ${c.driver}` : ' · unassigned'}
                    {c.truck ? ` · ${c.truck}` : ''}
                  </div>
                </button>
              ))
          ) : (
            shownDrivers.length === 0
              ? <div className="text-center text-slate-500 text-sm py-12 px-6">
                  No driver positions available.
                  <div className="text-xs mt-2 text-slate-600">
                    Drivers appear here while they are on a call and reporting GPS.
                  </div>
                </div>
              : shownDrivers.map(d => (
                <button key={d.name} onClick={() => pick(d.lat, d.lon, `d:${d.name}`)}
                  className={`w-full text-left px-4 py-3 border-b border-slate-800/60 transition-all ${
                    selected === `d:${d.name}` ? 'bg-brand-600/10' : 'hover:bg-slate-900'
                  }`}>
                  <div className="flex items-center gap-2">
                    <span className="text-slate-100 font-medium text-sm truncate">{d.name}</span>
                    <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded border border-slate-600/40
                                     bg-slate-700/30 text-slate-300">{d.status}</span>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-slate-400">
                    {d.truck && <span>{d.truck}</span>}
                    {d.job_count > 1 && (
                      <span className="text-amber-400/90">{d.job_count} calls assigned</span>
                    )}
                  </div>
                  <div className="text-xs text-slate-500 truncate mt-0.5">
                    On {d.sa_number} · {d.work_type}
                  </div>
                  <div className="text-xs text-slate-600 truncate">{d.destination}</div>
                </button>
              ))
          )}
        </div>

        {data && (
          <div className="px-4 py-2 border-t border-slate-800 text-[11px] text-slate-600">
            {data.facilities?.join(', ')} · refreshes every 60s
            {data.calls_without_location > 0 &&
              <> · {data.calls_without_location} call(s) without a location</>}
          </div>
        )}
      </div>

      {/* ── map ───────────────────────────────────────────────────── */}
      <div className="flex-1 relative">
        <MapContainer center={CENTER} zoom={9} className="w-full h-full" scrollWheelZoom>
          <TileLayer
            url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
            attribution='&copy; OpenStreetMap &copy; CARTO'
          />
          <FlyTo target={target} />

          {/* Route for the selected call. Dashed so it reads as a planned path
              rather than a track the truck has already driven. */}
          {route?.to_breakdown?.coords?.length > 1 && (
            <Polyline positions={route.to_breakdown.coords} pathOptions={{
              color: LEG_TO_BREAKDOWN, weight: 4, opacity: 0.9, dashArray: '6 8',
            }}>
              <Tooltip sticky className="cc-tooltip">
                <div style={{ fontSize: 12 }}>
                  <b style={{ color: LEG_TO_BREAKDOWN }}>To the breakdown</b><br />
                  {route.to_breakdown.miles} mi · {route.to_breakdown.minutes} min
                </div>
              </Tooltip>
            </Polyline>
          )}
          {route?.to_dropoff?.coords?.length > 1 && (
            <Polyline positions={route.to_dropoff.coords} pathOptions={{
              color: LEG_TO_DROPOFF, weight: 4, opacity: 0.9, dashArray: '2 7',
            }}>
              <Tooltip sticky className="cc-tooltip">
                <div style={{ fontSize: 12 }}>
                  <b style={{ color: LEG_TO_DROPOFF }}>Tow to drop-off</b><br />
                  {route.to_dropoff.miles} mi · {route.to_dropoff.minutes} min
                </div>
              </Tooltip>
            </Polyline>
          )}

          {calls.map(c => (
            <Marker key={`c-${c.sa_id}`} position={[c.lat, c.lon]}
              icon={(c.is_dropoff ? dropoffIcon : customerIcon)(selected === `c:${c.sa_id}`)}
              ref={m => { if (m) markers.current[`c:${c.sa_id}`] = m }}
              eventHandlers={{ click: () => setSelected(`c:${c.sa_id}`) }}>
              {/* hover detail only while this marker's popup is closed —
                  otherwise both render and the text appears twice */}
              {selected !== `c:${c.sa_id}` && (
              <Tooltip direction="top" offset={[0, -46]} opacity={1} className="cc-tooltip">
                <div style={{ fontSize: 12, lineHeight: 1.55, minWidth: 170 }}>
                  <div style={{ fontWeight: 700, color: '#f1f5f9', marginBottom: 3 }}>
                    {c.customer || 'Customer unknown'}
                  </div>
                  {c.is_dropoff && (
                    <div style={{ color: '#7dd3fc', fontWeight: 600, marginBottom: 2 }}>
                      Tow drop-off · this pin is the destination
                    </div>
                  )}
                  <Row k="Car" v={c.vehicle} />
                  <Row k="Service" v={c.work_type} />
                  <Row k="Status" v={c.status} />
                  <Row k="Driver" v={c.driver ? `${c.driver}${c.truck ? ` (${c.truck})` : ''}` : 'Unassigned'} />
                  <Row k={c.is_dropoff ? 'Dropping at' : 'Location'} v={c.address} />
                  <Row k="ETA" v={c.eta ? clock(c.eta) : ''} />
                  <div style={{ color: '#64748b', marginTop: 3 }}>{c.sa_number} · click for detail</div>
                </div>
              </Tooltip>
              )}
              <Popup>
                <div style={{ minWidth: 220 }}>
                  <div style={{ fontWeight: 700, marginBottom: 4 }}>
                    {c.vehicle || c.work_type}
                  </div>
                  <div style={{ fontSize: 12, lineHeight: 1.6 }}>
                    <div><b>Call</b> {c.sa_number}{c.wo_number ? ` · WO ${c.wo_number}` : ''}</div>
                    {c.customer && <div><b>Customer</b> {c.customer}</div>}
                    <div><b>Status</b> {c.status}</div>
                    <div><b>Service</b> {c.work_type}{c.reason ? ` · ${c.reason}` : ''}</div>
                    <div><b>{c.is_dropoff ? 'Dropping at' : 'Location'}</b> {c.address}</div>
                    {c.plate && <div><b>Plate</b> {c.plate}</div>}
                    <div><b>Driver</b> {c.driver || 'Unassigned'}{c.truck ? ` (${c.truck})` : ''}</div>
                    {c.eta && <div><b>ETA</b> {clock(c.eta)}</div>}
                    {c.coverage && <div><b>Coverage</b> {c.coverage}</div>}
                    <div><b>Account</b> {c.account || c.territory}</div>
                  </div>
                </div>
              </Popup>
            </Marker>
          ))}

          {drivers.map(d => (
            <Marker key={`d-${d.name}`} position={[d.lat, d.lon]}
              icon={truckIcon(TRUCK_TONE[d.status] || 'eligible',
                              d.truck || d.name.split(' ')[0],
                              selected === `d:${d.name}`)}
              ref={m => { if (m) markers.current[`d:${d.name}`] = m }}
              eventHandlers={{ click: () => setSelected(`d:${d.name}`) }}>
              {selected !== `d:${d.name}` && (
              <Tooltip direction="top" offset={[0, -24]} opacity={1} className="cc-tooltip">
                <div style={{ fontSize: 12, lineHeight: 1.55, minWidth: 170 }}>
                  <div style={{ fontWeight: 700, color: '#f1f5f9', marginBottom: 3 }}>{d.name}</div>
                  <Row k="Truck" v={d.truck} />
                  <Row k="Status" v={d.status} />
                  <Row k="On call" v={`${d.sa_number} · ${d.work_type}`} />
                  <Row k="Heading to" v={d.destination} />
                  {d.job_count > 1 && <Row k="Assigned" v={`${d.job_count} calls`} />}
                  <Row k="GPS" v={d.last_seen ? clock(d.last_seen) : ''} />
                </div>
              </Tooltip>
              )}
              <Popup>
                <div style={{ minWidth: 210 }}>
                  <div style={{ fontWeight: 700, marginBottom: 4 }}>{d.name}</div>
                  <div style={{ fontSize: 12, lineHeight: 1.6 }}>
                    {d.truck && <div><b>Truck</b> {d.truck}</div>}
                    <div><b>Status</b> {d.status}</div>
                    <div><b>On call</b> {d.sa_number} · {d.work_type}</div>
                    <div><b>Heading to</b> {d.destination}</div>
                    {d.last_seen && <div><b>GPS</b> {clock(d.last_seen)}</div>}
                    {d.job_count > 1 && (
                      <div style={{ marginTop: 6, paddingTop: 6, borderTop: '1px solid #ddd' }}>
                        <b>All {d.job_count} calls</b>
                        {d.jobs.map(j => (
                          <div key={j.sa_id} style={{ fontSize: 11 }}>
                            {j.sa_number} · {j.status} · {j.work_type}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </Popup>
            </Marker>
          ))}
        </MapContainer>

        {/* legend */}
        <div className="absolute bottom-4 left-4 z-[1000] bg-slate-900/90 backdrop-blur
                        border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-300 flex gap-4">
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-3 rounded-full bg-red-500 border border-white" /> Customer
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-3 rounded-full border border-white"
                  style={{ background: 'rgb(56,142,255)' }} /> Tow drop-off
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-4 h-2.5 rounded-sm bg-emerald-500 border border-white" /> Driver
          </span>
        </div>
      </div>
    </div>
  )
}
