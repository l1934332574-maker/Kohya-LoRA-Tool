<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { DatasetSummary } from '../bridge'
const props = defineProps<{ directory?: string; taskId?: string; desktop: boolean }>()
const opened = ref(false)
const source = ref<'raw' | 'processed'>(props.taskId ? 'processed' : 'raw')
const catalog = ref<DatasetSummary | null>(null)
const names = ref<string[]>([])
const selected = ref('')
const image = ref<{ data_url?: string; width?: number; height?: number; caption?: string } | null>(null)
const warning = ref('')
const loading = ref(false)
const reading = ref(false)
let request = 0
let imageRequest = 0
const index = computed(() => names.value.indexOf(selected.value))
const sourceLabel = computed(() => source.value === 'processed' ? '预处理后，当前项目用于训练的图片' : '源文件夹中的原图')
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
    const result = source.value === 'processed' && props.taskId ? await api.inspect_task_dataset(props.taskId) : await api.inspect_dataset(props.directory || '')
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
watch(selected, () => { void load() })
watch([opened, source, () => props.directory, () => props.taskId], ([open]) => {
  request++; imageRequest++
  if (open) void inspect()
})
</script>

<template>
  <section v-if="desktop && (directory || taskId)" class="dataset-browser" aria-label="图片与标签检查">
    <button type="button" :aria-expanded="opened" @click="opened = !opened">{{ opened ? '收起图片与标签' : taskId ? '查看原图 / 处理后训练图片' : '查看原图与标签' }}</button>
    <template v-if="opened">
      <div class="dataset-browser-controls"><label v-if="taskId">图片来源<select v-model="source"><option value="processed">处理后的训练图片</option><option v-if="directory" value="raw">源文件夹原图</option></select></label><button type="button" :disabled="loading" @click="inspect()">{{ loading ? '正在读取…' : '重新读取' }}</button><button v-if="catalog?.next_offset != null" type="button" :disabled="loading" @click="more">加载更多图片</button></div>
      <p>{{ sourceLabel }}。这里展示已有文件，不会重新缩放、裁切或改写标签。</p>
      <p v-if="source === 'raw'">原图细节不等于训练实际看到的细节。预处理完成后，请在训练确认窗口切换到处理后的图片检查。</p>
      <p v-else>请观察脸部、眼睛等目标细节在当前尺寸下是否仍清楚。默认 512 是资源起点，可自行提高分辨率并重新预处理。</p>
      <p v-if="warning" class="dataset-warning">{{ warning }}</p>
      <template v-if="names.length"><label>图片（共 {{ catalog?.images }} 张）<select v-model="selected"><option v-for="name in names" :key="name" :value="name">{{ name }}</option></select></label><div class="dataset-browser-controls"><button type="button" :disabled="index <= 0" @click="selected = names[index - 1] || selected">上一张</button><button type="button" :disabled="index >= names.length - 1" @click="selected = names[index + 1] || selected">下一张</button></div><p v-if="reading">正在读取图片…</p><div v-if="image?.data_url" class="dataset-inspect-image"><img :src="image.data_url" :alt="selected"><span>文件尺寸：{{ image.width }} × {{ image.height }}；屏幕预览会缩放显示</span></div><div v-if="image" class="dataset-caption"><strong>同名标签</strong><p>{{ image.caption || '没有标签或标签为空' }}</p></div></template>
      <p v-else-if="catalog?.ok">没有找到可预览的图片。媒体模式的视频与音频需单独检查。</p>
    </template>
  </section>
</template>

<style scoped>
.dataset-browser { display:grid; gap:9px; font-size:11px; color:var(--text); margin:8px 0; }p { margin:0; color:var(--hint); line-height:1.6; overflow-wrap:anywhere; }label { display:grid; gap:5px; min-width:0; }.dataset-browser-controls { display:flex; flex-wrap:wrap; align-items:end; gap:8px; }
select,button { font:inherit; padding:6px 9px; color:var(--text); background:var(--bg); border:1px solid var(--border); border-radius:4px; min-height:31px; }button { width:fit-content; cursor:pointer; }button:disabled { opacity:.5; cursor:default; }select { max-width:100%; }button:focus-visible,select:focus-visible { outline:2px solid var(--tone-8fb0c9); outline-offset:2px; }
.dataset-inspect-image { display:grid; gap:7px; }.dataset-inspect-image img { width:100%; max-height:440px; object-fit:contain; }.dataset-inspect-image span { color:var(--hint); }.dataset-caption { padding:9px; border:1px solid var(--border); border-radius:4px; }.dataset-caption p { white-space:pre-wrap; margin-top:5px; max-height:180px; overflow:auto; }.dataset-warning { color:var(--tone-d4b06a); }
</style>
