import { test } from 'node:test'
import assert from 'node:assert/strict'
import { can, homePath } from './access.js'

test('null features (not loaded) allow everything; a loaded list is strict', () => {
  assert.equal(can(null, 'page.accounting'), true)
  assert.equal(can(['page.help'], 'page.accounting'), false)
  assert.equal(can(['page.accounting'], 'page.accounting'), true)
})

test('home is the first menu page the user may open', () => {
  assert.equal(homePath(null), '/')
  assert.equal(homePath(['page.command_center']), '/')
  assert.equal(homePath(['page.garages', 'page.help']), '/garages')
  assert.equal(homePath(['page.help']), '/help')
  assert.equal(homePath([]), null)
})
