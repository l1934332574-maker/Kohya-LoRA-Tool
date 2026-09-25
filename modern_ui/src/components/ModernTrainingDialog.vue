<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import type { ModernTaskStatus, TrainingPlan } from '../bridge'

const props = defineProps<{
  open: boolean
  projectName: string
  plan: TrainingPlan | null
}>()
const emit = defineEmits<{ close: []; finished: []; notify: [message: string] }>()

const taskId = ref('')
const state = ref<ModernTaskStatus | null>(null)
const taskLogs = ref<string[]>([])
const logElement = ref<HTMLDivElement | null>(null)
const offset = ref(0)
const starting = ref(false)
const useResume = ref(false)
let timer = 0

const running = computed(() => state.value?.status === 'running')
const awaitingReview = computed(() => state.value?.status === 'awaiting_review')
const active = computed(() => running.value || awaitingReview.value)
const lines = computed(() => taskLogs.value)
const logEntries = computed(() => lines.value.map((text, index) => ({
  key: `${offset.value - lines.value.length + index}:${index}`,
  text,
  tone: logTone(text),
  parts: logParts(text),
})))
const hasResume = computed(() => Boolean(props.plan?.resume_path))
const engineDescription = computed(() => props.plan?.training_engine === 'kohya'
  ? '开始后先按当前设置预处理图集；你可以检查和修改自动标签，确认后直接调用现有 Kohya / sd-scripts 训练入口。'
  : props.plan?.mode === 'video'
    ? '先检查视频和字幕；确认后直接调用现有 MiniMax H3 训练入口。'
    : `开始后先按当前设置预处理图集；你可以检查和修改自动标签，确认后直接调用现有 ${props.plan?.engine_label || '训练引擎'}入口。`)

watch([() => props.open, () => props.plan?.resume_path], ([open, resumePath]) => {
  if (open) useResume.value = Boolean(resumePath)
}, { immediate: true })

function logTone(line: string) {
  // Keep the classic UI's log categories and palette semantics. The modern
  // training task also prefixes some classic warnings with [训练], so ⚠ is
  // treated like the classic [WARN] marker to keep those lines amber.
  if (['[OK]', '完成', '成功'].some((marker) => line.includes(marker))) return 'success'
  if (['[WARN]', '警告', '注意', '⚠'].some((marker) => line.includes(marker))) return 'warning'
  if (/\b(?:traceback|exception|fatal error|error|failed)\b|报错|\[ERROR\]|错误|异常|失败|崩溃|✘|退出码\s*[1-9]/i.test(line)) return 'error'
  if (line.includes('[训练]') || line.includes('loss') || /total optimization steps|训练步数|^\s*steps:/i.test(line)) return 'training'
  if (['[底模]', '[预处理]', '[WD14]', '[环境]', '[Kohya]'].some((marker) => line.includes(marker))) return 'info'
  return 'default'
}

function logParts(line: string) {
  const parts: { text: string; emphasis: boolean }[] = []
  const marker = /(\d+(?:[.,]\d+)?\s*%|\b\d+\s*\/\s*\d+\b)/g
  let previous = 0
  for (const match of line.matchAll(marker)) {
    const start = match.index ?? 0
    if (start > previous) parts.push({ text: line.slice(previous, start), emphasis: false })
    parts.push({ text: match[0], emphasis: true })
    previous = start + match[0].length
  }
  if (previous < line.length || parts.length === 0) parts.push({ text: line.slice(previous), emphasis: false })
  return parts
}

function stopPolling() {
  if (timer) window.clearInterval(timer)
  timer = 0
}

async function poll() {
  const api = window.pywebview?.api
  if (!api || !taskId.value) return
  try {
    const result = await api.get_task_status(taskId.value, offset.value)
    if (!result.ok) {
      stopPolling()
      emit('notify', result.error ?? '读取训练状态失败。')
      return
    }
    state.value = result
    taskLogs.value.push(...(result.logs ?? []))
    offset.value = result.next_offset ?? offset.value
    await nextTick()
    if (logElement.value) logElement.value.scrollTop = logElement.value.scrollHeight
    if (result.status && result.status !== 'running' && result.status !== 'awaiting_review') {
      stopPolling()
      emit('finished')
    }
  } catch (error) {
    stopPolling()
    emit('notify', error instanceof Error ? `读取训练状态失败：${error.message}` : '读取训练状态失败。')
  }
}

async function start() {
  if (starting.value || running.value) return
  const api = window.pywebview?.api
  if (!api) return emit('notify', '请从现代界面的 Windows 桌面版启动训练。')
  starting.value = true
  try {
    const result = await api.start_training(props.projectName, useResume.value)
    if (!result.ok || !result.task_id) {
      emit('notify', result.error ?? '无法启动训练。')
      return
    }
    taskId.value = result.task_id
    offset.value = 0
    state.value = { ok: true, status: 'running', message: '正在准备训练…', logs: [] }
    await poll()
    timer = window.setInterval(() => { void poll() }, 700)
  } catch (error) {
    emit('notify', error instanceof Error ? `无法启动训练：${error.message}` : '无法启动训练。')
  } finally {
    starting.value = false
  }
}

async function cancel() {
  const api = window.pywebview?.api
  if (!api || !taskId.value) return
  const result = await api.cancel_task(taskId.value)
  if (!result.ok) emit('notify', result.error ?? '无法停止训练。')
  else if (state.value) state.value = { ...state.value, message: awaitingReview.value ? '已取消后续训练；预处理结果会保留。' : '正在请求停止；训练引擎会在安全位置退出…' }
}

async function continueAfterReview() {
  const api = window.pywebview?.api
  if (!api || !taskId.value || !awaitingReview.value) return
  const result = await api.continue_training(taskId.value)
  if (!result.ok) {
    emit('notify', result.error ?? '无法继续训练。')
    return
  }
  await poll()
}

async function openLabelEditor() {
  const api = window.pywebview?.api
  if (!api) return emit('notify', '请在 Windows 桌面版打开标签编辑器。')
  const result = await api.run_action('label_editor', props.projectName)
  if (!result.ok) emit('notify', result.error ?? '无法打开标签编辑器。')
  else emit('notify', result.message ?? '标签编辑器已打开。')
}

function close() {
  if (active.value) return
  stopPolling()
  emit('close')
}

watch(() => props.open, (open) => {
  stopPolling()
  if (!open) {
    taskId.value = ''
    state.value = null
    taskLogs.value = []
    offset.value = 0
    return
  }
  useResume.value = false
})
onUnmounted(stopPolling)
</script>

<template>
  <Transition name="dialog">
    <div v-if="open" class="train-backdrop">
      <section class="train-dialog" role="dialog" aria-modal="true" aria-labelledby="modern-train-title">
        <header class="train-header">
          <div><span class="train-kicker">新界面训练</span><h2 id="modern-train-title">{{ plan?.mode_label || '训练' }} · {{ projectName }}</h2></div>
          <button class="train-close" type="button" aria-label="关闭" :disabled="active" @click="close">×</button>
        </header>

        <template v-if="!taskId && plan">
          <p class="train-description">{{ engineDescription }}</p>
          <div class="train-summary">
            <div><span>训练模型</span><strong>{{ plan.model_label }}</strong><small>{{ plan.model_path }}</small></div>
            <div><span>图集</span><strong>{{ plan.image_count }} 张（至少 {{ plan.min_images }} 张）</strong><small>{{ plan.raw_dir }}</small></div>
            <div><span>训练参数</span><strong>rank / alpha {{ plan.rank }} / {{ plan.alpha }} · 学习率 {{ plan.learning_rate }}</strong><small>{{ plan.resolution }} px · {{ plan.schedule_value || `${plan.steps} 步` }} · {{ plan.training_type === 'style' ? '画风' : plan.training_type === 'concept' ? '概念' : '人物' }}<template v-if="plan.training_target"> · {{ plan.training_target }}</template></small></div>
            <div><span>显卡</span><strong>{{ plan.gpu_vendor }}<template v-if="plan.vram_gb != null"> · {{ plan.vram_gb.toFixed(1) }} GB</template></strong><small>Trigger：{{ plan.trigger || '未填写' }}</small></div>
          </div>
          <div v-if="plan.model_download_required" class="train-warning"><strong>本机尚未准备好训练模型</strong><span>开始后可能会下载约 {{ plan.model_size || '较大体积' }} 的模型文件；下载由训练引擎执行，日志会显示进度。</span></div>
          <div v-for="warning in plan.warnings" :key="warning" class="train-warning"><span>{{ warning }}</span></div>
          <label v-if="hasResume" class="resume-choice"><input v-model="useResume" type="checkbox"><span><strong>发现可续训快照，默认从断点继续</strong><small>取消勾选即可从头训练 · {{ plan.resume_path }}</small></span></label>
          <div class="train-note">预处理完成后会先暂停，供你查看、修改自动标签并二次确认。没有现成断点时，训练达到首个保存间隔后停止，才会出现续训选项。</div>
          <footer class="train-actions">
            <button class="train-button" type="button" @click="close">返回检查设置</button>
            <button class="train-button primary" type="button" :disabled="starting" @click="start">{{ starting ? '正在启动…' : '确认并开始训练' }}</button>
          </footer>
        </template>

        <template v-else-if="taskId">
          <div class="train-state" :class="state?.status">
            <span v-if="running" class="train-spinner"></span>
            <span>{{ state?.message || '训练任务已启动…' }}</span>
          </div>
          <div class="train-progress"><span :class="{ indeterminate: running && state?.progress == null }" :style="state?.progress != null ? { width: `${Math.floor(state.progress * 100)}%` } : undefined"></span></div>
          <p v-if="state?.detail" class="train-detail">{{ state.detail }}</p>
          <div v-if="awaitingReview" class="review-callout">
            <strong>{{ plan?.mode === 'video' ? '训练尚未开始' : '训练尚未开始' }}</strong>
            <span>{{ plan?.mode === 'video' ? '请确认视频字幕和训练数据后继续。' : '请检查预处理后的图片和标签；需要时打开标签编辑器修改，回来后确认继续训练。' }}</span>
          </div>
          <div ref="logElement" class="train-log" role="log" aria-live="polite">
            <div v-if="!logEntries.length" class="train-log-line tone-muted">等待训练日志…</div>
            <div v-for="entry in logEntries" :key="entry.key" class="train-log-line" :class="`tone-${entry.tone}`">
              <span v-for="(part, partIndex) in entry.parts" :key="partIndex" :class="{ 'log-emphasis': part.emphasis }">{{ part.text }}</span>
            </div>
          </div>
          <footer class="train-actions">
            <template v-if="awaitingReview">
            <button v-if="plan?.mode !== 'video'" class="train-button" type="button" @click="openLabelEditor">打开标签编辑器</button>
              <button class="train-button" type="button" @click="cancel">取消训练</button>
              <button class="train-button primary" type="button" @click="continueAfterReview">确认标签并继续训练</button>
            </template>
            <button v-else-if="running" class="train-button" type="button" @click="cancel">停止训练</button>
            <button class="train-button primary" type="button" :disabled="active" @click="close">{{ active ? (awaitingReview ? '等待标签确认…' : '训练运行中…') : '关闭' }}</button>
          </footer>
        </template>
      </section>
    </div>
  </Transition>
</template>

<style scoped>
.train-backdrop { position: fixed; inset: 0; z-index: 35; display: grid; place-items: center; padding: 18px; background: rgb(10 12 16 / 54%); }
.train-dialog { display: flex; width: min(100%, 650px); max-height: min(84vh, 760px); flex-direction: column; gap: 11px; padding: 17px; border: 1px solid #41464f; border-radius: 8px; background: #272a32; box-shadow: 0 16px 44px rgb(0 0 0 / 34%); }
.train-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }.train-kicker { color: #858a93; font-size: 10px; }.train-header h2 { margin: 3px 0 0; color: #cbd0d7; font-size: 16px; font-weight: 350; }.train-close { width: 29px; height: 29px; border: 0; border-radius: 5px; color: #999da6; background: transparent; font-size: 21px; cursor: pointer; }.train-close:hover:not(:disabled) { color: #d0d3d9; background: #32363e; }.train-close:disabled { opacity: .45; cursor: wait; }
.train-description { margin: 0; color: #a0a5ae; font-size: 11px; line-height: 1.5; }.train-summary { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }.train-summary > div { display: grid; min-width: 0; gap: 3px; padding: 9px; border: 1px solid #373b44; border-radius: 5px; background: #22252c; }.train-summary span { color: #858b95; font-size: 9px; }.train-summary strong { overflow: hidden; color: #c1c6cf; font-size: 10px; font-weight: 400; text-overflow: ellipsis; white-space: nowrap; }.train-summary small { overflow: hidden; color: #858b95; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.train-warning { display: grid; gap: 3px; padding: 8px 9px; border: 1px solid #50473d; border-radius: 5px; color: #c6bba9; background: #302b27; font-size: 10px; line-height: 1.45; }.train-warning strong { font-weight: 450; }.resume-choice { display: flex; align-items: flex-start; gap: 8px; padding: 8px 9px; border: 1px solid #3b414b; border-radius: 5px; color: #bac0c9; background: #23262d; cursor: pointer; }.resume-choice input { margin: 2px 0 0; accent-color: #78869b; }.resume-choice span { display: grid; min-width: 0; gap: 3px; }.resume-choice strong { font-size: 10px; font-weight: 400; }.resume-choice small { overflow: hidden; color: #858b95; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }.train-note { padding: 8px 9px; border-radius: 5px; color: #949aa4; background: #22252c; font-size: 10px; line-height: 1.45; }
.train-state { display: flex; align-items: center; gap: 8px; min-height: 27px; color: #b4bac4; font-size: 11px; }.train-state.completed { color: #a8bea9; }.train-state.failed, .train-state.cancelled { color: #c6a8aa; }.train-spinner { width: 13px; height: 13px; border: 1.5px solid #515763; border-top-color: #aeb5c0; border-radius: 50%; animation: train-spin .8s linear infinite; }.train-progress { height: 4px; overflow: hidden; border-radius: 5px; background: #1d2026; }.train-progress > span { display: block; height: 100%; border-radius: inherit; background: #75849a; transition: width 180ms ease; }.train-progress > span.indeterminate { width: 32%; animation: train-slide 1.2s ease-in-out infinite alternate; }.train-detail { margin: -5px 0 0; color: #9299a4; font-size: 9px; }.train-log { min-height: 190px; max-height: 48vh; margin: 0; padding: 9px; overflow: auto; border: 1px solid #393d47; border-radius: 5px; color: #aeb4be; background: #1d2026; font: 10px/1.5 Consolas, "Microsoft YaHei UI", sans-serif; white-space: pre-wrap; overflow-wrap: anywhere; user-select: text; }.train-log-line { min-height: 1.5em; white-space: pre-wrap; overflow-wrap: anywhere; }.tone-default { color: #aeb4be; }.tone-muted { color: #858c98; }.tone-warning { color: #d4b06a; }.tone-error { color: #e08a8a; }.tone-success { color: #9ecb8f; }.tone-training { color: #8fb0c9; }.tone-info { color: #8fa8d4; }.log-emphasis { color: inherit; font-weight: 600; }
.train-state.awaiting_review { color: #c0baa8; }.review-callout { display: grid; gap: 4px; padding: 9px 10px; border: 1px solid #47443c; border-radius: 5px; color: #c3bcaa; background: #2d2a25; font-size: 10px; line-height: 1.45; }.review-callout strong { font-weight: 450; }
.train-actions { display: flex; justify-content: flex-end; gap: 7px; margin-top: 2px; }.train-button { min-height: 30px; padding: 0 10px; border: 1px solid #3d424b; border-radius: 5px; color: #b8bdc6; background: transparent; font-size: 10px; cursor: pointer; }.train-button:hover:not(:disabled) { border-color: #555c68; background: #2e323a; }.train-button.primary { border-color: transparent; color: #eff0f2; background: #626f81; }.train-button:disabled { opacity: .55; cursor: wait; }
@keyframes train-spin { to { transform: rotate(360deg); } } @keyframes train-slide { to { transform: translateX(210%); } }
@media (max-width: 560px) { .train-summary { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { .train-spinner, .train-progress > span.indeterminate { animation-duration: 1.8s; } }
</style>
