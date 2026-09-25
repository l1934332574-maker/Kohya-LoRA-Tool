<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import UiIcon from './UiIcon.vue'
import type { ModelDownloadItem, ModelDownloadList, ModernTaskStatus } from '../bridge'

const props = defineProps<{ open: boolean; mode: string }>()
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
let timer = 0

const running = computed(() => task.value?.status === 'running')
const logs = computed(() => task.value?.logs ?? [])
const canClose = computed(() => !running.value)

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
    const result = await api.get_model_downloads(props.mode)
    if (!result.ok) error.value = result.error ?? '读取模型清单失败。'
    else list.value = result
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '读取模型清单失败。'
  } finally {
    loading.value = false
  }
}

async function poll() {
  const api = window.pywebview?.api
  if (!api || !taskId.value) return
  const result = await api.get_task_status(taskId.value, offset.value)
  if (!result.ok) {
    stopPolling()
    error.value = result.error ?? '读取下载进度失败。'
    return
  }
  task.value = result
  offset.value = result.next_offset ?? offset.value
  if (result.status && result.status !== 'running') {
    stopPolling()
    emit('changed')
    await loadList()
  }
}

async function download(item: ModelDownloadItem) {
  if (running.value) return
  const api = window.pywebview?.api
  if (!api) { error.value = '模型下载需要在桌面版运行。'; return }
  error.value = ''
  const result = await api.start_model_download(props.mode, item.key)
  if (!result.ok || !result.task_id) {
    error.value = result.error ?? '无法启动模型下载。'
    await loadList()
    return
  }
  taskId.value = result.task_id
  taskKey.value = item.key
  task.value = { ok: true, status: 'running', message: '正在连接下载源…', logs: [] }
  offset.value = 0
  await poll()
  if (task.value?.status === 'running') timer = window.setInterval(() => { void poll() }, 600)
}

async function cancel() {
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

watch(() => [props.open, props.mode] as const, ([open]) => {
  if (open) {
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
        <p class="assets-description">{{ list?.description || '正在读取当前模式的模型文件清单…' }}</p>
        <div v-if="list?.asset_dir" class="assets-location"><UiIcon name="folder" /><span :title="list.asset_dir">保存位置：{{ list.asset_dir }}</span><button type="button" @click="openFolder">打开文件夹</button></div>
        <div v-if="list?.note" class="assets-note">{{ list.note }}</div>
        <div v-if="loading" class="assets-loading"><span class="assets-spinner"></span>正在检查本机模型文件…</div>
        <div v-else-if="list" class="assets-list">
          <article v-for="item in list.items" :key="item.key" class="asset-row" :class="{ present: item.present, active: taskKey === item.key && running }">
            <span class="asset-state" :class="{ ready: item.present }">{{ item.present ? '✓' : '·' }}</span>
            <div class="asset-copy">
              <strong>{{ item.label }}</strong>
              <span>{{ item.filename }}<template v-if="item.required_group"> · {{ item.required_group }}</template><template v-else-if="item.optional"> · 可选</template></span>
              <small v-if="item.part_size">发现未完成的下载（{{ (item.part_size / 1048576).toFixed(1) }} MB），继续时会尝试续传。</small>
            </div>
            <button class="asset-download" type="button" :disabled="item.present || running" :title="item.present ? '该文件已存在' : item.url" @click="download(item)">
              {{ item.present ? '已就绪' : running && taskKey === item.key ? '下载中…' : item.part_size ? '继续下载' : '下载' }}
            </button>
          </article>
        </div>
        <p v-if="error" class="assets-error">{{ error }}</p>
        <template v-if="taskId">
          <div class="download-status" :class="task?.status">
            <span>{{ task?.message || '正在下载…' }}</span>
            <span v-if="task?.progress != null">{{ Math.floor(task.progress * 100) }}%</span>
          </div>
          <div class="download-track"><span :class="{ indeterminate: task?.progress == null && running }" :style="task?.progress != null ? { width: `${Math.floor(task.progress * 100)}%` } : undefined"></span></div>
          <p v-if="task?.detail" class="download-detail">{{ task.detail }}</p>
          <pre v-if="logs.length" class="download-log">{{ logs.join('\n') }}</pre>
        </template>
        <footer class="assets-footer">
          <button v-if="running" class="asset-secondary" type="button" @click="cancel">取消下载</button>
          <button class="asset-primary" type="button" :disabled="!canClose" @click="close">{{ running ? '下载进行中…' : '关闭' }}</button>
        </footer>
      </section>
    </div>
  </Transition>
</template>

<style scoped>
.assets-backdrop { position: fixed; inset: 0; z-index: 31; display: grid; place-items: center; padding: 18px; background: rgb(10 12 16 / 52%); }
.assets-dialog { display: flex; width: min(100%, 700px); max-height: min(84vh, 780px); flex-direction: column; padding: 17px; border: 1px solid #41464f; border-radius: 8px; background: #272a32; box-shadow: 0 16px 44px rgb(0 0 0 / 32%); }
.assets-header { display: flex; justify-content: space-between; gap: 12px; }
.assets-kicker { color: #858a93; font-size: 10px; }
.assets-header h2 { margin: 3px 0 0; color: #cbd0d7; font-size: 17px; font-weight: 350; }
.assets-close { width: 29px; height: 29px; border: 0; border-radius: 5px; color: #999da6; background: transparent; font-size: 22px; cursor: pointer; }
.assets-close:hover:not(:disabled) { color: #d0d3d9; background: #32363e; }
.assets-close:disabled { opacity: .45; cursor: wait; }
.assets-description { margin: 10px 0; color: #9ea4ae; font-size: 11px; line-height: 1.5; }
.assets-location { display: flex; align-items: center; gap: 7px; min-width: 0; margin-bottom: 8px; color: #9097a2; font-size: 10px; }
.assets-location span { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.assets-location button { padding: 4px 7px; border: 1px solid #3a3f48; border-radius: 4px; color: #b9bec7; background: transparent; font-size: 10px; cursor: pointer; }
.assets-note { margin-bottom: 9px; padding: 7px 9px; border-radius: 4px; color: #9da4ae; background: #22252c; font-size: 10px; line-height: 1.45; }
.assets-list { display: grid; gap: 5px; min-height: 0; overflow-y: auto; padding-right: 3px; }
.asset-row { display: flex; align-items: center; gap: 8px; min-width: 0; padding: 8px 8px; border: 1px solid #363b44; border-radius: 5px; background: #23262d; }
.asset-row.present { border-color: #343d38; }
.asset-row.active { border-color: #586477; }
.asset-state { color: #8b7274; font-size: 12px; }
.asset-state.ready { color: #8ca58f; }
.asset-copy { display: grid; flex: 1; min-width: 0; gap: 3px; }
.asset-copy strong { overflow: hidden; color: #bbc0c9; font-size: 11px; font-weight: 400; text-overflow: ellipsis; white-space: nowrap; }
.asset-copy span { overflow: hidden; color: #838a95; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.asset-copy small { color: #a99f83; font-size: 9px; }
.asset-download, .asset-primary, .asset-secondary { min-width: 66px; min-height: 28px; padding: 0 8px; border: 1px solid #3c424b; border-radius: 4px; color: #b9bec7; background: transparent; font-size: 10px; cursor: pointer; }
.asset-download:hover:not(:disabled), .asset-secondary:hover { border-color: #575e69; background: #2d3139; }
.asset-download:disabled, .asset-primary:disabled { opacity: .48; cursor: wait; }
.assets-loading { display: flex; align-items: center; gap: 8px; min-height: 90px; color: #999fa9; font-size: 11px; }
.assets-spinner { width: 12px; height: 12px; border: 1.5px solid #505763; border-top-color: #b3bbc6; border-radius: 50%; animation: spin .8s linear infinite; }
.assets-error { margin: 8px 0 0; color: #c69da1; font-size: 10px; white-space: pre-line; }
.download-status { display: flex; justify-content: space-between; gap: 9px; margin-top: 10px; color: #aab2bd; font-size: 10px; }
.download-status.completed { color: #a8bea9; }
.download-status.failed, .download-status.cancelled { color: #c6a8aa; }
.download-track { height: 4px; margin-top: 5px; overflow: hidden; border-radius: 5px; background: #1c1f25; }
.download-track span { display: block; height: 100%; border-radius: inherit; background: #78869b; transition: width 180ms ease-out; }
.download-track span.indeterminate { width: 32%; animation: slide 1.3s ease-in-out infinite alternate; }
.download-detail { margin: 4px 0 0; color: #838a95; font-size: 9px; }
.download-log { max-height: 72px; margin: 6px 0 0; padding: 6px; overflow: auto; border: 1px solid #373b44; border-radius: 4px; color: #959ca7; background: #1d2026; font: 9px/1.4 Consolas, sans-serif; white-space: pre-wrap; }
.assets-footer { display: flex; justify-content: flex-end; gap: 7px; padding-top: 12px; }
.asset-primary { border-color: transparent; color: #f0f1f3; background: #626f81; }
.asset-primary:hover:not(:disabled) { background: #6a7789; }
.dialog-enter-active, .dialog-leave-active { transition: opacity 140ms ease; }
.dialog-enter-active .assets-dialog, .dialog-leave-active .assets-dialog { transition: opacity 140ms ease, transform 170ms var(--ease-out); }
.dialog-enter-from, .dialog-leave-to { opacity: 0; }
.dialog-enter-from .assets-dialog, .dialog-leave-to .assets-dialog { opacity: 0; transform: translateY(5px) scale(.99); }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes slide { from { transform: translateX(-80%); } to { transform: translateX(220%); } }
@media (prefers-reduced-motion: reduce) { .assets-spinner, .download-track span.indeterminate { animation-duration: 2.4s; } }
</style>
