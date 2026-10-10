import { test } from 'node:test'
import assert from 'node:assert/strict'
import { nextSelection, optionPayload } from '../src/bridge.js'

test('removal retains remaining selection and selects an available image', () => {
  const files = [{ key: 'b' }, { key: 'c' }]
  assert.deepEqual(nextSelection(files, ['a', 'c']), ['c'])
  assert.deepEqual(nextSelection(files, ['a']), ['b'])
  assert.deepEqual(nextSelection([], ['a']), [])
})

test('bridge receives an independent JSON snapshot of export parameters', () => {
  const options = { width: 32, direct: false }
  const snapshot = optionPayload(options)
  options.width = 64
  assert.equal(snapshot.width, 32)
  assert.equal(snapshot.direct, false)
})
