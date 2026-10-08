<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import type { SliderComparison, SliderResults } from '../bridge'
const props = defineProps<{ projectName: string; desktop: boolean }>()
const report = ref<SliderResults | null>(null)
const run = ref('')
const followLatest = ref(true)
const selection = ref('')
const image = ref('')
const error = ref('')
const loading = ref(false)
const selectedCheckpoint = ref('')
const direction = ref(false)
const preservation = ref(false)
const generalization = ref(false)
const saving = ref(false)
const enlarged = ref(false)
let disposed = false
let sequence = 0
let timer: ReturnType<typeof setTimeout> | undefined
const entries = computed(() => [...(report.value?.result?.comparisons || [])].reverse())
const selected = computed(() => entries.value.find(row => row.name === selection.value))
function checkpointEntries() {
  const rows = entries.value.filter(row => row.checkpoint === selectedCheckpoint.value)
  if (rows.length || selectedCheckpoint.value !== report.value?.result?.checkpoint) return rows
  const last = Math.max(0, ...entries.value.map(row => row.epoch))
  return entries.value.filter(row => row.epoch === last)
}
function resetRun() {
  sequence++; image.value = ''; selection.value = ''; selectedCheckpoint.value = ''
  direction.value = preservation.value = generalization.value = false
}
function label(row: SliderComparison) {
  return `第 ${row.epoch} 轮 · ${row.role === 'held_out_prompt' ? '新场景验证' : '训练画面'} · 种子 ${row.seed}`
}
async function loadImage() {
  const api = window.pywebview?.api
  if (!api || !selection.value || !run.value) return
  const current = ++sequence
  image.value = ''
  try {
    const result = await api.get_slider_sample(props.projectName, run.value, selection.value)
    if (current !== sequence || disposed) return
    if (result.ok) image.value = result.data_url || ''
    else error.value = result.error || '无法读取对照图。'
  } catch (exc) { if (current === sequence && !disposed) error.value = exc instanceof Error ? exc.message : '无法读取对照图。' }
}
async function refresh() {
  const api = window.pywebview?.api
  if (!props.desktop || !api || loading.value || disposed) return
  loading.value = true
  try {
    const result = await api.get_slider_results(props.projectName, followLatest.value ? '' : run.value)
    if (disposed) return
    if (!result.ok) { error.value = result.error || '无法读取滑块结果。'; return }
    report.value = result
    if (followLatest.value || !run.value) run.value = result.run_id || ''
    if (!selectedCheckpoint.value) selectedCheckpoint.value = result.review?.checkpoint || result.result?.checkpoint || result.checkpoints?.[0] || ''
    if (!selection.value && checkpointEntries()[0]) selection.value = checkpointEntries()[0].name
    error.value = ''
  } catch (exc) { if (!disposed) error.value = exc instanceof Error ? exc.message : '无法读取滑块结果。' }
  finally { loading.value = false }
}
async function exportCheckpoint() {
  const api = window.pywebview?.api
  if (!api || !run.value || !selectedCheckpoint.value || saving.value) return
  saving.value = true
  try {
    const result = await api.export_slider_checkpoint(props.projectName, run.value, selectedCheckpoint.value)
    error.value = result.ok ? result.message || '所选 LoRA 已导出。' : result.error || '导出失败。'
  } catch (exc) { error.value = exc instanceof Error ? exc.message : '导出失败。' }
  finally { saving.value = false }
}
async function saveReview() {
  const api = window.pywebview?.api
  if (!api || !run.value || !selectedCheckpoint.value || saving.value) return
  saving.value = true
  try {
    const result = await api.review_slider_result(props.projectName, run.value, {
      checkpoint: selectedCheckpoint.value, direction_ok: direction.value, preservation_ok: preservation.value, generalization_ok: generalization.value,
    })
    error.value = result.ok ? '已保存人工核对结果与选定的检查点。' : result.error || '核对结果保存失败。'
  } catch (exc) { error.value = exc instanceof Error ? exc.message : '核对结果保存失败。' }
  finally { saving.value = false }
}
watch(selection, () => {
  const row = selected.value
  if (row && row.checkpoint !== selectedCheckpoint.value && !checkpointEntries().some(item => item.name === row.name)) selectedCheckpoint.value = row.checkpoint
  void loadImage()
})
watch(run, (value, previous) => {
  if (value !== previous) resetRun()
}, { flush: 'sync' })
watch(selectedCheckpoint, () => {
  const saved = report.value?.review
  const same = saved?.checkpoint === selectedCheckpoint.value
  direction.value = same ? Boolean(saved?.direction_ok) : false
  preservation.value = same ? Boolean(saved?.preservation_ok) : false
  generalization.value = same ? Boolean(saved?.generalization_ok) : false
  selection.value = checkpointEntries()[0]?.name || ''
  if (!selection.value) { sequence++; image.value = '' }
}, { flush: 'sync' })
async function poll() { await refresh(); if (!disposed) timer = setTimeout(poll, 5000) }
void poll()
onUnmounted(() => { disposed = true; sequence++; if (timer) clearTimeout(timer) })
</script>

<template>
  <section class="slider-results" aria-labelledby="slider-results-title">
    <header><div><span class="step">04</span><h2 id="slider-results-title">效果对比</h2></div><button type="button" @click="refresh" :disabled="loading">刷新</button></header>
    <p v-if="entries.length">固定生成条件，仅改变 LoRA 权重；0 为底模基线。</p>
    <button v-if="report?.runs?.length && !followLatest" type="button" @click="followLatest=true;refresh()">返回最新训练</button>
    <div v-if="report?.runs?.length" class="result-controls">
      <label>训练记录<select v-model="run" @change="followLatest=false;refresh()"><option v-for="id in report.runs" :key="id" :value="id">{{ id }}</option></select></label>
      <label>对照画面<select v-model="selection"><option v-for="entry in entries" :key="entry.name" :value="entry.name">{{ label(entry) }}</option></select></label>
    </div>
    <template v-if="image && selected">
      <div class="weight-labels"><span v-for="weight in selected.multipliers" :key="weight">{{ weight === 0 ? '0 · 底模' : `${weight > 0 ? '+' : ''}${weight}` }}</span></div>
      <button class="strip-button" type="button" @click="enlarged=true" aria-label="放大权重对照图"><img :src="image" :alt="`${label(selected)}，各权重同种子对照`"></button>
      <p class="recipe">{{ selected.prompt }}<br>对应检查点 {{ selected.checkpoint }}<br>种子 {{ selected.seed }} · {{ selected.resolution }}px · {{ selected.steps }} 步 · CFG {{ selected.cfg }}</p>
    </template>
    <div v-else class="empty"><strong>{{ selectedCheckpoint ? '所选检查点暂无权重对照图' : report?.result?.status === 'running' ? '训练中，等待采样' : '暂无对照图' }}</strong><span>完成试训后查看权重对比。</span></div>
    <p v-if="report?.result?.status === 'failed'" class="error" role="status">训练失败：{{ report.result.error || '请查看训练日志' }}</p>
    <p v-if="report?.result?.preview_status === 'missing'" class="error">权重已保存，采样失败。详情见训练日志。</p>
    <details v-if="report?.result?.pair_validation?.length" class="review"><summary>留出验证</summary><p>未参与训练的样本误差，仅供参考。</p><p v-for="row in report.result.pair_validation" :key="row.epoch">第 {{ row.epoch }} 轮 · {{ row.pairs }} 对：停用 LoRA {{ row.baseline_loss.toFixed(4) }} → 使用 LoRA {{ row.slider_loss.toFixed(4) }}</p></details>
    <p v-if="report?.result?.holdout_validation_error" role="status">留出验证未完成。详情见训练日志。</p>
    <details v-if="report?.checkpoints?.length" class="review">
      <summary>检查点与效果评估</summary>
      <label>检查点<select v-model="selectedCheckpoint"><option v-for="name in report.checkpoints" :key="name" :value="name">{{ name }}</option></select></label>
      <div class="checks"><label><input v-model="direction" type="checkbox">变化方向与幅度符合预期</label><label><input v-model="preservation" type="checkbox">主体、画风与构图保持稳定</label><label><input v-model="generalization" type="checkbox">不同场景与种子下效果稳定</label></div>
      <button type="button" :disabled="saving || !selectedCheckpoint" @click="saveReview">保存评估</button> <button type="button" :disabled="saving || !selectedCheckpoint" @click="exportCheckpoint">导出 LoRA</button>
    </details>
    <p v-if="error" class="error" role="status">{{ error }}</p>
    <Teleport to="body"><div v-if="enlarged" class="slider-zoom" role="dialog" aria-modal="true" aria-label="权重对照大图" @click.self="enlarged=false" @keydown.esc="enlarged=false"><button type="button" autofocus @click="enlarged=false">关闭大图</button><img :src="image" alt="固定条件的权重对照大图"></div></Teleport>
  </section>
</template>

<style scoped>
.slider-results{display:grid;gap:14px;padding:24px;border:1px solid var(--border);border-radius:16px;background:var(--card);min-width:0}header,header>div{display:flex;align-items:center;gap:12px}header{justify-content:space-between}h2{font-size:17px;margin:0}.step{font-size:12px;color:var(--hint);font-variant-numeric:tabular-nums}p{margin:0;color:var(--hint);line-height:1.7;font-size:13px}button,select{font:inherit;font-size:13px;color:var(--text);border:1px solid var(--border);border-radius:8px;background:var(--bg);padding:9px 12px;cursor:pointer}.result-controls{display:grid;grid-template-columns:1fr 1fr;gap:12px}label{display:grid;gap:8px;font-size:13px}select{width:100%;min-width:0}.weight-labels{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));font-size:12px;text-align:center;color:var(--text)}.strip-button{padding:0;overflow:hidden;background:transparent}.strip-button img{display:block;width:100%;height:auto}.empty{display:grid;justify-items:center;gap:10px;padding:32px 16px;border:1px dashed var(--border);border-radius:10px;text-align:center}.empty strong{font-size:14px;font-weight:500}.empty span{color:var(--hint);font-size:13px}.recipe{overflow-wrap:anywhere;font-size:12px}.review{border-top:1px solid var(--border);padding-top:14px}.review summary{cursor:pointer;font-size:14px}.review>label,.checks,.review>p,.review>button{margin-top:14px}.checks{display:grid;gap:10px}.checks label{display:flex;align-items:center;gap:8px}.error{color:var(--text);overflow-wrap:anywhere}.slider-zoom{position:fixed;inset:0;background:rgba(0,0,0,.86);z-index:2200;display:grid;place-content:center;padding:24px;gap:16px}.slider-zoom button{justify-self:end}.slider-zoom img{max-width:95vw;max-height:83vh;object-fit:contain}button:focus-visible,select:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:3px}@media(max-width:700px){.slider-results{padding:18px}.result-controls{grid-template-columns:1fr}header{flex-wrap:wrap}}
</style>
