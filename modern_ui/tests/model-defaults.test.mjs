import assert from 'node:assert/strict'
import test from 'node:test'
import { normalizeWd14Model } from '../src/modelDefaults.ts'

test('uses the recommended WD14 model for missing or invalid legacy values', () => {
  assert.equal(normalizeWd14Model(undefined), 'swinv2-v3')
  assert.equal(normalizeWd14Model(''), 'swinv2-v3')
  assert.equal(normalizeWd14Model('unknown-model'), 'swinv2-v3')
})

test('preserves an explicitly selected supported WD14 model', () => {
  assert.equal(normalizeWd14Model(' swinv2-v3 '), 'swinv2-v3')
  assert.equal(normalizeWd14Model('moat-v2'), 'moat-v2')
})
