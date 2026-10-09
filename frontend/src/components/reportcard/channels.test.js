import test from 'node:test'
import assert from 'node:assert/strict'
import { channelOf, channelSplit } from './channels.js'

test('maps Source__c like the work-order replay', () => {
  assert.equal(channelOf('IVR').key, 'replicant')
  assert.equal(channelOf('intake').key, 'mcc')
  assert.equal(channelOf('Call Mover').key, 'partner')
  assert.equal(channelOf('RAP').key, 'partner')
  assert.equal(channelOf(null).key, 'unknown')
  assert.equal(channelOf('Something new').key, 'unknown')
})

test('counts distinct work orders, skips drop-offs, gives percentages', () => {
  const calls = [{ id: 'a' }, { id: 'b' }, { id: 'c' }, { id: 'd', is_drop_off: true }, { id: 'e' }]
  const flags = { a: { wo_id: 'W1', source: 'DRR' }, b: { wo_id: 'W1', source: 'DRR' }, c: { wo_id: 'W2', source: 'IVR' }, d: { wo_id: 'W3', source: 'DRR' } }
  const r = channelSplit(calls, flags)
  assert.equal(r.total, 2)
  assert.deepEqual(r.rows.map(x => [x.key, x.n, x.pct]), [['drr', 1, 50], ['replicant', 1, 50]])
})
