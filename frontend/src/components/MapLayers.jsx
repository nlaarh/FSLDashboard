import { useMemo } from 'react'
import { Marker, Popup, Polyline, CircleMarker, GeoJSON } from 'react-leaflet'
import L from 'leaflet'
import { clsx } from 'clsx'
import { CheckCircle2, Truck, Navigation, AlertTriangle, ChevronUp, ChevronDown } from 'lucide-react'
import { truckIcon } from '../mapIcons'
import SALink from './SALink'

// ── Grid / Weather layers ────────────────────────────────────────────────────

const _WMO_EMOJI = {
  0:'☀️',1:'🌤️',2:'⛅',3:'☁️',45:'🌫️',48:'🌫️',
  51:'🌦️',53:'🌦️',55:'🌧️',61:'🌧️',63:'🌧️',65:'⛈️',
  66:'🌧️',67:'⛈️',71:'🌨️',73:'❄️',75:'❄️',77:'🌨️',
  80:'🌦️',81:'🌧️',82:'⛈️',85:'🌨️',86:'❄️',95:'⛈️',96:'⛈️',99:'⛈️',
}

export const gridStyle = (f) => ({
  color: f.properties.color || '#818cf8', weight: 1.5, opacity: 0.85,
  fillColor: f.properties.color || '#818cf8', fillOpacity: 0.1,
})

export function onEachGrid(feature, layer) {
  layer.bindTooltip(feature.properties.name, { permanent: false, direction: 'center', className: 'cc-tooltip' })
  layer.bindPopup(`<strong>${feature.properties.name}</strong><br/>${feature.properties.territory_name}`)
}

export function makeWeatherIcon(s) {
  const emoji = _WMO_EMOJI[s.weather_code] ?? '🌡️'
  return L.divIcon({
    className: '',
    iconSize: [72, 44], iconAnchor: [36, 44], popupAnchor: [0, -44],
    html: `<div style="background:#0f172a;border:1px solid #334155;border-radius:8px;
      padding:4px 8px;text-align:center;color:white;font-family:-apple-system,sans-serif;
      white-space:nowrap;box-shadow:0 4px 12px rgba(0,0,0,0.6)">
      <div style="font-size:13px;font-weight:700">${emoji} ${s.temp_f}°F</div>
      <div style="font-size:10px;color:#94a3b8;margin-top:1px">${s.name}</div>
    </div>`,
  })
}

// ── Driver status helper ────────────────────────────────────────────────────

export function getDriverStatus(d, closestDist) {
  if (d.is_closest) return { tag: 'CLOSEST', color: 'text-green-400', bg: 'bg-green-500/10 border-green-500/20', reason: 'Nearest eligible driver — should have been dispatched' }
  if (!d.has_gps) return { tag: 'NO GPS', color: 'text-red-400', bg: 'bg-red-500/10 border-red-500/20', reason: 'No GPS position — cannot determine distance' }
  if (!d.has_skills) return { tag: 'WRONG SKILL', color: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/20', reason: 'Missing required skills for this call type' }
  if (d.distance != null && closestDist != null) {
    const extra = (d.distance - closestDist).toFixed(1)
    return { tag: `+${extra} mi`, color: 'text-slate-400', bg: 'bg-slate-500/10 border-slate-600/20', reason: `${extra} miles farther than closest eligible driver` }
  }
  return { tag: 'ELIGIBLE', color: 'text-slate-400', bg: 'bg-slate-500/10 border-slate-600/20', reason: 'Eligible but not closest' }
}

// ── Narrative Block ─────────────────────────────────────────────────────────

export function NarrativeBlock({ selected, tl, assignSteps, hasSteps }) {
  const lines = []

  // 1. Call received
  lines.push(`Call received at ${tl.created || '?'} for a ${selected.work_type} at ${selected.address || 'unknown location'}.`)

  // 2. Required skills
  const skills = selected.required_skills || []
  if (skills.length > 0) {
    lines.push(`This call requires the following skills: ${skills.join(', ')}.`)
  }

  // 3. Walk each assignment step
  if (hasSteps && assignSteps.length > 0) {
    assignSteps.forEach((step, i) => {
      const assigned = step.step_drivers?.find(d => d.is_assigned)
      const closest  = step.step_drivers?.find(d => d.is_closest)
      const onTrack  = step.step_drivers?.length || 0
      const wasClosest = assigned && closest && assigned.driver_id === closest.driver_id
      const byName = step.by_name
      const isHuman = step.is_human
      const actor = isHuman ? `Dispatcher ${byName}` : 'The system'
      const verb0 = isHuman ? 'manually assigned' : 'automatically assigned'
      const verbR = isHuman ? `Dispatcher ${byName} manually reassigned` : 'The system reassigned'

      if (i === 0) {
        if (assigned?.no_gps) {
          lines.push(`${actor} ${verb0} ${step.driver} at ${step.time} — no GPS location at dispatch time. ${onTrack} drivers were on Track.`)
        } else if (wasClosest) {
          lines.push(`${actor} ${verb0} ${step.driver} at ${step.time} — the closest eligible driver on Track at ${assigned.distance.toFixed(1)} mi. ${onTrack} drivers were on Track.`)
        } else if (assigned && closest) {
          lines.push(`${actor} ${verb0} ${step.driver} at ${step.time} (${assigned.distance.toFixed(1)} mi). However, ${closest.name} was the closest eligible driver at only ${closest.distance.toFixed(1)} mi. ${onTrack} drivers were on Track.`)
        } else {
          lines.push(`${actor} ${verb0} ${step.driver} at ${step.time}. ${onTrack} drivers were on Track.`)
        }
      } else {
        const prev = assignSteps[i - 1].driver
        const reason = step.reason ? ` Reason: ${step.reason}.` : ''
        if (assigned?.no_gps) {
          lines.push(`${verbR} from ${prev} to ${step.driver} at ${step.time} — no GPS location at dispatch time.${reason}`)
        } else if (wasClosest) {
          lines.push(`${verbR} from ${prev} to ${step.driver} at ${step.time} — closest available at ${assigned?.distance?.toFixed(1) || '?'} mi.${reason}`)
        } else if (assigned && closest) {
          lines.push(`${verbR} from ${prev} to ${step.driver} at ${step.time} (${assigned.distance.toFixed(1)} mi). Closest eligible was ${closest.name} at ${closest.distance.toFixed(1)} mi — not selected.${reason}`)
        } else {
          lines.push(`${verbR} from ${prev} to ${step.driver} at ${step.time}.${reason}`)
        }
      }
    })
  } else {
    const mode = tl.auto_assign ? 'automatically' : 'manually'
    const truck = selected.truck_id ? ` to Truck ${selected.truck_id.split('-').pop()}` : ''
    lines.push(`Dispatched ${mode}${truck} at ${tl.scheduled || '?'}.`)
    if (selected.closest_driver && selected.closest_driver !== '?') {
      const picked = selected.actual_driver === selected.closest_driver
      if (picked) {
        lines.push(`The closest eligible driver was selected: ${selected.closest_driver} at ${selected.closest_distance?.toFixed(1) || '?'} mi.`)
      } else {
        lines.push(`Closest eligible driver was ${selected.closest_driver} at ${selected.closest_distance?.toFixed(1) || '?'} mi — but a different driver was dispatched.`)
        if (tl.dispatched_distance != null) {
          lines.push(`The dispatched truck was ${tl.dispatched_distance.toFixed(1)} mi from the customer at dispatch time.`)
        }
      }
    }
    const noGps = (selected.drivers || []).filter(d => !d.has_gps).length
    const noSkill = (selected.drivers || []).filter(d => d.has_gps && !d.has_skills).length
    if (selected.total_drivers > 0) {
      lines.push(`Of ${selected.total_drivers} territory drivers: ${selected.eligible_count} eligible, ${noGps} without GPS, ${noSkill} missing required skills.`)
    }
  }

  // 4. PTA
  if (tl.pta_promised) {
    const vs45 = tl.pta_promised > 45
      ? `${Math.round(tl.pta_promised - 45)} min over the 45-min SLA target`
      : 'within the 45-min SLA target'
    lines.push(`Member was promised a ${tl.pta_promised}-minute ETA (${vs45}).`)
  }

  // 5. Arrival / response time
  if (tl.response_min) {
    if (tl.sla_met) {
      lines.push(`Driver arrived on location at ${tl.on_location || '?'} — ${tl.response_min}-minute response time. SLA met \u2713`)
    } else {
      lines.push(`Driver arrived on location at ${tl.on_location || '?'} — ${tl.response_min}-minute response time, ${tl.response_min - 45} minutes over the 45-min SLA target. \u2717`)
    }
  } else if (!tl.on_location) {
    lines.push('No on-location time recorded — driver may not have updated status, or SA was canceled.')
  }

  // 6. Completion
  if (tl.service_min && selected.status === 'Completed') {
    lines.push(`Service completed at ${tl.completed || '?'} after ${tl.service_min} min on-site. Total call time: ${tl.total_min || '?'} min.`)
  }

  // 7. Cancellation
  if (tl.cancel_reason) {
    lines.push(`Call was canceled: ${tl.cancel_reason}.`)
  }

  return (
    <div className="space-y-1.5 text-sm text-slate-300 leading-relaxed">
      {lines.map((line, i) => (
        <p key={i} className="flex gap-2">
          <span className="text-slate-600 shrink-0">{i + 1}.</span>
          <span>{line}</span>
        </p>
      ))}
    </div>
  )
}
