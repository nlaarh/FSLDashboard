// Pure-maths tests for the replay engine, the road path and the work order model. Run: cd frontend && npm test (node's built-in runner).
import test from 'node:test'
import assert from 'node:assert/strict'
import { indexAt, nextEvent, prevEvent, advance, effectiveRate, fmtSkip } from './engineMath.js'
import { buildPath, buildLeg, mergeRuns } from './roadPath.js'
import { waitState, fmtWait, driverPhase, toastFor, towbookTrack } from '../woreplay/woReplayModel.js'

const near = (a, b, eps = 1e-3) => assert.ok(Math.abs(a - b) < eps, `${a} is not near ${b}`)

test('event lookups', () => {
  const ev = [10, 20, 30]
  assert.equal(indexAt(ev, 5), -1)
  assert.equal(indexAt(ev, 20), 1)
  assert.equal(indexAt(ev, 99), 2)
  assert.equal(nextEvent(ev, 20), 30)
  assert.equal(nextEvent(ev, 30), null)
  assert.equal(prevEvent(ev, 25), 20)
  assert.equal(prevEvent(ev, 20), 10)        // standing on an event: Prev goes to the one before
  assert.equal(prevEvent(ev, 5), null)
})

test('advance moves by speed x wall time and never passes the end', () => {
  const cfg = { speed: 60, events: [0, 100], end: 1000, busy: () => true }
  const r = advance(0, 0.5, cfg)
  assert.equal(r.t, 30)
  assert.equal(r.boosted, false)
  assert.equal(advance(990, 1, cfg).ended, true)
})

test('quiet stretches are skipped faster, but not while a truck moves', () => {
  const events = [0, 3600]
  assert.deepEqual(effectiveRate(0, 60, events, () => false, 7200), { rate: 300, boosted: true, gap: 3600 })
  assert.equal(effectiveRate(0, 60, events, () => true, 7200).boosted, false)
  assert.equal(effectiveRate(3500, 60, events, () => false, 7200).boosted, false)   // next event under 10 min away
  assert.equal(advance(0, 1, { speed: 10, events, busy: () => false, end: 7200 }).t, 50)
})

test('"pause at problems" stops exactly on the flagged time', () => {
  const r = advance(0, 1, { speed: 300, events: [], end: 1000, busy: () => true, stops: [100] })
  assert.equal(r.t, 100)
  assert.equal(r.stopped, true)
  assert.equal(advance(100, 1, { speed: 300, events: [], end: 1000, busy: () => true, stops: [100] }).stopped, false)   // resumes past it
})

test('skip chip wording', () => {
  assert.equal(fmtSkip(14 * 60), '14 min')
  assert.equal(fmtSkip(125 * 60), '2 h 5 min')
  assert.equal(fmtSkip(10), '1 min')
})

test('straight GPS interpolation, heading and gap handling', () => {
  const p = buildPath([[0, 0, 0], [100, 0, 0.02]])
  const mid = p.at(50)
  near(mid.lon, 0.01); near(mid.heading, 90, 0.5)
  assert.equal(p.at(-1), null)
  assert.equal(p.at(101), null)
  const gap = buildPath([[0, 0, 0], [3000, 0, 0.5]]).at(1500)   // 50 min between pings: held, not driven
  assert.equal(gap.lon, 0); assert.equal(gap.stale, 1500)
})

test('a truck follows the road between pings, at the speed the pings imply', () => {
  const track = [[0, 0, 0], [100, 0, 0.02]]
  const run = { t: [0, 100], i: [0, 3], c: [[0, 0], [0.01, 0], [0.01, 0.02], [0, 0.02]] }
  const p = buildPath(track, [run])
  const mid = p.at(50)                       // half of the road distance is the middle of the long leg
  near(mid.lat, 0.01); near(mid.lon, 0.01)
  const early = p.at(10)                     // still on the first leg (north), not cutting across
  near(early.lon, 0, 1e-9); assert.ok(early.lat > 0)
  assert.equal(p.verts[0][0], 0); assert.equal(p.verts.at(-1)[0], 100)
  assert.ok(p.ahead(50, 30).length >= 2 && p.behind(50, 30).length >= 2)
  assert.ok(p.behind(5, 300).length >= 2)    // a trail window that starts before the track must not break
})

test('pings inside a run are replaced by its road; pings outside stay', () => {
  const track = [[0, 0, 0], [50, 0, 0.01], [100, 0, 0.02], [200, 1, 1]]
  const run = { t: [0, 100], i: [0, 1], c: [[0, 0], [0, 0.02]] }
  const m = mergeRuns(track, [run])
  assert.deepEqual(m.map(v => v[0]), [0, 100, 200])
  assert.deepEqual(mergeRuns(track, [{ t: [0, 100], i: [1, 0], c: [[0, 0], [0, 1]] }]).length, 4)   // bad run (indexes go backwards) ignored
})

test('timed leg for the estimated Towbook vehicle', () => {
  const leg = buildLeg([[0, 0], [0, 0.01], [0, 0.03]], 1000, 1400)
  assert.equal(leg[0][0], 1000); assert.equal(leg.at(-1)[0], 1400)
  near(leg[1][0], 1000 + 400 / 3, 0.5)       // 1/3 of the distance = 1/3 of the time
  const steps = [
    { ts: '2026-09-24T12:00:00Z', from: 'sf', to: 'towbook', title: 'Offered' },
    { ts: '2026-09-24T12:05:00Z', from: 'towbook', to: 'sf', title: 'En Route' },
    { ts: '2026-09-24T12:25:00Z', from: 'towbook', to: 'sf', title: 'On Location' },
  ]
  const tr = towbookTrack(steps, { lat: 0, lon: 0 }, { lat: 0, lon: 0.03 }, { c: [[0, 0], [0, 0.01], [0, 0.03]] })
  assert.ok(tr.length >= 5); assert.equal(tr[1][0], Date.parse(steps[1].ts) / 1000)
})

test('waiting timer: ok, soon, late, done (stops at arrival)', () => {
  const created = 1000, promise = created + 3600, onScene = created + 3600 + 720
  assert.equal(waitState(created + 60, created, promise, onScene).state, 'ok')
  assert.equal(waitState(promise - 300, created, promise, onScene).state, 'soon')
  const late = waitState(promise + 600, created, promise, onScene)
  assert.equal(late.state, 'late'); assert.equal(late.over, 10)
  const done = waitState(onScene + 5000, created, promise, onScene)
  assert.equal(done.state, 'done'); assert.equal(done.secs, 4320); assert.equal(done.over, 12)
  assert.equal(waitState(created + 5, created, null, null).state, 'ok')
  assert.equal(fmtWait(754), '12:34'); assert.equal(fmtWait(3725), '1:02:05')
})

test('driver phase and toast lines come from the steps', () => {
  const steps = [
    { id: 'E1', ts: '2026-09-24T12:00:00Z', from: 'member', to: 'sf', title: 'Service appointment created in Salesforce', clock: '08:00:00' },
    { id: 'E4', ts: '2026-09-24T12:02:00Z', from: 'sf', to: 'driver', title: 'Assigned to Adam Lucas', names: { driver: 'Adam Lucas' }, clock: '08:02:00' },
    { id: 'E11', ts: '2026-09-24T12:10:00Z', from: 'driver', to: 'sf', title: 'En Route', clock: '08:10:00' },
    { id: 'P1', ts: '2026-09-24T12:35:00Z', from: 'sf', to: 'sf', title: 'Promise time reached', kind: 'mark', clock: '08:35:00' },
    { id: 'E12', ts: '2026-09-24T12:47:00Z', from: 'driver', to: 'sf', title: 'On Location', clock: '08:47:00', names: { driver: 'Adam Lucas' } },
  ]
  assert.equal(driverPhase(steps, 1), 'assigned')
  assert.equal(driverPhase(steps, 2), 'en_route')
  assert.equal(driverPhase(steps, 4), 'on_scene')
  assert.equal(toastFor(steps, 4).text, 'Adam Lucas on scene: 47 min after the call, 12 min past the promise')
  assert.equal(toastFor(steps, 1).text, 'Assigned to Adam Lucas')
  assert.equal(toastFor([...steps, { id: 'E7', ts: '2026-09-24T12:03:00Z', from: 'driver', to: 'sf', title: 'Driver accepted in the FSL app', names: { driver: 'Adam Lucas' }, clock: '08:03:00' }], 5).text, 'Adam Lucas accepted')
})
