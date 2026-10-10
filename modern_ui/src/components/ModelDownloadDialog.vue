<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import UiIcon from './UiIcon.vue'
import type { ModelDownloadItem, ModelDownloadList, ModernTaskStatus } from '../bridge'

const props = defineProps<{ open: boolean; mode: string; projectName?: string }>()
const emit = defineEmits<{
  close: []
  changed: []
  notify: [message: string]
}>()

const list = ref<ModelDownloadList | null>(null)
const loading = ref(false)
const taskId = ref('')
const taskKey = ref('')
const task = ref<ModernTaskStatus | null>(null)
const offset = ref(0)
const error = ref('')
const selecting = ref(false)
const starting = ref(false)
const queue = ref<string[]>([])
let polling = false
let timer = 0

const running = computed(() => task.value?.status === 'running')
const logs = computed(() => task.value?.logs ?? [])
const busy = computed(() => running.value || loading.value || selecting.value || starting.value || queue.value.length > 0)
const canClose = computed(() => !busy.value)
const missingRequired = computed(() => (list.value?.items ?? []).filter(item => item.required && !item.present))

function stopPolling() {
  if (timer) window.clearInterval(timer)
  timer = 0
}

async function loadList() {
  const api = window.pywebview?.api
  if (!api) { error.value = '模型管理需要在桌面版运行。'; return }
  loading.value = true
  error.value = ''
  try {
    const result = await api.get_model_downloads(props.mode, props.projectName || '')
    if (!result?.ok) error.value = result?.error ?? '读取模型清单失败，请重试。'
    else list.value = result
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '读取模型清单失败。'
  } finally {
    loading.value = false
  }
}

async function poll() {
  const api = window.pywebview?.api
  if (!api || !taskId.value || polling) return
  polling = true
  try {
    const result = await api.get_task_status(taskId.value, offset.value)
    if (!result.ok) throw new Error(result.error || '读取下载进度失败。')
    task.value = result
    offset.value = result.next_offset ?? offset.value
    if (result.status && result.status !== 'running') {
      stopPolling()
      emit('changed')
      await loadList()
      if (result.status !== 'completed' || error.value) queue.value = []
      while (queue.value.length) {
        const key = queue.value.shift()
        const next = list.value?.items?.find(item => item.key === key && !item.present)
        if (next) { await download(next); break }
      }
    }
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '读取下载进度失败。'
    queue.value = []
  } finally {
    polling = false
  }
}

async function download(item: ModelDownloadItem) {
  if (running.value || starting.value) return
  const api = window.pywebview?.api
  if (!api) { error.value = '模型下载需要在桌面版运行。'; queue.value = []; return }
  starting.value = true
  error.value = ''
  try {
    const result = await api.start_model_download(props.mode, item.key, props.projectName || '')
    if (!result.ok || !result.task_id) {
      queue.value = []
      await loadList()
      error.value = result.error ?? '无法启动模型下载。'
      return
    }
    taskId.value = result.task_id
    taskKey.value = item.key
    task.value = { ok: true, status: 'running', message: '正在连接下载源…', logs: [] }
    offset.value = 0
    starting.value = false
    await poll()
    if (task.value?.status === 'running' && !timer) timer = window.setInterval(() => { void poll() }, 600)
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '无法启动模型下载。'
    queue.value = []
  } finally {
    starting.value = false
  }
}

async function downloadRequired() {
  if (busy.value) return
  await loadList()
  if (error.value) return
  queue.value = missingRequired.value.map(item => item.key)
  const first = queue.value.shift()
  const item = list.value?.items?.find(item => item.key === first)
  if (item) await download(item)
}

async function selectLocal(item: ModelDownloadItem, action: 'select' | 'default' | 'disable' = 'select') {
  const api = window.pywebview?.api
  if (busy.value || !api || !props.projectName) return
  selecting.value = true
  error.value = ''
  try {
    const result = await api.select_h3_component(props.projectName, item.key, action)
    if (!result.ok) { error.value = result.error || '组件设置失败。'; return }
    if (result.cancelled) return
    await loadList()
    emit('changed')
    emit('notify', result.message || '组件设置已保存。')
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '组件设置失败。'
  } finally {
    selecting.value = false
  }
}

async function cancel() {
  queue.value = []
  const api = window.pywebview?.api
  if (!api || !taskId.value) return
  const result = await api.cancel_task(taskId.value)
  if (!result.ok) error.value = result.error ?? '无法停止下载。'
  else task.value = { ...(task.value ?? { ok: true }), message: '正在停止下载；已下载部分会保留。' }
}

async function openFolder() {
  if (!window.pywebview?.api) return
  const result = await window.pywebview.api.run_action(`open_models:${props.mode}`)
  if (!result.ok) error.value = result.error ?? '无法打开模型文件夹。'
}

function close() {
  if (!canClose.value) return
  stopPolling()
  emit('close')
}

watch(() => [props.open, props.mode, props.projectName] as const, ([open]) => {
  if (open) {
    stopPolling()
    queue.value = []
    list.value = null
    taskId.value = ''
    taskKey.value = ''
    task.value = null
    void loadList()
  } else {
    stopPolling()
  }
})
onUnmounted(stopPolling)
</script>

<template>
  <Transition name="dialog">
    <div v-if="open" class="assets-backdrop">
      <section class="assets-dialog" role="dialog" aria-modal="true" aria-labelledby="assets-title">
        <header class="assets-header">
          <div><span class="assets-kicker">模型文件管理</span><h2 id="assets-title">{{ list?.title || '训练模型' }}</h2></div>
          <button class="assets-close" type="button" aria-label="关闭" :disabled="!canClose" @click="close">×</button>
        </header>
        <p class="assets-description">{{ list?.description || (error ? '模型文件清单读取失败。' : '正在读取当前模式的模型文件清单…') }}</p>
        <div v-if="list?.asset_dir" class="assets-location"><UiIcon name="folder" /><span :title="list.asset_dir">保存位置：{{ list.asset_dir }}</span><button type="button" @click="openFolder">打开文件夹</button></div>
        <div v-if="list?.note" class="assets-note">{{ list.note }}</div>
        <div v-if="loading" class="assets-loading"><span class="assets-spinner"></span>正在检查本机模型文件…</div>
        <div v-else-if="list" class="assets-list">
          <article v-for="item in list.items" :key="item.key" class="asset-row" :class="{ present: item.present, active: taskKey === item.key && running }">
            <span class="asset-state" :class="{ ready: item.present }">{{ item.present ? '✓' : '·' }}</span>
            <div class="asset-copy">
              <strong>{{ item.label }}</strong>
              <span :title="item.path">{{ item.manual && item.path ? item.path.split(/[\\/]/).pop() : item.filename }}<template v-if="item.required_group"> · {{ item.required_group }}</template><template v-else-if="item.optional"> · 可选</template></span>
              <small v-if="item.local_select && !item.validation_error" class="asset-validation">{{ item.disabled ? '已停用' : item.present ? item.detail : '未准备' }}<template v-if="item.manual && item.path"> · 本地文件</template></small>
              <small v-if="item.validation_error" class="asset-invalid">{{ item.validation_error }}</small>
              <div v-if="item.local_select" class="asset-links">
                <button v-if="item.manual" type="button" :disabled="busy" @click="selectLocal(item, 'default')">恢复默认</button>
                <button v-if="item.optional && item.present" type="button" :disabled="busy" @click="selectLocal(item, 'disable')">不使用</button>
              </div>
              <small v-if="item.part_size">发现未完成的下载（{{ (item.part_size / 1048576).toFixed(1) }} MB），继续时会尝试续传。</small>
            </div>
            <div class="asset-actions">
            <button v-if="item.local_select" class="asset-download" type="button" :disabled="busy" @click="selectLocal(item)">选择本地文件</button>
            <button class="asset-download" type="button" :disabled="item.present || busy" :title="item.present ? '该文件已存在' : item.url" @click="download(item)">
              {{ item.present ? '已就绪' : running && taskKey === item.key ? '下载中…' : item.part_size ? '继续下载' : '下载' }}
            </button>
            </div>
          </article>
        </div>
        <div v-if="error" class="assets-error"><span>{{ error }}</span><button v-if="!loading && !running" type="button" @click="loadList">重试</button></div>
        <template v-if="taskId">
          <div class="download-status" :class="task?.status">
            <span>{{ task?.message || '正在下载…' }}<template v-if="queue.length"> · 待下载 {{ queue.length }} 项</template></span>
            <span v-if="task?.progress != null">{{ Math.floor(task.progress * 100) }}%</span>
          </div>
          <div class="download-track"><span :class="{ indeterminate: task?.progress == null && running }" :style="task?.progress != null ? { width: `${Math.floor(task.progress * 100)}%` } : undefined"></span></div>
          <p v-if="task?.detail" class="download-detail">{{ task.detail }}</p>
          <pre v-if="logs.length" class="download-log">{{ logs.join('\n') }}</pre>
        </template>
        <footer class="assets-footer">
          <button v-if="mode === 'h3_fz' && missingRequired.length && !running" class="asset-secondary" type="button" :disabled="busy || loading" @click="downloadRequired">下载缺失必需组件（{{ missingRequired.length }}）</button>
          <button v-if="running" class="asset-secondary" type="button" @click="cancel">取消下载</button>
          <button class="asset-primary" type="button" :disabled="!canClose" @click="close">{{ running ? '下载进行中…' : '关闭' }}</button>
        </footer>
      </section>
    </div>
  </Transition>
</template>

<style scoped>
.assets-backdrop { position: fixed; inset: 0; z-index: 31; display: grid; place-items: center; padding: 18px; background: rgb(10 12 16 / 52%); }
.assets-dialog { display: flex; width: min(100%, 800px); max-height: min(84vh, 780px); flex-direction: column; padding: 17px; border: 1px solid var(--tone-41464f); border-radius: 8px; background: var(--tone-272a32); box-shadow: 0 16px 44px rgb(0 0 0 / 32%); }
.assets-header { display: flex; justify-content: space-between; gap: 12px; }
.assets-kicker { color: var(--tone-858a93); font-size: 10px; }
.assets-header h2 { margin: 3px 0 0; color: var(--tone-cbd0d7); font-size: 17px; font-weight: 350; }
.assets-close { width: 29px; height: 29px; border: 0; border-radius: 5px; color: var(--tone-999da6); background: transparent; font-size: 22px; cursor: pointer; }
.assets-close:hover:not(:disabled) { color: var(--tone-d0d3d9); background: var(--tone-32363e); }
.assets-close:disabled { opacity: .45; cursor: wait; }
.asset-actions { display: flex; gap: 6px; flex-shrink: 0; }
.asset-links { display: flex; gap: 10px; }
.asset-links button { padding: 0; border: 0; background: transparent; color: var(--tone-9ea4ae); font-size: 10px; cursor: pointer; text-decoration: underline; text-underline-offset: 3px; }
.asset-links button:disabled { opacity: .5; cursor: wait; }
.asset-copy .asset-invalid { color: var(--tone-c69da1); overflow-wrap: anywhere; }
.asset-copy .asset-validation { color: var(--tone-9ea4ae); }
@media (max-width: 640px) { .asset-row { flex-wrap: wrap; } .asset-copy { flex-basis: calc(100% - 28px); } .asset-actions { margin-left: 20px; } }
.assets-description { margin: 10px 0; color: var(--tone-9ea4ae); font-size: 11px; line-height: 1.5; }
.assets-location { display: flex; align-items: center; gap: 7px; min-width: 0; margin-bottom: 8px; color: var(--tone-9097a2); font-size: 10px; }
.assets-location span { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.assets-location button { padding: 4px 7px; border: 1px solid var(--tone-3a3f48); border-radius: 4px; color: var(--tone-b9bec7); background: transparent; font-size: 10px; cursor: pointer; }
.assets-note { margin-bottom: 9px; padding: 7px 9px; border-radius: 4px; color: var(--tone-9da4ae); background: var(--tone-22252c); font-size: 10px; line-height: 1.45; }
.assets-list { display: grid; gap: 5px; min-height: 0; overflow-y: auto; padding-right: 3px; }
.asset-row { display: flex; align-items: center; gap: 8px; min-width: 0; padding: 8px 8px; border: 1px solid var(--tone-363b44); border-radius: 5px; background: var(--tone-23262d); }
.asset-row.present { border-color: var(--tone-343d38); }
.asset-row.active { border-color: var(--tone-586477); }
.asset-state { color: var(--tone-8b7274); font-size: 12px; }
.asset-state.ready { color: var(--tone-8ca58f); }
.asset-copy { display: grid; flex: 1; min-width: 0; gap: 3px; }
.asset-copy strong { overflow: hidden; color: var(--tone-bbc0c9); font-size: 11px; font-weight: 400; text-overflow: ellipsis; white-space: nowrap; }
.asset-copy span { overflow: hidden; color: var(--tone-838a95); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.asset-copy small { color: var(--tone-a99f83); font-size: 9px; }
.asset-download, .asset-primary, .asset-secondary { min-width: 66px; min-height: 28px; padding: 0 8px; border: 1px solid var(--tone-3c424b); border-radius: 4px; color: var(--tone-b9bec7); background: transparent; font-size: 10px; cursor: pointer; }
.asset-download:hover:not(:disabled), .asset-secondary:hover { border-color: var(--tone-575e69); background: var(--tone-2d3139); }
.asset-download:disabled, .asset-primary:disabled { opacity: .48; cursor: wait; }
.assets-loading { display: flex; align-items: center; gap: 8px; min-height: 90px; color: var(--tone-999fa9); font-size: 11px; }
.assets-spinner { width: 12px; height: 12px; border: 1.5px solid var(--tone-505763); border-top-color: var(--tone-b3bbc6); border-radius: 50%; animation: spin .8s linear infinite; }
.assets-error { display: flex; align-items: center; gap: 10px; margin: 8px 0 0; color: var(--tone-c69da1); font-size: 10px; white-space: pre-line; }
.assets-error button { padding: 4px 9px; border: 1px solid var(--tone-3c424b); border-radius: 4px; color: var(--tone-b9bec7); background: transparent; cursor: pointer; }
.download-status { display: flex; justify-content: space-between; gap: 9px; margin-top: 10px; color: var(--tone-aab2bd); font-size: 10px; }
.download-status.completed { color: var(--tone-a8bea9); }
.download-status.failed, .download-status.cancelled { color: var(--tone-c6a8aa); }
.download-track { height: 4px; margin-top: 5px; overflow: hidden; border-radius: 5px; background: var(--tone-1c1f25); }
.download-track span { display: block; height: 100%; border-radius: inherit; background: var(--tone-78869b); transition: width 180ms ease-out; }
.download-track span.indeterminate { width: 32%; animation: slide 1.3s ease-in-out infinite alternate; }
.download-detail { margin: 4px 0 0; color: var(--tone-838a95); font-size: 9px; }
.download-log { max-height: 72px; margin: 6px 0 0; padding: 6px; overflow: auto; border: 1px solid var(--tone-373b44); border-radius: 4px; color: var(--tone-959ca7); background: var(--tone-1d2026); font: 9px/1.4 Consolas, sans-serif; white-space: pre-wrap; }
.assets-footer { display: flex; justify-content: flex-end; gap: 7px; padding-top: 12px; }
.asset-primary { border-color: transparent; color: var(--tone-f0f1f3); background: var(--tone-626f81); }
.asset-primary:hover:not(:disabled) { background: var(--tone-6a7789); }
.dialog-enter-active, .dialog-leave-active { transition: opacity 140ms ease; }
.dialog-enter-active .assets-dialog, .dialog-leave-active .assets-dialog { transition: opacity 140ms ease, transform 170ms var(--ease-out); }
.dialog-enter-from, .dialog-leave-to { opacity: 0; }
.dialog-enter-from .assets-dialog, .dialog-leave-to .assets-dialog { opacity: 0; transform: translateY(5px) scale(.99); }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes slide { from { transform: translateX(-80%); } to { transform: translateX(220%); } }
@media (prefers-reduced-motion: reduce) { .assets-spinner, .download-track span.indeterminate { animation-duration: 2.4s; } }
</style>
