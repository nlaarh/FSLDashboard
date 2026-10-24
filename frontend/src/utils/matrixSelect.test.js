import { test } from 'node:test'
import assert from 'node:assert/strict'
import { rectCells, bulkValue } from './matrixSelect.js'

test('a drag or shift-click covers the whole rectangle, whichever corner comes first', () => {
  const cells = rectCells({ r: 2, c: 3 }, { r: 1, c: 1 })
  assert.equal(cells.length, 6)
  assert.deepEqual(cells[0], { r: 1, c: 1 })
  assert.deepEqual(rectCells({ r: 0, c: 0 }, { r: 0, c: 0 }), [{ r: 0, c: 0 }])
})

test('select-all ticks everything unless every editable cell is already ticked', () => {
  assert.equal(bulkValue([{ on: true }, { on: false }]), true)
  assert.equal(bulkValue([{ on: true }, { on: true }]), false)
  assert.equal(bulkValue([{ on: true }, { on: false, disabled: true }]), false)   // locked cells are ignored
  assert.equal(bulkValue([{ on: false, disabled: true }]), false)
})
