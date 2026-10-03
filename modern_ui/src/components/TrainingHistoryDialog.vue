<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { TrainingRun, TrainingRunSummary } from '../bridge'
import TrainingMetrics from './TrainingMetrics.vue'

const props = defineProps<{ open: boolean; projectName: string }>()
const emit = defineEmits<{ close: []; restored: []; notify: [message: string] }>()
const runs = ref<TrainingRunSummary[]>([])
const selected = ref<TrainingRun | null>(null)
const loading = ref(false)
const error = ref('')
const restoring = ref(false)
let request = 0
const statusLabels: Record<string, string> = { running: '运行中', awaiting_review: '等待确认', completed: '已完成', failed: '失败', cancelled: '已停止', interrupted: '意外中断' }
const settings = computed(() => {
  const p = selected.value?.normalized_params || {}
  return [ ['分辨率', p.resolution], ['rank / alpha', `${p.rank ?? '—'} / ${p.alpha ?? '—'}`],
    ['学习率', p.unet_lr], ['量化', p.quant_mode], ['训练轮数', p.max_epochs],
    ['重复次数', p.repeats], ['批大小', p.batch_size],
    ['标签处理', p.keep_user_captions ? '保留已有标签' : '预处理与打标'] ]
})
function date(value?: number) { return value ? new Date(value * 1000).toLocaleString() : '—' }
async function load() {
  const token = ++request
  selected.value = null
  error.value = ''
  runs.value = []
  const api = window.pywebview?.api
  if (!api) { error.value = '训练记录仅在桌面版可用。'; return }
  loading.value = true
  try {
    const result = await api.list_training_runs(props.projectName)
    if (token !== request || !props.open) return
    if (!result.ok) error.value = result.error || '读取记录失败。'
    else runs.value = result.runs || []
  } catch (e) { if (token === request) error.value = e instanceof Error ? e.message : '读取记录失败。' }
  finally { if (token === request) loading.value = false }
}
async function select(run: TrainingRunSummary) {
  const token = ++request
  error.value = ''
  selected.value = null
  loading.value = true
  try {
    const result = await window.pywebview!.api.get_training_run(run.id)
    if (token !== request || !props.open) return
    if (!result.ok) error.value = result.error || '读取详情失败。'
    else if (result.run) selected.value = { ...result.run, status: run.status, message: run.message }
  } catch (e) { if (token === request) error.value = e instanceof Error ? e.message : '读取详情失败。' }
  finally { if (token === request) loading.value = false }
}
async function restore() {
  if (!selected.value || restoring.value) return
  restoring.value = true
  try {
    const result = await window.pywebview!.api.restore_training_run(selected.value.id, props.projectName)
    if (!result.ok) emit('notify', result.error || '恢复设置失败。')
    else { emit('restored'); emit('notify', '已恢复这次训练的设置，图集、模型和环境路径沿用当前项目。'); emit('close') }
  } catch (e) { emit('notify', e instanceof Error ? e.message : '恢复设置失败。') }
  finally { restoring.value = false }
}
watch(() => props.open, (open) => { if (open) void load(); else { ++request; loading.value = false } })
</script>

<template>
  <div v-if="open" class="history-backdrop">
    <section class="history-dialog" role="dialog" aria-modal="true" aria-labelledby="history-title">
      <header><div><h2 id="history-title">训练记录{{ projectName ? ` · ${projectName}` : '' }}</h2><p>仅记录启用此功能后从新版训练页启动的任务；显示最近 100 次。</p></div><button type="button" aria-label="关闭训练记录" @click="emit('close')">×</button></header>
      <p v-if="error" class="history-error" role="alert">{{ error }}</p>
      <div class="history-body">
        <nav aria-label="训练记录列表">
          <p v-if="!runs.length && !loading">暂无记录。开始一次训练后会在这里保留配置和结果。</p>
          <button v-for="run in runs" :key="run.id" type="button" :class="{ selected: selected?.id === run.id }" @click="select(run)"><strong>{{ run.project_name }}</strong><span>{{ run.mode_label }} · {{ statusLabels[run.status] || run.status }}</span><small>{{ date(run.started) }}</small></button>
        </nav>
        <article>
          <p v-if="loading" role="status">正在读取…</p>
          <template v-else-if="selected">
            <h3>{{ statusLabels[selected.status] || selected.status }} · {{ selected.mode_label }}</h3>
            <p>{{ selected.message }}</p><p class="history-muted">开始 {{ date(selected.started) }} · 结束 {{ date(selected.ended) }}</p>
            <TrainingMetrics :metrics="selected.metrics" :history="selected.loss_history" />
            <h3>本次设置</h3><dl><template v-for="[label, value] in settings" :key="String(label)"><dt>{{ label }}</dt><dd>{{ value ?? '自动' }}</dd></template></dl>
            <p class="history-muted">这里保存的是提交给引擎的设置；自动项以本次训练日志为准。恢复设置不会启动训练，路径沿用当前项目。</p>
            <button v-if="projectName && selected.project_name === projectName" type="button" :disabled="restoring || selected.status === 'running' || selected.status === 'awaiting_review'" @click="restore">{{ restoring ? '恢复中…' : '恢复本次训练设置' }}</button>
            <details v-if="selected.logs?.length"><summary>本次日志末尾（最多 300 行）</summary><pre>{{ selected.logs.join('\n') }}</pre></details>
          </template>
          <p v-else>选择一次训练，查看设置、曲线和结果。</p>
        </article>
      </div>
    </section>
  </div>
</template>

<style scoped>
.history-backdrop { position:fixed; inset:0; z-index:38; display:grid; place-items:center; padding:20px; background:rgb(10 12 16 / 60%); }
.history-dialog { width:min(100%,900px); max-height:85vh; display:flex; flex-direction:column; border:1px solid var(--border); border-radius:9px; padding:18px; background:var(--card); color:var(--text); }
header { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; } header > button { width:30px; height:30px; flex-shrink:0; padding:0; } h2 { margin:0; font-size:17px; font-weight:450; } h3 { font-size:13px; font-weight:500; } p { font-size:11px; line-height:1.6; } header p,.history-muted { color:var(--sub); }
button { padding:8px 11px; border:1px solid var(--border); border-radius:5px; background:var(--bg); color:var(--text); cursor:pointer; font-size:11px; } button:hover { border-color:var(--accent); } button:disabled { opacity:.5; cursor:wait; }
.history-body { display:grid; grid-template-columns:230px minmax(0,1fr); gap:18px; min-height:0; overflow:hidden; }
nav,article { overflow:auto; min-height:0; } nav { display:flex; flex-direction:column; gap:6px; } nav button { display:grid; text-align:left; gap:5px; flex-shrink:0; } nav button.selected { border-color:var(--accent); background:var(--card-hover); } nav strong { font-weight:450; } nav span,nav small { color:var(--sub); }
dl { display:grid; grid-template-columns:95px 1fr; gap:7px; font-size:11px; } dt { color:var(--sub); } dd { margin:0; overflow-wrap:anywhere; }
details { margin-top:14px; font-size:11px; } summary { cursor:pointer; } pre { max-height:220px; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; font-size:10px; user-select:text; } .history-error { color:var(--tone-e08a8a); }
@media(max-width:650px) { .history-body { grid-template-columns:1fr; overflow:auto; } nav { max-height:180px; flex-shrink:0; } article { overflow:visible; } }
</style>
