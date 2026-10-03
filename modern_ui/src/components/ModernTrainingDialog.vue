<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import type { ModernTaskStatus, TrainingPlan } from '../bridge'
import TrainingMetrics from './TrainingMetrics.vue'

const props = defineProps<{
  open: boolean
  projectName: string
  plan: TrainingPlan | null
}>()
const emit = defineEmits<{ close: []; finished: []; active: [value: boolean]; notify: [message: string] }>()

const minimized = ref(false)
const taskId = ref('')
const state = ref<ModernTaskStatus | null>(null)
const taskLogs = ref<string[]>([])
const logElement = ref<HTMLDivElement | null>(null)
const offset = ref(0)
const starting = ref(false)
const useResume = ref(false)
const sampleData = ref('')
const sampleName = ref('')
const sampleVersion = ref('')
const sampleWarning = ref('')
const sampleExpanded = ref(false)
const fullSampleData = ref('')
let sampleCheckedAt = 0
let sampleLoading = false
let timer = 0

const running = computed(() => state.value?.status === 'running')
const awaitingReview = computed(() => state.value?.status === 'awaiting_review')
const active = computed(() => starting.value || running.value || awaitingReview.value)
watch(active, (value) => emit('active', value), { immediate: true })
function expand() { minimized.value = false }
defineExpose({ expand })
const remainingTime = computed(() => {
  const seconds = state.value?.eta_seconds
  if (!running.value || seconds == null || !Number.isFinite(seconds) || seconds < 0) return ''
  if (seconds < 60) return `${Math.max(1, Math.ceil(seconds))} 秒`
  const minutes = Math.max(1, Math.round(seconds / 60))
  const days = Math.floor(minutes / 1440)
  const hours = Math.floor((minutes % 1440) / 60)
  const rest = minutes % 60
  return [days && `${days} 天`, hours && `${hours} 小时`, rest && `${rest} 分钟`].filter(Boolean).join(' ')
})
const lines = computed(() => taskLogs.value)
const sampleFailure = computed(() => [...taskLogs.value].reverse().find((line) =>
  /(?:\[preview\]|\[sample\]|采样|预览).*(?:fail|error|exception|disabling previews|失败|错误|异常|崩溃|出错)/i.test(line)
) || '')
const sampleEnabled = computed(() => {
  if (props.plan?.sampling_rule) return props.plan.sampling_rule.enabled
  const config = props.plan?.config_summary || {}
  if (['qwen_image', 'zimage'].includes(props.plan?.mode || '')) {
    const fastTier = String(config.fast_tier || 'auto')
    if (fastTier === 'on' || (fastTier === 'auto' && props.plan?.mode === 'zimage' &&
      props.plan.vram_gb != null && props.plan.vram_gb < 10)) return false
  }
  if (config.sample_preview === false) return false
  if (config.sample_preview === true) return true
  return props.plan?.vram_gb == null || props.plan.vram_gb >= 20
})
const sampleEmptyText = computed(() => {
  if (!sampleEnabled.value) return '本次训练的采样预览已关闭。'
  if (props.plan?.mode === 'h3_fz' && !sampleData.value) return '窗口只显示图片采样；视频和音频采样请打开当前项目输出目录查看。'
  if (state.value?.status === 'completed' || state.value?.status === 'failed' || state.value?.status === 'cancelled') {
    return '本次没有生成采样图。请检查采样间隔和下方日志。'
  }
  return '等待本次训练的首张采样图…'
})
const logEntries = computed(() => lines.value.map((text, index) => ({
  key: `${offset.value - lines.value.length + index}:${index}`,
  text,
  tone: logTone(text),
  parts: logParts(text),
})))
const settingSummary = computed(() => {
  const config = props.plan?.config_summary || {}
  const supports = props.plan?.config_supports || {}
  const rawMedia = ['video', 'h3_fz'].includes(props.plan?.mode || '')
  const rows = [
    ['标签处理', rawMedia ? '读取媒体同名字幕' : config.keep_user_captions ? '保留已有标签，不自动打标' : '按当前设置预处理与打标'],
    ['训练采样', props.plan?.sampling_rule ? `${props.plan.sampling_rule.enabled ? '开启' : '关闭'}（${props.plan.sampling_rule.reason}）` : config.sample_preview === false ? '关闭' : config.sample_preview === true ? '开启' : '按显存自动选择'],
    ['采样间隔', props.plan?.sampling_rule?.cadence || '训练时确定'],
    ['保存间隔', props.plan?.save_interval_effective != null ? `每 ${props.plan.save_interval_effective} ${props.plan.save_interval_unit === 'epochs' ? '轮' : '步'}` : '训练时确定'],
  ]
  if (supports.quant_mode) rows.unshift(['量化精度', config.quant_mode === 'auto' ? '引擎自动选择' : String(config.quant_mode || '自动')])
  if (supports.batch_size) rows.push(['批大小', String(config.batch_size || 1)])
  if (supports.gc) rows.push(['梯度检查点', ({ on: '开启', off: '关闭', 开启: '开启', 关闭: '关闭', auto: '按显存自动' } as Record<string, string>)[String(config.gc)] || '按显存自动'])
  return rows
})
const hasResume = computed(() => Boolean(props.plan?.resume_path))
const isRawMediaMode = computed(() => ['video', 'h3_fz'].includes(props.plan?.mode || ''))
const trainingTypeLabel = computed(() => props.plan?.mode === 'h3_fz' ? '混合媒体' : props.plan?.mode === 'video' ? '视频' : props.plan?.training_type === 'style' ? '画风' : props.plan?.training_type === 'concept' ? '概念' : '人物')
const engineDescription = computed(() => props.plan?.training_engine === 'kohya'
  ? '开始后先按当前设置预处理图集；你可以检查和修改自动标签，确认后直接调用现有 Kohya / sd-scripts 训练入口。'
  : props.plan?.mode === 'video'
    ? '先检查视频和字幕；确认后直接调用现有 MiniMax H3 训练入口。'
    : props.plan?.mode === 'h3_fz'
      ? '扫描原始目录中的图片、视频、音频和同名字幕；不会移动或转码媒体，确认后调用 Fizgig H3 训练入口。'
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

async function refreshSample(force = false) {
  const api = window.pywebview?.api
  if (!api || !taskId.value || sampleLoading) return
  const now = Date.now()
  if (!force && now - sampleCheckedAt < 4000) return
  sampleCheckedAt = now
  sampleLoading = true
  const currentTask = taskId.value
  try {
    const result = await api.get_task_sample(currentTask, sampleVersion.value)
    if (currentTask !== taskId.value) return
    if (!result.ok) {
      sampleWarning.value = result.error || '无法读取采样图。'
    } else if (result.data_url && result.version) {
      sampleData.value = result.data_url
      sampleName.value = result.name || '采样图'
      sampleVersion.value = result.version
      fullSampleData.value = ''
      sampleWarning.value = ''
    } else {
      sampleWarning.value = result.warning || ''
    }
  } catch (error) {
    sampleWarning.value = error instanceof Error ? `无法读取采样图：${error.message}` : '无法读取采样图。'
  } finally {
    sampleLoading = false
  }
}

async function expandSample() {
  if (!sampleData.value || !taskId.value) return
  sampleExpanded.value = true
  fullSampleData.value = ''
  const currentTask = taskId.value
  const currentVersion = sampleVersion.value
  try {
    const result = await window.pywebview?.api.get_task_sample(currentTask, currentVersion, true)
    if (sampleExpanded.value && currentTask === taskId.value && result?.version === currentVersion && result.data_url) {
      fullSampleData.value = result.data_url
    }
  } catch {
    // The available thumbnail remains visible if a full-size read is interrupted.
  }
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
    const shouldFollowLog = logElement.value
      ? logElement.value.scrollHeight - logElement.value.scrollTop - logElement.value.clientHeight <= 24
      : true
    taskLogs.value.push(...(result.logs ?? []))
    offset.value = result.next_offset ?? offset.value
    await nextTick()
    if (shouldFollowLog && logElement.value) logElement.value.scrollTop = logElement.value.scrollHeight
    if (result.status && result.status !== 'running' && result.status !== 'awaiting_review') {
      await refreshSample(true)
      stopPolling()
      emit('finished')
    } else if (result.status === 'running') {
      void refreshSample()
    }
  } catch (error) {
    stopPolling()
    emit('notify', error instanceof Error ? `读取训练状态失败：${error.message}` : '读取训练状态失败。')
  }
}

async function start() {
  if (starting.value || running.value) return
  const api = window.pywebview?.api
  if (!api) return emit('notify', '请从新版训练页的 Windows 桌面版启动训练。')
  starting.value = true
  try {
    const result = await api.start_training(props.projectName, useResume.value)
    if (!result.ok || !result.task_id) {
      emit('notify', result.error ?? '无法启动训练。')
      return
    }
    taskId.value = result.task_id
    offset.value = 0
    sampleData.value = ''
    sampleName.value = ''
    sampleVersion.value = ''
    sampleWarning.value = ''
    sampleExpanded.value = false
    fullSampleData.value = ''
    sampleCheckedAt = 0
    state.value = { ok: true, status: 'running', message: '正在准备训练…', logs: [] }
    await poll()
    if (state.value?.status === 'running' || state.value?.status === 'awaiting_review') {
      timer = window.setInterval(() => { void poll() }, 700)
    }
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

async function openOutputDirectory() {
  const api = window.pywebview?.api
  if (!api) return emit('notify', '请在 Windows 桌面版打开输出目录。')
  const result = await api.run_action('output_dir', props.projectName)
  if (!result.ok) emit('notify', result.error ?? '无法打开输出目录。')
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
  sampleExpanded.value = false
  emit('close')
}

watch(() => props.open, (open) => {
  stopPolling()
  minimized.value = false
  if (!open) {
    sampleExpanded.value = false
    sampleData.value = ''
    sampleName.value = ''
    sampleVersion.value = ''
    sampleWarning.value = ''
    fullSampleData.value = ''
    sampleCheckedAt = 0
    taskId.value = ''
    state.value = null
    taskLogs.value = []
    offset.value = 0
  }
})
onUnmounted(stopPolling)
</script>

<template>
  <Transition name="dialog">
    <div v-if="open && !minimized" class="train-backdrop">
      <section class="train-dialog" role="dialog" aria-modal="true" aria-labelledby="modern-train-title">
        <header class="train-header">
          <div><span class="train-kicker">新版训练页</span><h2 id="modern-train-title">{{ plan?.mode_label || '训练' }} · {{ projectName }}</h2></div>
          <button v-if="active" class="train-button" type="button" @click="minimized = true">最小化</button>
          <button class="train-close" type="button" aria-label="关闭" :disabled="active" @click="close">×</button>
        </header>

        <template v-if="!taskId && plan">
          <p class="train-description">{{ engineDescription }}</p>
          <div class="train-summary">
            <div><span>训练模型</span><strong>{{ plan.model_label }}</strong><small>{{ plan.model_path }}</small></div>
            <div><span>{{ plan.data_label || '图集' }}</span><strong>{{ plan.data_count ?? plan.image_count }} {{ plan.data_unit || '张' }}（至少 {{ plan.min_images }}）</strong><small>{{ plan.raw_dir }}</small></div>
            <div><span>训练参数</span><strong>rank / alpha {{ plan.rank }} / {{ plan.alpha }} · 学习率 {{ plan.learning_rate }}</strong><small>{{ plan.resolution }} px · {{ plan.schedule_value || `${plan.steps} 步` }} · {{ trainingTypeLabel }}<template v-if="plan.training_target"> · {{ plan.training_target }}</template></small></div>
            <div><span>显卡</span><strong>{{ plan.gpu_vendor }}<template v-if="plan.vram_gb != null"> · {{ plan.vram_gb.toFixed(1) }} GB</template></strong><small>Trigger：{{ plan.trigger || '未填写' }}</small></div>
            <div v-if="plan.sampling_rule"><span>采样预览</span><strong>{{ plan.sampling_rule.enabled ? '开启' : '关闭' }} · {{ plan.sampling_rule.reason }}</strong><small>{{ plan.sampling_rule.cadence }}</small></div>
          </div>
          <details v-if="plan.config_summary" class="train-config-summary"><summary>查看本次训练设置</summary><dl><template v-for="[label, value] in settingSummary" :key="label"><dt>{{ label }}</dt><dd>{{ value }}</dd></template></dl><p>自动项会由训练引擎按模型和显存确定，实际结果以训练日志为准。</p></details>
          <div v-if="plan.model_download_required" class="train-warning"><strong>本机尚未准备好训练模型</strong><span>开始后可能会下载约 {{ plan.model_size || '较大体积' }} 的模型文件；下载由训练引擎执行，日志会显示进度。</span></div>
          <div v-for="warning in plan.warnings" :key="warning" class="train-warning"><span>{{ warning }}</span></div>
          <label v-if="hasResume" class="resume-choice"><input v-model="useResume" type="checkbox"><span><strong>发现可续训快照，默认从断点继续</strong><small>取消勾选即可从头训练 · {{ plan.resume_path }}</small></span></label>
          <div class="train-note">预处理完成后会先暂停，供你查看、修改自动标签并二次确认。{{ plan.training_engine === 'ai_toolkit' ? '当前 AI Toolkit 模式暂不支持从训练状态快照续训。' : '训练产生保存快照后，才有可续训的断点。' }}</div>
          <footer class="train-actions">
            <button class="train-button" type="button" @click="close">返回检查设置</button>
            <button class="train-button primary" type="button" :disabled="starting" @click="start">{{ starting ? '正在启动…' : '确认并开始训练' }}</button>
          </footer>
        </template>

        <template v-else-if="taskId">
          <div class="train-progress-heading">
            <div class="train-state" :class="state?.status">
              <span v-if="running" class="train-spinner"></span>
              <span>{{ state?.message || '训练任务已启动…' }}</span>
            </div>
            <div v-if="remainingTime" class="train-eta"><span>预计剩余</span><strong>{{ remainingTime }}</strong></div>
          </div>
          <div class="train-progress"><span :class="{ indeterminate: running && state?.progress == null }" :style="state?.progress != null ? { width: `${Math.floor(state.progress * 100)}%` } : undefined"></span></div>
          <p v-if="state?.detail" class="train-detail">{{ state.detail }}</p>
          <div v-if="awaitingReview" class="review-callout">
            <strong>训练尚未开始</strong>
            <span>{{ plan?.mode === 'video' ? '请确认视频字幕和训练数据后继续。' : plan?.mode === 'h3_fz' ? '请确认混合媒体样本与同名字幕后继续；格式会在引擎缓存阶段校验。' : '请检查预处理后的图片和标签；需要时打开标签编辑器修改，回来后确认继续训练。' }}</span>
          </div>
          <TrainingMetrics :metrics="state?.metrics" :history="state?.loss_history" />
          <section v-if="!awaitingReview" class="train-sample" aria-label="训练采样预览">
            <div class="train-sample-heading"><strong>采样预览</strong><span v-if="sampleName">{{ sampleName }}</span><button class="train-button" type="button" @click="openOutputDirectory">打开输出目录</button><button v-if="sampleData" class="train-button" type="button" @click="expandSample">查看大图</button></div>
            <button v-if="sampleData" class="train-sample-image-button" type="button" aria-label="查看采样预览大图" @click="expandSample"><img class="train-sample-image" :src="sampleData" :alt="`当前训练采样：${sampleName}`"></button>
            <p v-else class="train-sample-empty">{{ sampleEmptyText }}</p>
            <p v-if="sampleFailure" class="train-sample-warning">引擎报告采样失败：{{ sampleFailure }}</p>
            <p v-else-if="sampleWarning" class="train-sample-warning">{{ sampleWarning }}</p>
          </section>
          <div ref="logElement" class="train-log" role="log" aria-live="polite">
            <div v-if="!logEntries.length" class="train-log-line tone-muted">等待训练日志…</div>
            <div v-for="entry in logEntries" :key="entry.key" class="train-log-line" :class="`tone-${entry.tone}`">
              <span v-for="(part, partIndex) in entry.parts" :key="partIndex" :class="{ 'log-emphasis': part.emphasis }">{{ part.text }}</span>
            </div>
          </div>
          <footer class="train-actions">
            <template v-if="awaitingReview">
              <button v-if="!isRawMediaMode" class="train-button" type="button" @click="openLabelEditor">打开标签编辑器</button>
              <button class="train-button" type="button" @click="cancel">取消训练</button>
              <button class="train-button primary" type="button" @click="continueAfterReview">{{ plan?.mode === 'h3_fz' ? '确认数据并继续训练' : isRawMediaMode ? '确认字幕并继续训练' : '确认标签并继续训练' }}</button>
            </template>
            <button v-else-if="running" class="train-button" type="button" @click="cancel">停止训练</button>
            <button class="train-button primary" type="button" :disabled="active" @click="close">{{ active ? (awaitingReview ? '等待标签确认…' : '训练运行中…') : '关闭' }}</button>
          </footer>
        </template>
      </section>
    </div>
  </Transition>
  <div v-if="open && !minimized && sampleExpanded" class="sample-lightbox" role="dialog" aria-modal="true" aria-label="采样预览大图" @click.self="sampleExpanded = false">
    <button type="button" class="sample-lightbox-close" aria-label="关闭大图" @click="sampleExpanded = false">×</button>
    <img :src="fullSampleData || sampleData" :alt="`采样预览：${sampleName}`">
    <span>{{ sampleName }}</span>
  </div>
  <button v-if="open && minimized" class="training-mini" type="button" @click="expand"><strong>{{ projectName }} · {{ starting ? '正在启动' : awaitingReview ? '等待确认' : running ? '训练中' : '训练已结束' }}</strong><span>{{ state?.metrics?.total ? `${state.metrics.step} / ${state.metrics.total} 步` : state?.message }} · 查看进度</span></button>
</template>

<style scoped>
.training-mini { position:fixed; right:22px; bottom:24px; z-index:34; display:grid; gap:5px; max-width:340px; padding:12px 16px; border:1px solid var(--accent); border-radius:7px; background:var(--card); color:var(--text); text-align:left; cursor:pointer; box-shadow:0 4px 20px rgb(0 0 0 / 25%); } .training-mini strong { font-size:12px; font-weight:500; } .training-mini span { font-size:10px; color:var(--sub); overflow-wrap:anywhere; }
.train-backdrop { position: fixed; inset: 0; z-index: 35; display: grid; place-items: center; padding: 18px; background: rgb(10 12 16 / 54%); }
.train-dialog { display: flex; width: min(100%, 650px); max-height: min(84vh, 760px); overflow-y: auto; flex-direction: column; gap: 11px; padding: 17px; border: 1px solid var(--tone-41464f); border-radius: 8px; background: var(--tone-272a32); box-shadow: 0 16px 44px rgb(0 0 0 / 34%); }
.train-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }.train-kicker { color: var(--tone-858a93); font-size: 10px; }.train-header h2 { margin: 3px 0 0; color: var(--tone-cbd0d7); font-size: 16px; font-weight: 350; }.train-close { width: 29px; height: 29px; border: 0; border-radius: 5px; color: var(--tone-999da6); background: transparent; font-size: 21px; cursor: pointer; }.train-close:hover:not(:disabled) { color: var(--tone-d0d3d9); background: var(--tone-32363e); }.train-close:disabled { opacity: .45; cursor: wait; }
.train-description { margin: 0; color: var(--tone-a0a5ae); font-size: 11px; line-height: 1.5; }.train-summary { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }.train-summary > div { display: grid; min-width: 0; gap: 3px; padding: 9px; border: 1px solid var(--tone-373b44); border-radius: 5px; background: var(--tone-22252c); }.train-summary span { color: var(--tone-858b95); font-size: 9px; }.train-summary strong { overflow: hidden; color: var(--tone-c1c6cf); font-size: 10px; font-weight: 400; text-overflow: ellipsis; white-space: nowrap; }.train-summary small { overflow: hidden; color: var(--tone-858b95); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.train-warning { display: grid; gap: 3px; padding: 8px 9px; border: 1px solid var(--tone-50473d); border-radius: 5px; color: var(--tone-c6bba9); background: var(--tone-302b27); font-size: 10px; line-height: 1.45; }.train-warning strong { font-weight: 450; }.resume-choice { display: flex; align-items: flex-start; gap: 8px; padding: 8px 9px; border: 1px solid var(--tone-3b414b); border-radius: 5px; color: var(--tone-bac0c9); background: var(--tone-23262d); cursor: pointer; }.resume-choice input { margin: 2px 0 0; accent-color: var(--tone-78869b); }.resume-choice span { display: grid; min-width: 0; gap: 3px; }.resume-choice strong { font-size: 10px; font-weight: 400; }.resume-choice small { overflow: hidden; color: var(--tone-858b95); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }.train-note { padding: 8px 9px; border-radius: 5px; color: var(--tone-949aa4); background: var(--tone-22252c); font-size: 10px; line-height: 1.45; }
.train-progress-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; }.train-state { display: flex; flex: 1; min-width: 0; align-items: center; gap: 8px; min-height: 27px; color: var(--tone-b4bac4); font-size: 11px; overflow-wrap: anywhere; }.train-state.completed { color: var(--tone-a8bea9); }.train-state.failed, .train-state.cancelled { color: var(--tone-c6a8aa); }.train-spinner { flex: none; width: 13px; height: 13px; border: 1.5px solid var(--tone-515763); border-top-color: var(--tone-aeb5c0); border-radius: 50%; animation: train-spin .8s linear infinite; }.train-eta { display: flex; flex: none; align-items: baseline; gap: 5px; padding: 5px 8px; border: 1px solid var(--tone-47443c); border-radius: 5px; color: var(--tone-c3bcaa); background: var(--tone-2d2a25); font-size: 10px; white-space: nowrap; }.train-eta strong { color: var(--tone-d4b06a); font-size: 12px; font-variant-numeric: tabular-nums; font-weight: 600; }.train-progress { height: 4px; overflow: hidden; border-radius: 5px; background: var(--tone-1d2026); }.train-progress > span { display: block; height: 100%; border-radius: inherit; background: var(--tone-75849a); transition: width 180ms ease; }.train-progress > span.indeterminate { width: 32%; animation: train-slide 1.2s ease-in-out infinite alternate; }.train-detail { margin: -5px 0 0; color: var(--tone-9299a4); font-size: 9px; }.train-log { min-height: 190px; max-height: 48vh; margin: 0; padding: 9px; overflow: auto; border: 1px solid var(--tone-393d47); border-radius: 5px; color: var(--tone-aeb4be); background: var(--tone-1d2026); font: 10px/1.5 Consolas, "Microsoft YaHei UI", sans-serif; white-space: pre-wrap; overflow-wrap: anywhere; user-select: text; }.train-log-line { min-height: 1.5em; white-space: pre-wrap; overflow-wrap: anywhere; }.tone-default { color: var(--tone-aeb4be); }.tone-muted { color: var(--tone-858c98); }.tone-warning { color: var(--tone-d4b06a); }.tone-error { color: var(--tone-e08a8a); }.tone-success { color: var(--tone-9ecb8f); }.tone-training { color: var(--tone-8fb0c9); }.tone-info { color: var(--tone-8fa8d4); }.log-emphasis { color: inherit; font-weight: 600; }
.train-state.awaiting_review { color: var(--tone-c0baa8); }.review-callout { display: grid; gap: 4px; padding: 9px 10px; border: 1px solid var(--tone-47443c); border-radius: 5px; color: var(--tone-c3bcaa); background: var(--tone-2d2a25); font-size: 10px; line-height: 1.45; }.review-callout strong { font-weight: 450; }
.train-actions { display: flex; flex-wrap: wrap; flex-shrink: 0; justify-content: flex-end; gap: 7px; margin-top: 2px; }.train-button { min-height: 30px; padding: 0 10px; border: 1px solid var(--tone-3d424b); border-radius: 5px; color: var(--tone-b8bdc6); background: transparent; font-size: 10px; cursor: pointer; }.train-button:hover:not(:disabled) { border-color: var(--tone-555c68); background: var(--tone-2e323a); }.train-button.primary { border-color: transparent; color: var(--tone-eff0f2); background: var(--tone-626f81); }.train-button:disabled { opacity: .55; cursor: wait; }
@keyframes train-spin { to { transform: rotate(360deg); } } @keyframes train-slide { to { transform: translateX(210%); } }
@media (max-width: 560px) { .train-summary { grid-template-columns: 1fr; } .train-progress-heading { align-items: flex-start; flex-direction: column; gap: 3px; } }
@media (prefers-reduced-motion: reduce) { .train-spinner, .train-progress > span.indeterminate { animation-duration: 1.8s; } }
.train-config-summary { border: 1px solid var(--tone-373b44); border-radius: 5px; padding: 9px; color: var(--tone-b8bdc6); font-size: 11px; }
.train-config-summary summary { cursor: pointer; }
.train-config-summary dl { display: grid; grid-template-columns: 100px 1fr; gap: 6px; }
.train-config-summary dt { color: var(--tone-9299a4); }.train-config-summary dd { margin: 0; }
.train-config-summary p { margin: 6px 0 0; color: var(--tone-9299a4); font-size: 10px; }
.train-sample { display: grid; gap: 7px; padding: 9px; border: 1px solid var(--tone-393d47); border-radius: 5px; background: var(--tone-22252c); }
.train-sample-heading { display: flex; align-items: center; gap: 8px; min-width: 0; color: var(--tone-b8bdc6); font-size: 11px; }
.train-sample-heading strong { flex: none; font-weight: 500; }.train-sample-heading span { flex: 1; min-width: 0; overflow: hidden; color: var(--tone-9299a4); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.train-sample-heading button { margin-left: auto; }
.train-sample-image-button { display: block; width: fit-content; max-width: 100%; margin: auto; padding: 0; border: 0; background: transparent; cursor: zoom-in; }.train-sample-image { display: block; width: auto; max-width: 100%; max-height: 250px; margin: auto; border-radius: 4px; object-fit: contain; cursor: zoom-in; }
.train-sample-empty, .train-sample-warning { margin: 0; color: var(--tone-9299a4); font-size: 10px; line-height: 1.45; }.train-sample-warning { color: var(--tone-d4b06a); overflow-wrap: anywhere; }
.sample-lightbox { position: fixed; inset: 0; z-index: 36; display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 10px; padding: 45px 20px 20px; background: rgb(10 12 16 / 90%); color: var(--tone-cbd0d7); font-size: 11px; }.sample-lightbox img { display: block; max-width: 100%; max-height: 100%; object-fit: contain; }.sample-lightbox-close { position: absolute; top: 12px; right: 18px; border: 0; background: transparent; color: var(--tone-cbd0d7); font-size: 28px; cursor: pointer; }
</style>
