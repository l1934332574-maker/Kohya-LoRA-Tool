<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import type { ModeWorkspaceData, ProjectCard, ProjectConfig, QwenModelChoice, QwenModelSaveResult, QwenModelSelection, QwenModelSetup } from '../bridge'
import UiIcon from './UiIcon.vue'
import CropRatioField from './CropRatioField.vue'
import { legacyTooltips } from '../legacyTooltips'
import { normalizeWd14Model } from '../modelDefaults'

const props = defineProps<{
  project: ProjectCard
  config?: ProjectConfig | null
  desktop: boolean
  mode?: 'qwen_image' | 'zimage'
  modelSetup?: QwenModelSetup | null
  details?: ModeWorkspaceData | null
  choosePath: (kind: 'folder' | 'model') => Promise<string | null>
  saveModel: (selection: QwenModelSelection) => Promise<QwenModelSaveResult>
}>()
const emit = defineEmits<{
  back: [patch: ProjectConfig]
  notify: [message: string]
  save: [patch: ProjectConfig]
  train: [patch: ProjectConfig]
  classicAction: [action: string, patch?: ProjectConfig]
}>()

const demoChoices: QwenModelChoice[] = [
  { key: 'qwen_2512', label: 'Qwen-Image-2512（默认）', model_id: 'Qwen/Qwen-Image-2512', arch: 'qwen_image', size: '约 40GB', default: true },
  { key: 'qwen_21', label: 'Qwen-Image-2.1', model_id: 'Qwen/Qwen-Image-2.1', arch: 'qwen_image_2', size: '约 40GB' },
]
const demoZimageChoices: QwenModelChoice[] = [
  { key: 'zimage', label: 'Z-Image（默认）', model_id: 'Tongyi-MAI/Z-Image', arch: 'zimage', size: '约 16GB', default: true },
]
const modelChoices = computed(() => props.modelSetup?.choices?.length ? props.modelSetup.choices : props.mode === 'zimage' ? demoZimageChoices : demoChoices)
const workspaceLabel = computed(() => props.mode === 'zimage' ? 'Z-Image' : 'Qwen-Image')
const modelDialogOpen = ref(false)
const advancedOpen = ref(false)
const selectedModel = ref(props.mode === 'zimage' ? 'Z-Image' : 'Qwen-Image-2.1')
const selectedModelKey = ref(props.mode === 'zimage' ? 'zimage' : 'qwen_21')
const modelSource = ref<'local' | 'download'>('local')
const modelLocalPath = ref(props.desktop ? '' : props.mode === 'zimage' ? 'D:\\AI\\models\\Z-Image' : 'D:\\AI\\ComfyUI\\models\\unet\\qwen_image_2.1_bf16.safetensors')
const textEncoderPath = ref('')
const vaePath = ref('')
const draftModel = ref(selectedModel.value)
const draftModelKey = ref(selectedModelKey.value)
const draftSource = ref(modelSource.value)
const draftLocalPath = ref(modelLocalPath.value)
const draftTextEncoderPath = ref(textEncoderPath.value)
const draftVaePath = ref(vaePath.value)
const dirty = reactive(new Set<string>())
const configuredParams = new Set<string>()
const trainingDraft = reactive({
  at_sub_mode: 'character',
  concept_type: 'form',
  fast_tier: 'auto',
  raw_dir: '',
  trigger: '',
  style_preset: '自定义',
  reg_dir: '',
  style_caption: '',
  crop_ratio: '',
  rank: '',
  alpha: '',
  unet_lr: '',
  resolution: '',
  video_steps: '',
  save_every: '',
  sample_interval: '',
  optimizer: 'auto',
  sample_prompt: '',
  wd14_model: 'swinv2-v3',
  strong_bind: true,
  clean_concept: true,
  sample_preview_mode: 'auto',
  overwrite: false,
  amd_mode: false,
})
const conceptOptions = [
  { key: 'form', label: '形态/种族（美人鱼·半人马）' },
  { key: 'outfit', label: '服装（同款衣服）' },
  { key: 'object', label: '物品（道具/武器）' },
  { key: 'bodypart', label: '身体部位（异色瞳/翅膀）' },
]
const trainingTypeOptions = [
  { key: 'character', label: '人物（保留全部标签）' },
  { key: 'style', label: '画风（过滤人物标签）' },
  { key: 'concept', label: '概念（形态/种族）' },
]
const trainingType = ref('人物（保留全部标签）')
const resizeMode = ref('不裁切（保比例）')
const customResizeRatio = ref('')
const strongBind = ref(true)
const samplePreview = ref(true)
const trigger = ref('qwen_person')
const regexDirectory = ref('')
const styleCaption = ref('')
const conceptType = ref('形态 / 种族')
const cleanConceptTags = ref(true)
const overwriteExisting = ref(false)
const wd14Model = ref('swinv2-v3（推荐）')
const samplePrompt = ref('')
function modelName(choice?: QwenModelChoice) {
  if (!choice) return props.mode === 'zimage' ? 'Z-Image' : 'Qwen-Image-2.1'
  return choice.model_id?.split('/').pop() || choice.label.replace(/（默认）/g, '')
}

function applySetup(setup?: QwenModelSetup | null) {
  if (!setup?.ok) return
  const choice = modelChoices.value.find((item) => item.key === setup.selected_key) ?? modelChoices.value[0]
  selectedModelKey.value = setup.selected_key || choice?.key || ''
  selectedModel.value = modelName(choice)
  modelSource.value = setup.source || 'download'
  modelLocalPath.value = String(setup.settings?.local_dir || '')
  textEncoderPath.value = String(setup.settings?.text_encoder_path || '')
  vaePath.value = String(setup.settings?.vae_path || '')
  draftModelKey.value = selectedModelKey.value
  draftModel.value = selectedModel.value
  draftSource.value = modelSource.value
  draftLocalPath.value = modelLocalPath.value
  draftTextEncoderPath.value = textEncoderPath.value
  draftVaePath.value = vaePath.value
}

watch(() => props.modelSetup, (setup) => applySetup(setup), { immediate: true, deep: true })

const selectedChoice = computed(() => modelChoices.value.find((item) => item.key === selectedModelKey.value))
const draftChoice = computed(() => modelChoices.value.find((item) => item.key === draftModelKey.value))
const modelLabel = computed(() => `${selectedModel.value}${modelSource.value === 'local' ? '（本地）' : '（下载）'}`)
const modelPathSummary = computed(() => modelSource.value === 'download'
  ? `${selectedChoice.value?.model_id || `Qwen/${selectedModel.value}`} · 开始训练时按需准备`
  : modelLocalPath.value ? `${props.desktop ? '' : '示例路径 · '}${modelLocalPath.value}` : '尚未指定本地模型路径')
const isStyle = computed(() => trainingType.value === '画风')
const isConcept = computed(() => trainingType.value === '概念')
const draftIsConcept = computed(() => trainingDraft.at_sub_mode === 'concept')
const draftIsStyle = computed(() => trainingDraft.at_sub_mode === 'style')
const usesFastTier = computed(() => selectedChoice.value?.arch === 'qwen_image' || selectedChoice.value?.arch === 'zimage')
const isAmdGpu = computed(() => String(props.modelSetup?.gpu_vendor || props.details?.gpu_vendor || '').toLowerCase() === 'amd')
const canSetComponents = computed(() => draftChoice.value?.arch === 'qwen_image_2' && draftSource.value === 'local' && draftLocalPath.value.toLowerCase().endsWith('.safetensors'))
const presetParamKeys = ['rank', 'alpha', 'unet_lr', 'resolution', 'video_steps', 'save_every', 'sample_interval'] as const
function presetFor(): Record<string, unknown> {
  const key = props.mode === 'zimage' ? 'zimage' : 'qwen_image'
  return props.details?.presets?.[key]?.sdxl ?? props.details?.defaults ?? {}
}
function styledPresetValue(key: string, style = trainingDraft.style_preset): string {
  const raw = presetFor()[key]
  if (raw === undefined || raw === null || raw === '') return ''
  const number = Number(raw)
  const factor = style === '动漫' ? 0.85 : style === '写实' ? 1.15 : 1
  return factor !== 1 && Number.isFinite(number) ? (number * factor).toExponential(2).replace('e-0', 'e-').replace('e+0', 'e+') : String(raw)
}
const componentStatus = (kind: 'text_encoder_path' | 'vae_path') => {
  if (!props.desktop) return '未验证'
  if (modelSource.value === 'download') return '随模型仓库准备'
  if (!modelLocalPath.value.toLowerCase().endsWith('.safetensors')) return '由本地 Diffusers 模型提供'
  const configured = String(props.modelSetup?.settings?.[kind] || '')
  const detected = String(props.modelSetup?.auto_components?.[kind] || '')
  return configured ? '已手动指定' : detected ? '已在本机找到' : '缺少时才会准备'
}

function hydrateConfig(config?: ProjectConfig | null) {
  const params = config?.params && typeof config.params === 'object' ? config.params : {}
  const text = (value: unknown) => value === null || value === undefined ? '' : String(value)
  const demo = !props.desktop && !config
  trainingDraft.at_sub_mode = text(config?.at_sub_mode) || 'character'
  trainingDraft.concept_type = text(config?.concept_type) || 'form'
  trainingDraft.fast_tier = text(config?.fast_tier) || 'auto'
  trainingDraft.raw_dir = text(config?.raw_dir ?? props.project.raw_dir) || (demo ? 'C:\\Users\\admin\\Desktop\\图集\\Qwen 人像' : '')
  trainingDraft.trigger = text(config?.trigger) || (demo ? 'qwen_person' : '')
  trainingDraft.style_preset = text(config?.style_preset) || '自定义'
  trainingDraft.reg_dir = text(config?.reg_dir)
  trainingDraft.style_caption = text(config?.style_caption)
  configuredParams.clear()
  Object.keys(params).forEach((key) => configuredParams.add(key))
  const preset = presetFor()
  const demoValues: Record<string, string> = { rank: '16', alpha: '16', unet_lr: '1e-4', resolution: '1024', video_steps: '2000', save_every: '200', sample_interval: '250' }
  for (const key of ['crop_ratio', 'rank', 'alpha', 'unet_lr', 'resolution', 'video_steps', 'save_every', 'sample_interval', 'optimizer', 'sample_prompt', 'wd14_model'] as const) {
    const defaultValue = preset[key] === undefined ? '' : key === 'unet_lr' ? styledPresetValue(key, trainingDraft.style_preset) : String(preset[key])
    const value = text(params[key]) || defaultValue || (demo ? demoValues[key] ?? (key === 'optimizer' ? 'auto' : '') : key === 'optimizer' ? 'auto' : '')
    trainingDraft[key] = key === 'wd14_model' ? normalizeWd14Model(value) : value
  }
  trainingDraft.strong_bind = params.strong_bind === undefined ? true : Boolean(params.strong_bind)
  trainingDraft.clean_concept = params.clean_concept === undefined ? true : Boolean(params.clean_concept)
  trainingDraft.sample_preview_mode = params.sample_preview === undefined ? 'auto' : Boolean(params.sample_preview) ? 'on' : 'off'
  trainingDraft.overwrite = Boolean(params.overwrite)
  trainingDraft.amd_mode = Boolean(params.amd_mode)
  dirty.clear()
}

watch(() => props.config, (config) => hydrateConfig(config), { immediate: true, deep: true })

function markRoot(key: string) { dirty.add(key) }
function markParam(key: string) { dirty.add(`params.${key}`) }

function onStylePresetChange() {
  markRoot('style_preset')
  const value = styledPresetValue('unet_lr')
  if (value) { trainingDraft.unet_lr = value; markParam('unet_lr') }
}

function resetPreset() {
  trainingDraft.style_preset = '自定义'
  markRoot('style_preset')
  const preset = presetFor()
  for (const key of presetParamKeys) {
    if (preset[key] === undefined) continue
    trainingDraft[key] = String(preset[key])
    configuredParams.delete(key)
    markParam(key)
  }
  emit('notify', '当前模式的推荐预设已恢复。保存设置后生效。')
}

function makePatch(): ProjectConfig {
  const patch: ProjectConfig = {}
  for (const key of ['at_sub_mode', 'concept_type', 'fast_tier', 'raw_dir', 'trigger', 'reg_dir', 'style_preset', 'style_caption'] as const) {
    if (dirty.has(key)) patch[key] = trainingDraft[key]
  }
  const params: Record<string, unknown> = {}
  for (const key of ['crop_ratio', 'rank', 'alpha', 'unet_lr', 'resolution', 'video_steps', 'save_every', 'sample_interval', 'optimizer', 'sample_prompt', 'wd14_model'] as const) {
    if (dirty.has(`params.${key}`)) params[key] = trainingDraft[key]
  }
  for (const key of ['strong_bind', 'clean_concept', 'overwrite', 'amd_mode'] as const) {
    if (dirty.has(`params.${key}`)) params[key] = trainingDraft[key]
  }
  if (dirty.has('params.sample_preview')) params.sample_preview = trainingDraft.sample_preview_mode === 'auto' ? null : trainingDraft.sample_preview_mode === 'on'
  if (Object.keys(params).length) patch.params = params
  return patch
}

function saveConfig() {
  const patch = makePatch()
  if (!Object.keys(patch).length) return emit('notify', '当前没有修改训练配置。')
  emit('save', patch)
}

function startTraining() {
  if (!props.desktop) return previewOnly('训练')
  emit('train', makePatch())
}

async function browseDataset() {
  if (!props.desktop) return previewOnly('选择图集')
  const path = await props.choosePath('folder')
  if (!path) return
  trainingDraft.raw_dir = path
  markRoot('raw_dir')
}

async function guideAction(action: string): Promise<ProjectConfig | null> {
  if (action !== 'cmd_pick_raw') return null
  await browseDataset()
  return dirty.has('raw_dir') ? makePatch() : null
}

async function browseRegDirectory() {
  if (!props.desktop) return previewOnly('选择正则图片文件夹')
  const path = await props.choosePath('folder')
  if (!path) return
  trainingDraft.reg_dir = path
  markRoot('reg_dir')
}

async function applyModelChoice() {
  if (props.desktop) {
    const result = await props.saveModel({
      mode: props.mode || 'qwen_image',
      key: draftModelKey.value,
      source: draftSource.value,
      local_dir: draftLocalPath.value,
      text_encoder_path: draftTextEncoderPath.value,
      vae_path: draftVaePath.value,
    })
    if (!result.ok) return
    if (result.setup) applySetup(result.setup)
    modelDialogOpen.value = false
    return
  }
  selectedModel.value = draftModel.value
  selectedModelKey.value = draftModelKey.value
  modelSource.value = draftSource.value
  modelLocalPath.value = draftLocalPath.value
  textEncoderPath.value = draftTextEncoderPath.value
  vaePath.value = draftVaePath.value
  modelDialogOpen.value = false
  emit('notify', `预览已应用 ${selectedModel.value}；此操作不会修改项目配置。`)
}

function setModelSource(source: 'local' | 'download') {
  draftSource.value = source
  if (!props.desktop && source === 'local' && !draftLocalPath.value) {
    draftLocalPath.value = props.mode === 'zimage'
      ? 'D:\AI\models\Z-Image'
      : draftModel.value === 'Qwen-Image-2.1'
      ? 'D:\\AI\\ComfyUI\\models\\unet\\qwen_image_2.1_bf16.safetensors'
      : 'D:\\AI\\ComfyUI\\models\\diffusion_models\\qwen_image_2512_bf16.safetensors'
  }
}

function openModelDialog() {
  draftModel.value = selectedModel.value
  draftModelKey.value = selectedModelKey.value
  draftSource.value = modelSource.value
  draftLocalPath.value = modelLocalPath.value
  draftTextEncoderPath.value = textEncoderPath.value
  draftVaePath.value = vaePath.value
  modelDialogOpen.value = true
}

function selectModel(key: string) {
  const choice = modelChoices.value.find((item) => item.key === key)
  if (!choice) return
  draftModelKey.value = key
  draftModel.value = modelName(choice)
  if (draftSource.value === 'local') {
    draftLocalPath.value = props.desktop ? '' : props.mode === 'zimage'
      ? 'D:\AI\models\Z-Image'
      : choice.arch === 'qwen_image_2'
      ? 'D:\\AI\\ComfyUI\\models\\unet\\qwen_image_2.1_bf16.safetensors'
      : 'D:\\AI\\ComfyUI\\models\\diffusion_models\\qwen_image_2512_bf16.safetensors'
    if (choice.arch !== 'qwen_image_2') {
      draftTextEncoderPath.value = ''
      draftVaePath.value = ''
    }
  }
}

async function browseModel(kind: 'folder' | 'model') {
  if (!props.desktop) return previewOnly('浏览本地模型')
  const path = await props.choosePath(kind)
  if (path) draftLocalPath.value = path
}

async function browseComponent(kind: 'text_encoder_path' | 'vae_path') {
  if (!props.desktop) return previewOnly(kind === 'text_encoder_path' ? '浏览文本编码器' : '浏览 VAE')
  const path = await props.choosePath('model')
  if (path) {
    if (kind === 'text_encoder_path') draftTextEncoderPath.value = path
    else draftVaePath.value = path
  }
}

function resetModelChoice() {
  const fallback = modelChoices.value.find((item) => item.default) ?? modelChoices.value[0]
  if (!fallback) return
  draftModelKey.value = fallback.key
  draftModel.value = modelName(fallback)
  draftSource.value = 'download'
  draftLocalPath.value = ''
  draftTextEncoderPath.value = ''
  draftVaePath.value = ''
}

function previewOnly(action: string) {
  emit('notify', `${action}仅展示界面效果，当前不会调用本机训练功能。`)
}

function requestAction(action: string) {
  if (!props.desktop && !['readme', 'at_model_help'].includes(action)) return previewOnly(action)
  emit('classicAction', action, makePatch())
}

defineExpose({ startTraining, guideAction, openModelDialog })

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && modelDialogOpen.value) modelDialogOpen.value = false
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <section class="qwen-workspace" :aria-label="`${workspaceLabel} 训练工作区`">
    <header class="qwen-toolbar">
      <div class="qwen-heading">
        <button class="qwen-back" type="button" @click="emit('back', makePatch())"><UiIcon name="back" /> 返回项目</button>
        <div class="qwen-heading-copy">
          <h1>{{ workspaceLabel }} LoRA 训练</h1>
          <span>项目：{{ project.name }}</span>
        </div>
      </div>
      <div class="qwen-toolbar-actions">
        <button v-if="desktop && details?.engine_update_available" class="qwen-engine-update" type="button" :title="legacyTooltips.engineUpdate" @click="requestAction('at_engine_update')"><span class="update-arrow">↗</span> 引擎更新可用</button>
        <button class="qwen-button subtle" type="button" :title="legacyTooltips.modelHelp" @click="requestAction('at_model_help')">模型 / 显存说明</button>
        <button class="qwen-button" type="button" :title="legacyTooltips.modelPath" @click="openModelDialog">{{ desktop ? '模型设置' : '选择训练模型' }}</button>
        <button v-if="desktop" class="qwen-button" type="button" @click="saveConfig">保存设置</button>
        <button v-else class="qwen-button" type="button" @click="saveConfig">保存预览设置</button>
        <button v-if="desktop" class="qwen-button primary" type="button" @click="startTraining"><UiIcon name="play" /> 一键开始训练</button>
      </div>
    </header>

    <div class="qwen-status-line" aria-label="运行状态">
      <span v-if="desktop" class="status-chip sample">模型设置已连接</span>
      <span v-else class="status-chip sample">运行环境状态 · 示例</span>
      <span v-if="!desktop" class="status-chip gpu">GPU 信息 · 示例</span>
    </div>

    <div class="qwen-scroll-area">
      <div class="qwen-scroll-content">
        <section class="qwen-model-card">
          <div class="model-mark"><UiIcon name="model" /></div>
          <div class="model-copy">
            <span class="eyebrow">当前训练模型</span>
            <strong>{{ modelLabel }}</strong>
            <span class="model-path" :title="legacyTooltips.modelPath + '\n' + modelPathSummary">{{ modelPathSummary }}</span>
          </div>
          <div class="model-components">
            <span class="component-unverified">文本编码器 · {{ componentStatus('text_encoder_path') }}</span>
            <span class="component-unverified">VAE · {{ componentStatus('vae_path') }}</span>
          </div>
          <button class="qwen-button compact" type="button" :title="legacyTooltips.modelPath" @click="openModelDialog">更换模型</button>
        </section>

        <section class="qwen-card qwen-editor-card">
            <header class="qwen-card-header"><div><span class="section-index">01</span><h2>图集与训练方式</h2></div><span class="card-note">修改后可保存到当前项目</span></header>
            <div class="dataset-path-row">
              <div class="path-mark"><UiIcon name="folder" /></div>
              <div class="path-copy"><span class="field-caption">原始图片文件夹</span><strong :title="trainingDraft.raw_dir || undefined">{{ trainingDraft.raw_dir || '尚未选择图集文件夹' }}</strong></div>
              <button class="qwen-button compact" type="button" :title="legacyTooltips.chooseRawDir" @click="browseDataset">浏览…</button>
            </div>
            <div class="desktop-dataset-options">
              <label class="qwen-field" :title="legacyTooltips.wd14Model"><span class="field-caption">自动打标模型</span><select v-model="trainingDraft.wd14_model" class="qwen-select" @change="markParam('wd14_model')"><option value="swinv2-v3">swinv2-v3（推荐）</option><option value="moat-v2">moat-v2（旧版）</option></select></label>
              <button class="check-toggle" :title="legacyTooltips.overwrite" :class="{ checked: trainingDraft.overwrite }" type="button" role="checkbox" :aria-checked="trainingDraft.overwrite" @click="trainingDraft.overwrite = !trainingDraft.overwrite; markParam('overwrite')"><i></i><span>重新处理已存在的图片（改过标签后勾上，否则不生效）</span></button>
            </div>
            <p class="card-footnote">修改过标签、裁切比例或打标模型时，勾选重新处理已有图片后再执行数据预处理。</p>
            <div class="task-fields qwen-project-fields">
              <label class="qwen-field" :title="legacyTooltips.atSubMode"><span class="field-caption">训练类型</span><select v-model="trainingDraft.at_sub_mode" class="qwen-select" @change="markRoot('at_sub_mode')"><option v-for="option in trainingTypeOptions" :key="option.key" :value="option.key">{{ option.label }}</option></select></label>
              <label class="qwen-field" :title="legacyTooltips.cropRatio"><span class="field-caption">预处理裁切比例</span><CropRatioField v-model="trainingDraft.crop_ratio" input-class="qwen-input" @update:model-value="markParam('crop_ratio')" /></label>
              <label class="qwen-field" :title="legacyTooltips.stylePreset"><span class="field-caption">出图风格</span><select v-model="trainingDraft.style_preset" class="qwen-select" @change="onStylePresetChange"><option>自定义</option><option>动漫</option><option>写实</option></select></label>
              <label v-if="usesFastTier" class="qwen-field" :title="legacyTooltips.fastTier"><span class="field-caption">快跑档</span><select v-model="trainingDraft.fast_tier" class="qwen-select" @change="markRoot('fast_tier')"><option value="auto">自动（8G）</option><option value="on">开（强制）</option><option value="off">关</option></select></label>
              <label class="qwen-field" :title="legacyTooltips.trigger"><span class="field-caption">Trigger 触发词</span><input v-model="trainingDraft.trigger" class="qwen-input" placeholder="输入触发词" @input="markRoot('trigger')" /></label>
              <label v-if="details?.supports?.reg_dir" class="qwen-field" :title="legacyTooltips.regDir"><span class="field-caption">正则数据集（可选）</span><span class="reg-path-row"><input v-model="trainingDraft.reg_dir" class="qwen-input" placeholder="可留空" @input="markRoot('reg_dir')" /><button class="qwen-button compact" type="button" :title="legacyTooltips.chooseRegDir" @click.stop="browseRegDirectory">选择文件夹…</button></span></label>
              <label v-if="draftIsStyle" class="qwen-field" :title="legacyTooltips.styleCaption"><span class="field-caption">画风描述词（可选）</span><input v-model="trainingDraft.style_caption" class="qwen-input" placeholder="留空使用自动打标" @input="markRoot('style_caption')" /></label>
              <label v-if="draftIsConcept" class="qwen-field" :title="details?.concept_type_hints?.[trainingDraft.concept_type] || legacyTooltips.conceptType"><span class="field-caption">概念类型</span><select v-model="trainingDraft.concept_type" class="qwen-select" @change="markRoot('concept_type')"><option v-for="option in conceptOptions" :key="option.key" :value="option.key">{{ option.label }}</option></select></label>
            </div>
            <div v-if="draftIsConcept" class="concept-fields">
              <button class="check-toggle" :title="legacyTooltips.cleanConcept" :class="{ checked: trainingDraft.clean_concept }" type="button" role="checkbox" :aria-checked="trainingDraft.clean_concept" @click="trainingDraft.clean_concept = !trainingDraft.clean_concept; markParam('clean_concept')"><i></i><span>自动清洗概念标签（推荐）</span></button>
              <span class="card-footnote">按概念类型去除概念本身的重复标签，仅在概念模式生效。</span>
            </div>
            <button v-if="!draftIsStyle" class="bind-toggle" :title="legacyTooltips.strongBind" :class="{ active: trainingDraft.strong_bind }" type="button" role="switch" :aria-checked="trainingDraft.strong_bind" @click="trainingDraft.strong_bind = !trainingDraft.strong_bind; markParam('strong_bind')"><span class="toggle-track"><i></i></span><span class="bind-copy"><strong>强绑定</strong><small>自动把 trigger + 训练集 100% 一致的特征词固定到标签开头</small></span></button>
            <label class="qwen-field sample-preview-field" :title="legacyTooltips.samplePreview"><span class="field-caption">训练中采样预览</span><select v-model="trainingDraft.sample_preview_mode" class="qwen-select" @change="markParam('sample_preview')"><option value="auto">按显存使用默认设置</option><option value="on">开启</option><option value="off">关闭（减少额外耗时）</option></select></label>
          </section>

          <section class="qwen-card parameter-card">
            <header class="qwen-card-header parameter-header"><div><span class="section-index">02</span><h2>训练参数</h2><span class="parameters-summary">空白沿用项目预设</span></div><button class="advanced-trigger" type="button" :aria-expanded="advancedOpen" @click="advancedOpen = !advancedOpen">{{ advancedOpen ? '收起高级参数' : '高级参数' }}<span class="chevron" :class="{ open: advancedOpen }">⌄</span></button></header>
            <div class="parameter-grid qwen-project-params">
              <label class="qwen-field parameter-field" :title="legacyTooltips.rank"><span class="field-caption">LoRA rank</span><input v-model="trainingDraft.rank" class="qwen-input" type="number" min="1" placeholder="16" @input="markParam('rank')" /></label>
              <label class="qwen-field parameter-field" :title="legacyTooltips.alpha"><span class="field-caption">LoRA alpha</span><input v-model="trainingDraft.alpha" class="qwen-input" type="number" min="1" placeholder="16" @input="markParam('alpha')" /></label>
              <label class="qwen-field parameter-field" :title="legacyTooltips.unet_lr"><span class="field-caption">学习率</span><input v-model="trainingDraft.unet_lr" class="qwen-input" placeholder="1e-4" @input="markParam('unet_lr')" /></label>
              <label class="qwen-field parameter-field" :title="legacyTooltips.resolution"><span class="field-caption">训练分辨率</span><input v-model="trainingDraft.resolution" class="qwen-input" type="number" min="64" step="64" placeholder="1024" @input="markParam('resolution')" /></label>
              <label class="qwen-field parameter-field" :title="legacyTooltips.videoSteps"><span class="field-caption">训练步数</span><input v-model="trainingDraft.video_steps" class="qwen-input" type="number" min="1" placeholder="2000" @input="markParam('video_steps')" /></label>
              <div class="fixed-setting" title="Qwen-Image 按总训练步数运行，不使用图片循环次数。"><span class="field-caption">图片循环次数</span><strong>此模式按总训练步数运行</strong><small>经典界面也不启用 repeats。</small></div>
            </div>
            <Transition name="accordion">
              <div v-if="advancedOpen" class="advanced-panel"><div class="advanced-controls">
                <label class="qwen-field" :title="legacyTooltips.saveEverySteps"><span class="field-caption">模型保存间隔（步）</span><input v-model="trainingDraft.save_every" class="qwen-input" type="number" min="1" placeholder="沿用自动值" @input="markParam('save_every')" /></label>
                <label class="qwen-field" :title="legacyTooltips.sampleIntervalSteps"><span class="field-caption">采样预览间隔（步）</span><input v-model="trainingDraft.sample_interval" class="qwen-input" type="number" min="0" placeholder="留空 / 0 使用默认 250 步" @input="markParam('sample_interval')" /></label>
                <label class="qwen-field" :title="legacyTooltips.optimizer"><span class="field-caption">优化器</span><select v-model="trainingDraft.optimizer" class="qwen-select" @change="markParam('optimizer')"><option value="auto">自动</option><option value="adamw">AdamW</option><option value="adamw8bit">AdamW8bit</option><option value="lion">Lion</option></select></label>
                <label class="qwen-field advanced-prompt" :title="legacyTooltips.samplePrompt"><span class="field-caption">采样预览提示词</span><input v-model="trainingDraft.sample_prompt" class="qwen-input" placeholder="留空自动生成；填写后整句生效" @input="markParam('sample_prompt')" /></label>
                <button class="reset-preset" type="button" :title="legacyTooltips.resetPreset" @click="resetPreset">恢复预设</button>
                <button v-if="isAmdGpu" class="check-toggle" :title="legacyTooltips.amdMode" :class="{ checked: trainingDraft.amd_mode }" type="button" role="checkbox" :aria-checked="trainingDraft.amd_mode" @click="trainingDraft.amd_mode = !trainingDraft.amd_mode; markParam('amd_mode')"><i></i><span>AMD 兼容模式（实验性）</span></button>
              </div></div>
            </Transition>
          </section>

          <div class="qwen-utility-row" aria-label="训练工具">
            <button class="utility-button" type="button" :title="legacyTooltips.preprocess" @click="requestAction('preprocess')">数据预处理（含自动打标）</button>
            <button class="utility-button" type="button" :title="legacyTooltips.labelEditor" @click="requestAction('label_editor')">标签编辑器</button>
            <button class="utility-button" type="button" :title="legacyTooltips.openOutput" @click="requestAction('output_dir')">打开输出目录</button>
            <button class="utility-button" type="button" @click="requestAction('export_config')">导出配置</button>
            <button class="utility-button" type="button" :title="legacyTooltips.readme" @click="requestAction('readme')">使用说明</button>
            <button v-if="isAmdGpu" class="utility-button" type="button" @click="requestAction('amd_env')">AMD 环境检查 / 安装引导</button>
          </div>

        <p v-if="desktop" class="qwen-bottom-hint"><span class="hint-dot"></span>训练配置保存到当前项目；{{ workspaceLabel }} 按训练步数运行，不使用图片循环次数。预处理、训练、日志和停止均在此界面完成。</p>
        <p v-else class="qwen-bottom-hint"><span class="hint-dot"></span>训练页预览 · 设置可暂存在当前浏览器会话；不会写入本机项目或启动训练。</p>
      </div>
    </div>

    <Transition name="model-dialog">
      <div v-if="modelDialogOpen" class="model-dialog-backdrop" @click.self="modelDialogOpen = false">
        <section class="model-dialog" role="dialog" aria-modal="true" aria-labelledby="qwen-model-title" @keydown.esc="modelDialogOpen = false">
          <header class="model-dialog-header">
          <div><span class="eyebrow">AI Toolkit · {{ workspaceLabel }}</span><h2 id="qwen-model-title">选择训练模型</h2></div>
            <button class="dialog-close" type="button" aria-label="关闭" @click="modelDialogOpen = false">×</button>
          </header>
          <p class="dialog-description">选择{{ workspaceLabel }}模型来源。下载会在开始训练时按需进行；本地模型可沿用已有权重及配套组件。</p>
          <div class="model-options">
            <button v-for="choice in modelChoices" :key="choice.key" class="model-option" :title="choice.hint || legacyTooltips.modelPath" :class="{ chosen: draftModelKey === choice.key }" type="button" @click="selectModel(choice.key)">
              <span class="option-radio"></span><span class="option-copy"><strong>{{ choice.label }}</strong><small>{{ choice.arch === 'qwen_image_2' ? '支持指定本地权重、文本编码器与 VAE' : `${choice.size || 'Qwen-Image'} · 官方架构` }}</small></span>
            </button>
          </div>
          <div class="model-source-switch" role="tablist" aria-label="模型来源">
            <button :class="{ selected: draftSource === 'download' }" type="button" role="tab" :aria-selected="draftSource === 'download'" @click="setModelSource('download')">下载模型</button>
            <button :class="{ selected: draftSource === 'local' }" type="button" role="tab" :aria-selected="draftSource === 'local'" @click="setModelSource('local')">使用本地模型</button>
          </div>
          <div v-if="draftSource === 'download'" class="source-detail">
            <span class="field-caption">下载仓库</span>
            <strong>{{ draftChoice?.model_id || draftModel }}</strong>
            <p>这里只保存模型选择；模型文件在经典训练流程中按需准备，本机已缓存的文件会复用。</p>
          </div>
          <div v-else class="source-detail local-source-detail">
            <label class="qwen-field" :title="legacyTooltips.modelPath"><span class="field-caption">本地 Diffusers 目录或权重文件</span><span class="path-input-row"><input v-model="draftLocalPath" class="qwen-input" type="text" placeholder="粘贴路径，或选择本机目录 / 文件" /><button class="qwen-button compact" type="button" @click="browseModel('folder')">选目录…</button><button v-if="draftChoice?.arch === 'qwen_image_2'" class="qwen-button compact" type="button" @click="browseModel('model')">选权重…</button></span></label>
            <div v-if="canSetComponents" class="component-paths">
              <label class="qwen-field" :title="legacyTooltips.textEncoderPath"><span class="field-caption">文本编码器（可选）</span><span class="path-input-row"><input v-model="draftTextEncoderPath" class="qwen-input" type="text" placeholder="留空自动查找，或指定现有文件" /><button class="qwen-button compact" type="button" @click="browseComponent('text_encoder_path')">浏览…</button><button class="qwen-button compact" type="button" @click="draftTextEncoderPath = ''">自动</button></span></label>
              <label class="qwen-field" :title="legacyTooltips.vaePath"><span class="field-caption">VAE（可选）</span><span class="path-input-row"><input v-model="draftVaePath" class="qwen-input" type="text" placeholder="留空自动查找，或指定现有文件" /><button class="qwen-button compact" type="button" @click="browseComponent('vae_path')">浏览…</button><button class="qwen-button compact" type="button" @click="draftVaePath = ''">自动</button></span></label>
              <p>文本编码器和 VAE 路径会在保存时校验；留空优先自动查找本机已有组件，只准备缺失组件。</p>
            </div>
          </div>
          <div class="model-dialog-note"><UiIcon name="folder" /><span>{{ desktop ? '保存时会检查本地模型和组件文件；不会下载模型。' : '预览不扫描磁盘、不校验路径，也不会写入模型设置。' }}</span></div>
          <footer><button class="qwen-button compact" type="button" @click="modelDialogOpen = false">取消</button><button v-if="desktop" class="qwen-button compact" type="button" @click="resetModelChoice">恢复官方默认</button><button class="qwen-button primary compact" type="button" @click="applyModelChoice">{{ desktop ? '保存模型设置' : '使用所选模型' }}</button></footer>
        </section>
      </div>
    </Transition>
  </section>
</template>

<style scoped>
.qwen-workspace { display: flex; flex: 1 1 auto; flex-direction: column; min-width: 0; min-height: 0; color: var(--text); animation: workspace-in 180ms var(--ease-out) both; }
@keyframes workspace-in { from { opacity: .55; transform: translateY(3px); } to { opacity: 1; transform: translateY(0); } }
.qwen-toolbar { display: flex; flex: 0 0 auto; align-items: center; justify-content: space-between; gap: 16px; min-height: 58px; padding: 9px 24px 7px; border-bottom: 1px solid rgb(255 255 255 / 2.5%); }
.qwen-heading { display: flex; align-items: center; gap: 16px; min-width: 0; }
.qwen-back { display: inline-flex; align-items: center; gap: 6px; height: 29px; padding: 0 9px; border: 1px solid var(--border); border-radius: 5px; color: #abb1bb; background: transparent; font-size: 11px; cursor: pointer; transition: background-color 130ms ease, border-color 130ms ease, color 130ms ease; }
.qwen-back:hover { border-color: #4a505b; color: #d0d3d9; background: #272a32; }
.qwen-back :deep(.ui-icon) { width: 13px; height: 13px; }
.qwen-heading-copy { display: flex; align-items: baseline; gap: 12px; min-width: 0; }
.qwen-heading-copy h1 { margin: 0; color: #d1d4da; font-size: 17px; font-weight: 350; white-space: nowrap; }
.qwen-heading-copy span { overflow: hidden; color: var(--hint); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.qwen-toolbar-actions { display: flex; gap: 8px; }
.qwen-engine-update { display: inline-flex; align-items: center; gap: 6px; min-height: 32px; padding: 0 10px; border: 1px solid #827047; border-radius: 6px; color: #d3bd8b; background: #302c22; font-size: 11px; white-space: nowrap; cursor: pointer; transition: background-color 140ms ease, border-color 140ms ease; }
.qwen-engine-update:hover { border-color: #a18a59; background: #393326; }
.update-arrow { display: inline-block; animation: update-arrow-pulse 900ms ease-in-out infinite alternate; }
@keyframes update-arrow-pulse { from { transform: translateY(2px) rotate(-10deg); opacity: .68; } to { transform: translateY(-2px) rotate(8deg); opacity: 1; } }
.qwen-button { display: inline-flex; align-items: center; justify-content: center; min-height: 32px; padding: 0 11px; border: 1px solid var(--border); border-radius: 6px; color: #b7bdc6; background: transparent; font-size: 11px; cursor: pointer; transition: background-color 140ms ease, border-color 140ms ease, color 140ms ease, transform 110ms ease-out; }
.qwen-button:hover { border-color: #4c525d; color: #d2d5db; background: #2a2e36; }
.qwen-button:active { transform: translateY(1px); }
.qwen-button.primary { border-color: transparent; color: #e5e7eb; background: #626f81; }
.qwen-button.primary:hover { background: #6b7788; }
.qwen-button.compact { min-height: 29px; padding: 0 10px; font-size: 11px; white-space: nowrap; }
.qwen-status-line { display: flex; flex: 0 0 auto; align-items: center; gap: 7px; min-height: 37px; padding: 3px 24px 7px; overflow: hidden; }
.status-chip { display: inline-flex; align-items: center; gap: 6px; height: 24px; padding: 0 9px; border: 1px solid transparent; border-radius: 4px; color: #9da4ae; background: #292c34; font-size: 10px; white-space: nowrap; }
.status-chip.gpu { color: #aab3c0; background: #282e38; }
.status-chip.sample { border-color: #3b3e46; color: #a0a4ab; background: #262930; }
.qwen-scroll-area { flex: 1 1 auto; min-height: 0; overflow: auto; scrollbar-color: #4a4e56 transparent; scrollbar-width: thin; }
.qwen-scroll-area::-webkit-scrollbar { width: 9px; }
.qwen-scroll-area::-webkit-scrollbar-thumb { border: 2px solid var(--bg); border-radius: 8px; background: #4b5059; }
.qwen-scroll-content { display: flex; flex-direction: column; gap: 11px; padding: 5px 26px 13px 24px; }
.qwen-model-card, .qwen-card { border: 1px solid rgb(255 255 255 / 2%); border-radius: 7px; background: var(--card); transition: background-color 150ms ease, border-color 150ms ease; }
.qwen-model-card { display: flex; align-items: center; gap: 12px; min-height: 68px; padding: 10px 13px; }
.model-mark { display: grid; width: 34px; height: 34px; flex: 0 0 auto; place-items: center; border: 1px solid #414752; border-radius: 6px; color: #aeb6c1; background: #2b2f38; }
.model-mark :deep(.ui-icon) { width: 17px; height: 17px; }
.model-copy { display: grid; flex: 1 1 auto; min-width: 0; gap: 2px; }
.eyebrow, .field-caption { color: var(--hint); font-size: 10px; font-weight: 400; }
.model-copy strong { color: #cdd1d8; font-size: 13px; font-weight: 400; }
.model-path { overflow: hidden; color: #858b95; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.model-components { display: flex; flex: 0 0 auto; gap: 13px; margin: 0 6px; }
.component-unverified, .dataset-ready { display: inline-flex; align-items: center; gap: 6px; color: #9298a2; font-size: 10px; white-space: nowrap; }
.component-planned { color: #9298a2; font-size: 10px; white-space: nowrap; }
.qwen-card-grid { display: grid; grid-template-columns: minmax(0, 1.06fr) minmax(0, .94fr); gap: 11px; }
.qwen-card { min-width: 0; padding: 12px 13px 11px; }
.qwen-editor-card .dataset-path-row { margin-bottom: 9px; }
.qwen-project-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.qwen-project-params { grid-template-columns: repeat(6, minmax(88px, 1fr)); }
.sample-preview-field { max-width:360px; margin-top:8px; }
.reg-path-row { display:flex; min-width:0; gap:6px; }.reg-path-row .qwen-input { flex:1; }
.advanced-prompt { grid-column: span 2; }
.qwen-card:hover { border-color: rgb(255 255 255 / 5%); background: #292c34; }
.qwen-card-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 23px; margin-bottom: 9px; }
.qwen-card-header > div { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
.section-index { color: #8993a0; font-size: 10px; font-weight: 400; letter-spacing: .04em; }
.qwen-card-header h2 { margin: 0; color: #cbd0d7; font-size: 13px; font-weight: 400; }
.card-note { overflow: hidden; color: var(--hint); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.dataset-path-row { display: flex; align-items: center; gap: 9px; min-height: 45px; padding: 6px 8px; border: 1px solid #393d46; border-radius: 5px; background: #22252c; }
.path-mark { display: grid; width: 27px; height: 27px; flex: 0 0 auto; place-items: center; border-radius: 4px; color: #9da7b5; background: #2c3039; }
.path-mark :deep(.ui-icon) { width: 14px; height: 14px; }
.path-copy { display: grid; flex: 1; min-width: 0; gap: 3px; }
.path-copy strong { overflow: hidden; color: #bfc4cc; font-size: 11px; font-weight: 350; text-overflow: ellipsis; white-space: nowrap; }
.dataset-meta { display: flex; align-items: center; gap: 9px; min-height: 27px; padding: 0 2px; color: #8f959f; font-size: 10px; }
.dataset-meta b { color: #c2c7cf; font-weight: 400; }
.meta-divider { width: 1px; height: 11px; background: #454951; }
.dataset-ready { margin-left: auto; }
.dataset-options { display: grid; grid-template-columns: minmax(180px, .75fr) minmax(150px, 1fr); align-items: end; gap: 11px; margin: 2px 0 7px; }
.dataset-options .qwen-select { height: 28px; }
.card-footnote { margin: 0; color: var(--hint); font-size: 10px; line-height: 1.4; }
.task-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; }
.trigger-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; margin-top: 8px; }
.conditional-field { margin-top: 8px; }
.concept-fields { display: grid; grid-template-columns: minmax(170px, .8fr) 1fr; align-items: end; gap: 10px; margin-top: 8px; }
.qwen-field { display: grid; min-width: 0; gap: 5px; }
.qwen-select, .qwen-input { width: 100%; min-width: 0; height: 31px; padding: 0 9px; border: 1px solid #3d414a; border-radius: 5px; color: #c6cbd3; background: #22252c; font-size: 11px; font-weight: 350; }
.qwen-select { padding-right: 25px; cursor: pointer; }
.qwen-select option { color: #cbd0d7; background: #252830; }
.qwen-input::placeholder { color: #707680; }
.bind-toggle { display: flex; align-items: center; gap: 8px; width: 100%; margin-top: 8px; padding: 5px 0 0; border: 0; color: inherit; background: transparent; text-align: left; cursor: pointer; }
.toggle-track { position: relative; width: 27px; height: 15px; flex: 0 0 auto; border-radius: 10px; background: #454951; transition: background-color 160ms ease; }
.toggle-track i { position: absolute; top: 2px; left: 2px; width: 11px; height: 11px; border-radius: 50%; background: #aeb3bb; transition: transform 170ms var(--ease-out), background-color 160ms ease; }
.bind-toggle.active .toggle-track { background: #626f81; }
.bind-toggle.active .toggle-track i { background: #e0e3e8; transform: translateX(12px); }
.bind-copy { display: grid; gap: 2px; }
.bind-copy strong { color: #bfc4cc; font-size: 11px; font-weight: 400; }
.bind-copy small { color: var(--hint); font-size: 9px; }
.check-toggle { display: inline-flex; align-items: center; gap: 7px; min-height: 28px; padding: 2px 3px; border: 0; color: #a7adb7; background: transparent; font-size: 10px; text-align: left; cursor: pointer; }
.check-toggle > i { display: grid; width: 14px; height: 14px; flex: 0 0 auto; place-items: center; border: 1px solid #646a75; border-radius: 3px; background: #22252c; transition: border-color 130ms ease, background-color 130ms ease; }
.check-toggle.checked > i { border-color: #687689; background: #626f81; }
.check-toggle.checked > i::after { width: 6px; height: 3px; border-bottom: 1.4px solid #e2e5e9; border-left: 1.4px solid #e2e5e9; transform: translateY(-1px) rotate(-45deg); content: ''; }
.check-toggle:hover { color: #d0d4da; }
.sampling-row { display: grid; grid-template-columns: auto minmax(180px, 1fr); align-items: end; gap: 10px; margin-top: 8px; padding-top: 7px; border-top: 1px solid #373b44; }
.sampling-prompt .qwen-input { height: 28px; }
.parameter-card { padding: 12px 13px 13px; }
.parameter-header { margin-bottom: 10px; }
.parameters-summary { margin-left: 2px; color: #808690; font-size: 10px; }
.advanced-trigger { display: inline-flex; align-items: center; gap: 7px; min-height: 27px; padding: 0 9px; border: 1px solid #3c414a; border-radius: 5px; color: #aab1bc; background: transparent; font-size: 10px; cursor: pointer; transition: border-color 140ms ease, color 140ms ease, background-color 140ms ease; }
.advanced-trigger:hover { border-color: #515761; color: #cbd0d7; background: #2b2e36; }
.chevron { display: inline-block; transform: rotate(0); transition: transform 180ms var(--ease-out); }
.chevron.open { transform: rotate(180deg); }
.parameter-grid { display: grid; grid-template-columns: repeat(5, minmax(90px, 1fr)); gap: 8px; }
.parameter-field { gap: 4px; }
.parameter-field .qwen-select, .parameter-field .qwen-input { height: 29px; }
.advanced-panel { overflow: hidden; }
.advanced-controls { display: grid; grid-template-columns: repeat(4, minmax(110px, 1fr)); align-items: end; gap: 9px; margin-top: 10px; padding: 10px; border: 1px solid #363a43; border-radius: 5px; background: #23262d; }
.advanced-controls .qwen-select, .advanced-controls .qwen-input { height: 29px; }
.fixed-setting { display: grid; min-height: 50px; align-content: center; gap: 3px; padding: 4px 1px; }
.fixed-setting strong { color: #bac0c9; font-size: 10px; font-weight: 400; }
.fixed-setting small { color: var(--hint); font-size: 9px; }
.reset-preset { min-height: 28px; justify-self: start; padding: 0 9px; border: 1px solid #41464f; border-radius: 5px; color: #aeb4be; background: transparent; font-size: 10px; cursor: pointer; }
.reset-preset:hover { border-color: #59616f; color: #d1d5db; background: #2b2f37; }
.accordion-enter-active, .accordion-leave-active { transition: max-height 190ms var(--ease-out), opacity 140ms ease, transform 180ms var(--ease-out); }
.accordion-enter-from, .accordion-leave-to { max-height: 0; opacity: 0; transform: translateY(-3px); }
.accordion-enter-to, .accordion-leave-from { max-height: 90px; opacity: 1; transform: translateY(0); }
.qwen-utility-row { display: flex; flex-wrap: wrap; gap: 7px; padding: 2px 1px; }
.utility-button { min-height: 30px; padding: 0 10px; border: 1px solid var(--border); border-radius: 5px; color: #afb5bf; background: #252830; font-size: 10px; cursor: pointer; transition: border-color 130ms ease, color 130ms ease, background-color 130ms ease, transform 110ms ease-out; }
.utility-button:hover { border-color: #505660; color: #d0d4da; background: #2b2e36; }
.utility-button:active { transform: scale(.985); }
.qwen-bottom-hint { display: flex; align-items: center; gap: 7px; margin: -3px 1px 0; color: #818792; font-size: 10px; }
.hint-dot { width: 5px; height: 5px; border-radius: 50%; background: #929baa; }
.model-dialog-backdrop { position: fixed; inset: 0; z-index: 20; display: grid; place-items: center; padding: 22px; background: rgb(10 12 16 / 48%); }
.model-dialog { width: min(100%, 470px); padding: 18px; border: 1px solid #41464f; border-radius: 8px; background: #272a32; box-shadow: 0 16px 42px rgb(0 0 0 / 30%); }
.model-dialog-header { display: flex; align-items: flex-start; justify-content: space-between; }
.model-dialog-header h2 { margin: 4px 0 0; color: #d0d4da; font-size: 17px; font-weight: 350; }
.dialog-close { display: grid; width: 29px; height: 29px; place-items: center; border: 0; border-radius: 5px; color: #aab0b9; background: transparent; font-size: 21px; cursor: pointer; }
.dialog-close:hover { color: #d4d7dd; background: #32363e; }
.dialog-description { margin: 12px 0 14px; color: var(--hint); font-size: 11px; line-height: 1.5; }
.model-options { display: grid; gap: 7px; }
.model-option { display: flex; align-items: center; gap: 10px; min-height: 54px; padding: 8px 10px; border: 1px solid #3c4049; border-radius: 6px; color: inherit; background: #23262d; text-align: left; cursor: pointer; transition: border-color 130ms ease, background-color 130ms ease; }
.model-option:hover, .model-option.chosen { border-color: #667286; background: #2a2f38; }
.option-radio { display: grid; width: 14px; height: 14px; flex: 0 0 auto; place-items: center; border: 1px solid #6d7480; border-radius: 50%; }
.model-option.chosen .option-radio { border-color: #8794a7; }
.model-option.chosen .option-radio::after { width: 6px; height: 6px; border-radius: 50%; background: #aab4c2; content: ''; }
.option-copy { display: grid; flex: 1; gap: 3px; }
.option-copy strong { color: #c9ced6; font-size: 12px; font-weight: 400; }
.option-copy small { color: var(--hint); font-size: 10px; }
.option-state { color: #8f9c91; font-size: 10px; white-space: nowrap; }
.model-dialog-note { display: flex; align-items: center; gap: 7px; margin: 12px 0; color: #858b95; font-size: 10px; }
.model-dialog-note :deep(.ui-icon) { width: 13px; height: 13px; }
.model-source-switch { display: inline-flex; gap: 3px; margin: 13px 0 9px; padding: 3px; border: 1px solid #3b4049; border-radius: 6px; background: #22252c; }
.model-source-switch button { min-height: 28px; padding: 0 10px; border: 1px solid transparent; border-radius: 4px; color: #a3a9b3; background: transparent; font-size: 10px; cursor: pointer; transition: background-color 130ms ease, color 130ms ease, border-color 130ms ease; }
.model-source-switch button:hover { color: #d0d4da; }
.model-source-switch button.selected { border-color: #424853; color: #d2d6dd; background: #30343d; }
.source-detail { display: grid; gap: 6px; padding: 11px; border: 1px solid #3a3e47; border-radius: 5px; background: #22252c; }
.source-detail > strong { color: #c4c9d1; font-size: 11px; font-weight: 400; }
.source-detail > p, .component-paths > p { margin: 0; color: var(--hint); font-size: 10px; line-height: 1.45; }
.local-source-detail { gap: 10px; }
.path-input-row { display: flex; align-items: center; gap: 6px; min-width: 0; }
.path-input-row .qwen-input { flex: 1; }
.component-paths { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 10px; padding-top: 9px; border-top: 1px solid #373b44; }
.component-paths > p { grid-column: 1 / -1; }
.model-dialog footer { display: flex; justify-content: flex-end; gap: 7px; padding-top: 8px; border-top: 1px solid #373b44; }
.model-dialog-enter-active, .model-dialog-leave-active { transition: opacity 150ms ease; }
.model-dialog-enter-active .model-dialog, .model-dialog-leave-active .model-dialog { transition: opacity 150ms ease, transform 180ms var(--ease-out); }
.model-dialog-enter-from, .model-dialog-leave-to { opacity: 0; }
.model-dialog-enter-from .model-dialog, .model-dialog-leave-to .model-dialog { opacity: 0; transform: translateY(6px) scale(.99); }
@media (max-width: 1280px) {
  .qwen-toolbar { padding-right: 18px; padding-left: 20px; }
  .qwen-status-line { padding-left: 20px; }
  .qwen-scroll-content { padding-right: 21px; padding-left: 20px; }
  .model-components { gap: 8px; }
  .parameter-grid { grid-template-columns: repeat(3, minmax(100px, 1fr)); }
}
@media (max-width: 1120px) {
  .qwen-heading-copy { display: grid; gap: 2px; }
  .qwen-card-grid { grid-template-columns: 1fr; }
  .qwen-model-card { flex-wrap: wrap; }
  .model-components { margin-left: 46px; }
  .qwen-project-params { grid-template-columns: repeat(3, minmax(100px, 1fr)); }
  .dataset-options { grid-template-columns: 1fr; gap: 5px; }
  .advanced-controls { grid-template-columns: repeat(2, minmax(110px, 1fr)); }
}
@media (prefers-reduced-motion: reduce) {
  .qwen-workspace { animation: none; }
  .accordion-enter-active, .accordion-leave-active, .model-dialog-enter-active, .model-dialog-leave-active { transition-duration: .01ms; }
}
</style>
