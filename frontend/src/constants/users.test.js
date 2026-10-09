import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ROLES, roleOptions } from './users.js'

const adminPy = readFileSync(new URL('../../../backend/routers/admin.py', import.meta.url), 'utf8')
const serverRoles = adminPy.match(/valid_roles = \(([^)]*)\)/)[1].match(/"([^"]+)"/g).map(s => s.slice(1, -1))

test('every role offered is one the server accepts', () => {
  for (const r of ROLES) assert.ok(serverRoles.includes(r), r)
})

test('the ERS roles in use are offered', () => {
  for (const r of ['ers-manager', 'ers-supervisor', 'ers-member-relations', 'ers-director']) assert.ok(ROLES.includes(r), r)
})

test('legacy roles are not offered', () => {
  for (const r of ['manager', 'officer', 'supervisor', 'viewer']) assert.ok(!ROLES.includes(r), r)
})

test("opening a user keeps their current role selected, even a legacy one", () => {
  assert.equal(roleOptions('ers-manager')[0], 'superadmin')
  assert.ok(roleOptions('ers-manager').includes('ers-manager'))
  assert.deepEqual(roleOptions('viewer'), ['viewer', ...ROLES])
  assert.deepEqual(roleOptions(''), ROLES)
})
