import { test } from 'node:test'
import assert from 'node:assert/strict'
import { setUnsaved, hasUnsaved, confirmLeave, isInternalNavClick } from './unsavedGuard.js'

test('leaving is free when nothing is unsaved, and asks when something is', () => {
  setUnsaved(0)
  assert.equal(confirmLeave(() => assert.fail('must not ask')), true)
  setUnsaved(3)
  assert.equal(hasUnsaved(), true)
  assert.equal(confirmLeave(() => false), false)
  assert.equal(confirmLeave(() => true), true)
  setUnsaved(0)
})

test('only plain clicks on in-app links count as leaving', () => {
  const a = href => ({ getAttribute: k => (k === 'href' ? href : null) })
  assert.equal(isInternalNavClick(a('/garages')), true)
  assert.equal(isInternalNavClick(a('https://example.com')), false)
  assert.equal(isInternalNavClick(a('//example.com')), false)
  assert.equal(isInternalNavClick(a('/garages'), { ctrlKey: true }), false)
  assert.equal(isInternalNavClick(null), false)
})
