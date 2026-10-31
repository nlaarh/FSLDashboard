// Driver Replay pure helpers. Run: cd frontend && npm test
import test from 'node:test'
import assert from 'node:assert/strict'
import { HOP_M, hopsUntil, facing, drivePace, stopWallS, DAY_WALL_S, QUIET_WALL_S, driverRows, sortDrivers, splitAtGaps, fmtDur, bucketTotals, replayWindow, stopState, doingAt, daySegments, stopEvents, anyDriving, kindOf, glyph, DRIVER_COLOURS } from './driverModel.js'

const T = 1_759_000_000
const D = {
  shift: [[T + 600, T + 30000]],
  track: [[T, 0, 0], [T + 1000, 0, 0], [T + 5000, 1, 1], [T + 9000, 1, 1], [T + 20000, 2, 2]],
  stops: [{ t0: T, t1: T + 1200, kind: 'garage' }, { t0: T + 5000, t1: T + 6500, kind: 'coffee' }],
  gaps: [[T + 9000, T + 12000]],
  summary: { driving_s: 100, no_signal_s: 50, stopped_s: { garage: 1200, coffee: 1500, call: 60, unknown: 5 } },
}

test('fmtDur', () => {
  assert.equal(fmtDur(20), 'under 1 min')
  assert.equal(fmtDur(25 * 60), '25 min')
  assert.equal(fmtDur(65 * 60), '1 h 5 min')
  assert.equal(fmtDur(120 * 60), '2 h')
})

test('the day splits into the buckets a supervisor reads', () => {
  assert.deepEqual(bucketTotals(D.summary), { driving: 100, calls: 60, places: 1500, base: 1200, unknown: 5, no_signal: 50, off: 0 })
  assert.deepEqual(bucketTotals(null), { driving: 0, calls: 0, places: 0, base: 0, unknown: 0, no_signal: 0, off: 0 })
})

test('the clock opens at the shift start, the slider covers GPS and shift with 15 min each side, clipped to the day', () => {
  assert.deepEqual(replayWindow([D], T - 99999, T + 99999), { start: T - 900, end: T + 30900, initial: T + 600 })
  assert.deepEqual(replayWindow([D], T + 100, T + 25000), { start: T + 100, end: T + 25000, initial: T + 600 })
  const noShift = { ...D, shift: [] }
  assert.equal(replayWindow([noShift], T - 99999, T + 99999).initial, T)         // no shift: at the first ping
  assert.deepEqual(replayWindow([], 5, 9), { start: 5, end: 9, initial: 5 })
})

test('stop state and what the driver is doing', () => {
  assert.equal(stopState(D.stops[1], T + 4999), 'hidden')
  assert.equal(stopState(D.stops[1], T + 5000), 'live')
  assert.equal(stopState(D.stops[1], T + 6500), 'done')
  assert.equal(doingAt(D, T - 1).state, 'before')
  assert.equal(doingAt(D, T + 100).stop.kind, 'garage')
  assert.equal(doingAt(D, T + 3000).state, 'driving')
  assert.equal(doingAt(D, T + 10000).state, 'no_signal')
  assert.equal(doingAt(D, T + 20001).state, 'after')
})

test('day segments cover first to last ping with no overlap', () => {
  const seg = daySegments(D)
  assert.deepEqual(seg.map(s => s.kind), ['garage', 'driving', 'coffee', 'driving', 'no_signal', 'driving'])
  assert.equal(seg[0].t0, T)
  assert.equal(seg[seg.length - 1].t1, T + 20000)
  for (let i = 1; i < seg.length; i++) assert.equal(seg[i].t0, seg[i - 1].t1)
})

test('events, busy, kinds and colours', () => {
  assert.deepEqual(stopEvents([D, D]), [T, T + 1200, T + 5000, T + 6500])
  const busy = anyDriving([D])
  assert.equal(busy(T + 3000), true)
  assert.equal(busy(T + 5500), false)
  assert.equal(kindOf('nope').name, 'Unlisted stop')
  assert.match(glyph('coffee'), /^<svg/)
  assert.equal(DRIVER_COLOURS[0], '#fbbf24')                      // one driver = gold
})

test('the covered line breaks at a GPS silence instead of inventing a straight line', () => {
  const tr = [[T, 0, 0], [T + 60, 0, 1], [T + 60 + 1201, 5, 5], [T + 1400, 5, 6]]
  assert.deepEqual(splitAtGaps(tr, Infinity), [[[0, 0], [0, 1]], [[5, 5], [5, 6]]])
  assert.deepEqual(splitAtGaps(tr, T + 30, { lat: 0, lon: 0.5 }), [[[0, 0], [0, 0.5]]])
  assert.deepEqual(splitAtGaps(tr, T - 1), [])
})

test('the driver list sorts by name both ways, by most calls and by earliest shift', () => {
  const rows = [{ name: 'zoe Park', calls: 2, start: 300 }, { name: 'Adam Lee', calls: 5, start: null }, { name: 'Mia Stone', calls: 5, start: 100 }]
  const names = s => sortDrivers(rows, s).map(r => r.name)
  assert.deepEqual(names('name'), ['Adam Lee', 'Mia Stone', 'zoe Park'])       // ignores upper/lower case
  assert.deepEqual(names('name_desc'), ['zoe Park', 'Mia Stone', 'Adam Lee'])
  assert.deepEqual(names('calls'), ['Adam Lee', 'Mia Stone', 'zoe Park'])      // ties by name
  assert.deepEqual(names('start'), ['Mia Stone', 'zoe Park', 'Adam Lee'])      // no shift last
  assert.equal(rows[0].name, 'zoe Park')                                        // input untouched
})

test('driver rows: on-platform drivers with GPS only, their calls for this garage and first shift that day', () => {
  const day0 = Date.parse('2026-09-09T04:00:00Z') / 1000
  const replay = { day_start: day0, drivers: [{ id: 'A', name: 'Ann', mode: 'gps' }, { id: 'B', name: 'Bo', mode: 'gps' },
    { id: 'C', name: 'Cy', mode: 'estimated' }, { id: 'tb:1', name: 'Towbook Driver 1', mode: 'estimated', towbook: true }] }
  const day = {
    sas: [{ final_driver_id: 'A' }, { final_driver_id: 'A' }, { final_driver_id: 'A', is_drop_off: true }, { final_driver_id: 'C' }],
    drivers: [{ id: 'A', on_shift: [['2026-09-09T12:51:00Z', '2026-09-09T21:38:00Z']] }, { id: 'B', on_shift: [['2026-09-09T04:00:00Z', '2026-09-09T09:00:00Z']] }],
  }
  assert.deepEqual(driverRows(replay, day), [
    { id: 'A', name: 'Ann', calls: 2, start: Date.parse('2026-09-09T12:51:00Z') / 1000, overnight: false },
    { id: 'B', name: 'Bo', calls: 0, start: day0, overnight: true },
  ])
})

test('pace: a whole day in about 3 minutes, each stop 2 to 5 seconds on screen, speed buttons scale it', () => {
  const pace = drivePace([D], T - 900, T + 30000)
  const driveS = daySegments(D).filter(s => s.kind === 'driving').reduce((a, s) => a + s.t1 - s.t0, 0)
  const quiet = stopWallS(D.stops[0]) + stopWallS(D.stops[1]) + 3 * QUIET_WALL_S
  assert.equal(pace.base, Math.min(400, Math.max(20, driveS / (DAY_WALL_S - quiet))))
  assert.deepEqual(pace(T + 3000, 1), { rate: pace.base, boosted: false, gap: 0 })            // driving
  assert.equal(pace(T + 3000, 2).rate, pace.base * 2)                                           // 2x = twice as fast
  const coffee = pace(T + 5500, 1)                                                              // the 25-min coffee stop
  assert.equal(coffee.rate, 1500 / stopWallS(D.stops[1]))
  assert.equal(pace(T + 5500, 0.5).rate, 1500 / (stopWallS(D.stops[1]) * 2))                  // half speed = on screen twice as long
  assert.ok(stopWallS({ t0: 0, t1: 60 }) < 2.1)                                                // short stop: about 2 s
  assert.equal(stopWallS({ t0: 0, t1: 45 * 60 }), 5)                                           // 45 min: 5 s
  assert.equal(pace(T + 10000, 1).rate, 3000 / QUIET_WALL_S)                                   // no signal: skipped quickly
})

test('a side-view truck faces the way it drives, and keeps its side on a north-south road', () => {
  assert.equal(facing('left', 90), 'right')
  assert.equal(facing('right', 270), 'left')
  assert.equal(facing('left', 5), 'left')
  assert.equal(facing('right', 180), 'right')
  assert.equal(facing('right', null), 'right')
})

test('far-apart GPS points are a hop: the solid trail breaks there and the hop is listed', () => {
  const tr = [[T, 43, -77.5], [T + 60, 43, -77.499], [T + 180, 43, -77.44], [T + 240, 43, -77.439]]   // ~80 m, then ~4.8 km, then ~80 m
  assert.equal(splitAtGaps(tr, Infinity, null, HOP_M).length, 2)
  assert.equal(splitAtGaps(tr, Infinity).length, 1)                                                     // default: no hop rule
  assert.deepEqual(hopsUntil(tr, Infinity), [[[43, -77.499], [43, -77.44]]])
  assert.deepEqual(hopsUntil(tr, T + 100), [])
})
