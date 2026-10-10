<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { ModelCatalogData, ModelChoice } from '../bridge'
const props = defineProps<{ catalog: ModelCatalogData; initialModel?: string; initialGoal?: string }>()
const emit = defineEmits<{ choose: [choice: ModelChoice, template: string, mode: string, goal: string]; valid: [available: boolean] }>()
const modelKey = ref(props.initialModel || 'sdxl')
const variantKey = ref('')
const engineKey = ref('')
const goal = ref(props.initialGoal || 'character')
const expanded = ref(false)
const model = computed(() => props.catalog.models.find(m => m.key === modelKey.value) || props.catalog.models[0])
const variant = computed(() => model.value?.variants.find(v => v.key === variantKey.value) || model.value?.variants[0])
const engine = computed(() => variant.value?.engines.find(e => e.key === engineKey.value))
function available(e: { vendors: string[]; supported?: boolean; mode?: string }) {
  if (goal.value === 'multi_character' && ['video', 'h3_fz'].includes(e.mode || '')) return false
  if (goal.value === 'slider' && !['sdxl_fz', 'anima_fz'].includes(e.mode || '')) return false
  return e.supported ?? (props.catalog.gpu_vendor === 'unknown' || e.vendors.includes(props.catalog.gpu_vendor))
}
function chooseEngine() {
  const preferred = variant.value?.preferred[props.catalog.gpu_vendor]
  const options = variant.value?.engines || []
  engineKey.value = (options.find(e => e.recommended && available(e)) || options.find(e => e.key === preferred && available(e)) || options.find(available))?.key || ''
}
watch(modelKey, () => {
  const variants = model.value?.variants || []
  variantKey.value = (variants.find(v => v.engines.some(available)) || variants[0])?.key || ''
}, { immediate: true })
watch([variantKey, goal], chooseEngine, { immediate: true })
watch(() => props.catalog, chooseEngine)
watch([modelKey, variantKey, engineKey, goal], () => {
  emit('valid', Boolean(engine.value))
  if (engine.value && variant.value && model.value) emit('choose', { model: model.value.key, variant: variant.value.key, engine: engine.value.key }, engine.value.template, engine.value.mode, goal.value)
}, { immediate: true })
</script>

<template>
  <div class="model-chooser">
    <p class="device">{{ catalog.gpu }} · {{ catalog.gpu_vendor === 'amd' ? 'AMD：优先推荐已接入的 ROCm 训练路径' : catalog.gpu_vendor === 'nvidia' ? 'NVIDIA：按模型推荐训练路径' : '未识别显卡：请检查驱动，或手动选择引擎' }}</p>
    <div class="choice-fields">
      <label><span>要训练的模型</span><select v-model="modelKey"><option v-for="m in catalog.models" :key="m.key" :value="m.key">{{ m.label }}</option></select></label>
      <label><span>模型版本</span><select v-model="variantKey"><option v-for="v in model?.variants" :key="v.key" :value="v.key">{{ v.label }}</option></select></label>
    </div>
    <p class="variant-note">{{ variant?.note }}</p>
    <fieldset class="purpose"><legend>训练目的</legend><label v-for="item in [{key:'character',label:'人物'}, {key:'multi_character',label:'多角色（实验性）'}, {key:'style',label:'画风'}, {key:'concept',label:'概念 / 物品'}, {key:'slider',label:'概念滑块'}]" :key="item.key" :class="{selected:goal===item.key}"><input v-model="goal" type="radio" name="create-goal" :value="item.key" />{{ item.label }}</label></fieldset>
    <div v-if="engine" class="recommendation">
      <header><strong>{{ engine.label }}</strong><span>{{ engine.status || '创建后检查安装状态' }}</span></header>
      <p>{{ goal === 'multi_character' ? '独立角色触发词、同框素材与组合验证；训练参数沿用当前模型。' : goal === 'slider' ? '通过文字或图片对训练可调节属性的 LoRA。实验性功能。' : engine.reason }}</p>
      <span v-if="engine.experimental" class="experimental">实验性入口 · 需观察实际训练效果</span>
    </div>
    <p v-else class="unavailable" role="status">{{ goal === 'slider' ? '支持 SDXL 与标准 28 层 Anima；Anima 2.9B / 40 层暂不支持滑块训练。' : goal === 'multi_character' ? '多角色模式仅用于图像人物 LoRA，请选择已接入当前显卡的图像训练入口。' : '这个模型版本尚未接入当前显卡的训练路径，请选择其他版本。' }}</p>
    <button v-if="variant && variant.engines.length > 1" class="compare" type="button" :aria-expanded="expanded" @click="expanded=!expanded">{{ expanded ? '收起引擎选择' : '查看其他引擎 / 手动选择' }}</button>
    <div v-if="expanded && variant" class="engine-options">
      <label v-for="e in variant.engines" :key="e.key" :class="{selected:engineKey===e.key, unavailable:!available(e)}"><input v-model="engineKey" type="radio" name="create-engine" :value="e.key" :disabled="!available(e)" /><div><strong>{{ e.label }}</strong><small>{{ e.reason }} {{ !available(e) ? goal === 'slider' && !['sdxl_fz', 'anima_fz'].includes(e.mode) ? '当前引擎未接入滑块训练。' : '当前显卡路径未接入。' : '' }}</small></div></label>
    </div>
  </div>
</template>
<style scoped>
.model-chooser{display:grid;gap:10px;margin-bottom:16px}.device,.variant-note{margin:0;color:var(--hint);font-size:12px;line-height:1.6}.choice-fields{display:grid;grid-template-columns:1fr 1fr;gap:12px}.choice-fields label{display:grid;gap:7px;font-size:12px}.choice-fields select{min-width:0;width:100%;padding:10px;color:var(--text);background:var(--bg);border:1px solid var(--border);border-radius:6px;font:inherit}.purpose{display:flex;flex-wrap:wrap;gap:8px;border:0;padding:0;margin:0}.purpose legend{font-size:12px;padding:0;margin-bottom:8px}.purpose label{display:flex;align-items:center;gap:6px;padding:8px 10px;border:1px solid var(--border);border-radius:6px;font-size:12px;cursor:pointer}.selected{border-color:var(--accent)!important;background:var(--card)}.recommendation{padding:12px;border:1px solid var(--border);border-radius:8px}.recommendation header{display:flex;justify-content:space-between;gap:12px;font-size:13px}.recommendation header span{font-size:11px;color:var(--hint)}.recommendation p{font-size:12px;line-height:1.7;margin:8px 0 0;color:var(--hint)}.experimental{font-size:11px;color:var(--hint)}.compare{justify-self:start;color:var(--text);padding:5px 0;background:none;border:0;font:inherit;font-size:12px;cursor:pointer;text-decoration:underline;text-underline-offset:3px}.engine-options{display:grid;gap:7px}.engine-options label{display:flex;gap:9px;padding:10px;border:1px solid var(--border);border-radius:6px;cursor:pointer}.engine-options small{display:block;color:var(--hint);line-height:1.5;margin-top:4px}.engine-options strong{font-size:12px}.unavailable{color:var(--hint);font-size:12px}.engine-options .unavailable{opacity:.65}@media(max-width:560px){.choice-fields{grid-template-columns:1fr}.purpose{flex-wrap:wrap}}
</style>
