import test from 'node:test'
import assert from 'node:assert/strict'
import { latenessLevel, buildEvents, pinState, shortPerson, phoneText, agoText, asGarageLive } from './callMapModel.js'

test('pin colour by minutes late', () => {
  const lv = [null, -5, 0, 1, 30, 31, 89, 90, 400].map(latenessLevel)
  assert.deepEqual(lv, ['ok', 'ok', 'ok', 'yellow', 'yellow', 'orange', 'orange', 'red', 'red'])
})

const data = {
  sa: { created_at: '2026-10-09T17:00:00Z', promise_at: '2026-10-09T17:45:00Z' },
  steps: [{ id: 'a', ts: '2026-10-09T17:00:10Z', kind: 'member', title: 'Call came in', detail: '' },
    { id: 'b', ts: '2026-10-09T17:20:00Z', kind: 'sms', title: 'Text sent', detail: 'hello' }],
  extras: { calls: [{ id: 'c1', ts: '2026-10-09T17:30:00Z', kind: 'callback', line: 'ERS', duration_s: 60 }], inbound_texts: [] },
  cases: { events: [{ id: 'case:1:created', case_id: '1', ts: '2026-10-09T17:50:00Z', type: 'case_created', title: 'Case 1 opened', detail: '', by: 'IT' }] },
}

test('events merge steps, contact marks and cases in time order, a text once', () => {
  const ev = buildEvents(data)
  assert.deepEqual(ev.map(e => e.cat), ['step', 'contact', 'contact', 'case'])
  assert.equal(ev.filter(e => e.type === 'text_out').length, 1)
  assert.deepEqual(buildEvents(null), [])
})

test('pin state: wait, minutes late and level; stops when the driver is on scene', () => {
  const t = Date.parse('2026-10-09T18:30:00Z') / 1000
  const p = pinState(data, t, null)
  assert.equal(p.lateMin, 45); assert.equal(p.level, 'orange'); assert.equal(p.state, 'late')
  const done = pinState(data, t, Date.parse('2026-10-09T17:40:00Z') / 1000)
  assert.equal(done.level, 'ok'); assert.equal(done.state, 'done')
  assert.equal(pinState(data, Date.parse('2026-10-09T17:10:00Z') / 1000, null).level, 'ok')
})

test('small formatters', () => {
  assert.equal(shortPerson('Jane Dee'), 'Jane D.')
  assert.equal(phoneText('5855550199'), '(585) 555-0199')
  assert.equal(agoText(4), '4 min ago'); assert.equal(agoText(0), 'just now')
})

test('the call map answer becomes the Garage Live map data: one ticket, the assigned driver first, the qualified drivers after', () => {
  const d = (id, status, held, lat) => ({ id, name: `Driver ${id}`, status, label: status, held, lat, lon: -78.8, gps_at: '2026-10-09T17:55:00Z', truck: `T${id}`, skills: ['Tow'], phone: null,
    queue: held ? [{ sa: 'SA-9', work_type: 'Battery', label: 'not started' }] : [] })
  const call = { now: '2026-10-09T18:00:00Z', sa: { id: 'SA1', number: 'SA-1', status: 'Dispatched', work_type: 'Tow', lat: 42.9, lon: -78.8, created_at: '2026-10-09T17:00:00Z', promise_at: '2026-10-09T17:45:00Z', towbook: false },
    garage: { name: '100 - Fleet', lat: 42.8, lon: -78.7 }, driver: d('A', 'driving', 0, 42.85), peers: [d('B', 'free', 0, 42.95), d('C', 'waiting', 1, null)],
    steps: [{ id: 'x', ts: '2026-10-09T17:50:00Z', kind: 'driver', title: 'Status: On Location', detail: '', names: {} }] }
  const g = asGarageLive(call)
  assert.deepEqual(g.drivers.map(x => x.id), ['A', 'B', 'C'])
  assert.equal(g.drivers[0].job.number, 'SA-1'); assert.equal(g.drivers[1].job, null)
  assert.equal(g.drivers[0].gps_age_min, 5); assert.equal(g.drivers[2].stale_position, true)
  assert.deepEqual(g.drivers[2].queue, [{ sa_id: 'SA-9', number: 'SA-9', work_type: 'Battery', label: 'not started' }])
  assert.equal(g.tickets.length, 1); assert.equal(g.tickets[0].driver_name, 'Driver A'); assert.equal(g.garage.name, '100 - Fleet')
  assert.equal(asGarageLive({ ...call, driver: null }).drivers.length, 2)
})
