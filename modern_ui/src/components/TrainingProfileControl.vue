<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { trainingProfileChanges, trainingProfiles, profileFieldLabels, profileValue, sameProfileValue, type TrainingProfile } from '../fastRunPreset'
const props = defineProps<{ canUndo: boolean; draft: object; mode: string; defaults: Record<string, unknown>; supported: (key: string) => boolean }>()
const emit = defineEmits<{ apply: [profile: TrainingProfile]; undo: [] }>()
const profile = ref<TrainingProfile | ''>('')
const reviewing = ref(false)
const selected = computed(() => trainingProfiles.find((item) => item.key === profile.value))
const targets = (key: TrainingProfile) => trainingProfileChanges(props.draft, props.mode, key, props.supported, props.defaults)
const changes = computed(() => {
  if (!profile.value) return []
  const current = props.draft as Record<string, unknown>
  return Object.entries(targets(profile.value)).filter(([key, value]) => !sameProfileValue(current[key], value)).map(([key, value]) => ({ key, label: profileFieldLabels[key] || key, before: profileValue(key, current[key]), after: profileValue(key, value) }))
})
const currentLabel = computed(() => {
  const current = props.draft as Record<string, unknown>
  for (const item of [trainingProfiles[3]!, ...trainingProfiles.filter((item) => item.key !== 'standard')]) {
    const values = Object.entries(targets(item.key))
    if (values.length && values.every(([key, value]) => sameProfileValue(current[key], value))) return item.label
  }
  return '自定义设置'
})
const limitedSpeed = computed(() => props.mode === 'qwen_image' || props.mode === 'zimage' || !props.supported('gc') && !props.supported('blocks_to_swap'))
watch(() => [props.mode, props.defaults], () => { reviewing.value = false; profile.value = '' }, { deep: true })
function apply() { if (profile.value && changes.value.length) emit('apply', profile.value); reviewing.value = false }
</script>

<template>
  <section class="training-profile" aria-label="训练方案">
    <div class="profile-heading"><strong>训练方案</strong><span>当前：{{ currentLabel }}</span></div>
    <div class="profile-controls">
      <select v-model="profile" aria-label="选择待应用的训练方案" @change="reviewing = false">
        <option value="" disabled>选择一个方案…</option>
        <option v-for="item in trainingProfiles" :key="item.key" :value="item.key">{{ item.label }}</option>
      </select>
      <button type="button" :disabled="!profile" @click="reviewing = !reviewing">查看并应用</button>
      <button v-if="canUndo" type="button" @click="emit('undo')">撤销上次应用</button>
    </div>
    <p v-if="selected">{{ selected.description }}</p>
    <div v-if="reviewing" class="profile-review">
      <p>以下是相对当前设置的变化。切换方案会重新设置这些受支持的参数；学习率、分辨率、手动量化、采样开关和采样间隔保留当前值。</p>
      <p v-if="mode === 'qwen21_fz'" class="profile-warning">本模式的官方预设会接管 rank、alpha 和学习率。选择 Fast 后学习率由引擎自适应，不能按页面中的手填值理解。</p>
      <p v-if="profile === 'speed' && limitedSpeed" class="profile-warning">此模式部分省显存设置由引擎固定或自动选择，不能全部关闭；本方案仅调整下表中的项目，不保证每步一定更快。</p>
      <p v-if="profile === 'long'" class="profile-warning">增加训练量不保证效果更好。请保留中间模型，并用相同采样条件比较。</p>
      <div v-if="changes.length" class="profile-table"><table><thead><tr><th>参数</th><th>当前值</th><th>应用后</th></tr></thead><tbody><tr v-for="item in changes" :key="item.key"><td>{{ item.label }}</td><td>{{ item.before }}</td><td>{{ item.after }}</td></tr></tbody></table></div>
      <p v-else>当前设置已经符合此方案，没有需要修改的参数。</p>
      <div class="profile-controls"><button type="button" :disabled="!changes.length" @click="apply">确认应用 {{ changes.length }} 项修改</button><button type="button" @click="reviewing = false">取消</button></div>
    </div>
  </section>
</template>

<style scoped>
.training-profile { display: grid; gap: 9px; margin: 9px 0 12px; padding: 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg); }
.profile-heading,.profile-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.profile-heading { justify-content: space-between; font-size: 12px; }.profile-heading span,p { color: var(--hint); font-size: 11px; line-height: 1.6; }p { margin: 0; }
select { flex: 1; min-width: 170px; max-width: 310px; }
select,button { min-height: 32px; padding: 5px 9px; border: 1px solid var(--border); border-radius: 4px; color: var(--text); background: var(--bg); font: inherit; font-size: 12px; }
button { cursor: pointer; }button:disabled { opacity: .5; cursor: default; }
.profile-review { display: grid; gap: 10px; padding-top: 10px; border-top: 1px solid var(--border); }.profile-warning { color: var(--tone-d4b06a); }
.profile-table { overflow-x: auto; }table { width: 100%; border-collapse: collapse; font-size: 11px; }th,td { padding: 8px; border-bottom: 1px solid var(--border); text-align: left; }th { color: var(--hint); font-weight: 500; }
select:focus-visible,button:focus-visible { outline: 2px solid var(--tone-78869b); outline-offset: 2px; }
</style>
