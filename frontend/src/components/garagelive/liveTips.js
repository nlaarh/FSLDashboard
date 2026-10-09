/** The hover / click cards of Garage Live (HTML strings for Leaflet tooltips and popups). Styled by the call map's .cm-tip classes. */
import { esc } from '../replay/useLeafletMap'
import { phoneText } from '../callmap/callMapModel'
import { shortDriverName } from '../../utils/driverName'
import { fmtMin, minutesSince, DRIVER_STATUS } from './garageLiveModel'

const row = (label, value) => `<div><span class="m">${label}</span> ${value}</div>`

export function driverTip(d, nowS) {
  const st = DRIVER_STATUS[d.status] || DRIVER_STATUS.free
  const since = d.status_since ? ` for ${fmtMin(minutesSince(d.status_since, nowS))}` : ''
  const job = d.job ? `${esc(d.job.number)}${d.job.work_type ? ` (${esc(d.job.work_type)})` : ''}` : 'none'
  const queue = d.queue?.length
    ? `<div class="m" style="margin-top:4px">Backlog, in the order given</div><ol>${d.queue.map(q => `<li><b>${esc(q.number)}</b> ${esc(q.work_type || '')} <span class="m">${esc(q.label)}</span></li>`).join('')}</ol>`
    : '<div class="m" style="margin-top:4px">No other calls waiting for this driver.</div>'
  const gps = d.gps_age_min == null ? 'No GPS position' : d.gps_age_min < 1 ? 'GPS just now' : `GPS ${fmtMin(d.gps_age_min)} ago`
  return `<div class="cm-tip" style="min-width:230px"><b>${esc(shortDriverName(d.name))}</b>
    <div style="color:${st.colour};font-weight:700">${esc(st.label)}${since}</div>
    ${row('Current job', job)}
    <div class="m">${d.truck ? `Truck ${esc(d.truck)} · ` : ''}${d.phone ? esc(phoneText(d.phone)) : 'Phone not on file'}</div>
    <div class="m"${d.stale_position || (d.gps_age_min ?? 0) >= 30 ? ' style="color:#fca5a5"' : ''}>${gps}</div>${queue}</div>`
}

export function ticketTip(t, nowS, canReplay) {
  const created = Date.parse(t.created_at) / 1000
  const waited = fmtMin((nowS - created) / 60)
  const promised = t.promise_at ? Date.parse(t.promise_at) / 1000 : null
  let wait = `Member waiting ${waited}`
  if (!t.waiting) wait = `Driver arrived after ${fmtMin(((t.on_scene_at ? Date.parse(t.on_scene_at) / 1000 : nowS) - created) / 60)}`
  else if (promised != null) wait += nowS > promised ? ` · promised ${fmtMin((promised - created) / 60)}, <b style="color:#fca5a5">${fmtMin((nowS - promised) / 60)} late</b>` : ` · promised ${fmtMin((promised - created) / 60)}, ${fmtMin((promised - nowS) / 60)} left`
  const who = t.towbook ? 'Towbook driver (no GPS)' : t.driver_name ? esc(shortDriverName(t.driver_name)) : 'No driver yet'
  const since = t.status_since ? ` · ${fmtMin(minutesSince(t.status_since, nowS))} in this status` : ''
  const flags = t.flags?.length ? `<div style="margin-top:4px;color:#fcd34d">Watchlist: ${t.flags.map(esc).join(', ')}</div>` : ''
  const replay = canReplay ? `<div style="margin-top:6px"><button type="button" data-replay="${esc(t.sa_id)}" style="background:#2563eb;color:#fff;border:0;border-radius:8px;padding:5px 10px;font-weight:700;cursor:pointer">Replay</button></div>` : ''
  return `<div class="cm-tip" style="min-width:230px"><b>${esc(t.number)}</b> <span class="m">${esc(t.work_type)}${t.city ? ` · ${esc(t.city)}` : ''}</span>
    <div>${esc(t.status)}${since}</div><div>${wait}</div>${row('Driver', who)}${flags}${replay}</div>`
}
