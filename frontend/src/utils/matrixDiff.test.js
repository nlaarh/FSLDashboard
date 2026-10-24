import { test } from 'node:test'
import assert from 'node:assert/strict'
import { diffFeatures, toggleUserRole, blockedReason, makePrimary, diffUsers } from './matrixDiff.js'

const EX = ['contractor', 'ers-supervisor', 'ers-member-relations']

test('only features whose roles changed are sent (order does not matter)', () => {
  const original = { a: ['admin', 'superadmin'], b: ['superadmin'] }
  assert.deepEqual(diffFeatures(original, { a: ['superadmin', 'admin'], b: ['superadmin', 'finance'] }), { b: ['superadmin', 'finance'] })
  assert.deepEqual(diffFeatures(original, original), {})
})

test('ticking adds an extra role, unticking removes it, the primary stays', () => {
  let u = { primary: 'finance', extra: [] }
  u = toggleUserRole(u, 'ers-director', EX)
  assert.deepEqual(u, { primary: 'finance', extra: ['ers-director'] })
  assert.deepEqual(toggleUserRole(u, 'finance', EX), u)
  assert.deepEqual(toggleUserRole(u, 'ers-director', EX), { primary: 'finance', extra: [] })
})

test('restricted roles are never added, never combined and never replaced', () => {
  const finance = { primary: 'finance', extra: [] }
  const contractor = { primary: 'contractor', extra: [] }
  assert.match(blockedReason(finance, 'contractor', EX), /restricted/)
  assert.match(blockedReason(finance, 'ers-supervisor', EX), /restricted/)
  assert.match(blockedReason(contractor, 'manager', EX), /Users & Sessions/)
  assert.equal(blockedReason(contractor, 'contractor', EX), '')
  assert.equal(toggleUserRole(contractor, 'manager', EX), contractor)     // the QA bug: contractor became manager
  assert.equal(toggleUserRole(finance, 'contractor', EX), finance)
  assert.equal(setUserRole(contractor, 'viewer', true, EX), contractor)
})

test('the star makes a ticked role primary and keeps the old one', () => {
  assert.deepEqual(makePrimary({ primary: 'finance', extra: ['admin'] }, 'admin'), { primary: 'admin', extra: ['finance'] })
  assert.deepEqual(makePrimary({ primary: 'finance', extra: [] }, 'admin'), { primary: 'finance', extra: [] })
})

test('only users whose roles changed are sent', () => {
  const original = { a: { primary: 'finance', extra: [] }, b: { primary: 'admin', extra: ['executive'] } }
  const edited = { a: { primary: 'finance', extra: [] }, b: { primary: 'executive', extra: ['admin'] } }
  assert.deepEqual(diffUsers(original, edited), [{ username: 'b', primary: 'executive', extra: ['admin'] }])
})

import { setUserRole } from './matrixDiff.js'

test('setting a role is idempotent and respects the restrictive-role rule', () => {
  const u = { primary: 'finance', extra: ['admin'] }
  assert.equal(setUserRole(u, 'admin', true, EX), u)
  assert.deepEqual(setUserRole(u, 'admin', false, EX), { primary: 'finance', extra: [] })
  assert.equal(setUserRole(u, 'contractor', true, EX), u)       // blocked
  assert.equal(setUserRole(u, 'finance', false, EX), u)         // the primary role cannot be unticked
})
