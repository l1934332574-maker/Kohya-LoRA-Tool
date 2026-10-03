<script setup lang="ts">
import { ref, watch } from 'vue'
import type { DatasetSummary } from '../bridge'

const props = defineProps<{ directory: string; desktop: boolean; keepCaptions: boolean }>()
const emit = defineEmits<{ preserve: [] }>()
const result = ref<DatasetSummary | null>(null)
const checking = ref(false)
let request = 0

async function inspect(directory: string) {
  const token = ++request
  result.value = null
  checking.value = false
  if (!directory || !props.desktop || !window.pywebview?.api) return
  checking.value = true
  try {
    const summary = await window.pywebview.api.inspect_dataset(directory)
    if (token === request) result.value = summary
  } catch {
    if (token === request) result.value = { ok: false, error: '暂时无法检查图集，请重试。' }
  } finally {
    if (token === request) checking.value = false
  }
}

watch(() => props.directory, (directory) => { void inspect(directory) }, { immediate: true })
</script>

<template>
  <div v-if="directory && desktop" class="dataset-inspection" aria-live="polite">
    <span v-if="checking">正在检查图片与同名标签…</span>
    <template v-else-if="result?.ok">
      <div class="dataset-counts"><strong>{{ result.images }} 张图片</strong><span>{{ result.captioned }} 张有标签</span><span :class="{ warning: result.missing_captions || result.empty_captions }">{{ (result.missing_captions || 0) + (result.empty_captions || 0) }} 张缺少或空标签</span><button type="button" @click="inspect(directory)">重新检查</button></div>
      <p v-if="keepCaptions">将保留已有标签并跳过自动打标；缺标签的图片不会自动补写文本。图片仍按设置缩放或裁切。</p>
      <p v-else-if="result.keep_user_captions">检测到大部分图片已有标签。<button type="button" @click="emit('preserve')">保留这些标签，不重新打标</button></p>
      <p v-else-if="!result.images" class="warning">没有找到支持的图片，请检查数据文件夹。</p>
      <p v-else>未开启标签保护，预处理会按当前训练类型整理标签。</p>
    </template>
    <span v-else-if="result?.error" class="warning">{{ result.error }} <button type="button" @click="inspect(directory)">重试</button></span>
  </div>
</template>

<style scoped>
.dataset-inspection { display: grid; gap: 6px; margin: 9px 0; padding: 10px; border: 1px solid var(--border); border-radius: 5px; color: var(--sub); background: var(--bg); font-size: 11px; line-height: 1.55; }
.dataset-counts { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 12px; }
strong { color: var(--text); font-weight: 500; }
p { margin: 0; color: var(--hint); }
.warning { color: var(--tone-d4b06a); }
button { padding: 0; border: 0; background: transparent; color: var(--tone-adb6c2); font: inherit; text-decoration: underline; cursor: pointer; }
button:focus-visible { outline: 2px solid var(--tone-78869b); outline-offset: 3px; }
</style>
