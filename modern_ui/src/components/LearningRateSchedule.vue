<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ scheduler: string; warmup: string; mode: string; version?: string; optimizer?: string }>()
const emit = defineEmits<{ change: [key: string, value: string] }>()
const ai = computed(() => ['qwen_image','zimage','krea2_at','video'].includes(props.mode))
const locked = computed(() => props.mode.endsWith('_fz') && !['v7.0.1','v7.3.1','v8.5.0','v8.9.6'].includes(props.version || ''))
const warmupEnabled = computed(() => !locked.value && props.scheduler !== 'constant' && (!ai.value || props.scheduler === 'constant_with_warmup'))
function select(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  emit('change','lr_scheduler',value)
  if (value === 'constant' || (ai.value && value !== 'constant_with_warmup')) emit('change','lr_warmup_steps','')
}
</script>
<template><div class="schedule-fields"><label>学习率调度<select :value="scheduler || 'auto'" :disabled="locked" @change="select"><option value="auto">自动（沿用引擎预设）</option><option value="constant">恒定</option><option value="constant_with_warmup">恒定＋预热</option><option value="cosine">余弦（cosine）</option><option value="linear">线性衰减</option></select></label><label>预热步数<input :value="warmup" :disabled="!warmupEnabled" type="number" min="0" max="100000" placeholder="自动；恒定＋预热默认 100" @input="emit('change','lr_warmup_steps',($event.target as HTMLInputElement).value)"></label><small>{{ locked ? '此旧版引擎仅沿用预设。切换支持的引擎版本后可自定义。' : ai ? 'AI Toolkit 的单独预热适用于恒定＋预热。' : mode === 'qwen21_fz' && scheduler !== 'auto' ? '自定义调度会关闭 Qwen 自适应学习率。' : '预热属于训练步数；不是模型加载或编译时间。' }}</small></div></template>
<style scoped>.schedule-fields{display:grid;grid-template-columns:1fr 1fr;gap:12px;grid-column:1/-1}label{display:grid;gap:5px;font-size:12px}select,input{background:var(--input,#22252c);color:inherit;border:1px solid var(--border,#444);border-radius:5px;min-width:0;width:100%;padding:7px}small{grid-column:1/-1;color:var(--sub);line-height:1.5}input:disabled,select:disabled{opacity:.5}</style>
