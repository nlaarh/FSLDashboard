import { Clock, Building2, Truck, UserCog, Phone, MessageSquare, Briefcase, ExternalLink } from 'lucide-react'
import { clsx } from 'clsx'
import { LATE_COLOUR, shortPerson, phoneText, telHref, minutesSince, agoText } from './callMapModel'
import { shortDriverName } from '../../utils/driverName'

const SF_BASE = 'https://aaawcny.lightning.force.com'
const Card = ({ icon: Icon, title, children, accent }) => (
  <section className="rounded-xl border border-slate-700/70 bg-slate-900/70 p-3 min-w-0" style={accent ? { borderColor: accent } : undefined}>
    <h2 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400 flex items-center gap-1.5 mb-1.5"><Icon className="w-3.5 h-3.5" />{title}</h2>
    {children}
  </section>
)
const CallBtn = ({ phone }) => (
  <a href={telHref(phone)} className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold px-2.5 py-1 shrink-0"><Phone className="w-3.5 h-3.5" />Call</a>
)
const PhoneLink = ({ phone }) => <a href={telHref(phone)} className="text-sky-300 hover:text-sky-200 tabular-nums">{phoneText(phone)}</a>

/** The four cards under the top bar. pin = pinState at the time on the slider; nowS = epoch seconds of "now" (for "x min ago"). */
export default function QuickInfo({ data, pin, nowS }) {
  const { sa, garage, driver, working, contact, cases } = data
  const lateColour = LATE_COLOUR[pin.level]
  const waitMin = Math.floor(pin.secs / 60)
  const promiseTxt = sa.promise_at ? new Date(sa.promise_at).toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit' }) : null
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3 px-4 pt-3">
      <Card icon={Clock} title="Member waiting" accent={pin.level !== 'ok' ? lateColour : undefined}>
        <div className="text-2xl font-bold tabular-nums" style={{ color: lateColour }}>{waitMin} min</div>
        <div className="text-xs text-slate-300">
          {promiseTxt ? <>Promised {promiseTxt} ET · </> : <>No promise time · </>}
          {pin.state === 'done' ? 'driver arrived' : pin.lateMin ? <b style={{ color: lateColour }}>{pin.lateMin} min late</b> : promiseTxt ? 'on time' : ''}
        </div>
      </Card>

      <Card icon={Building2} title="Garage">
        <div className="text-sm font-semibold text-white truncate">{(garage.name || 'No garage yet').replace(/^\w+\s+-\s+/, '')}</div>
        <div className="flex items-center gap-2 text-xs mt-0.5">
          {garage.phone ? <><PhoneLink phone={garage.phone} /><CallBtn phone={garage.phone} /></> : <span className="text-slate-500">No main phone on file</span>}
        </div>
        {garage.contacts.map(c => (
          <div key={`${c.name}${c.phone}`} className="flex items-center gap-2 text-xs mt-1 text-slate-300">
            <span className="truncate flex-1">{c.name}{c.title ? <span className="text-slate-500"> · {c.title}</span> : null}</span><PhoneLink phone={c.phone} />
          </div>
        ))}
      </Card>

      <Card icon={Truck} title="Assigned driver">
        {sa.towbook ? <div className="text-sm text-amber-300">Towbook garage: no driver GPS, so the driver is not shown.</div>
          : driver ? (
            <>
              <div className="text-sm font-semibold text-white truncate">{shortDriverName(driver.name)}{driver.truck ? <span className="text-slate-400 font-normal"> · {driver.truck}</span> : null}</div>
              <div className="text-xs text-slate-300">{driver.label}{driver.miles != null ? ` · ${driver.miles} mi from the member` : ' · no recent position'}{driver.queue_known && driver.held ? ` · ${driver.held} job${driver.held === 1 ? '' : 's'} ahead` : ''}</div>
              <div className="flex items-center gap-2 text-xs mt-1">{driver.phone ? <><PhoneLink phone={driver.phone} /><CallBtn phone={driver.phone} /></> : <span className="text-slate-500">Phone not on file</span>}</div>
            </>
          ) : <div className="text-sm text-slate-400">No driver has been assigned yet.</div>}
      </Card>

      <Card icon={UserCog} title="Who is working it">
        {working ? <div className="text-sm text-white">{working.kind === 'garage' ? 'Garage dispatcher:' : 'Being worked by'} <b>{working.kind === 'garage' ? working.name : shortPerson(working.name)}</b> <span className="text-slate-400">· last action {agoText(minutesSince(working.at, nowS))}</span></div>
          : <div className="text-sm text-slate-400">No dispatcher has touched it yet</div>}
        <div className="text-xs text-slate-300 mt-1 flex items-center gap-1.5 flex-wrap">
          {contact.available ? (
            <>
              <Phone className="w-3.5 h-3.5 text-slate-500" />called {contact.calls}×
              <MessageSquare className="w-3.5 h-3.5 text-slate-500" />texted {contact.texts_in}× <span className="text-slate-500">(AAA texted {contact.texts_out}×)</span>
              <span className="text-slate-400">· {contact.last_member_contact ? `last contact ${agoText(minutesSince(contact.last_member_contact, nowS))}` : 'no contact yet'}</span>
            </>
          ) : <span className="text-slate-500">Member calls and texts are not available</span>}
        </div>
        <div className="mt-1.5 flex items-center gap-1.5 flex-wrap text-xs">
          <Briefcase className="w-3.5 h-3.5 text-slate-500" />
          {cases.count === 0 ? <span className="text-slate-500">No cases</span> : (
            <>
              <span className={clsx('font-semibold', cases.open ? 'text-rose-300' : 'text-slate-300')}>{cases.open ? `${cases.open} open case${cases.open === 1 ? '' : 's'}` : `${cases.count} closed case${cases.count === 1 ? '' : 's'}`}</span>
              {cases.items.filter(c => (cases.open ? !c.is_closed : true)).slice(0, 3).map(c => (
                <a key={c.id} href={`${SF_BASE}/lightning/r/Case/${c.id}/view`} target="_blank" rel="noopener noreferrer" className="text-sky-300 hover:text-sky-200 inline-flex items-center gap-0.5" title={c.subject}>{c.number}<ExternalLink className="w-2.5 h-2.5" /></a>
              ))}
            </>
          )}
        </div>
      </Card>
    </div>
  )
}
