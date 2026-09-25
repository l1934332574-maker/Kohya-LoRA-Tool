import assert from 'node:assert/strict'
import test from 'node:test'
import { loadBootstrap, waitForDesktopBridge } from '../src/bridge.ts'

function createWindow(api) {
  const listeners = new Map()
  return {
    pywebview: { api },
    addEventListener(type, callback) {
      listeners.set(type, callback)
    },
    removeEventListener(type, callback) {
      if (listeners.get(type) === callback) listeners.delete(type)
    },
    setTimeout,
    clearTimeout,
    dispatch(type) {
      listeners.get(type)?.()
    },
  }
}

test('waits for bootstrap to be exposed before declaring the desktop bridge ready', async () => {
  const api = {}
  globalThis.window = createWindow(api)
  const pending = waitForDesktopBridge(500)
  let settled = false
  pending.then(() => { settled = true })

  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(settled, false, 'an empty pywebview api object is not ready')

  api.bootstrap = async () => ({ schema_version: 1 })
  window.dispatch('pywebviewready')
  assert.equal(await pending, true)
})

test('does not accept an incomplete bridge when the ready event never arrives', async () => {
  globalThis.window = createWindow({})
  assert.equal(await waitForDesktopBridge(2), false)
})

test('loads desktop bootstrap only after pywebview exposes the method', async () => {
  const api = {}
  globalThis.window = createWindow(api)
  const loading = loadBootstrap()

  await new Promise((resolve) => setImmediate(resolve))
  api.bootstrap = async () => ({ schema_version: 1, app_name: 'Kohya-LoRA' })
  window.dispatch('pywebviewready')

  assert.deepEqual(await loading, {
    data: { schema_version: 1, app_name: 'Kohya-LoRA' },
    preview: false,
  })
})
