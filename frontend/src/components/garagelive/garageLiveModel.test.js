import test from 'node:test'
import assert from 'node:assert/strict'
import { fmtMin, turn, filterGarages, initialGarage, dataAgeS, replayAlert, attentionCount } from './garageLiveModel.js'

test('minutes read as people say them', () => {
  assert.deepEqual([0, 52, 59.6, 60, 125, null].map(fmtMin), ['0 min', '52 min', '1 h 00 min', '1 h 00 min', '2 h 05 min', ''])
})

test('the shortest turn', () => {
  assert.equal(turn(350, 10), 20)
  assert.equal(turn(10, 350), -20)
  assert.equal(turn(0, 180), -180)
})

test('one attention number: everything but the info line', () => {
  const items = [{ severity: 'red' }, { severity: 'yellow' }, { severity: 'info' }]
  assert.equal(attentionCount(items), 2)
  assert.equal(attentionCount([{ severity: 'info' }]), 0)
  assert.equal(attentionCount(null), 0)
})

test('picker: every typed word must match, busiest first', () => {
  const g = [{ id: 'a', name: '100 - Western NY Fleet', sa_count_28d: 900 }, { id: 'b', name: '076DO - Transit Auto', city: 'Buffalo', sa_count_28d: 50 }, { id: 'c', name: '201 - Buffalo Western', sa_count_28d: 200 }]
  assert.deepEqual(filterGarages(g, 'western').map(x => x.id), ['a', 'c'])
  assert.deepEqual(filterGarages(g, 'BUFFALO west').map(x => x.id), ['c'])
  assert.deepEqual(filterGarages(g, '').map(x => x.id), ['a', 'c', 'b'])
  assert.deepEqual(filterGarages(g, 'zzz'), [])
})

test('which garage opens: the URL, else the remembered one, else the picker', () => {
  const g = [{ id: 'a' }, { id: 'b' }]
  assert.equal(initialGarage('b', 'a', g), 'b')
  assert.equal(initialGarage(null, 'a', g), 'a')
  assert.equal(initialGarage(null, 'gone', g), null)
  assert.equal(initialGarage(null, null, g), null)
  assert.equal(initialGarage(null, 'a', null), 'a')
})

test('"updated N s ago" counts from the data, not from the click', () => {
  const data = { now: '2026-10-09T18:00:00Z', watchlist_at: '2026-10-09T17:59:30Z' }
  assert.equal(dataAgeS(data, 1000, 1000), 30)
  assert.equal(dataAgeS(data, 1000, 21000), 50)
  assert.equal(dataAgeS(null, 0, 0), null)
})

test('the Replay button gets the fields the call map reads', () => {
  const a = replayAlert({ sa_id: 'x', number: 'SA-1', wo_number: '0520', work_type: 'Tow', priority: 'P1', city: 'Buffalo', lat: 43, lon: -78, flags: ['Call Not Closed'] }, { name: '100 - WNY' })
  assert.deepEqual([a.sa_id, a.sa_number, a.facility_name, a.latitude, a.flag], ['x', 'SA-1', '100 - WNY', 43, 'Call Not Closed'])
})
