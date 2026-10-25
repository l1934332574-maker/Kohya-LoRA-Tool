<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import MaskEditor from './MaskEditor.vue'
import type { DatasetSummary, DatasetPreview } from '../bridge'
const props = defineProps<{ directory?: string; taskId?: string; desktop: boolean; recursive?: boolean; rawMedia?: boolean; projectName?: string; showMasks?: boolean }>()
const opened = ref(false)
const source = ref<'raw' | 'processed'>(props.taskId ? 'processed' : 'raw')
const catalog = ref<DatasetSummary | null>(null)
const names = ref<string[]>([])
const selected = ref('')
const image = ref<DatasetPreview | null>(null)
const view = ref<'original' | 'overlay' | 'mask'>('overlay')
const editing = ref(false), saving = ref(false)
const canvas = ref<HTMLCanvasElement | null>(null)
const brush = ref('white'), brushSize = ref(28)
const undo = ref<string[]>([])
let painting = false
let lastPoint: [number, number] | null = null
const maskView = computed(() => Boolean(props.showMasks))
const displayUrl = computed(() => view.value === 'mask' ? image.value?.mask_data_url || image.value?.data_url : view.value === 'overlay' ? image.value?.overlay_data_url || image.value?.data_url : image.value?.data_url)
const warning = ref('')
const loading = ref(false)
const reading = ref(false)
let request = 0
let imageRequest = 0
const issuesOnly = ref(false)
const visibleNames = computed(() => issuesOnly.value ? (catalog.value?.mask_report?.rows || []).filter(r => r.status !== 'valid' && !['exclude','unmasked'].includes(r.decision)).map(r => r.name) : names.value)
const index = computed(() => visibleNames.value.indexOf(selected.value))
const rawSource = computed(() => props.rawMedia || catalog.value?.source_kind === 'raw_media')
const sourceLabel = computed(() => rawSource.value ? '当前项目训练目录中的原图' : source.value === 'processed' ? '预处理后，当前项目用于训练的图片' : '源文件夹中的原图')
async function inspect() {
  const api = window.pywebview?.api
  if (!api || !props.desktop) return
  const token = ++request
  imageRequest++
  loading.value = true
  catalog.value = null
  image.value = null
  names.value = []
  selected.value = ''
  warning.value = ''
  try {
    const result = props.projectName && props.showMasks ? await api.inspect_mask_dataset(props.projectName) : source.value === 'processed' && props.taskId ? await api.inspect_task_dataset(props.taskId) : await api.inspect_dataset(props.directory || '', Boolean(props.recursive), Boolean(props.rawMedia))
    if (token !== request) return
    if (!result.ok) { warning.value = result.error || '无法检查图片。'; return }
    catalog.value = result
    names.value = result.preview_images || []
    if (names.value[0]) selected.value = names.value[0]
  } catch (error) {
    if (token === request) warning.value = error instanceof Error ? error.message : '无法检查图片。'
  } finally { if (token === request) loading.value = false }
}
async function load() {
  const token = ++imageRequest
  editing.value = false; undo.value = []; painting = false; lastPoint = null
  image.value = null
  reading.value = false
  if (!selected.value || !catalog.value?.preview_token) return
  reading.value = true
  try {
    const result = await window.pywebview?.api.get_dataset_preview(catalog.value.preview_token, selected.value)
    if (token !== imageRequest) return
    if (!result?.ok) warning.value = result?.error || '无法读取图片。'
    else { image.value = result; warning.value = '' }
  } catch (error) {
    if (token === imageRequest) warning.value = error instanceof Error ? error.message : '无法读取图片。'
  } finally { if (token === imageRequest) reading.value = false }
}
async function more() {
  if (!catalog.value?.preview_token || catalog.value.next_offset == null) return
  const token = request
  loading.value = true
  try {
    const result = await window.pywebview?.api.list_dataset_preview(catalog.value.preview_token, catalog.value.next_offset)
    if (token !== request) return
    if (!result?.ok) { warning.value = result?.error || '无法读取更多图片。'; return }
    names.value.push(...(result.images || []))
    catalog.value.next_offset = result.next_offset ?? null
  } catch (error) {
    if (token === request) warning.value = error instanceof Error ? error.message : '无法读取更多图片。'
  } finally { if (token === request) loading.value = false }
}
async function decide(decision: string) {
  if (!catalog.value?.preview_token || !selected.value) return
  saving.value = true; warning.value = ''
  try {
    const result = await window.pywebview?.api.set_dataset_mask_decision(catalog.value.preview_token, selected.value, decision)
    if (!result?.ok) warning.value = result?.error || '无法保存处理决定。'
    else { image.value = result; if (result.mask_report) catalog.value.mask_report = result.mask_report }
  } catch (error) { warning.value = String(error) }
  finally { saving.value = false }
}
function readImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => { const img = new Image(); img.onload = () => resolve(img); img.onerror = () => reject(new Error('无法读取遮罩。')); img.src = url })
}
async function beginEdit() {
  if (!image.value?.mask_editable || !image.value.width || !image.value.height) return
  editing.value = true; undo.value = []; await nextTick()
  const el = canvas.value; if (!el) return
  el.width = image.value.width; el.height = image.value.height
  const ctx = el.getContext('2d'); if (!ctx) return
  ctx.fillStyle = 'black'; ctx.fillRect(0, 0, el.width, el.height)
  if (image.value.mask_edit_data_url || image.value.mask_data_url) {
    try { const src = await readImage(image.value.mask_edit_data_url || image.value.mask_data_url!); ctx.drawImage(src, 0, 0, el.width, el.height) }
    catch (error) { warning.value = String(error); editing.value = false }
  }
}
function point(event: PointerEvent): [number, number] {
  const el = canvas.value!, rect = el.getBoundingClientRect()
  return [(event.clientX - rect.left) * el.width / rect.width, (event.clientY - rect.top) * el.height / rect.height]
}
function paint(event: PointerEvent) {
  if (!painting || !canvas.value) return
  const ctx = canvas.value.getContext('2d'); if (!ctx) return
  const p = point(event)
  ctx.strokeStyle = brush.value; ctx.fillStyle = brush.value; ctx.lineWidth = brushSize.value; ctx.lineCap = 'round'
  if (lastPoint) { ctx.beginPath(); ctx.moveTo(...lastPoint); ctx.lineTo(...p); ctx.stroke() }
  else { ctx.beginPath(); ctx.arc(...p, brushSize.value / 2, 0, Math.PI * 2); ctx.fill() }
  lastPoint = p
}
function paintStart(event: PointerEvent) {
  if (saving.value || !canvas.value || event.button !== 0) return
  undo.value = [...undo.value.slice(-2), canvas.value.toDataURL('image/png')]
  canvas.value.setPointerCapture(event.pointerId); painting = true; lastPoint = null; paint(event)
}
async function undoStroke() {
  const previous = undo.value.pop(); if (!previous || !canvas.value) return
  const src = await readImage(previous); canvas.value.getContext('2d')?.drawImage(src, 0, 0)
}
async function saveMask() {
  if (!canvas.value || !catalog.value?.preview_token) return
  saving.value = true; warning.value = ''
  try {
    const result = await window.pywebview?.api.save_dataset_mask(catalog.value.preview_token, selected.value, canvas.value.toDataURL('image/png'))
    if (!result?.ok) warning.value = result?.error || '无法保存遮罩。'
    else { image.value = result; editing.value = false; undo.value = []; if (result.mask_report) catalog.value.mask_report = result.mask_report }
  } catch (error) { warning.value = String(error) }
  finally { saving.value = false }
}
watch(visibleNames, (names) => { if (issuesOnly.value && !names.includes(selected.value)) selected.value = names[0] || '' })
watch(selected, () => { void load() })
watch([opened, source, () => props.directory, () => props.taskId, () => props.projectName], ([open]) => {
  request++; imageRequest++
  if (open) void inspect()
})
</script>

<template>
  <MaskEditor v-if="showMasks && projectName && desktop" :project-name="projectName" />
  <section v-else-if="desktop && (directory || taskId || projectName)" class="dataset-browser" aria-label="图片与标签检查">
    <button type="button" :aria-expanded="opened" @click="opened = !opened">{{ opened ? (maskView ? '收起学习区域' : '收起图片与标签') : maskView ? '查看学习区域 / 处理问题图' : taskId && !rawSource ? '查看原图 / 处理后训练图片' : '查看原图与标签' }}</button>
    <template v-if="opened">
      <div class="dataset-browser-controls"><label v-if="taskId && !rawSource">图片来源<select v-model="source"><option value="processed">处理后的训练图片</option><option v-if="directory" value="raw">源文件夹原图</option></select></label><button type="button" :disabled="loading || editing || saving" @click="inspect()">{{ loading ? '正在读取…' : '重新读取' }}</button><button v-if="catalog?.next_offset != null" type="button" :disabled="loading" @click="more">加载更多图片</button></div>
      <p v-if="!maskView">{{ sourceLabel }}。这里展示已有文件，不会重新缩放、裁切或改写标签。</p>
      <p v-if="maskView && catalog?.mask_report">有效 {{ catalog.mask_report.valid }}/{{ catalog.mask_report.total }} · {{ catalog.mask_report.issues }} 张待检查 · 排除 {{ catalog.mask_report.excluded }} · 整图学习 {{ catalog.mask_report.unmasked }}</p>
      <p v-if="rawMedia || catalog?.source_kind === 'raw_media'">H3 使用原始媒体缓存训练；请结合当前训练分辨率检查脸部和妆容细节。</p>
      <p v-else-if="!maskView && source === 'raw'">原图细节不等于训练实际看到的细节。预处理完成后，请在训练确认窗口切换到处理后的图片检查。</p>
      <p v-else-if="!maskView">请观察脸部、眼睛等目标细节在当前尺寸下是否仍清楚。默认 512 是资源起点，可自行提高分辨率并重新预处理。</p>
      <label v-if="maskView && catalog?.mask_report?.rows" class="dataset-browser-controls"><input v-model="issuesOnly" type="checkbox" :disabled="editing || saving">只看需要处理的图片</label>
      <p v-if="warning" class="dataset-warning">{{ warning }}</p>
      <template v-if="visibleNames.length"><label>图片（共 {{ catalog?.images }} 张）<select v-model="selected" :disabled="editing || saving"><option v-for="name in visibleNames" :key="name" :value="name">{{ name }}</option></select></label><div class="dataset-browser-controls"><button type="button" :disabled="index <= 0 || editing || saving" @click="selected = visibleNames[index - 1] || selected">上一张</button><button type="button" :disabled="index >= visibleNames.length - 1 || editing || saving" @click="selected = visibleNames[index + 1] || selected">下一张</button></div><p v-if="reading">正在读取图片…</p><div v-if="image?.data_url && !editing" class="dataset-inspect-image"><img :src="maskView ? displayUrl : image.data_url" :alt="selected"><span>文件尺寸：{{ image.width }} × {{ image.height }}；屏幕预览会缩放显示</span></div><div v-if="maskView && image" class="mask-controls">
        <label>显示<select v-model="view" :disabled="editing"><option value="original">原图</option><option value="overlay">学习区域高亮</option><option value="mask">黑白遮罩</option></select></label>
        <p v-if="image.problem" class="dataset-warning">{{ image.problem }}</p><p v-if="image.warning">{{ image.warning }}</p>
        <p v-if="image.coverage != null">白色学习区域约 {{ Math.round(image.coverage * 100) }}%；请检查实际覆盖。</p>
        <p v-if="image.mask_balanced">此图的均衡副本会同步修改；统计包含副本。</p>
        <label>此图片的处理<select :value="image.decision || 'default'" :disabled="!image.mask_editable || saving || editing" @change="decide(($event.target as HTMLSelectElement).value)"><option value="default">使用遮罩（问题需修正）</option><option value="exclude">排除此图</option><option value="unmasked">明确允许整图学习</option></select></label>
        <button v-if="!editing" type="button" :disabled="!image.mask_editable || saving" @click="beginEdit">手动修正学习区域</button>
        <template v-else>
          <p>白笔增加学习区域，黑笔排除；修改只保存到项目训练副本，原遮罩会备份。</p>
          <div class="dataset-browser-controls"><label>画笔<select v-model="brush" :disabled="saving"><option value="white">白笔 · 学习</option><option value="black">黑笔 · 排除</option></select></label><label>大小<input v-model.number="brushSize" type="range" min="2" max="150" :disabled="saving"></label><button type="button" :disabled="!undo.length || saving" @click="undoStroke">撤销</button></div>
          <div class="paint-stage" :style="{aspectRatio: `${image.width} / ${image.height}`}"><img :src="image.data_url" alt="训练副本"><canvas ref="canvas" aria-label="学习区域画布" @pointerdown.prevent="paintStart" @pointermove.prevent="paint" @pointerup="painting = false; lastPoint = null" @pointercancel="painting = false; lastPoint = null" /></div>
          <div class="dataset-browser-controls"><button type="button" :disabled="saving" @click="saveMask">{{ saving ? '保存中…' : '保存学习区域' }}</button><button type="button" :disabled="saving" @click="editing = false">取消修改</button></div>
        </template>
      </div><div v-if="image" class="dataset-caption"><strong>同名标签</strong><p>{{ image.caption || '没有标签或标签为空' }}</p></div></template>
      <p v-else-if="catalog?.ok">{{ issuesOnly ? '没有待处理的问题图。' : '没有找到可预览的图片。媒体模式的视频与音频需单独检查。' }}</p>
    </template>
  </section>
</template>

<style scoped>
.dataset-browser { display:grid; gap:9px; font-size:11px; color:var(--text); margin:8px 0; }p { margin:0; color:var(--hint); line-height:1.6; overflow-wrap:anywhere; }label { display:grid; gap:5px; min-width:0; }.dataset-browser-controls { display:flex; flex-wrap:wrap; align-items:end; gap:8px; }
select,button { font:inherit; padding:6px 9px; color:var(--text); background:var(--bg); border:1px solid var(--border); border-radius:4px; min-height:31px; }button { width:fit-content; cursor:pointer; }button:disabled { opacity:.5; cursor:default; }select { max-width:100%; }button:focus-visible,select:focus-visible { outline:2px solid var(--tone-8fb0c9); outline-offset:2px; }
.dataset-inspect-image { display:grid; gap:7px; }.dataset-inspect-image img { width:100%; max-height:440px; object-fit:contain; }.dataset-inspect-image span { color:var(--hint); }.dataset-caption { padding:9px; border:1px solid var(--border); border-radius:4px; }.dataset-caption p { white-space:pre-wrap; margin-top:5px; max-height:180px; overflow:auto; }.dataset-warning { color:var(--tone-d4b06a); }
.mask-controls{display:grid;gap:9px}.paint-stage{position:relative;width:min(100%,640px);background:#333}.paint-stage img,.paint-stage canvas{position:absolute;inset:0;width:100%;height:100%;object-fit:fill}.paint-stage canvas{opacity:.5;touch-action:none;cursor:crosshair}
</style>
