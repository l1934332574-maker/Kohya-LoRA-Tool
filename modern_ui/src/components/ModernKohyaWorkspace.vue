<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { ModeWorkspaceData, ProjectCard, ProjectConfig } from '../bridge'
import UiIcon from './UiIcon.vue'
import CropRatioField from './CropRatioField.vue'
import { legacyTooltips } from '../legacyTooltips'
import { normalizeWd14Model } from '../modelDefaults'

type BrowseKind = 'folder' | 'model'
const props = defineProps<{
  project: ProjectCard
  config?: ProjectConfig | null
  details?: ModeWorkspaceData | null
  desktop: boolean
  choosePath: (kind: BrowseKind) => Promise<string | null>
}>()
const emit = defineEmits<{
  back: [patch: ProjectConfig]
  notify: [message: string]
  save: [patch: ProjectConfig]
  train: [patch: ProjectConfig]
  classicAction: [action: string, patch?: ProjectConfig]
}>()

const trainingType = ref(props.project.mode === 'style' ? '画风' : props.project.mode === 'concept' ? '概念' : '人物')
const advancedOpen = ref(false)
const dirty = reactive(new Set<string>())
const configuredParams = new Set<string>()
const draft = reactive({
  mode: props.project.mode,
  base_type: props.project.base_type,
  base_model: '', raw_dir: '', trigger: '', reg_dir: '', style_preset: '自定义', style_caption: '', concept_type: 'form', global_pos: '', global_neg: '',
  rank: '', alpha: '', unet_lr: '', te_lr: '', repeats: '', max_epochs: '', resolution: '',
  save_every: '', sample_interval: '', sample_prompt: '', optimizer: 'auto', strong_bind: false, clean_concept: true,
  sample_preview_mode: 'auto', unet_only: false, compile: false, crop_ratio: '', noise_offset: '', min_snr_gamma: '',
  wd14_model: 'swinv2-v3', overwrite: false, amd_mode: false, train_env: '',
})

const baseTypeOptions = [
  { key: 'sd15', label: 'SD 1.5（512px）' },
  { key: 'sdxl', label: 'SDXL 1.0（1024px）' },
  { key: 'flux', label: 'FLUX.1（1024px）' },
  { key: 'anima', label: 'Anima（1024px）' },
]
const currentModeKey = computed(() => trainingType.value === '画风' ? 'style' : trainingType.value === '概念' ? 'concept' : 'character')
const isAnimaDirect = computed(() => props.desktop && draft.base_type === 'anima')
const isAmdGpu = computed(() => String(props.details?.gpu_vendor || '').toLowerCase() === 'amd')
const supportsSdQuality = computed(() => ['sd15', 'sdxl'].includes(draft.base_type))
const supports = (key: string) => Boolean(props.details?.supports?.[key])
const intervalUnit = (key: 'save_every' | 'sample_interval') => props.details?.interval_units?.[key] === 'epochs' ? '轮' : '步'
const intervalTooltip = (key: 'save_every' | 'sample_interval') => key === 'save_every'
  ? props.details?.interval_units?.[key] === 'epochs' ? legacyTooltips.saveEveryEpochs : legacyTooltips.saveEverySteps
  : props.details?.interval_units?.[key] === 'epochs' ? legacyTooltips.sampleIntervalEpochs : legacyTooltips.sampleIntervalSteps
const datasetGuidance = computed(() => {
  if (currentModeKey.value === 'concept') {
    return props.details?.concept_type_hints?.[draft.concept_type] || props.details?.dataset_hints?.concept || '概念图集保持概念一致，并混合其他主体属性。'
  }
  return props.details?.dataset_hints?.[currentModeKey.value] || (currentModeKey.value === 'style'
    ? '画风模式建议 20–60 张不同主体的作品。'
    : '人物模式建议 15–30 张同一人物的清晰图片。')
})
const triggerGuidance = computed(() => props.details?.trigger_hints?.[currentModeKey.value] || props.details?.trigger_hint || '')
const baseTypeLabel = computed(() => baseTypeOptions.find((item) => item.key === draft.base_type)?.label || draft.base_type || '尚未选择底模类型')

const presetParamKeys = ['rank', 'alpha', 'unet_lr', 'te_lr', 'repeats', 'max_epochs', 'resolution', 'save_every', 'sample_interval', 'noise_offset', 'min_snr_gamma'] as const
function presetFor(mode = currentModeKey.value, baseType = draft.base_type): Record<string, unknown> {
  return props.details?.presets?.[mode]?.[baseType] ?? props.details?.defaults ?? {}
}
function styledPresetValue(key: string, mode = currentModeKey.value, baseType = draft.base_type, style = draft.style_preset): string {
  const raw = presetFor(mode, baseType)[key]
  if (raw === undefined || raw === null || raw === '') return ''
  const factor = style === '动漫' ? 0.85 : style === '写实' ? 1.15 : 1
  const number = Number(raw)
  if (factor === 1 || !Number.isFinite(number)) return String(raw)
  return (number * factor).toExponential(2).replace('e-0', 'e-').replace('e+0', 'e+')
}
function syncPresetValues(mode = currentModeKey.value, baseType = draft.base_type, force = false) {
  for (const key of presetParamKeys) {
    if (!force && (configuredParams.has(key) || dirty.has(`params.${key}`))) continue
    const value = styledPresetValue(key, mode, baseType)
    if (value !== '') draft[key] = value
  }
}

function hydrate(config?: ProjectConfig | null) {
  const params = (config?.params && typeof config.params === 'object') ? config.params : {}
  const get = (value: unknown) => value === null || value === undefined ? '' : String(value)
  const demo = !props.desktop && !config
  draft.mode = String(config?.mode ?? props.project.mode)
  draft.base_type = String(config?.base_type ?? props.project.base_type)
  trainingType.value = draft.mode === 'style' ? '画风' : draft.mode === 'concept' ? '概念' : '人物'
  draft.base_model = get(config?.base_model ?? props.project.base_model)
  draft.raw_dir = get(config?.raw_dir ?? props.project.raw_dir) || (demo ? 'C:\\Users\\admin\\Desktop\\图集\\人物项目' : '')
  draft.trigger = get(config?.trigger) || (demo ? 'character_name' : '')
  draft.reg_dir = get(config?.reg_dir)
  draft.style_preset = get(config?.style_preset) || '自定义'
  draft.style_caption = get(config?.style_caption)
  draft.concept_type = get(config?.concept_type) || 'form'
  draft.global_pos = get(config?.global_pos)
  draft.global_neg = get(config?.global_neg)
  draft.train_env = get(config?.train_env)
  const demoValues: Record<string, string> = { rank: '12', alpha: '6', unet_lr: '3e-4', te_lr: '1.5e-4', repeats: '5', max_epochs: '8', resolution: '1024' }
  configuredParams.clear()
  Object.keys(params).forEach((key) => configuredParams.add(key))
  const preset = presetFor(currentModeKey.value, draft.base_type)
  for (const key of ['rank', 'alpha', 'unet_lr', 'te_lr', 'repeats', 'max_epochs', 'resolution', 'save_every', 'sample_interval', 'sample_prompt', 'optimizer', 'crop_ratio', 'noise_offset', 'min_snr_gamma', 'wd14_model'] as const) {
    const presetValue = preset[key] === undefined ? '' : key === 'unet_lr' || key === 'te_lr' ? styledPresetValue(key, currentModeKey.value, draft.base_type, get(config?.style_preset) || '自定义') : String(preset[key])
    const value = get(params[key]) || presetValue || (demo ? demoValues[key] ?? (key === 'optimizer' ? 'auto' : '') : key === 'optimizer' ? 'auto' : '')
    draft[key] = key === 'wd14_model' ? normalizeWd14Model(value) : value
  }
  draft.strong_bind = params.strong_bind === undefined ? true : Boolean(params.strong_bind)
  draft.clean_concept = params.clean_concept === undefined ? true : Boolean(params.clean_concept)
  draft.sample_preview_mode = params.sample_preview === undefined ? 'auto' : Boolean(params.sample_preview) ? 'on' : 'off'
  draft.unet_only = Boolean(config?.unet_only)
  draft.compile = Boolean(params.compile)
  draft.overwrite = Boolean(params.overwrite)
  draft.amd_mode = Boolean(params.amd_mode)
  dirty.clear()
}

watch(() => props.config, (config) => hydrate(config), { immediate: true, deep: true })

function markRoot(key: string) { dirty.add(key) }
function markParam(key: string) { dirty.add(`params.${key}`) }

function onBaseTypeChange() {
  draft.base_model = ''
  markRoot('base_type')
  markRoot('base_model')
  draft.unet_only = draft.base_type === 'flux' || draft.base_type === 'anima'
  markRoot('unet_only')
  syncPresetValues(currentModeKey.value, draft.base_type)
}

function onTrainingTypeChange() {
  markRoot('mode')
  syncPresetValues(currentModeKey.value, draft.base_type)
}

function onStylePresetChange() {
  markRoot('style_preset')
  for (const key of ['unet_lr', 'te_lr'] as const) {
    const value = styledPresetValue(key)
    if (value) { draft[key] = value; markParam(key) }
  }
}

function resetPreset() {
  draft.style_preset = '自定义'
  markRoot('style_preset')
  const preset = presetFor()
  for (const key of presetParamKeys) {
    if (preset[key] === undefined) continue
    draft[key] = String(preset[key])
    configuredParams.delete(key)
    markParam(key)
  }
  emit('notify', '当前模式和底模的推荐预设已恢复。保存修改后生效。')
}

const conceptOptions = [
  { key: 'form', label: '形态/种族（美人鱼·半人马）' },
  { key: 'outfit', label: '服装（同款衣服）' },
  { key: 'object', label: '物品（道具/武器）' },
  { key: 'bodypart', label: '身体部位（异色瞳/翅膀）' },
]

function makePatch(): ProjectConfig {
  const patch: ProjectConfig = {}
  for (const key of ['mode', 'base_type', 'base_model', 'raw_dir', 'trigger', 'reg_dir', 'style_preset', 'style_caption', 'concept_type', 'global_pos', 'global_neg', 'train_env'] as const) {
    if (dirty.has(key)) patch[key] = key === 'mode'
      ? trainingType.value === '画风' ? 'style' : trainingType.value === '概念' ? 'concept' : 'character'
      : draft[key]
  }
  if (dirty.has('unet_only')) patch.unet_only = draft.unet_only
  const params: Record<string, unknown> = {}
  for (const key of ['rank', 'alpha', 'unet_lr', 'te_lr', 'repeats', 'max_epochs', 'resolution', 'save_every', 'sample_interval', 'sample_prompt', 'optimizer', 'crop_ratio', 'noise_offset', 'min_snr_gamma', 'wd14_model'] as const) {
    if (dirty.has(`params.${key}`)) params[key] = draft[key]
  }
  if (dirty.has('params.strong_bind')) params.strong_bind = draft.strong_bind
  if (dirty.has('params.clean_concept')) params.clean_concept = draft.clean_concept
  if (dirty.has('params.sample_preview')) params.sample_preview = draft.sample_preview_mode === 'auto' ? null : draft.sample_preview_mode === 'on'
  if (dirty.has('params.compile')) params.compile = draft.compile
  if (dirty.has('params.overwrite')) params.overwrite = draft.overwrite
  if (dirty.has('params.amd_mode')) params.amd_mode = draft.amd_mode
  if (Object.keys(params).length) patch.params = params
  return patch
}

function save() {
  const patch = makePatch()
  if (Object.keys(patch).length === 0) return emit('notify', '当前没有修改项目配置。')
  emit('save', patch)
}

function startTraining() {
  if (!props.desktop) return previewOnly('开始训练')
  emit('train', makePatch())
}

async function browse(target: 'raw_dir' | 'base_model' | 'reg_dir') {
  if (!props.desktop) return previewOnly(target === 'base_model' ? '选择训练底模' : target === 'reg_dir' ? '选择正则图片文件夹' : '选择图集文件夹')
  const path = await props.choosePath(target === 'base_model' ? 'model' : 'folder')
  if (!path) return
  draft[target] = path
  markRoot(target)
}

async function guideAction(action: string): Promise<ProjectConfig | null> {
  if (action === 'cmd_pick_raw') {
    await browse('raw_dir')
    return dirty.has('raw_dir') ? makePatch() : null
  }
  if (action === 'cmd_pick_model_type') {
    if (!props.desktop) return previewOnly('选择模型架构和底模'), null
    const path = await props.choosePath('model')
    if (!path) return null
    draft.base_model = path
    markRoot('base_model')
    try {
      const detected = await window.pywebview?.api.inspect_base_model(path)
      if (detected?.base_type && baseTypeOptions.some((item) => item.key === detected.base_type)) {
        draft.base_type = detected.base_type
        markRoot('base_type')
        draft.unet_only = draft.base_type === 'flux' || draft.base_type === 'anima'
        markRoot('unet_only')
        emit('notify', `已识别底模架构：${baseTypeOptions.find((item) => item.key === detected.base_type)?.label ?? detected.base_type}`)
      } else {
        emit('notify', '已选择底模文件；请在「当前底模架构」下拉框确认模型类型。')
      }
    } catch {
      emit('notify', '已选择底模文件；请在「当前底模架构」下拉框确认模型类型。')
    }
    return makePatch()
  }
  return null
}

async function browseTrainEnv() {
  if (!props.desktop) return previewOnly('选择 AMD 训练环境')
  const path = await props.choosePath('folder')
  if (!path) return
  draft.train_env = path
  markRoot('train_env')
}

function previewOnly(action: string) {
  emit('notify', props.desktop ? `${action}暂未接入现代工作区。` : `${action}仅展示界面效果，当前不会调用本机训练功能。`)
}

function requestAction(action: string) {
  if (!props.desktop && action !== 'readme') return previewOnly(action)
  emit('classicAction', action, makePatch())
}

defineExpose({ startTraining, guideAction })
</script>

<template>
  <section class="kohya-workspace" aria-label="Kohya LoRA 训练工作区">
    <header class="kohya-toolbar">
      <div class="kohya-heading">
        <button class="kohya-back" type="button" @click="emit('back', makePatch())"><UiIcon name="back" /> 返回项目</button>
      <div class="kohya-heading-copy"><h1>Kohya LoRA 训练</h1><span>项目：{{ props.project.name }}</span></div>
      </div>
      <div class="kohya-toolbar-actions">
        <button class="kohya-button" type="button" :title="legacyTooltips.readme" @click="emit('classicAction', 'readme')">训练说明</button>
        <button v-if="desktop" class="kohya-button primary" type="button" @click="startTraining"><UiIcon name="play" /> 一键开始训练</button>
        <button v-else class="kohya-button primary" type="button" @click="previewOnly('开始训练')"><UiIcon name="play" /> 一键开始训练</button>
      </div>
    </header>

    <div class="kohya-status-line"><span v-if="desktop" class="status-sample">项目配置已加载</span><span v-else class="status-sample">工作区预览</span><span v-if="!desktop" class="status-sample">示例值 · 保存仅在当前预览会话</span></div>

    <div class="kohya-scroll-area">
      <div class="kohya-scroll-content">
        <section class="base-summary">
          <span class="base-mark"><UiIcon name="model" /></span>
          <div class="base-copy"><span>当前底模架构</span><select v-model="draft.base_type" class="kohya-select base-type-select" :title="legacyTooltips.baseModel" @change="onBaseTypeChange"><option v-for="item in baseTypeOptions" :key="item.key" :value="item.key">{{ item.label }}</option></select><small :title="draft.base_model || undefined">{{ draft.base_model || '未指定模型文件' }}</small></div>
          <button class="kohya-button compact" type="button" :title="legacyTooltips.baseModel" @click="browse('base_model')">选择底模</button>
        <button class="kohya-button compact save-button" type="button" @click="save">{{ desktop ? '保存修改' : '保存预览设置' }}</button>
        </section>

        <div class="kohya-columns">
          <div class="kohya-column">
          <section class="kohya-card kohya-dataset-card">
            <header class="card-heading"><span class="step-number">01</span><div><h2>准备图片数据</h2><small>数据集与自动打标</small></div></header>
            <div class="folder-row">
              <UiIcon name="folder" />
              <div class="folder-copy"><span>原始图片文件夹</span><strong :title="draft.raw_dir || undefined">{{ draft.raw_dir || (desktop ? '尚未选择图集文件夹' : 'C:\Users\admin\Desktop\图集\人物项目') }}</strong></div>
              <button class="kohya-button compact" type="button" :title="legacyTooltips.chooseRawDir" @click="browse('raw_dir')">浏览…</button>
            </div>
            <div class="dataset-counts"><span>{{ desktop ? '图片数量会在数据预处理时检查' : '26 张示例图片' }}</span><span v-if="!desktop" class="sample-state">预览数据</span></div>
            <p class="card-hint">{{ datasetGuidance }}</p>
            <div class="field-row equal-columns spaced-row dataset-options-row">
              <label class="kohya-field" :title="legacyTooltips.wd14Model"><span>自动打标模型</span><select v-model="draft.wd14_model" class="kohya-select" @change="markParam('wd14_model')"><option value="swinv2-v3">swinv2-v3（推荐）</option><option value="moat-v2">moat-v2（旧版）</option></select></label>
              <button class="check-line" :title="legacyTooltips.overwrite" :class="{ checked: draft.overwrite }" type="button" role="checkbox" :aria-checked="draft.overwrite" @click="draft.overwrite = !draft.overwrite; markParam('overwrite')"><i></i><span>重新处理已存在的图片（改过标签后勾上，否则不生效）</span></button>
            </div>
          </section>

          <section class="kohya-card parameter-card">
            <header class="card-heading parameter-heading">
              <span class="step-number">03</span><div class="parameter-title"><h2>训练参数</h2><small>{{ desktop ? '项目覆盖值 · 空白沿用推荐值' : '常用参数 · 示例值' }}</small></div>
              <button class="kohya-button compact" type="button" :aria-expanded="advancedOpen" @click="advancedOpen = !advancedOpen">{{ advancedOpen ? '收起高级参数' : '高级参数' }}<span class="chevron" :class="{ open: advancedOpen }">⌄</span></button>
            </header>
            <div class="parameter-grid">
              <label class="kohya-field" :title="legacyTooltips.rank"><span>LoRA rank</span><input v-model="draft.rank" class="kohya-input" type="number" min="1" @input="markParam('rank')" /></label>
              <label class="kohya-field" :title="legacyTooltips.alpha"><span>LoRA alpha</span><input v-model="draft.alpha" class="kohya-input" type="number" min="1" @input="markParam('alpha')" /></label>
              <label class="kohya-field" :title="legacyTooltips.unet_lr"><span>学习率</span><input v-model="draft.unet_lr" class="kohya-input" type="text" @input="markParam('unet_lr')" /></label>
              <label v-if="supports('te_lr')" class="kohya-field" :title="legacyTooltips.te_lr"><span>文本编码器学习率</span><input v-model="draft.te_lr" class="kohya-input" type="text" @input="markParam('te_lr')" /></label>
              <label class="kohya-field" :title="legacyTooltips.resolution"><span>训练分辨率</span><input v-model="draft.resolution" class="kohya-input" type="number" min="64" step="64" @input="markParam('resolution')" /></label>
              <label class="kohya-field" :title="legacyTooltips.maxEpochs"><span>最大 epoch</span><input v-model="draft.max_epochs" class="kohya-input" type="number" min="1" @input="markParam('max_epochs')" /></label>
              <label class="kohya-field" :title="legacyTooltips.repeats"><span>图片循环次数</span><input v-model="draft.repeats" class="kohya-input" type="number" min="1" @input="markParam('repeats')" /></label>
            </div>
            <Transition name="kohya-accordion">
              <div v-if="advancedOpen" class="advanced-grid">
                <label class="kohya-field" :title="intervalTooltip('save_every')"><span>模型保存间隔（{{ intervalUnit('save_every') }}）</span><input v-model="draft.save_every" class="kohya-input" type="text" placeholder="沿用自动值" @input="markParam('save_every')" /></label>
                <label class="kohya-field" :title="intervalTooltip('sample_interval')"><span>采样预览间隔（{{ intervalUnit('sample_interval') }}）</span><input v-model="draft.sample_interval" class="kohya-input" type="text" placeholder="留空 / 0 沿用默认值" @input="markParam('sample_interval')" /></label>
                <label class="kohya-field" :title="legacyTooltips.samplePrompt"><span>采样预览提示词</span><input v-model="draft.sample_prompt" class="kohya-input" placeholder="留空自动生成；填写后整句生效" @input="markParam('sample_prompt')" /></label>
                <label class="kohya-field" :title="legacyTooltips.optimizer"><span>优化器</span><select v-model="draft.optimizer" class="kohya-select" @change="markParam('optimizer')"><option value="auto">自动</option><option value="adamw">AdamW</option><option value="adamw8bit">AdamW8bit</option><option value="lion">Lion</option></select></label>
                <label v-if="supportsSdQuality" class="kohya-field" :title="legacyTooltips.noiseOffset"><span>Noise offset</span><input v-model="draft.noise_offset" class="kohya-input" placeholder="默认预设" @input="markParam('noise_offset')" /></label>
                <label v-if="supportsSdQuality" class="kohya-field" :title="legacyTooltips.minSnrGamma"><span>Min-SNR gamma</span><input v-model="draft.min_snr_gamma" class="kohya-input" placeholder="默认预设" @input="markParam('min_snr_gamma')" /></label>
                <p v-if="!supportsSdQuality" class="parameter-scope-note">Noise offset 和 Min-SNR 只会传给 SD 1.5 / SDXL 训练；当前底模架构不使用这两项。</p>
                <button class="kohya-button compact" type="button" :title="legacyTooltips.resetPreset" @click="resetPreset">恢复预设</button>
                <button class="check-line" :title="legacyTooltips.unetOnly" :class="{ checked: draft.unet_only }" type="button" role="checkbox" :aria-checked="draft.unet_only" @click="draft.unet_only = !draft.unet_only; markRoot('unet_only')"><i></i><span>只训练 UNet / DiT，不训练文本编码器</span></button>
                <button v-if="supports('compile')" class="check-line" :title="legacyTooltips.compile" :class="{ checked: draft.compile }" type="button" role="checkbox" :aria-checked="draft.compile" @click="draft.compile = !draft.compile; markParam('compile')"><i></i><span>启用 torch.compile</span></button>
                <button v-if="isAmdGpu && supports('amd_mode')" class="check-line" :title="legacyTooltips.amdMode" :class="{ checked: draft.amd_mode }" type="button" role="checkbox" :aria-checked="draft.amd_mode" @click="draft.amd_mode = !draft.amd_mode; markParam('amd_mode')"><i></i><span>AMD 兼容模式（实验性）</span></button>
                <label v-if="supports('global_pos')" class="kohya-field" :title="legacyTooltips.globalPos"><span>附加全局提示词（正向）</span><input v-model="draft.global_pos" class="kohya-input" @input="markRoot('global_pos')" /></label>
                <label v-if="supports('global_neg')" class="kohya-field" :title="legacyTooltips.globalNeg"><span>附加全局提示词（负向）</span><input v-model="draft.global_neg" class="kohya-input" @input="markRoot('global_neg')" /></label>
                <label v-if="isAmdGpu" class="kohya-field train-env-field" :title="legacyTooltips.trainEnv"><span>训练环境（venv，留空使用默认 Kohya 环境）</span><span class="reg-path-row"><input v-model="draft.train_env" class="kohya-input" placeholder="需包含 Scripts\\python.exe" @input="markRoot('train_env')" /><button class="kohya-button compact" type="button" @click="browseTrainEnv">选择环境…</button></span></label>
              </div>
            </Transition>
          </section>
          </div>

          <div class="kohya-column">
          <section class="kohya-card kohya-training-card">
            <header class="card-heading"><span class="step-number">02</span><div><h2>训练方式</h2><small>按类型显示适用设置</small></div></header>
            <div class="field-row equal-columns">
              <label class="kohya-field" :title="legacyTooltips.mode"><span>训练类型</span><select v-model="trainingType" class="kohya-select" @change="onTrainingTypeChange"><option>人物</option><option>画风</option><option>概念</option></select></label>
              <label class="kohya-field" :title="legacyTooltips.cropRatio"><span>预处理裁切比例</span><CropRatioField v-model="draft.crop_ratio" input-class="kohya-input" @update:model-value="markParam('crop_ratio')" /></label>
            </div>
            <div class="field-row equal-columns spaced-row">
              <label class="kohya-field" :title="legacyTooltips.trigger"><span>Trigger 触发词</span><input v-model="draft.trigger" class="kohya-input" type="text" placeholder="输入触发词" @input="markRoot('trigger')" /></label>
              <label class="kohya-field" :title="legacyTooltips.regDir"><span>正则数据集（可选）</span><span class="reg-path-row"><input v-model="draft.reg_dir" class="kohya-input" type="text" placeholder="可留空" @input="markRoot('reg_dir')" /><button class="kohya-button compact" type="button" :title="legacyTooltips.chooseRegDir" @click.stop="browse('reg_dir')">选择文件夹…</button></span></label>
            </div>
            <div class="field-row spaced-row">
              <label class="kohya-field" :title="legacyTooltips.stylePreset"><span>出图风格</span><select v-model="draft.style_preset" class="kohya-select" @change="onStylePresetChange"><option>自定义</option><option>动漫</option><option>写实</option></select></label>
              <span class="inline-hint">只微调学习率：动漫 ×0.85 更精细、写实 ×1.15 更自然；rank 等仍按模式自动。</span>
            </div>
            <div v-if="trainingType === '画风'" class="field-row spaced-row">
              <label class="kohya-field" :title="legacyTooltips.styleCaption"><span>画风描述词（可选）</span><input v-model="draft.style_caption" class="kohya-input" placeholder="留空使用自动打标" @input="markRoot('style_caption')" /></label>
            </div>
            <p v-if="triggerGuidance" class="card-hint trigger-hint">{{ triggerGuidance }}</p>
            <div v-if="trainingType === '概念'" class="field-row spaced-row concept-row">
              <label class="kohya-field" :title="datasetGuidance"><span>概念类型</span><select v-model="draft.concept_type" class="kohya-select" @change="markRoot('concept_type')"><option v-for="option in conceptOptions" :key="option.key" :value="option.key">{{ option.label }}</option></select></label>
              <button class="check-line" :title="legacyTooltips.cleanConcept" :class="{ checked: draft.clean_concept }" type="button" role="checkbox" :aria-checked="draft.clean_concept" @click="draft.clean_concept = !draft.clean_concept; markParam('clean_concept')"><i></i><span>自动清洗概念标签（推荐）</span></button>
            </div>
            <button v-if="trainingType !== '画风'" class="switch-line" :title="legacyTooltips.strongBind" :class="{ enabled: draft.strong_bind }" type="button" role="switch" :aria-checked="draft.strong_bind" @click="draft.strong_bind = !draft.strong_bind; markParam('strong_bind')">
              <span class="switch-track"><i></i></span><span><strong>强绑定</strong><small>固定 trigger 与训练集共有特征词在标签开头</small></span>
            </button>
            <label class="kohya-field sample-preview-field" :title="legacyTooltips.samplePreview"><span>训练中采样预览</span><select v-model="draft.sample_preview_mode" class="kohya-select" @change="markParam('sample_preview')"><option value="auto">按显存使用默认设置</option><option value="on">开启</option><option value="off">关闭（减少额外耗时）</option></select></label>
          </section>
          </div>
        </div>

        <div class="utility-row">
          <button v-for="action in [{ label: '数据预处理', key: 'preprocess', tip: legacyTooltips.preprocess }, { label: '标签编辑器', key: 'label_editor', tip: legacyTooltips.labelEditor }, { label: '打开输出目录', key: 'output_dir', tip: legacyTooltips.openOutput }, { label: '导出配置', key: 'export_config', tip: '' }, { label: '使用说明', key: 'readme', tip: legacyTooltips.readme }]" :key="action.key" class="utility-button" type="button" :title="action.tip || undefined" @click="desktop ? requestAction(action.key) : previewOnly(action.label)">{{ action.label }}</button>
          <button v-if="draft.base_type === 'anima'" class="utility-button" type="button" :title="legacyTooltips.animaComponents" @click="requestAction('anima_components')">Anima 配套组件</button>
          <button v-if="isAmdGpu && supports('amd_mode')" class="utility-button" type="button" @click="requestAction('amd_env')">AMD 环境检查 / 安装引导</button>
        </div>
        <p v-if="desktop" class="preview-note"><span></span>配置直接保存到项目；可在此预处理图集、检查标签，再按当前模式支持情况启动训练。</p>
        <p v-else class="preview-note"><span></span>工作区视觉预览 · 修改可暂存在当前浏览器会话；不会写入本机项目，也不会启动训练。</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.kohya-workspace { display:flex; flex:1 1 auto; flex-direction:column; min-width:0; min-height:0; color:var(--text); }
.kohya-toolbar { display:flex; flex:0 0 auto; align-items:center; justify-content:space-between; gap:16px; min-height:58px; padding:9px 24px 7px; border-bottom:1px solid rgb(255 255 255 / 2.5%); }
.kohya-heading,.kohya-heading-copy,.kohya-toolbar-actions { display:flex; align-items:center; }
.kohya-heading { gap:16px; min-width:0; }.kohya-heading-copy { gap:12px; min-width:0; }.kohya-heading-copy h1 { margin:0; color:#d1d4da; font-size:17px; font-weight:350; white-space:nowrap; }.kohya-heading-copy span { overflow:hidden; color:var(--hint); font-size:11px; text-overflow:ellipsis; white-space:nowrap; }
.kohya-back,.kohya-button { display:inline-flex; align-items:center; justify-content:center; gap:6px; min-height:31px; padding:0 10px; border:1px solid var(--border); border-radius:5px; color:#afb5bf; background:transparent; font-size:11px; cursor:pointer; transition:background-color 140ms ease,border-color 140ms ease,color 140ms ease,transform 110ms ease-out; }.kohya-back:hover,.kohya-button:hover { border-color:#4c525d; color:#d2d5db; background:#2a2e36; }.kohya-back:active,.kohya-button:active { transform:translateY(1px); }.kohya-back .ui-icon { width:13px; height:13px; }.kohya-toolbar-actions { gap:8px; }.kohya-button.primary { border-color:transparent; color:#e5e7eb; background:#626f81; }.kohya-button.primary:hover { background:#6b7788; }.kohya-button.primary .ui-icon { width:13px; height:13px; }.kohya-button.compact { min-height:28px; padding:0 9px; font-size:10px; white-space:nowrap; }
.kohya-status-line { display:flex; flex:0 0 auto; gap:7px; min-height:35px; align-items:center; padding:3px 24px 6px; }.status-sample { display:inline-flex; align-items:center; height:23px; padding:0 9px; border:1px solid #3b3e46; border-radius:4px; color:#9da4ae; background:#262930; font-size:10px; }
.kohya-scroll-area { flex:1 1 auto; min-height:0; overflow:auto; scrollbar-color:#4a4e56 transparent; scrollbar-width:thin; }.kohya-scroll-area::-webkit-scrollbar { width:9px; }.kohya-scroll-area::-webkit-scrollbar-thumb { border:2px solid var(--bg); border-radius:8px; background:#4b5059; }.kohya-scroll-content { display:flex; flex-direction:column; gap:11px; padding:5px 26px 13px 24px; }
.base-summary { display:flex; align-items:center; gap:10px; min-height:58px; padding:8px 11px; border:1px solid rgb(255 255 255 / 2%); border-radius:7px; background:var(--card); }.base-mark { display:grid; width:32px; height:32px; flex:0 0 auto; place-items:center; border:1px solid #414752; border-radius:6px; color:#aeb6c1; background:#2b2f38; }.base-mark .ui-icon { width:16px; height:16px; }.base-copy { display:grid; flex:1; min-width:0; gap:2px; }.base-copy span,.output-name > span { color:var(--hint); font-size:9px; }.base-copy strong { overflow:hidden; color:#cdd1d8; font-size:12px; font-weight:400; text-overflow:ellipsis; white-space:nowrap; }.base-copy small { overflow:hidden; color:#858b95; font-size:9px; text-overflow:ellipsis; white-space:nowrap; }.base-type-select { width:min(280px,100%); height:26px; min-height:26px; padding-left:6px; font-size:10px; }.output-name { display:grid; width:min(220px,24%); gap:4px; }.output-name .kohya-input { height:27px; }
.kohya-columns { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); align-items:start; gap:11px; }.kohya-column { display:flex; min-width:0; flex-direction:column; gap:11px; }.kohya-card { min-width:0; padding:12px 13px 11px; border:1px solid rgb(255 255 255 / 2%); border-radius:7px; background:var(--card); transition:background-color 150ms ease,border-color 150ms ease; }.kohya-card:hover { border-color:rgb(255 255 255 / 5%); background:#292c34; }
.card-heading { display:flex; align-items:center; gap:9px; min-height:25px; margin-bottom:10px; }.step-number { color:#8993a0; font-size:10px; letter-spacing:.04em; }.card-heading > div:not(.parameter-title) { display:grid; gap:2px; }.card-heading h2 { margin:0; color:#cbd0d7; font-size:13px; font-weight:400; }.card-heading small { color:var(--hint); font-size:9px; }.parameter-heading { margin-bottom:10px; }.parameter-title { display:flex; flex:1; align-items:baseline; gap:8px; }
.folder-row { display:flex; align-items:center; gap:9px; min-height:43px; padding:6px 8px; border:1px solid #393d46; border-radius:5px; background:#22252c; }.folder-row > .ui-icon { width:15px; height:15px; color:#9da7b5; }.folder-copy { display:grid; flex:1; min-width:0; gap:3px; }.folder-copy span,.kohya-field > span { color:var(--hint); font-size:10px; }.folder-copy strong { overflow:hidden; color:#bfc4cc; font-size:11px; font-weight:350; text-overflow:ellipsis; white-space:nowrap; }.dataset-counts { display:flex; align-items:center; gap:9px; min-height:28px; color:#8f959f; font-size:10px; }.dataset-counts b { color:#c2c7cf; font-weight:400; }.dataset-counts > i { width:1px; height:11px; background:#454951; }.sample-state { margin-left:auto; color:#9298a2; }.field-row { display:flex; align-items:end; gap:10px; }.field-row.equal-columns > * { flex:1; }.kohya-field { display:grid; min-width:0; gap:5px; }.kohya-input,.kohya-select { width:100%; min-width:0; height:30px; padding:0 9px; border:1px solid #3d414a; border-radius:5px; color:#c6cbd3; background:#22252c; font-size:11px; font-weight:350; }.kohya-select { padding-right:22px; cursor:pointer; }.kohya-select option { color:#cbd0d7; background:#252830; }.kohya-input::placeholder { color:#707680; }.card-hint,.inline-hint { margin:8px 0 0; color:var(--hint); font-size:10px; line-height:1.4; }.inline-hint { align-self:center; }.spaced-row { margin-top:9px; }
.sample-preview-field { max-width:360px; margin-top:8px; }.trigger-hint { white-space:pre-line; }.train-env-field { grid-column:1/-1; }
.reg-path-row { display:flex; min-width:0; gap:6px; }.reg-path-row .kohya-input { flex:1; }
.check-line { display:inline-flex; align-items:center; gap:7px; min-height:28px; padding:2px 3px; border:0; color:#a7adb7; background:transparent; font-size:10px; text-align:left; cursor:pointer; }.check-line > i { display:grid; width:14px; height:14px; flex:0 0 auto; place-items:center; border:1px solid #646a75; border-radius:3px; background:#22252c; transition:border-color 130ms ease,background-color 130ms ease; }.check-line.checked > i { border-color:#687689; background:#626f81; }.check-line.checked > i::after { width:6px; height:3px; border-bottom:1.4px solid #e2e5e9; border-left:1.4px solid #e2e5e9; transform:translateY(-1px) rotate(-45deg); content:''; }.check-line:hover { color:#d0d4da; }.switch-line { display:flex; align-items:center; gap:8px; width:100%; margin-top:10px; padding:5px 0 0; border:0; color:inherit; background:transparent; text-align:left; cursor:pointer; }.switch-track { position:relative; width:27px; height:15px; flex:0 0 auto; border-radius:10px; background:#454951; transition:background-color 160ms ease; }.switch-track i { position:absolute; top:2px; left:2px; width:11px; height:11px; border-radius:50%; background:#aeb3bb; transition:transform 170ms var(--ease-out),background-color 160ms ease; }.switch-line.enabled .switch-track { background:#626f81; }.switch-line.enabled .switch-track i { background:#e0e3e8; transform:translateX(12px); }.switch-line > span:last-child { display:grid; gap:2px; }.switch-line strong { color:#bfc4cc; font-size:11px; font-weight:400; }.switch-line small { color:var(--hint); font-size:9px; }
.parameter-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; }.concept-row .check-line { align-self:end; }.advanced-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); align-items:end; gap:9px; margin-top:10px; padding:10px; border:1px solid #363a43; border-radius:5px; background:#23262d; }.advanced-grid .kohya-select,.advanced-grid .kohya-input { height:29px; }.chevron { display:inline-block; margin-left:5px; transition:transform 180ms var(--ease-out); }.chevron.open { transform:rotate(180deg); }.kohya-accordion-enter-active,.kohya-accordion-leave-active { transition:max-height 190ms var(--ease-out),opacity 140ms ease,transform 180ms var(--ease-out); }.kohya-accordion-enter-from,.kohya-accordion-leave-to { max-height:0; opacity:0; transform:translateY(-3px); }.kohya-accordion-enter-to,.kohya-accordion-leave-from { max-height:100px; opacity:1; transform:translateY(0); }
.parameter-scope-note { grid-column:1/-1; margin:0; color:var(--hint); font-size:10px; line-height:1.4; }
.utility-row { display:flex; flex-wrap:wrap; gap:7px; padding:2px 1px; }.utility-button { min-height:29px; padding:0 10px; border:1px solid var(--border); border-radius:5px; color:#afb5bf; background:#252830; font-size:10px; cursor:pointer; transition:border-color 130ms ease,color 130ms ease,background-color 130ms ease,transform 110ms ease-out; }.utility-button:hover { border-color:#505660; color:#d0d4da; background:#2b2e36; }.utility-button:active { transform:scale(.985); }.preview-note { display:flex; align-items:center; gap:7px; margin:-3px 1px 0; color:#818792; font-size:10px; }.preview-note > span { width:5px; height:5px; border-radius:50%; background:#929baa; }
@media(max-width:1200px) { .kohya-toolbar { padding-right:18px; padding-left:20px; }.kohya-scroll-content { padding-right:21px; padding-left:20px; } }
@media(max-width:1120px) { .kohya-heading-copy { display:grid; gap:2px; }.kohya-columns,.kohya-column { display:contents; }.kohya-dataset-card { order:1; }.kohya-training-card { order:2; }.parameter-card { order:3; }.utility-row { order:4; }.preview-note { order:5; }.advanced-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }.base-summary { flex-wrap:wrap; }.output-name { flex:1 0 100%; width:100%; } }
@media(prefers-reduced-motion:reduce) { .kohya-accordion-enter-active,.kohya-accordion-leave-active { transition-duration:.01ms; } }
</style>
