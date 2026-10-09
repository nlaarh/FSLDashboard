import test from 'node:test'
import assert from 'node:assert/strict'
import { moveKind, legPath, stitch, createRoadFetcher } from './glideRoute.js'

test('what a move needs', () => {
  assert.equal(moveKind([43, -78], [43.00005, -78]), 'still')
  assert.equal(moveKind([43, -78], [43.0004, -78]), 'line')
  assert.equal(moveKind([43, -78], [43.01, -78]), 'road')
  assert.equal(moveKind([43, -78], [43.3, -78]), 'line')          // ~20 miles: a jump
})

test('a leg drives the road at constant speed and turns with it', () => {
  const road = stitch([[43.0, -78.0], [43.0, -77.99]], [43.0, -78.0], [43.01, -77.99])   // east, then north
  const p = legPath(road, 100, 160)
  assert.deepEqual([p.at(99), p.at(161)], [null, null])
  const a = p.at(100), z = p.at(160)
  assert.ok(Math.abs(a.lat - 43.0) < 1e-9 && Math.abs(z.lat - 43.01) < 1e-9)
  assert.equal(Math.round(p.at(5 + 100).heading), 90)
  assert.equal(Math.round(p.at(155).heading), 0)
  const half = p.at(130)
  assert.ok(half.lon > -78.0 && half.lon < -77.99 + 1e-9)
  assert.ok(p.behind(150, 30).length >= 2)
})

test('road lookups: cached, deduplicated, at most 3 at a time, failures become null', async () => {
  let live = 0, peak = 0, calls = 0
  const f = createRoadFetcher(async (a, b) => { calls++; live++; peak = Math.max(peak, live); await new Promise(r => setTimeout(r, 10)); live--; if (a[0] === 9) throw new Error('osrm down'); return [a, b] })
  const moves = [0, 1, 2, 3, 4, 5].map(i => [[43 + i / 100, -78], [43 + i / 100 + 0.01, -78]])
  const res = await Promise.all([...moves.map(([a, b]) => f.get(a, b)), f.get(...moves[0])])
  assert.equal(res.length, 7)
  assert.equal(calls, 6)
  assert.ok(peak <= 3)
  await f.get(...moves[1])
  assert.equal(calls, 6)
  assert.equal(await f.get([9, -78], [9.01, -78]), null)
})
