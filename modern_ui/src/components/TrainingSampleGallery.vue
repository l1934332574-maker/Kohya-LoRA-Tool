<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import type { TrainingSampleEntry, ModernTaskSample } from '../bridge'
const props = defineProps<{ taskId: string; active: boolean; settings?: Record<string, unknown> }>()
const opened = ref(false)
const entries = ref<TrainingSampleEntry[]>([])
const selectedA = ref('')
const selectedB = ref('')
const imageA = ref<ModernTaskSample | null>(null)
const imageB = ref<ModernTaskSample | null>(null)
const warning = ref('')
const loading = ref(false)
const total = ref(0)
const nextOffset = ref<number | null>(null)
const browsingOlder = ref(false)
const enlarged = ref<'a' | 'b' | null>(null)
let generation = 0
let listBusy = false
let timer = 0
let readingA = 0
let readingB = 0
const zoomImage = computed(() => enlarged.value === 'a' ? imageA.value : imageB.value)
const recipe = computed(() => {
  const s = props.settings || {}
  return [['固定种子', s.sample_seed], ['采样尺寸', s.sample_width && s.sample_height ? `${s.sample_width} × ${s.sample_height}` : ''], ['采样器', s.sample_sampler], ['采样步数', s.sample_steps]].filter((item) => item[1] !== undefined && item[1] !== '')
})
function timeLabel(timestamp: number) { return new Date(timestamp * 1000).toLocaleTimeString() }
function stop() { if (timer) window.clearInterval(timer); timer = 0 }
async function refresh(more = false) {
  const api = window.pywebview?.api
  if (!api || !props.taskId || listBusy) return
  listBusy = true
  loading.value = true
  const token = generation
  try {
    const result = await api.list_task_samples(props.taskId, more ? nextOffset.value || 0 : 0)
    if (token !== generation) return
    if (!result.ok) { warning.value = result.error || '无法读取采样历史。'; return }
    const incoming = result.samples || []
    const retained = entries.value.filter((entry) => [selectedA.value, selectedB.value].includes(entry.name))
    entries.value = (more ? [...entries.value, ...incoming] : [...incoming, ...retained]).filter((entry, index, list) => list.findIndex((item) => item.name === entry.name) === index)
    browsingOlder.value = more
    for (const [side, name, image] of [['a', selectedA.value, imageA.value], ['b', selectedB.value, imageB.value]] as const) {
      const updated = incoming.find((entry) => entry.name === name)
      if (updated && image?.version !== updated.version) void load(side, name)
    }
    total.value = result.total || 0
    nextOffset.value = result.next_offset ?? null
    warning.value = ''
    if (!selectedA.value && entries.value[0]) selectedA.value = entries.value[0].name
    if (!selectedB.value && entries.value[1]) selectedB.value = entries.value[1].name
  } catch (error) {
    if (token === generation) warning.value = error instanceof Error ? error.message : '无法读取采样历史。'
  } finally { listBusy = false; if (token === generation) loading.value = false }
}
async function load(side: 'a' | 'b', name: string) {
  const token = side === 'a' ? ++readingA : ++readingB
  const currentTask = props.taskId
  if (side === 'a') imageA.value = null; else imageB.value = null
  if (!name || !currentTask) return
  try {
    const image = await window.pywebview?.api.get_task_sample(currentTask, '', true, name)
    if (currentTask !== props.taskId || token !== (side === 'a' ? readingA : readingB)) return
    if (!image?.ok || !image.data_url) { warning.value = image?.error || image?.warning || '图片暂时无法读取，请重试。'; return }
    if (side === 'a') imageA.value = image; else imageB.value = image
  } catch (error) {
    if (currentTask === props.taskId) warning.value = error instanceof Error ? error.message : '图片暂时无法读取。'
  }
}
watch(selectedA, (name) => { void load('a', name) })
watch(selectedB, (name) => { void load('b', name) })
watch(() => props.taskId, () => { generation++; readingA++; readingB++; entries.value = []; selectedA.value = ''; selectedB.value = ''; imageA.value = null; imageB.value = null; warning.value = ''; nextOffset.value = null; total.value = 0; browsingOlder.value = false; enlarged.value = null; opened.value = false })
watch([opened, () => props.active], ([open, active]) => {
  stop()
  if (open) { void refresh(); if (active) timer = window.setInterval(() => { if (!browsingOlder.value) void refresh() }, 8000) }
})
onUnmounted(() => { generation++; stop() })
</script>

<template>
  <section v-if="taskId" class="sample-gallery" aria-label="本次采样历史与对比">
    <button class="gallery-button" type="button" :aria-expanded="opened" @click="opened = !opened">{{ opened ? '收起' : '查看' }}本次采样历史与对比</button>
    <template v-if="opened">
      <div class="gallery-heading"><span>{{ total }} 张本次采样图</span><button class="gallery-button" type="button" :disabled="loading" @click="refresh()">{{ loading ? '正在读取…' : '刷新列表' }}</button><button v-if="nextOffset !== null" class="gallery-button" type="button" :disabled="loading" @click="refresh(true)">加载更早的图片</button></div>
      <p v-if="browsingOlder">查看更早图片时暂停列表自动更新；点击“刷新列表”可回到最新记录。已选的对比图片会保留。</p>
      <p>两侧选择不同训练阶段的图片。文件名由引擎生成；只有确认提示词、种子、尺寸和采样设置一致时，才适合比较训练变化。</p>
      <div v-if="recipe.length" class="gallery-recipe"><span v-for="item in recipe" :key="String(item[0])">{{ item[0] }}：{{ item[1] }}</span></div>
      <details v-if="settings?.sample_prompt"><summary>本次记录的采样提示词</summary><p>{{ settings.sample_prompt }}</p></details>
      <p v-if="warning" class="gallery-warning">{{ warning }} <button class="gallery-button" type="button" @click="load('a', selectedA); load('b', selectedB)">重试图片</button></p>
      <div v-if="entries.length" class="gallery-compare">
        <div><label>图片 A<select v-model="selectedA"><option value="">选择图片</option><option v-for="entry in entries" :key="entry.version" :value="entry.name">{{ timeLabel(entry.modified) }} · {{ entry.name }}</option></select></label><button v-if="imageA?.data_url" class="gallery-image" type="button" aria-label="放大图片 A" @click="enlarged = 'a'"><img :src="imageA.data_url" :alt="selectedA"></button><small v-if="imageA">{{ imageA.width }} × {{ imageA.height }}</small></div>
        <div><label>图片 B<select v-model="selectedB"><option value="">选择图片</option><option v-for="entry in entries" :key="entry.version" :value="entry.name">{{ timeLabel(entry.modified) }} · {{ entry.name }}</option></select></label><button v-if="imageB?.data_url" class="gallery-image" type="button" aria-label="放大图片 B" @click="enlarged = 'b'"><img :src="imageB.data_url" :alt="selectedB"></button><small v-if="imageB">{{ imageB.width }} × {{ imageB.height }}</small></div>
      </div>
      <p v-else>本次尚未发现图片采样。视频和音频产物请到项目输出目录查看。</p>
    </template>
    <div v-if="enlarged && zoomImage?.data_url" class="gallery-lightbox" role="dialog" aria-modal="true" aria-label="采样图放大" @click.self="enlarged = null"><button class="gallery-button" type="button" @click="enlarged = null">关闭大图</button><img :src="zoomImage.data_url" :alt="enlarged === 'a' ? selectedA : selectedB"></div>
  </section>
</template>

<style scoped>
.sample-gallery { display:grid; gap:9px; padding-top:10px; border-top:1px solid var(--tone-373b44); color:var(--tone-c1c6cf); font-size:11px; }
.gallery-heading,.gallery-recipe { display:flex; align-items:center; flex-wrap:wrap; gap:9px; }
p { margin:0; color:var(--tone-9299a4); line-height:1.6; overflow-wrap:anywhere; }.gallery-warning { color:var(--tone-d4b06a); }
.gallery-button,select { min-height:30px; border:1px solid var(--tone-41464f); border-radius:4px; padding:5px 8px; background:var(--tone-22252c); color:var(--tone-c1c6cf); font:inherit; }.gallery-button { cursor:pointer; width:fit-content; }.gallery-button:disabled { opacity:.5; }
.gallery-compare { display:grid; grid-template-columns:1fr 1fr; gap:10px; }.gallery-compare > div { min-width:0; display:grid; align-content:start; gap:7px; }label { display:grid; gap:5px; }select { width:100%; }small { color:var(--tone-9299a4); }
.gallery-image { border:0; padding:0; cursor:zoom-in; background:var(--tone-22252c); }img { display:block; width:100%; object-fit:contain; }.gallery-image img { max-height:330px; }
.gallery-lightbox { position:fixed; inset:0; z-index:90; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:12px; padding:20px; background:rgb(0 0 0 / 85%); }.gallery-lightbox img { width:auto; max-width:94vw; max-height:85vh; }
summary { cursor:pointer; color:var(--tone-9299a4); }button:focus-visible,select:focus-visible,summary:focus-visible { outline:2px solid var(--tone-8fb0c9); outline-offset:2px; }
@media(max-width:560px) { .gallery-compare { grid-template-columns:1fr; } }
</style>
