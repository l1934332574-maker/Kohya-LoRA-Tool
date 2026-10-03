import assert from 'node:assert/strict'
import { test } from 'node:test'
import { trainingProfileChanges } from '../src/fastRunPreset.ts'

const draft = { rank: '32', alpha: '32', batch_size: '3', gc: 'auto', repeats: '4', max_epochs: '30',
  resolution: '1024', quant_mode: 'nf4', compile: true, sample_preview_mode: 'on', blocks_to_swap: '12' }

for (const profile of ['quick', 'memory', 'speed']) {
  test(`${profile} preserves resolution and explicit quantization`, () => {
    const changes = trainingProfileChanges(draft, 'krea2', profile, () => true)
    assert.equal('resolution' in changes, false)
    assert.equal('quant_mode' in changes, false)
    assert.equal(draft.rank, '32')
  })
}
test('quick only includes fields supported by this mode', () => {
  const changes = trainingProfileChanges(draft, 'krea2', 'quick', (key) => ['rank', 'max_epochs'].includes(key))
  assert.equal(changes.rank, '8')
  assert.equal(changes.max_epochs, '4')
  assert.equal('batch_size' in changes, false)
  assert.equal('gc' in changes, false)
})
test('memory and speed restore the standard training duration', () => {
  for (const profile of ['memory', 'speed']) {
    const changes = trainingProfileChanges(draft, 'krea2', profile, () => true)
    assert.equal(changes.max_epochs, '8')
    assert.equal(changes.repeats, '1')
  }
})
test('quick video mode sets a supported step limit', () => {
  const changes = trainingProfileChanges({ ...draft, video_steps: '2000' }, 'video', 'quick', (key) => key !== 'max_epochs')
  assert.equal(changes.video_steps, '400')
})
test('Qwen 2.1 uses its official preset', () => {
  const changes = trainingProfileChanges({ ...draft, fizgig_qwen_preset: 'auto' }, 'qwen21_fz', 'quick', () => true)
  assert.equal(changes.fizgig_qwen_preset, 'fast')
  assert.equal('rank' in changes, false)
})
