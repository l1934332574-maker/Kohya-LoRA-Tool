<script setup lang="ts">
import LearningRateSchedule from './LearningRateSchedule.vue'
import TrainingFocusControl from './TrainingFocusControl.vue'
import OutputDirectoryControl from './OutputDirectoryControl.vue'
import { computed, reactive, ref, watch } from 'vue'
import type { ModeWorkspaceData, ProjectCard, ProjectConfig } from '../bridge'
import UiIcon from './UiIcon.vue'
import MultiCharacterPanel from './MultiCharacterPanel.vue'
import { useMultiCharacter } from '../useMultiCharacter'
import CropRatioField from './CropRatioField.vue'
import Krea2ComponentsPanel from './Krea2ComponentsPanel.vue'
import DatasetInspection from './DatasetInspection.vue'
import CaptionControls from './CaptionControls.vue'
import H3DataControls from './H3DataControls.vue'
import PixaiTagOptions from './PixaiTagOptions.vue'
import TrainingProfileControl from './TrainingProfileControl.vue'
import AmdCompatibilityBar from './AmdCompatibilityBar.vue'
import { legacyTooltips } from '../legacyTooltips'
import { normalizeWd14Model } from '../modelDefaults'
import { useTrainingProfiles } from '../useTrainingProfiles'
import { normalizeGradientCheckpointing } from '../trainingParameters'

type BrowseKind = 'folder' | 'model'
const props = defineProps<{
  project: ProjectCard
  mode: string
  config?: ProjectConfig | null
  details: ModeWorkspaceData
  desktop: boolean
  componentBusy?: boolean
  saveConfig?: (patch: ProjectConfig) => Promise<boolean>
  choosePath: (kind: BrowseKind, currentPath?: string, memoryKey?: string) => Promise<string | null>
}>()
const emit = defineEmits<{
  continue: [patch: ProjectConfig]
  back: [patch: ProjectConfig]
  notify: [message: string]
  save: [patch: ProjectConfig]
  train: [patch: ProjectConfig]
  classicAction: [action: string, patch?: ProjectConfig]
}>()

const switchingVersion = ref(false)
const dirty = reactive(new Set<string>())
const configuredParams = new Set<string>()
const draft = reactive({
  base_model: '', fizgig_version: '', global_pos: '', global_neg: '', raw_dir: '', trigger: '', reg_dir: '', style_preset: '自定义', style_caption: '', at_sub_mode: 'character', concept_type: 'form',
  rank: '', alpha: '', unet_lr: '', te_lr: '', repeats: '', max_epochs: '', resolution: '',
  video_steps: '', video_frames: '', save_every: '', sample_interval: '', sample_seed: '1234', optimizer: 'auto',
  crop_ratio: '', sample_prompt: '', noise_offset: '', min_snr_gamma: '', quant_mode: 'auto',
  blocks_to_swap: '', pixai_character: false, pixai_copyright: false, pixai_style: false, pixai_threshold: '.17', wd14_model: 'swinv2-v3', sample_preview_mode: 'auto', fast_tier: 'auto', fizgig_qwen_preset: 'auto',
  // ★ 2026-09-27：批大小（留空 = 自动 1）/ 梯度检查点（auto / on / off）
  caption_method: 'wd14', caption_language: 'zh', caption_length: 'brief',
  lr_scheduler: 'auto', lr_warmup_steps: '',
  batch_size: '', gc: 'auto', mask_mode: 'off', mask_source: 'photo', mask_floor: '0.1', mask_overwrite_auto: false,
  moss_preview_base: false, h3_caption_replace: false, h3_sync_trigger: true, strong_bind: true, clean_concept: true, compile: false, overwrite: false, keep_user_captions: false, amd_mode: false,
})

const isKrea2 = computed(() => props.mode === 'krea2_fz')
const componentVersionPending = computed(() => draft.fizgig_version !== props.details.fizgig_version)
const isFizgig = computed(() => props.mode.endsWith('_fz'))
const isV7 = computed(() => isFizgig.value && (props.details.fizgig_standard_versions || ['v7.0.1', 'v7.3.1', 'v8.5.0', 'v8.9.6']).includes(draft.fizgig_version))
const supported = (key: string) => key === 'global_neg' && props.mode === 'zimage_fz' ? false : isFizgig.value && ['optimizer','compile','global_pos','global_neg'].includes(key) ? isV7.value : Boolean(props.details.supports?.[key])
const versions = computed(() => {
  const allowed = props.details.fizgig_compatible_versions || (props.mode === 'moss_fz' ? ['v8.5.0', 'v8.9.6'] : props.mode === 'zimage_fz' ? ['v7.3.1', 'v8.9.6'] : isMulti.value || ['anima_fz', 'sdxl_fz'].includes(props.mode) ? ['v7.0.1', 'v7.3.1', 'v8.9.6'] : ['v6.5.0', 'v7.0.1', 'v7.3.1', 'v8.9.6'])
  return [...new Set([draft.fizgig_version, ...(props.details.fizgig_versions || []), props.details.fizgig_target_version || 'v8.9.6'])].filter(v => v && allowed.includes(v))
})
const legacyFizgigQuant: Record<string, string[]> = { krea2_fz:['auto','fp8','int8','nf4','bf16'], flux2_fz:['auto','fp8','int8','nf4'], qwen21_fz:['auto','bf16','int8','nf4'], h3_fz:['auto','int8','nf4','hqq'] }
const quantModes = computed(() => isV7.value ? (props.mode === 'h3_fz' ? ['auto','int8','nf4','hqq'] : ['auto','bf16','int8','nf4']) : isFizgig.value ? legacyFizgigQuant[props.mode] || [] : props.details.quant_modes?.length ? props.details.quant_modes : ['auto', 'fp8', 'int8', 'nf4'])
const defaults = computed(() => props.details.defaults ?? {})
const isConcept = computed(() => draft.at_sub_mode === 'concept')
const isStyle = computed(() => draft.at_sub_mode === 'style')
const isVideo = computed(() => props.details.is_video)
const officialQwenPreset = computed(() => props.mode === 'qwen21_fz')
const isH3Fizgig = computed(() => props.mode === 'h3_fz')
const engineUpdateAction = computed(() => String(props.details.engine_key || '').includes('fizgig') ? 'fizgig_engine_update' : 'at_engine_update')
const assetReady = computed(() => props.details.missing_models.length === 0)
const modelAction = computed(() => isKrea2.value ? 'cmd_dl_krea2_models' : props.mode === 'moss_fz' ? 'cmd_dl_moss_models' : props.mode === 'zimage_fz' ? 'cmd_dl_zimage_fz_models' : `open_models:${props.mode}`)
const intervalUnit = (key: 'save_every' | 'sample_interval') => props.details.interval_units?.[key] === 'epochs' ? '轮' : '步'
const intervalTooltip = (key: 'save_every' | 'sample_interval') => props.details.interval_hints?.[key] || (key === 'save_every'
  ? props.details.interval_units?.[key] === 'epochs' ? legacyTooltips.saveEveryEpochs : legacyTooltips.saveEverySteps
  : props.details.interval_units?.[key] === 'epochs' ? legacyTooltips.sampleIntervalEpochs : legacyTooltips.sampleIntervalSteps)
const presetParamKeys = ['rank', 'alpha', 'unet_lr', 'te_lr', 'repeats', 'max_epochs', 'resolution', 'video_steps', 'video_frames', 'save_every', 'sample_interval'] as const
function presetFor(): Record<string, unknown> {
  return props.details.presets?.[props.mode]?.sdxl ?? props.details.defaults ?? {}
}
function styledPresetValue(key: string, style = draft.style_preset): string {
  const raw = presetFor()[key]
  if (raw === undefined || raw === null || raw === '') return ''
  const number = Number(raw)
  const factor = !['unet_lr', 'te_lr'].includes(key) ? 1 : style === '动漫' ? 0.85 : style === '写实' ? 1.15 : 1
  return factor !== 1 && Number.isFinite(number) ? (number * factor).toExponential(2).replace(/e([+-])0+(\d+)$/, 'e$1$2') : String(raw)
}
const currentDatasetHint = computed(() => {
  if (!props.details.has_training_submode) return props.details.dataset_hint
  const semanticHint = props.details.dataset_hints?.[draft.at_sub_mode]
  if (isKrea2.value) return semanticHint || '选择原始图集，检查自动生成或已有的标签；预处理完成后确认再开始训练。'
  return semanticHint ? `${semanticHint}\n${props.details.dataset_hint}` : props.details.dataset_hint
})
const currentTriggerHint = computed(() => {
  if (draft.at_sub_mode === 'style') return props.details.trigger_hints?.style || props.details.trigger_hint
  if (draft.at_sub_mode === 'concept') return props.details.trigger_hints?.concept || props.details.trigger_hint
  return props.details.trigger_hint
})

function value(value: unknown, fallback = ''): string {
  return value === null || value === undefined ? fallback : String(value)
}

function hydrate(config?: ProjectConfig | null) {
  const params = config?.params && typeof config.params === 'object' ? config.params : {}
  const rootValue = (key: string, fallback = '') => value(config?.[key], fallback)
  draft.base_model = rootValue('base_model', props.project.base_model || '')
  draft.fizgig_version = value(params.fizgig_version, props.details.fizgig_version || 'v6.5.0')
  draft.global_pos = rootValue('global_pos', value(params.global_pos))
  draft.global_neg = rootValue('global_neg', value(params.global_neg))
  draft.raw_dir = rootValue('raw_dir', props.project.raw_dir || '')
  draft.trigger = rootValue('trigger')
  draft.reg_dir = rootValue('reg_dir')
  draft.style_preset = rootValue('style_preset', '自定义')
  draft.style_caption = rootValue('style_caption')
  draft.at_sub_mode = rootValue('at_sub_mode', 'character')
  draft.concept_type = rootValue('concept_type', 'form')
  draft.style_preset = rootValue('style_preset', '自定义')
  draft.fast_tier = rootValue('fast_tier', 'auto')
  configuredParams.clear()
  Object.keys(params).forEach((key) => configuredParams.add(key))
  const preset = presetFor()
  for (const key of ['rank', 'alpha', 'unet_lr', 'te_lr', 'repeats', 'max_epochs', 'resolution', 'video_steps', 'video_frames', 'save_every', 'sample_interval', 'lr_scheduler', 'lr_warmup_steps', 'sample_seed', 'optimizer', 'crop_ratio', 'sample_prompt', 'noise_offset', 'min_snr_gamma', 'quant_mode', 'blocks_to_swap', 'batch_size', 'gc', 'wd14_model', 'fizgig_qwen_preset'] as const) {
    const defaultValue = preset[key] === undefined ? defaults.value[key] : preset[key]
    const styledDefault = key === 'unet_lr' || key === 'te_lr' ? styledPresetValue(key, draft.style_preset) : defaultValue
    const hydratedValue = value(params[key], styledDefault === undefined ? (key === 'optimizer' || key === 'quant_mode' || key === 'gc' ? 'auto' : '') : String(styledDefault))
    draft[key] = (key === 'wd14_model' ? normalizeWd14Model(hydratedValue) : key === 'gc' ? normalizeGradientCheckpointing(hydratedValue) : key === 'sample_seed' ? hydratedValue || '1234' : hydratedValue) as never
  }
  draft.mask_source = String(params.mask_source || 'photo')
  draft.mask_mode = String(params.mask_mode || 'off')
  draft.mask_floor = String(params.mask_floor ?? .1)
  draft.mask_overwrite_auto = Boolean(params.mask_overwrite_auto)
  draft.pixai_threshold = String(params.pixai_threshold ?? '.17')
  for (const key of ['pixai_character', 'pixai_copyright', 'pixai_style'] as const) draft[key] = Boolean(params[key])
  draft.caption_method = String(params.caption_method || 'wd14')
  draft.caption_language = String(params.caption_language || 'zh')
  draft.caption_length = String(params.caption_length || 'brief')
  draft.strong_bind = params.strong_bind === undefined ? true : Boolean(params.strong_bind)
  draft.clean_concept = params.clean_concept === undefined ? true : Boolean(params.clean_concept)
  draft.sample_preview_mode = params.sample_preview == null ? 'auto' : Boolean(params.sample_preview) ? 'on' : 'off'
  draft.moss_preview_base = Boolean(params.moss_preview_base)
  draft.compile = Boolean(params.compile)
  draft.overwrite = Boolean(params.overwrite)
  draft.keep_user_captions = Boolean(params.keep_user_captions)
  draft.h3_caption_replace = Boolean(params.h3_caption_replace)
  draft.h3_sync_trigger = params.h3_sync_trigger === undefined ? true : Boolean(params.h3_sync_trigger)
  draft.amd_mode = Boolean(params.amd_mode)
  dirty.clear()
}

watch(() => [props.config, props.details] as const, () => hydrate(props.config), { immediate: true, deep: true })

function markRoot(key: string) { dirty.add(key) }
function markParam(key: string) { dirty.add(`params.${key}`) }

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
  if (props.mode === 'qwen21_fz') {
    draft.fizgig_qwen_preset = 'auto'
    configuredParams.delete('fizgig_qwen_preset')
    markParam('fizgig_qwen_preset')
  }
  emit('notify', '当前模式的推荐预设已恢复。保存修改后生效。')
}

const { profileUndo, profileDefaults, profileSupported, applyProfile, undoProfile } = useTrainingProfiles(
  draft, dirty, () => ({ mode: props.mode, defaults: presetFor(), supported: (key) => supported(key) }),
  (message) => emit('notify', message), () => [props.config, props.mode, props.details],
)

const { isMulti, multiSettings, updateMulti, multiPatch } = useMultiCharacter(() => props.config, dirty)

function makePatch(): ProjectConfig {
  const patch: ProjectConfig = { mode: props.mode }
  for (const key of ['base_model', 'global_pos', 'global_neg', 'raw_dir', 'trigger', 'reg_dir', 'style_preset', 'style_caption', 'at_sub_mode', 'concept_type', 'fast_tier'] as const) {
    if (dirty.has(key)) patch[key] = draft[key]
  }
  const params: Record<string, unknown> = {}
  for (const key of ['pixai_character', 'pixai_copyright', 'pixai_style', 'pixai_threshold'] as const) {
    if (dirty.has(`params.${key}`)) params[key] = draft[key]
  }
  for (const key of ['mask_mode', 'mask_floor', 'mask_overwrite_auto', 'mask_source'] as const) {
    if (dirty.has(`params.${key}`)) params[key] = draft[key]
  }
  if (dirty.has('params.fizgig_version')) params.fizgig_version = draft.fizgig_version
  for (const key of ['caption_method', 'caption_language', 'caption_length'] as const) {
    if (dirty.has(`params.${key}`)) params[key] = draft[key]
  }
  for (const key of ['rank', 'alpha', 'unet_lr', 'te_lr', 'repeats', 'max_epochs', 'resolution', 'video_steps', 'video_frames', 'save_every', 'sample_interval', 'lr_scheduler', 'lr_warmup_steps', 'sample_seed', 'optimizer', 'crop_ratio', 'sample_prompt', 'noise_offset', 'min_snr_gamma', 'quant_mode', 'blocks_to_swap', 'batch_size', 'gc', 'wd14_model', 'fizgig_qwen_preset'] as const) {
    if (dirty.has(`params.${key}`)) params[key] = draft[key]
  }
  for (const key of ['strong_bind', 'clean_concept', 'compile', 'overwrite', 'keep_user_captions', 'amd_mode', 'h3_caption_replace', 'h3_sync_trigger', 'moss_preview_base'] as const) {
    if (dirty.has(`params.${key}`)) params[key] = draft[key]
  }
  if (dirty.has('params.sample_preview')) params.sample_preview = draft.sample_preview_mode === 'auto' ? null : draft.sample_preview_mode === 'on'
  if (Object.keys(params).length) patch.params = params
  return multiPatch(patch)
}

function save() {
  if (props.componentBusy || switchingVersion.value) return
  const patch = makePatch()
  if (Object.keys(patch).length === 1 && patch.mode === props.mode) return emit('notify', '当前没有修改项目配置。')
  emit('save', patch)
}

function startTraining() {
  if (props.componentBusy || switchingVersion.value) return
  if (!props.desktop) return emit('notify', '浏览器预览不会启动训练。')
  emit('train', makePatch())
}

async function browseDataset() {
  if (!props.desktop) return emit('notify', '浏览器预览不会调用本机文件选择器。')
  const path = await props.choosePath('folder', String(draft.raw_dir || ''), 'raw_dir')
  if (path) { draft.raw_dir = path; markRoot('raw_dir') }
}

async function browseModel() {
  if (!props.desktop) return emit('notify','浏览器预览不会调用文件选择器。')
  const path = await props.choosePath('model', draft.base_model, 'base_model')
  if (path) { draft.base_model=path; markRoot('base_model') }
}
async function onVersionChange() {
  if (draft.mask_mode !== 'off' && draft.fizgig_version !== 'v8.9.6') {
    draft.fizgig_version = props.details.fizgig_version || 'v8.9.6'
    emit('notify', '旧引擎不支持学习区域。请先把学习重点设为整张图片，再切换版本。')
    return
  }
  if (switchingVersion.value) return
  markParam('fizgig_version')
  if (!quantModes.value.includes(draft.quant_mode)) { draft.quant_mode='auto'; markParam('quant_mode') }
  if (isV7.value && !['auto','adamw','adamw8bit'].includes(draft.optimizer)) { draft.optimizer='auto'; markParam('optimizer') }
  if (!props.saveConfig) { save(); return }
  switchingVersion.value = true
  try {
    if (await props.saveConfig(makePatch())) emit('notify', '已保存所选引擎版本。续训请使用原快照对应的版本。')
  } finally { switchingVersion.value = false }
}
async function guideAction(action: string): Promise<ProjectConfig | null> {
  if (switchingVersion.value) return null
  if (isFizgig.value && action === 'cmd_install_fizgig') return makePatch()
  if (isMulti.value && action === 'cmd_pick_raw') {
    document.querySelector('.multi-panel')?.scrollIntoView({ block: 'start' })
    emit('notify', '请在角色库中分别选择素材目录。')
    return null
  }
  if (action === 'cmd_pick_model_type') {
    if (!supported('base_model')) {
      emit('notify', '当前模式的模型由引擎管理，请使用对应的模型下载入口。')
      return null
    }
    await browseModel()
    return makePatch()
  }
  if (isKrea2.value && action === 'cmd_dl_krea2_models') return makePatch()
  if (action !== 'cmd_pick_raw') return null
  await browseDataset()
  return dirty.has('raw_dir') ? makePatch() : null
}

function requestAction(action: string) {
  if (switchingVersion.value) return
  if (!props.desktop && !['readme', 'krea2_guide', 'flux2_guide', 'h3_guide'].includes(action)) return emit('notify', '浏览器预览中，此操作不会触碰本机数据。')
  emit('classicAction', action, makePatch())
}

defineExpose({ hasUnsavedChanges: () => dirty.size > 0, isBusy: () => switchingVersion.value, startTraining, guideAction, save })

const isAmdGpu = computed(() => String(props.details.gpu_vendor || '').toLowerCase() === 'amd')
</script>

<template>
  <section class="engine-workspace" :aria-label="`${details.label} 新版训练页`">
    <header class="engine-toolbar">
      <div class="engine-heading">
        <button class="engine-back" type="button" :disabled="componentBusy || switchingVersion" @click="emit('back', makePatch())"><UiIcon name="back" /> 返回项目</button>
      <div class="engine-heading-copy"><h1>{{ isMulti ? '多角色 LoRA · ' + details.label : details.label + '训练' }}</h1><span>项目：{{ project.name }}</span></div>
      </div>
      <div class="engine-actions">
        <button class="engine-button" type="button" :disabled="componentBusy || switchingVersion" @click="emit('continue', makePatch())">已有 LoRA 追加训练</button>
        <button v-if="desktop && details.engine_update_available" class="engine-update-button" type="button" :title="isFizgig ? '可选安装新版；项目继续使用当前所选版本。' : legacyTooltips.engineUpdate" :disabled="componentBusy || switchingVersion" @click="requestAction(engineUpdateAction)"><span class="update-arrow">↗</span> {{ isFizgig ? '可选升级引擎' : '引擎更新可用' }}</button>
        <button v-if="desktop" class="engine-button" type="button" :disabled="componentBusy || switchingVersion" @click="save">{{ dirty.size ? '保存修改 · 未保存' : '设置已保存' }}</button>
        <!-- ★ 2026-10-02：与左侧栏重复的「一键开始训练」已移除 ✗（同一动作，只保留侧栏那个）-->

        <button v-else class="engine-button primary" type="button" @click="save">保存预览设置</button>
      </div>
    </header>

    <div class="engine-status-line">
      <span class="engine-status" :class="{ ready: details.engine_ready }">{{ details.engine_ready ? '训练引擎就绪' : '训练引擎未就绪' }}</span>
      <span class="engine-status" :class="{ ready: assetReady }">{{ assetReady ? '模型文件齐全' : `模型文件缺少 ${details.missing_models.length} 项` }}</span>
      <span class="engine-status">{{ details.gpu }}</span>
          <button class="engine-link" type="button" :disabled="componentBusy || switchingVersion" :title="isKrea2 ? '配置项目实际使用的模型和编码器' : '打开当前训练模式的模型文件夹。'" @click="requestAction(modelAction)">{{ isKrea2 ? '配置模型与组件' : '打开模型目录' }}</button>
    </div>
    <AmdCompatibilityBar
      v-if="isAmdGpu && supported('amd_mode')"
      :enabled="draft.amd_mode"
      @toggle="draft.amd_mode = !draft.amd_mode; markParam('amd_mode')"
      @inspect="requestAction('amd_env')"
    />

    <div class="engine-scroll-area">
      <div class="engine-scroll-content" :inert="componentBusy || switchingVersion">
        <p v-if="isKrea2" class="krea2-workflow">环境准备 <span>→</span> 模型与组件 <span>→</span> 图集与标签 <span>→</span> 开始训练</p>
        <MultiCharacterPanel v-if="isMulti" :mode="mode" :model-value="multiSettings" :project-name="project.name" :desktop="desktop" :choose-path="choosePath" @update:model-value="updateMulti" @notify="emit('notify',$event)" />
        <component :is="isKrea2 ? 'details' : 'section'" v-if="isFizgig" class="engine-card runtime-card">
          <summary v-if="isKrea2" class="runtime-summary">环境与引擎 · {{ details.fizgig_version }}<span>{{ switchingVersion ? '正在切换版本' : componentVersionPending ? '版本修改待保存' : details.engine_ready ? '已就绪 · 可展开调整' : '未就绪 · 展开安装' }}</span></summary>
          <div class="runtime-choice"><label class="engine-field"><span>此项目的训练引擎版本</span><select v-model="draft.fizgig_version" class="engine-select" :disabled="switchingVersion" @change="onVersionChange"><option v-for="v in versions" :key="v" :value="v">{{ v }}{{ details.fizgig_versions?.includes(v) ? ' · 已安装' : ' · 需安装 / 更新' }}</option></select></label><button v-if="desktop && !details.engine_ready" class="engine-button compact" type="button" :disabled="componentVersionPending || switchingVersion" @click="requestAction('cmd_install_fizgig')">配置 {{ draft.fizgig_version }}</button></div>
          <p v-if="details.fizgig_engine_detail" class="engine-hint">{{ componentVersionPending ? '版本切换尚未保存。' : details.fizgig_engine_detail }}</p>
          <p class="engine-hint">{{ isV7 ? '普通 LoRA · 文本编码器冻结 · 新版独立缓存。预览按轮数触发，开始时不额外采样，最后一轮只有满足间隔才采样。' : '旧版本项目继续使用原训练入口；升级软件不会自动迁移训练参数和续训快照。' }}</p>
          <p v-if="['anima_fz','sdxl_fz'].includes(mode)" class="engine-hint">上游实验性入口。{{ mode==='anima_fz' ? '仅支持标准 28 层 Anima；2.9B / 40 层请选 Kohya。' : '支持完整 SDXL 同架构底模；不训练文本编码器。' }}</p>
        </component>
        <Krea2ComponentsPanel v-if="isKrea2" :setup="details.krea2_components" :disabled="componentBusy || !desktop" :version-pending="componentVersionPending" @configure="requestAction(modelAction)" @select-encoder="requestAction('krea2_encoder:' + $event)" @component="(key, action) => requestAction('krea2_component:' + key + ':' + action)" />
        <section v-if="mode === 'moss_fz'" class="engine-card">
          <header class="engine-card-heading"><div><h2>模型与训练组件</h2><small>Base 训练 · SFT 预览</small></div><button class="engine-button compact" type="button" @click="requestAction(modelAction)">配置与下载</button></header>
          <div v-for="item in details.moss_components?.items || []" :key="item.key" class="zimage-component-row">
            <span>{{ item.label }}</span><small :title="item.path">{{ item.validation_error || (item.present ? item.path : '未准备') }}</small>
          </div>
          <label class="engine-check"><input v-model="draft.moss_preview_base" type="checkbox" @change="markParam('moss_preview_base')" />使用训练 Base 预览（默认使用 SFT）</label>
        </section>
        <section v-if="mode === 'zimage_fz'" class="engine-card">
          <header class="engine-card-heading"><div><h2>模型与训练组件</h2><small>Z-Image Turbo · 8 步 / CFG 1</small></div><button class="engine-button compact" type="button" @click="requestAction(modelAction)">配置与下载</button></header>
          <div v-for="item in details.zimage_components?.items || []" :key="item.key" class="zimage-component-row">
            <span>{{ item.label }}</span><small :title="item.path">{{ item.validation_error || (item.present ? item.path : '未准备') }}</small>
          </div>
          <p class="engine-hint">可直接指定本地文件。训练适配器保持冻结，预览与成品不包含它。Base 请使用 AI Toolkit 入口。</p>
        </section>
        <section v-if="supported('base_model')" class="engine-card">
          <header class="engine-card-heading"><div><h2>训练底模</h2><small>可选择已有第三方底模；缺少组件再下载</small></div></header>
          <div class="runtime-choice"><input v-model="draft.base_model" class="engine-input" placeholder="选择已有完整 safetensors 底模；留空使用模型目录的标准底模" @input="markRoot('base_model')" /><button class="engine-button compact" type="button" @click="browseModel">选择底模</button><button class="engine-button compact" type="button" @click="requestAction(mode==='anima_fz'?'cmd_dl_anima_fz_models':'cmd_dl_sdxl_fz_models')">下载模型 / 组件</button></div>
        </section>
        <section v-if="!isMulti" class="engine-summary" :class="{ 'dataset-only': isKrea2 }">
          <div class="summary-main">
            <span class="summary-label">{{ isH3Fizgig ? '混合媒体原始目录' : isVideo ? '视频数据目录' : '训练图片目录' }}</span>
            <strong :title="draft.raw_dir || undefined">{{ draft.raw_dir || (desktop ? '尚未选择数据目录' : '预览中：桌面模式会显示项目数据目录') }}</strong>
            <small v-if="currentDatasetHint" :title="currentDatasetHint">{{ currentDatasetHint }}</small>
          </div>
          <button class="engine-button compact" type="button" @click="browseDataset">选择文件夹</button>
          <div v-if="!isKrea2" class="asset-copy">
            <span class="summary-label">模型文件位置</span>
            <strong :title="details.asset_dir || undefined">{{ details.asset_dir || '由引擎按配置管理' }}</strong>
            <small v-if="details.missing_models.length">缺少：{{ details.missing_models.join('、') }}</small>
          </div>
          <button v-if="!isKrea2" class="engine-button compact" type="button" @click="requestAction(modelAction)">{{ ['zimage_fz','moss_fz'].includes(mode) ? '配置模型 / 组件' : '打开模型目录' }}</button>
        </section>

        <div v-if="isMulti"><TrainingFocusControl v-if="supported('loss_masks') || draft.mask_mode !== 'off'" :project-name="project.name" :desktop="desktop" :multi="isMulti" :mode="draft.mask_mode" :source="draft.mask_source" :floor="draft.mask_floor" :overwrite-auto="draft.mask_overwrite_auto" :disabled="Boolean(componentBusy || componentVersionPending)" @change="(key, value) => { Object.assign(draft, { [key]: value }); markParam(key) }" @generate="requestAction('masks')" @edit="requestAction('mask_editor')" /></div>
        <div class="engine-card-grid" :class="{multi:isMulti}">
          <section v-if="!isMulti" class="engine-card">
            <header class="engine-card-heading"><span>{{ isKrea2 ? '02' : '01' }}</span><div><h2>{{ isKrea2 ? '图集、标签与训练方式' : '数据与训练方式' }}</h2><small>按当前模式显示适用项目</small></div></header>
            <div v-if="details.has_training_submode" class="engine-fields two-columns">
              <label class="engine-field" :title="legacyTooltips.atSubMode"><span>训练类型</span><select v-model="draft.at_sub_mode" class="engine-select" @change="markRoot('at_sub_mode')"><option value="character">人物（保留全部标签）</option><option value="style">{{ isH3Fizgig ? '画风（过滤新标签中的人物特征）' : '画风（过滤人物标签）' }}</option><option value="concept">概念</option></select></label>
              <label v-if="isConcept" class="engine-field" :title="details.concept_type_hints?.[draft.concept_type] || legacyTooltips.conceptType"><span>概念类型</span><select v-model="draft.concept_type" class="engine-select" @change="markRoot('concept_type')"><option value="form">形态/种族（美人鱼·半人马）</option><option value="outfit">服装（同款衣服）</option><option value="object">物品（道具/武器）</option><option value="bodypart">身体部位（异色瞳/翅膀）</option></select></label>
            </div>
            <div class="engine-fields two-columns spaced">
              <label v-if="!isVideo" class="engine-field" :title="legacyTooltips.stylePreset"><span>素材风格 / 学习率微调</span><select v-model="draft.style_preset" :disabled="officialQwenPreset" class="engine-select" @change="onStylePresetChange"><option value="自定义">不调整（自定义）</option><option value="动漫">动漫（预设学习率 −15%）</option><option value="写实">写实（预设学习率 +15%）</option></select></label>
              <label class="engine-field" :title="legacyTooltips.trigger"><span>Trigger 触发词</span><input v-model="draft.trigger" class="engine-input" placeholder="可留空；建议使用少见的英文词" @input="markRoot('trigger')" /></label>
              <label v-if="isStyle && (!isH3Fizgig || draft.caption_method === 'wd14')" class="engine-field" :title="legacyTooltips.styleCaption"><span>画风描述词（可选）</span><input v-model="draft.style_caption" class="engine-input" :placeholder="isH3Fizgig ? '添加到新生成的关键词标签' : '留空使用自动打标'" @input="markRoot('style_caption')" /></label>
              <label v-if="supported('crop_ratio') && !isH3Fizgig" class="engine-field" :title="legacyTooltips.cropRatio"><span>预处理裁切比例</span><CropRatioField v-model="draft.crop_ratio" input-class="engine-input" @update:model-value="markParam('crop_ratio')" /></label>
              <label v-if="supported('reg_dir')" class="engine-field" :title="legacyTooltips.regDir"><span>正则数据集（可选）</span><input v-model="draft.reg_dir" class="engine-input" placeholder="选择正则图片文件夹" @input="markRoot('reg_dir')" /></label>
            </div>
            <TrainingFocusControl v-if="supported('loss_masks') || draft.mask_mode !== 'off'" :project-name="project.name" :desktop="desktop" :multi="isMulti" :mode="draft.mask_mode" :source="draft.mask_source" :floor="draft.mask_floor" :overwrite-auto="draft.mask_overwrite_auto" :disabled="Boolean(componentBusy || componentVersionPending)" @change="(key, value) => { Object.assign(draft, { [key]: value }); markParam(key) }" @generate="requestAction('masks')" @edit="requestAction('mask_editor')" />
            <p v-if="officialQwenPreset" class="engine-hint">本模式 rank、alpha 和学习率由下方官方预设接管；页面保留的旧值不参与训练。</p>
            <p v-else-if="!isVideo" class="engine-hint">选择后从当前模式预设重算学习率：动漫降低 15%，写实提高 15%；不保证更清晰或更自然。</p>
            <button v-if="details.has_training_submode && !isStyle && !isH3Fizgig" class="engine-switch" :disabled="draft.caption_method === 'natural'" :title="legacyTooltips.strongBind" :class="{ active: draft.strong_bind }" type="button" role="switch" :aria-checked="draft.strong_bind" @click="draft.strong_bind = !draft.strong_bind; markParam('strong_bind')"><i></i><span><strong>强绑定</strong><small>自动把 trigger + 训练集 100% 一致的特征词固定到标签开头</small></span></button>
            <button v-if="isConcept && (!isH3Fizgig || (draft.caption_method === 'wd14' && ['form', 'outfit'].includes(draft.concept_type)))" class="engine-check" :disabled="draft.caption_method === 'natural'" :title="legacyTooltips.cleanConcept" :class="{ checked: draft.clean_concept }" type="button" role="checkbox" :aria-checked="draft.clean_concept" @click="draft.clean_concept = !draft.clean_concept; markParam('clean_concept')"><i></i><span>{{ isH3Fizgig ? '清洗新生成标签中的概念特征' : '自动清洗概念标签（推荐）' }}</span></button>
            <label v-if="supported('wd14_model') && (!isVideo || isH3Fizgig) && draft.caption_method === 'wd14'" class="engine-field spaced" :title="legacyTooltips.wd14Model"><span>自动打标模型</span><select v-model="draft.wd14_model" class="engine-select" @change="markParam('wd14_model')"><option value="swinv2-v3">WD14 swinv2-v3（默认）</option><option value="moat-v2">WD14 moat-v2（旧版）</option><option value="pixai-v1">PixAI v1.0（内容 / 角色 / 画风）</option></select></label>
            <button v-if="!isVideo && draft.caption_method === 'wd14'" class="engine-check" :class="{ checked: draft.keep_user_captions }" type="button" role="checkbox" :aria-checked="draft.keep_user_captions" @click="draft.keep_user_captions = !draft.keep_user_captions; markParam('keep_user_captions')"><i></i><span>保留已有标签（不自动打标）</span></button>
              <PixaiTagOptions v-if="draft.caption_method === 'wd14' && draft.wd14_model === 'pixai-v1'" :options="draft" :desktop="desktop" @change="(key, value) => { Object.assign(draft, { [key]: value }); markParam(key) }" />
              <CaptionControls v-if="!isVideo || isH3Fizgig" :recursive="isH3Fizgig" :project-name="project.name" :directory="draft.raw_dir" :desktop="desktop" :method="draft.caption_method" :language="draft.caption_language" :length="draft.caption_length" @update:method="draft.caption_method = $event; markParam('caption_method')" @update:language="draft.caption_language = $event; markParam('caption_language')" @update:length="draft.caption_length = $event; markParam('caption_length')" />
              <H3DataControls v-if="isH3Fizgig" :directory="draft.raw_dir" :trigger="draft.trigger" :desktop="desktop" :method="draft.caption_method" :sync-trigger="draft.h3_sync_trigger" :replace="draft.h3_caption_replace" @update:sync-trigger="draft.h3_sync_trigger = $event; markParam('h3_sync_trigger')" @update:replace="draft.h3_caption_replace = $event; markParam('h3_caption_replace')" @action="requestAction" />
              <DatasetInspection v-if="!isVideo" :directory="draft.raw_dir" :desktop="desktop" :natural="draft.caption_method === 'natural'" :keep-captions="draft.keep_user_captions || draft.caption_method !== 'wd14'" @preserve="draft.keep_user_captions = true; markParam('keep_user_captions')" />
              <button v-if="supported('overwrite') && !isVideo" class="engine-check" :title="legacyTooltips.overwrite" :class="{ checked: draft.overwrite }" type="button" role="checkbox" :aria-checked="draft.overwrite" @click="draft.overwrite = !draft.overwrite; markParam('overwrite')"><i></i><span>重新处理已存在的图片（改过标签后勾上，否则不生效）</span></button>
            <p v-if="isH3Fizgig && isConcept && ['object', 'bodypart'].includes(draft.concept_type)" class="engine-hint">物品与身体部位的标签请在标签编辑器中手动检查。</p>
            <p v-if="currentTriggerHint" class="engine-hint">{{ currentTriggerHint }}</p>
          </section>

          <section class="engine-card">
            <header class="engine-card-heading"><span>{{ isKrea2 ? '03' : '02' }}</span><div><h2>常用训练参数</h2><small>空白项沿用当前引擎预设</small></div></header>
            <label v-if="isMulti" class="engine-field"><span>训练中采样预览</span><select v-model="draft.sample_preview_mode" class="engine-select" @change="markParam('sample_preview')"><option value="auto">按显存使用默认设置</option><option value="on">开启</option><option value="off">关闭</option></select></label>
            <TrainingProfileControl :draft="draft" :mode="mode" :defaults="profileDefaults" :supported="profileSupported" :can-undo="Boolean(profileUndo)" @apply="applyProfile" @undo="undoProfile" />
            <div class="engine-param-grid">
              <label v-if="mode !== 'qwen21_fz'" class="engine-field" :title="legacyTooltips.rank"><span>LoRA rank</span><input v-model="draft.rank" :disabled="officialQwenPreset" class="engine-input" type="number" min="1" placeholder="按模式预设" @input="markParam('rank')" /></label>
              <label v-if="mode !== 'qwen21_fz'" class="engine-field" :title="legacyTooltips.alpha"><span>LoRA alpha</span><input v-model="draft.alpha" :disabled="officialQwenPreset" class="engine-input" type="number" min="1" placeholder="按模式预设" @input="markParam('alpha')" /></label>
              <label v-if="mode !== 'qwen21_fz'" class="engine-field" :title="legacyTooltips.unet_lr"><span>学习率</span><input v-model="draft.unet_lr" :disabled="officialQwenPreset" class="engine-input" placeholder="按模式预设" @input="markParam('unet_lr')" /></label>
              <label v-if="supported('te_lr')" class="engine-field" :title="legacyTooltips.te_lr"><span>文本编码器学习率</span><input v-model="draft.te_lr" class="engine-input" placeholder="按模式预设" @input="markParam('te_lr')" /></label>
              <label class="engine-field" :title="legacyTooltips.resolution"><span>训练分辨率</span><input v-model="draft.resolution" class="engine-input" type="number" min="64" step="64" placeholder="按模式预设" @input="markParam('resolution')" /></label>
              <label v-if="supported('quant_mode')" class="engine-field" :title="legacyTooltips.quantMode"><span>{{ isKrea2 ? 'RAW 底模训练量化（与编码器无关）' : '底模量化精度（可手动选 NF4）' }}</span><select v-model="draft.quant_mode" class="engine-select" @change="markParam('quant_mode')"><option v-for="modeOption in quantModes" :key="modeOption" :value="modeOption">{{ modeOption === 'auto' ? '自动（由引擎选择）' : modeOption.toUpperCase() }}</option></select></label>
              <label v-if="supported('repeats')" class="engine-field" :title="legacyTooltips.repeats"><span>{{ isH3Fizgig ? '素材循环次数' : '图片循环次数' }}</span><input v-model="draft.repeats" class="engine-input" type="number" min="1" placeholder="按模式预设" @input="markParam('repeats')" /></label>
              <label v-if="supported('max_epochs')" class="engine-field" :title="legacyTooltips.maxEpochs"><span>最大 epoch</span><input v-model="draft.max_epochs" class="engine-input" type="number" min="1" placeholder="按模式预设" @input="markParam('max_epochs')" /></label>
              <label v-if="supported('video_steps')" class="engine-field" :title="legacyTooltips.videoSteps"><span>训练步数</span><input v-model="draft.video_steps" class="engine-input" type="number" min="1" placeholder="按模式预设" @input="markParam('video_steps')" /></label>
              <label v-if="supported('video_frames')" class="engine-field" :title="legacyTooltips.videoFrames"><span>{{ isH3Fizgig ? '预览采样帧数' : '视频帧数（17n+5）' }}</span><input v-model="draft.video_frames" class="engine-input" type="number" :min="isH3Fizgig ? 1 : 5" :step="isH3Fizgig ? 1 : 17" :placeholder="isH3Fizgig ? '56' : '73'" @input="markParam('video_frames')" /></label>
            </div>
            <label v-if="mode === 'qwen21_fz'" class="engine-field spaced" :title="legacyTooltips.fizgigQwenPreset"><span>Fizgig 官方预设</span><select v-model="draft.fizgig_qwen_preset" class="engine-select" @change="markParam('fizgig_qwen_preset')"><option value="auto">自动（人物/概念 Fast，画风 Style）</option><option value="fast">Fast · rank 8 · 学习率自适应 2e-4~4e-4</option><option value="standard">Standard · rank 16 · 学习率 1e-4~2e-4</option><option value="style">Style · rank 16 · flat 1.5e-4</option></select></label>
            <p v-if="mode === 'qwen21_fz'" class="engine-hint">Fizgig 官方预设控制 rank、alpha 和学习率；底模量化精度可独立选择。默认分辨率 512px，可自行调高。</p>
            <p v-if="isVideo && !isH3Fizgig" class="engine-hint">H3 AI Toolkit 输入视频和同名 .txt 字幕；视频帧数需符合 17n+5 格式。</p>
            <p v-if="isH3Fizgig" class="engine-hint">图片、视频和音频可放在同一目录或子目录，每个媒体都需同名 .txt。MP4 必须为 24fps、帧数符合 17n+5、宽高为 32 的倍数；带音轨时必须为 32kHz 立体声。图片可自动打标，视频可 AI 描述；缓存阶段校验媒体格式。无 audio VAE 时视频音轨会忽略。56 帧只用于预览，不裁剪训练视频。AMD ROCm 为实验性路径，训练兼容性尚未验证。</p>
          </section>
        </div>

        <section class="engine-card advanced-card">
          <header class="engine-card-heading advanced-heading"><span>{{ isKrea2 ? '04' : '03' }}</span><div><h2>采样与高级参数</h2><small>显示此模式确实支持的选项</small></div></header>
          <div class="engine-advanced-grid">
            <label class="engine-field" :title="legacyTooltips.samplePreview"><span>训练中采样预览</span><select v-model="draft.sample_preview_mode" class="engine-select" @change="markParam('sample_preview')"><option value="auto">按显存使用默认设置</option><option value="on">开启</option><option value="off">关闭（减少额外耗时）</option></select></label>
            <label class="engine-field" :title="intervalTooltip('save_every')"><span>模型保存间隔（{{ intervalUnit('save_every') }}）</span><input v-model="draft.save_every" class="engine-input" type="number" min="0" placeholder="使用默认" @input="markParam('save_every')" /></label>
            <label class="engine-field" :title="intervalTooltip('sample_interval')"><span>采样预览间隔（{{ intervalUnit('sample_interval') }}）</span><input v-model="draft.sample_interval" class="engine-input" type="number" min="0" placeholder="使用默认" @input="markParam('sample_interval')" /></label>
            <label v-if="supported('optimizer')" class="engine-field" :title="legacyTooltips.optimizer"><span>优化器</span><select v-model="draft.optimizer" class="engine-select" @change="markParam('optimizer')"><option value="auto">自动</option><option value="adamw">AdamW</option><option value="adamw8bit">AdamW8bit</option><option v-if="!isFizgig" value="lion">Lion</option></select></label>
<LearningRateSchedule :scheduler="draft.lr_scheduler" :warmup="draft.lr_warmup_steps" :mode="mode" :version="draft.fizgig_version" :optimizer="draft.optimizer" @change="(key, value) => { if (key === 'lr_scheduler' || key === 'lr_warmup_steps') { draft[key] = value; markParam(key) } }" />
            <label v-if="supported('batch_size')" class="engine-field" :title="legacyTooltips.batchSize"><span>批大小（留空 = 自动）</span><input v-model="draft.batch_size" class="engine-input" type="number" min="1" max="8" placeholder="自动（1）" @input="markParam('batch_size')" /></label>
            <label v-if="supported('gc')" class="engine-field" :title="legacyTooltips.gradientCheckpointing"><span>梯度检查点</span><select v-model="draft.gc" class="engine-select" @change="markParam('gc')"><option value="auto">自动（按显存）</option><option value="开启">开启（省显存，较慢）</option><option value="关闭">关闭（更快，更吃显存）</option></select></label>
            <label v-if="isV7" class="engine-field wide-field"><span>预览正向补充词</span><input v-model="draft.global_pos" class="engine-input" @input="markRoot('global_pos')" /></label>
            <label v-if="supported('global_neg')" class="engine-field wide-field"><span>预览负向词</span><input v-model="draft.global_neg" class="engine-input" @input="markRoot('global_neg')" /></label>
            <label v-if="supported('blocks_to_swap')" class="engine-field" :title="legacyTooltips.blocksToSwap"><span>块交换数（NF4 下停用）</span><select v-model="draft.blocks_to_swap" class="engine-select" @change="markParam('blocks_to_swap')"><option value="">自动</option><option v-for="count in [0, 2, 4, 6, 8, 10, 12]" :key="count" :value="String(count)">{{ count }}</option></select></label>
            <label v-if="supported('sample_prompt')" class="engine-field wide-field" :title="legacyTooltips.samplePrompt"><span>采样预览提示词</span><input v-model="draft.sample_prompt" class="engine-input" placeholder="留空自动生成；填写后整句生效" @input="markParam('sample_prompt')" /></label>
              <label class="engine-field" title="各次采样使用同一个正整数种子，便于比较不同训练阶段。固定种子不保证不同引擎或不同提示词的图片可直接比较。"><span>固定采样种子</span><input v-model="draft.sample_seed" class="engine-input" type="number" min="1" max="4294967295" placeholder="默认 1234" @input="markParam('sample_seed')" /></label>
            <label v-if="supported('noise_offset')" class="engine-field" :title="legacyTooltips.noiseOffset"><span>Noise offset</span><input v-model="draft.noise_offset" class="engine-input" @input="markParam('noise_offset')" /></label>
            <label v-if="supported('min_snr_gamma')" class="engine-field" :title="legacyTooltips.minSnrGamma"><span>Min-SNR gamma</span><input v-model="draft.min_snr_gamma" class="engine-input" @input="markParam('min_snr_gamma')" /></label>
            <button class="engine-utility" type="button" :title="legacyTooltips.resetPreset" @click="resetPreset">恢复预设</button>
            <button v-if="supported('compile')" class="engine-check" :title="legacyTooltips.compile" :class="{ checked: draft.compile }" type="button" role="checkbox" :aria-checked="draft.compile" @click="draft.compile = !draft.compile; markParam('compile')"><i></i><span>torch.compile 加速（实验性）</span></button>
          </div>
        </section>

        <OutputDirectoryControl :project-name="project.name" :config="config" :desktop="desktop" @action="requestAction" />
        <div class="engine-utility-row">
          <button v-if="!isH3Fizgig" class="engine-utility" type="button" :title="legacyTooltips.preprocess" @click="requestAction('preprocess')">数据预处理</button>
          <button v-if="!isVideo || isH3Fizgig" class="engine-utility" type="button" :title="legacyTooltips.labelEditor" @click="requestAction('label_editor')">标签编辑器</button>
          <button class="engine-utility" type="button" :title="legacyTooltips.openOutput" @click="requestAction('output_dir')">打开输出目录</button>
          <button class="engine-utility" type="button" @click="requestAction('training_history')">训练记录</button>
          <button class="engine-utility" type="button" @click="requestAction('export_config')">导出配置</button>
          <button class="engine-utility" type="button" :title="legacyTooltips.readme" @click="requestAction('readme')">训练说明</button>
          <button v-if="mode === 'krea2' || mode === 'krea2_fz'" class="engine-utility" type="button" :title="legacyTooltips.krea2Guide" @click="requestAction('krea2_guide')">Krea2 使用引导</button>
          <button v-if="mode === 'flux2' || mode === 'flux2_fz'" class="engine-utility" type="button" :title="legacyTooltips.flux2Guide" @click="requestAction('flux2_guide')">FLUX.2 使用引导</button>
          <button v-if="isVideo && !isH3Fizgig" class="engine-utility" type="button" :title="legacyTooltips.h3Guide" @click="requestAction('h3_guide')">H3 视频引导</button>
          <button v-if="!isKrea2" class="engine-utility" type="button" title="配置当前训练模式的模型文件。" @click="requestAction(modelAction)">{{ ['zimage_fz','moss_fz'].includes(mode) ? '配置模型 / 组件' : '打开模型目录' }}</button>
          <template v-if="isVideo && !isH3Fizgig">
            <button class="engine-utility" type="button" title="为没有字幕的视频生成占位 txt（内容=触发词），避免训练缺字幕报错；建议之后手动改成具体描述。" @click="requestAction('video_caption_stub')">一键生成占位字幕</button>
            <button class="engine-utility" type="button" title="用 Qwen2.5-VL 自动给视频生成英文描述（首次下载模型约 6~7GB，已有 txt 的会跳过）。" @click="requestAction('video_caption')">AI 自动描述</button>
          </template>
        </div>
        <p v-if="desktop" class="engine-footer-note"><i></i>训练与预处理直接调用当前模式原有引擎；运行状态、日志和停止操作都在新版训练页内。</p>
        <p v-else class="engine-footer-note"><i></i>工作区预览 · 设置可暂存在当前浏览器会话；不会写入本机项目或启动训练。</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.zimage-component-row {display:grid;grid-template-columns:minmax(150px,1fr) minmax(0,2fr);gap:12px;padding:8px 0;border-bottom:1px solid var(--outline-subtle);font-size:11px;}
.zimage-component-row small {color:var(--hint);overflow-wrap:anywhere;}

.engine-workspace{display:flex;flex:1;flex-direction:column;min-width:0;min-height:0;color:var(--text)}
.engine-toolbar{display:flex;flex:0 0 auto;align-items:center;justify-content:space-between;gap:14px;min-height:58px;padding:9px 24px 7px;border-bottom:1px solid var(--outline-subtle)}
.engine-heading,.engine-heading-copy,.engine-actions{display:flex;align-items:center}.engine-heading{gap:15px;min-width:0}.engine-heading-copy{gap:11px;min-width:0}.engine-heading-copy h1{margin:0;color:var(--tone-d1d4da);font-size:17px;font-weight:350;white-space:nowrap}.engine-heading-copy span{overflow:hidden;color:var(--hint);font-size:11px;text-overflow:ellipsis;white-space:nowrap}.engine-actions{gap:7px}.engine-update-button{display:inline-flex;align-items:center;gap:6px;min-height:31px;padding:0 10px;border:1px solid var(--tone-827047);border-radius:5px;color:var(--tone-d3bd8b);background:var(--tone-302c22);font-size:10px;white-space:nowrap;cursor:pointer;transition:background-color 140ms ease,border-color 140ms ease}.engine-update-button:hover{border-color:var(--tone-a18a59);background:var(--tone-393326)}.update-arrow{display:inline-block;animation:update-arrow-pulse 900ms ease-in-out infinite alternate}@keyframes update-arrow-pulse{from{transform:translateY(2px) rotate(-10deg);opacity:.68}to{transform:translateY(-2px) rotate(8deg);opacity:1}}
.engine-button,.engine-back{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:31px;padding:0 10px;border:1px solid var(--border);border-radius:5px;color:var(--tone-b3bac4);background:transparent;font-size:11px;white-space:nowrap;cursor:pointer;transition:background-color 140ms ease,border-color 140ms ease,color 140ms ease,transform 120ms var(--ease-out)}.engine-button:hover,.engine-back:hover{border-color:var(--tone-505660);color:var(--tone-d2d5db);background:var(--tone-292c34)}.engine-button:active,.engine-back:active{transform:scale(.985)}.engine-button .ui-icon,.engine-back .ui-icon{width:13px;height:13px}.engine-button.primary{border-color:transparent;color:var(--tone-e5e7eb);background:var(--tone-626f81)}.engine-button.primary:hover{background:var(--tone-6b7788)}.engine-button.compact{min-height:28px;padding:0 9px;font-size:10px}
.engine-status-line{display:flex;align-items:center;gap:7px;min-height:36px;padding:3px 24px 6px}.engine-status{display:inline-flex;align-items:center;min-height:22px;padding:0 8px;border:1px solid var(--tone-3b3e46);border-radius:4px;color:var(--tone-a9aeb6);background:var(--tone-262930);font-size:10px}.engine-status.ready{color:var(--tone-aab8ad)}.engine-link{padding:3px 2px;border:0;color:var(--tone-adb6c2);background:transparent;font-size:10px;cursor:pointer}.engine-link:hover{color:var(--tone-d1d5dc);text-decoration:underline}
.engine-scroll-area{flex:1;min-height:0;overflow:auto;scrollbar-color:var(--tone-4a4e56) transparent;scrollbar-width:thin}.engine-scroll-content{display:flex;flex-direction:column;gap:10px;padding:5px 25px 13px 24px}.engine-summary,.engine-card{min-width:0;border:1px solid var(--outline-subtle);border-radius:7px;background:var(--card)}.engine-summary{display:grid;grid-template-columns:minmax(0,1.2fr) auto minmax(0,1fr) auto;align-items:center;gap:10px;padding:10px 12px}.summary-main,.asset-copy{display:grid;min-width:0;gap:4px}.summary-label,.engine-field>span{color:var(--hint);font-size:10px}.summary-main strong,.asset-copy strong{overflow:hidden;color:var(--tone-c5cad1);font-size:11px;font-weight:350;text-overflow:ellipsis;white-space:nowrap}.summary-main small,.asset-copy small{overflow:hidden;color:var(--tone-888e97);font-size:9px;line-height:1.4;text-overflow:ellipsis}.engine-card-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px}.engine-card{padding:12px 13px 11px}.engine-card-heading{display:flex;align-items:center;gap:9px;min-height:25px;margin-bottom:10px}.engine-card-heading>span{color:var(--tone-8993a0);font-size:10px;letter-spacing:.04em}.engine-card-heading>div{display:grid;gap:2px}.engine-card-heading h2{margin:0;color:var(--tone-cbd0d7);font-size:13px;font-weight:400}.engine-card-heading small{color:var(--hint);font-size:9px}
.engine-fields{display:grid;gap:9px}.engine-fields.two-columns{grid-template-columns:repeat(2,minmax(0,1fr))}.engine-fields.spaced{margin-top:9px}.engine-field{display:grid;min-width:0;gap:5px}.engine-input,.engine-select{width:100%;min-width:0;height:30px;padding:0 9px;border:1px solid var(--tone-3d414a);border-radius:5px;color:var(--tone-c6cbd3);background:var(--tone-22252c);font-size:11px;font-weight:350}.engine-select{padding-right:24px;cursor:pointer}.engine-select option{color:var(--tone-cbd0d7);background:var(--tone-252830)}.engine-input::placeholder{color:var(--tone-707680)}.engine-param-grid{display:grid;grid-template-columns:repeat(4,minmax(82px,1fr));gap:8px}.engine-hint{margin:8px 0 0;color:var(--tone-898f99);font-size:10px;line-height:1.45;white-space:pre-line}
.engine-switch{display:flex;align-items:center;gap:8px;width:100%;margin-top:8px;padding:4px 0;border:0;color:inherit;background:transparent;text-align:left;cursor:pointer}.engine-switch>i{position:relative;width:27px;height:15px;flex:0 0 auto;border-radius:9px;background:var(--tone-454951);transition:background-color 150ms ease}.engine-switch>i:after{position:absolute;top:2px;left:2px;width:11px;height:11px;border-radius:50%;background:var(--tone-adb3bc);transition:transform 160ms var(--ease-out);content:''}.engine-switch.active>i{background:var(--tone-626f81)}.engine-switch.active>i:after{transform:translateX(12px)}.engine-switch>span{display:grid;gap:2px}.engine-switch strong{color:var(--tone-bfc4cc);font-size:11px;font-weight:400}.engine-switch small{color:var(--hint);font-size:9px}.engine-check{display:inline-flex;align-items:center;gap:7px;min-height:28px;padding:2px 3px;border:0;color:var(--tone-a7adb7);background:transparent;font-size:10px;text-align:left;cursor:pointer}.engine-check>i{display:grid;width:14px;height:14px;flex:0 0 auto;place-items:center;border:1px solid var(--tone-646a75);border-radius:3px;background:var(--tone-22252c);transition:border-color 130ms ease,background-color 130ms ease}.engine-check.checked>i{border-color:var(--tone-687689);background:var(--tone-626f81)}.engine-check.checked>i:after{width:6px;height:3px;border-bottom:1.4px solid var(--tone-e2e5e9);border-left:1.4px solid var(--tone-e2e5e9);transform:translateY(-1px) rotate(-45deg);content:''}.engine-check:hover{color:var(--tone-d0d4da)}
.krea2-workflow{margin:0 0 2px;color:var(--hint);font-size:10px;line-height:1.6}.krea2-workflow span{margin:0 9px;color:var(--tone-8993a0)}.runtime-summary{cursor:pointer;color:var(--tone-c5cad1);font-size:11px}.runtime-summary span{margin-left:14px;color:var(--hint);font-size:10px}.runtime-card[open] .runtime-choice{margin-top:12px}.engine-summary.dataset-only{grid-template-columns:minmax(0,1fr) auto}.engine-button:disabled,.engine-back:disabled{opacity:.5;cursor:wait}
.runtime-choice{display:flex;align-items:end;gap:10px;flex-wrap:wrap}.runtime-choice .engine-field,.runtime-choice .engine-input{flex:1;min-width:180px}.runtime-card .engine-hint{margin-top:10px}
.advanced-heading{margin-bottom:9px}.engine-advanced-grid{display:grid;grid-template-columns:repeat(4,minmax(100px,1fr));align-items:end;gap:9px}.wide-field{grid-column:span 2}.engine-utility-row{display:flex;flex-wrap:wrap;gap:7px}.engine-utility{min-height:29px;padding:0 10px;border:1px solid var(--border);border-radius:5px;color:var(--tone-afb5bf);background:var(--tone-252830);font-size:10px;cursor:pointer;transition:border-color 130ms ease,color 130ms ease,background-color 130ms ease,transform 110ms ease-out}.engine-utility:hover{border-color:var(--tone-505660);color:var(--tone-d0d4da);background:var(--tone-2b2e36)}.engine-utility:active{transform:scale(.985)}.engine-footer-note{display:flex;align-items:center;gap:7px;margin:-2px 1px 0;color:var(--tone-818792);font-size:10px}.engine-footer-note i{width:5px;height:5px;border-radius:50%;background:var(--tone-929baa)}
@media(max-width:1180px){.engine-toolbar{align-items:flex-start;flex-direction:column}.engine-actions{flex-wrap:wrap}.engine-card-grid{grid-template-columns:1fr}.engine-param-grid{grid-template-columns:repeat(3,minmax(100px,1fr))}.engine-advanced-grid{grid-template-columns:repeat(3,minmax(100px,1fr))}.engine-summary{grid-template-columns:minmax(0,1fr) auto}.asset-copy{grid-column:1}}
@media(prefers-reduced-motion:reduce){.engine-button,.engine-back,.engine-switch>i,.engine-switch>i:after{transition:none}}
.engine-card-grid.multi { grid-template-columns:minmax(0,1fr); }
</style>
