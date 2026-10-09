import { test, beforeEach } from 'node:test'
import assert from 'node:assert/strict'
import { pollWhileVisible } from './pollWhileVisible.js'

// Minimal document stand-in: a hidden flag plus the visibilitychange listeners.
let listeners
beforeEach(() => {
  listeners = new Set()
  globalThis.document = {
    hidden: false,
    addEventListener: (_e, fn) => listeners.add(fn),
    removeEventListener: (_e, fn) => listeners.delete(fn),
  }
})
const setHidden = (h) => { document.hidden = h; listeners.forEach(fn => fn()) }
const wait = (ms) => new Promise(r => setTimeout(r, ms))

test('polls while visible, stays quiet while hidden, resumes on return', async () => {
  let n = 0
  const stop = pollWhileVisible(() => { n++ }, 20)
  await wait(70)
  assert.ok(n >= 2, `expected polling while visible, got ${n}`)
  setHidden(true)
  const atHide = n
  await wait(80)
  assert.equal(n, atHide, 'no calls while hidden')
  setHidden(false)                       // data is older than the interval: refresh at once
  await wait(10)
  assert.ok(n > atHide, 'resumed after returning')
  stop()
  assert.equal(listeners.size, 0)
})
