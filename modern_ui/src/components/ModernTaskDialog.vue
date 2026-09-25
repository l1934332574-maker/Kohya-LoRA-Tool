<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import type { ModernTaskStatus } from '../bridge'

const props = defineProps<{
  open: boolean
  title: string
  action: string
  description: string
  projectName?: string
}>()
const emit = defineEmits<{
  close: []
  finished: []
  notify: [message: string]
}>()

const taskId = ref('')
const state = ref<ModernTaskStatus | null>(null)
const taskLogs = ref<string[]>([])
const offset = ref(0)
const starting = ref(false)
let timer = 0

const running = () => state.value?.status === 'running'
const lines = () => taskLogs.value

function stopPolling() {
  if (timer) window.clearInterval(timer)
  timer = 0
}

async function poll() {
  if (!taskId.value || !window.pywebview?.api) return
  const result = await window.pywebview.api.get_task_status(taskId.value, offset.value)
  if (!result.ok) {
    stopPolling()
    emit('notify', result.error ?? '读取任务状态失败。')
    return
  }
  state.value = result
  taskLogs.value.push(...(result.logs ?? []))
  offset.value = result.next_offset ?? offset.value
  if (result.status && result.status !== 'running') {
    stopPolling()
    emit('finished')
  }
}

async function start() {
  if (starting.value || running()) return
  const api = window.pywebview?.api
  if (!api) return emit('notify', '安装任务需要在桌面版运行。')
  starting.value = true
  try {
    const result = props.action === 'preprocess'
      ? await api.start_preprocess_task(props.projectName ?? '')
      : await api.start_setup_task(props.action)
    if (!result.ok || !result.task_id) {
      emit('notify', result.error ?? '无法启动安装任务。')
      return
    }
    taskId.value = result.task_id
    offset.value = 0
    taskLogs.value = []
    state.value = { ok: true, status: 'running', message: '正在准备任务…', logs: [] }
    await poll()
    timer = window.setInterval(() => { void poll() }, 700)
  } catch (error) {
    emit('notify', error instanceof Error ? error.message : '无法启动安装任务。')
  } finally {
    starting.value = false
  }
}

async function cancel() {
  if (!taskId.value || !window.pywebview?.api) return
  const result = await window.pywebview.api.cancel_task(taskId.value)
  if (!result.ok) emit('notify', result.error ?? '无法停止当前任务。')
  else state.value = { ...state.value, ok: true, message: '正在请求停止…' }
}

function close() {
  if (running()) return
  stopPolling()
  emit('close')
}

watch(() => props.open, (open) => {
  if (!open) {
    stopPolling()
    taskId.value = ''
    state.value = null
    taskLogs.value = []
    offset.value = 0
    return
  }
})
onUnmounted(stopPolling)
</script>

<template>
  <Transition name="dialog">
    <div v-if="open" class="task-backdrop">
      <section class="task-dialog" role="dialog" aria-modal="true" :aria-labelledby="`task-title-${action}`">
        <header class="task-header">
          <div><span class="task-kicker">训练环境设置</span><h2 :id="`task-title-${action}`">{{ title }}</h2></div>
          <button class="task-close" type="button" aria-label="关闭" :disabled="running()" @click="close">×</button>
        </header>
        <p class="task-description">{{ description }}</p>
        <template v-if="!taskId">
          <div class="task-note">{{ action === 'preprocess' ? '只处理当前项目的数据并生成标签，不会启动训练。完成后可打开标签编辑器检查。日志会显示在此窗口和主页运行日志中。' : '安装操作会在后台运行，并复用软件现有的安装与检测流程。日志会显示在此窗口和主页运行日志中。' }}</div>
          <footer class="task-actions">
            <button class="task-button" type="button" @click="close">稍后再说</button>
            <button class="task-button primary" type="button" :disabled="starting" @click="start">{{ starting ? '正在启动…' : '开始操作' }}</button>
          </footer>
        </template>
        <template v-else>
          <div class="task-state" :class="state?.status">
            <span v-if="running()" class="task-spinner"></span>
            <span>{{ state?.message || '任务运行中…' }}</span>
          </div>
          <pre class="task-log" aria-live="polite">{{ lines().length ? lines().join('\n') : (action === 'preprocess' ? '等待预处理日志…' : '等待安装日志…') }}</pre>
          <footer class="task-actions">
            <button v-if="running()" class="task-button" type="button" @click="cancel">停止任务</button>
            <button class="task-button primary" type="button" :disabled="running()" @click="close">{{ running() ? '运行中…' : '完成' }}</button>
          </footer>
        </template>
      </section>
    </div>
  </Transition>
</template>

<style scoped>
.task-backdrop { position: fixed; inset: 0; z-index: 30; display: grid; place-items: center; padding: 20px; background: rgb(10 12 16 / 52%); }
.task-dialog { display: flex; width: min(100%, 640px); max-height: min(80vh, 720px); flex-direction: column; padding: 18px; border: 1px solid #41464f; border-radius: 8px; background: #272a32; box-shadow: 0 16px 44px rgb(0 0 0 / 32%); }
.task-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.task-kicker { color: #858a93; font-size: 10px; }
.task-header h2 { margin: 3px 0 0; color: #cbd0d7; font-size: 17px; font-weight: 350; }
.task-close { width: 30px; height: 30px; border: 0; border-radius: 5px; color: #999da6; background: transparent; font-size: 22px; cursor: pointer; }
.task-close:hover:not(:disabled) { color: #d0d3d9; background: #32363e; }
.task-close:disabled { opacity: .4; cursor: wait; }
.task-description { margin: 12px 0; color: #a0a5ae; font-size: 11px; line-height: 1.5; }
.task-note { margin: 0 0 12px; padding: 10px; border: 1px solid #373b44; border-radius: 5px; color: #959ba5; background: #22252c; font-size: 11px; line-height: 1.55; }
.task-state { display: flex; align-items: center; gap: 8px; min-height: 31px; color: #aeb5c0; font-size: 11px; }
.task-state.completed { color: #a8bea9; }
.task-state.failed, .task-state.cancelled { color: #c6a8aa; }
.task-spinner { width: 13px; height: 13px; border: 1.5px solid #515763; border-top-color: #aeb5c0; border-radius: 50%; animation: spin .8s linear infinite; }
.task-log { min-height: 170px; max-height: 48vh; margin: 0; padding: 9px; overflow: auto; border: 1px solid #393d47; border-radius: 5px; color: #aeb4be; background: #1d2026; font: 10px/1.5 Consolas, "Microsoft YaHei UI", sans-serif; white-space: pre-wrap; overflow-wrap: anywhere; }
.task-actions { display: flex; justify-content: flex-end; gap: 7px; margin-top: 14px; }
.task-button { min-width: 82px; min-height: 31px; padding: 0 10px; border: 1px solid #3d424b; border-radius: 5px; color: #b8bdc6; background: transparent; font-size: 11px; cursor: pointer; }
.task-button:hover:not(:disabled) { border-color: #555c68; background: #2e323a; }
.task-button.primary { border-color: transparent; color: #eff0f2; background: #626f81; }
.task-button:disabled { opacity: .55; cursor: wait; }
.dialog-enter-active, .dialog-leave-active { transition: opacity 140ms ease; }
.dialog-enter-active .task-dialog, .dialog-leave-active .task-dialog { transition: opacity 140ms ease, transform 170ms var(--ease-out); }
.dialog-enter-from, .dialog-leave-to { opacity: 0; }
.dialog-enter-from .task-dialog, .dialog-leave-to .task-dialog { opacity: 0; transform: translateY(5px) scale(.99); }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .task-spinner { animation-duration: 1.8s; } }
</style>
