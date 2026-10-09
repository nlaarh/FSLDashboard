import test from 'node:test'
import assert from 'node:assert/strict'
import { peerSentence, peerMoments } from './peerNotes.js'

const d = (name, miles, label) => ({ name, miles, label, held: 0, status: 'free' })

test('the toast names the closest qualified driver, miles and status', () => {
  const t = peerSentence({ kind: 'given', drivers: [d('Ann Lee', 2.1, 'free'), d('Bo Chan', 4, 'towing'), d('Cy Dow', 6, 'on a job')], not_qualified: 2 })
  assert.equal(t, '3 other qualified drivers were on shift: closest Ann Lee, 2.1 mi, free')
})

test('one driver reads in the singular and accept is labelled', () => {
  assert.equal(peerSentence({ kind: 'accepted', drivers: [d('Ann Lee', 1, 'driving to a job')] }),
    'At accept: 1 other qualified driver was on shift: closest Ann Lee, 1 mi, driving to a job')
})

test('nobody qualified says so and counts the unqualified', () => {
  assert.match(peerSentence({ kind: 'given', drivers: [], not_qualified: 3 }), /No other qualified driver.*\(3 on shift, not qualified\)/)
})

test('a Towbook garage or unbuilt day has no moments', () => {
  assert.deepEqual(peerMoments({ available: false, moments: [] }), [])
  assert.deepEqual(peerMoments(null), [])
})

test('moments get epoch seconds', () => {
  const [m] = peerMoments({ available: true, moments: [{ kind: 'given', at: '2026-10-07T17:40:52Z', drivers: [], not_qualified: 0 }] })
  assert.equal(m.at, Date.UTC(2026, 9, 7, 17, 40, 52) / 1000)
  assert.equal(m.clock, '1:40:52 PM')
})

import { queueFromLoad, queueFromPeer } from './peerNotes.js'

test('the assigned driver queue comes from driver_load; Towbook is never named', () => {
  const load = { driver: 'Zack Felix 4652D', channel: 'on_platform', given_at: '2026-10-07T17:28:37Z',
    ahead: [{ sa: 'SA-1', wo: '05195136', label: 'driving to it', lat: 42.9, lon: -78.8 }],
    after: [{ sa: 'SA-2', given_at: '2026-10-07T20:42:00Z', reached_at: '2026-10-07T20:50:00Z', lat: 42.9, lon: -78.8 }] }
  const q = queueFromLoad(load, { lat: 42.9, lon: -78.8 })
  assert.deepEqual(q.rows, [{ sa: 'SA-1', label: 'driving to it', given_at: null, miles: 0 }])
  assert.equal(q.next.sa, 'SA-2')
  assert.equal(queueFromLoad({ ...load, driver: 'Towbook Driver', channel: 'towbook' }, null).title, 'The Towbook driver')
  assert.equal(queueFromLoad(undefined, null), null)
})

test('another driver queue is passed through', () => {
  const q = queueFromPeer({ name: 'Ann Lee', queue: [{ sa: 'SA-1' }], next: null }, '2026-10-07T17:00:00Z')
  assert.equal(q.title, 'Ann Lee'); assert.equal(q.rows.length, 1)
})
