<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import type { ModeWorkspaceData, ProjectCard, ProjectConfig } from '../bridge'
import UiIcon from './UiIcon.vue'
import CropRatioField from './CropRatioField.vue'
import { legacyTooltips } from '../legacyTooltips'
import { normalizeWd14Model } from '../modelDefaults'

type BrowseKind = 'folder' | 'model'
const props = defineProps<{
  project: ProjectCard
  mode: string
  config?: ProjectConfig | null
  details: ModeWorkspaceData
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

const dirty = reactive(new Set<string>())
const configuredParams = new Set<string>()
const draft = reactive({
  raw_dir: '', trigger: '', reg_dir: '', style_preset: '自定义', style_caption: '', at_sub_mode: 'character', concept_type: 'form',
  rank: '', alpha: '', unet_lr: '', te_lr: '', repeats: '', max_epochs: '', resolution: '',
  video_steps: '', video_frames: '', save_every: '', sample_interval: '', optimizer: 'auto',
  crop_ratio: '', sample_prompt: '', noise_offset: '', min_snr_gamma: '', quant_mode: 'auto',
  blocks_to_swap: '', wd14_model: 'swinv2-v3', sample_preview_mode: 'auto', fast_tier: 'auto',
  strong_bind: true, clean_concept: true, compile: false, overwrite: false, amd_mode: false,
})

const supported = (key: string) => Boolean(props.details.supports?.[key])
const defaults = computed(() => props.details.defaults ?? {})
const isConcept = computed(() => draft.at_sub_mode === 'concept')
const isStyle = computed(() => draft.at_sub_mode === 'style')
const isVideo = computed(() => props.mode === 'video')
const assetReady = computed(() => props.details.missing_models.length === 0)
const modelAction = computed(() => `open_models:${props.mode}`)
const intervalUnit = (key: 'save_every' | 'sample_interval') => props.details.interval_units?.[key] === 'epochs' ? '轮' : '步'
const intervalTooltip = (key: 'save_every' | 'sample_interval') => key === 'save_every'
  ? props.details.interval_units?.[key] === 'epochs' ? legacyTooltips.saveEveryEpochs : legacyTooltips.saveEverySteps
  : props.details.interval_units?.[key] === 'epochs' ? legacyTooltips.sampleIntervalEpochs : legacyTooltips.sampleIntervalSteps
const presetParamKeys = ['rank', 'alpha', 'unet_lr', 'te_lr', 'repeats', 'max_epochs', 'resolution', 'video_steps', 'video_frames', 'save_every', 'sample_interval'] as const
function presetFor(): Record<string, unknown> {
  return props.details.presets?.[props.mode]?.sdxl ?? props.details.defaults ?? {}
}
function styledPresetValue(key: string, style = draft.style_preset): string {
  const raw = presetFor()[key]
  if (raw === undefined || raw === null || raw === '') return ''
  const number = Number(raw)
  const factor = style === '动漫' ? 0.85 : style === '写实' ? 1.15 : 1
  return factor !== 1 && Number.isFinite(number) ? (number * factor).toExponential(2).replace('e-0', 'e-').replace('e+0', 'e+') : String(raw)
}
const currentDatasetHint = computed(() => {
  if (!props.details.has_training_submode) return props.details.dataset_hint
  const semanticHint = props.details.dataset_hints?.[draft.at_sub_mode]
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
  for (const key of ['rank', 'alpha', 'unet_lr', 'te_lr', 'repeats', 'max_epochs', 'resolution', 'video_steps', 'video_frames', 'save_every', 'sample_interval', 'optimizer', 'crop_ratio', 'sample_prompt', 'noise_offset', 'min_snr_gamma', 'quant_mode', 'blocks_to_swap', 'wd14_model'] as const) {
    const defaultValue = preset[key] === undefined ? defaults.value[key] : preset[key]
    const styledDefault = key === 'unet_lr' || key === 'te_lr' ? styledPresetValue(key, draft.style_preset) : defaultValue
    const hydratedValue = value(params[key], styledDefault === undefined ? (key === 'optimizer' || key === 'quant_mode' ? 'auto' : '') : String(styledDefault))
    draft[key] = (key === 'wd14_model' ? normalizeWd14Model(hydratedValue) : hydratedValue) as never
  }
  draft.strong_bind = params.strong_bind === undefined ? true : Boolean(params.strong_bind)
  draft.clean_concept = params.clean_concept === undefined ? true : Boolean(params.clean_concept)
  draft.sample_preview_mode = params.sample_preview === undefined ? 'auto' : Boolean(params.sample_preview) ? 'on' : 'off'
  draft.compile = Boolean(params.compile)
  draft.overwrite = Boolean(params.overwrite)
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
  emit('notify', '当前模式的推荐预设已恢复。保存修改后生效。')
}

function makePatch(): ProjectConfig {
  const patch: ProjectConfig = { mode: props.mode }
  for (const key of ['raw_dir', 'trigger', 'reg_dir', 'style_preset', 'style_caption', 'at_sub_mode', 'concept_type', 'fast_tier'] as const) {
    if (dirty.has(key)) patch[key] = draft[key]
  }
  const params: Record<string, unknown> = {}
  for (const key of ['rank', 'alpha', 'unet_lr', 'te_lr', 'repeats', 'max_epochs', 'resolution', 'video_steps', 'video_frames', 'save_every', 'sample_interval', 'optimizer', 'crop_ratio', 'sample_prompt', 'noise_offset', 'min_snr_gamma', 'quant_mode', 'blocks_to_swap', 'wd14_model'] as const) {
    if (dirty.has(`params.${key}`)) params[key] = draft[key]
  }
  for (const key of ['strong_bind', 'clean_concept', 'compile', 'overwrite', 'amd_mode'] as const) {
    if (dirty.has(`params.${key}`)) params[key] = draft[key]
  }
  if (dirty.has('params.sample_preview')) params.sample_preview = draft.sample_preview_mode === 'auto' ? null : draft.sample_preview_mode === 'on'
  if (Object.keys(params).length) patch.params = params
  return patch
}

function save() {
  const patch = makePatch()
  if (Object.keys(patch).length === 1 && patch.mode === props.mode) return emit('notify', '当前没有修改项目配置。')
  emit('save', patch)
}

function startTraining() {
  if (!props.desktop) return emit('notify', '浏览器预览不会启动训练。')
  emit('train', makePatch())
}

async function browseDataset() {
  if (!props.desktop) return emit('notify', '浏览器预览不会调用本机文件选择器。')
  const path = await props.choosePath('folder')
  if (path) { draft.raw_dir = path; markRoot('raw_dir') }
}

async function guideAction(action: string): Promise<ProjectConfig | null> {
  if (action !== 'cmd_pick_raw') return null
  await browseDataset()
  return dirty.has('raw_dir') ? makePatch() : null
}

function requestAction(action: string) {
  if (!props.desktop && !['readme', 'krea2_guide', 'flux2_guide', 'h3_guide'].includes(action)) return emit('notify', '浏览器预览中，此操作不会触碰本机数据。')
  emit('classicAction', action, makePatch())
}

defineExpose({ startTraining, guideAction })

const isAmdGpu = computed(() => String(props.details.gpu_vendor || '').toLowerCase() === 'amd')
</script>

<template>
  <section class="engine-workspace" :aria-label="`${details.label} 新版训练页`">
    <header class="engine-toolbar">
      <div class="engine-heading">
        <button class="engine-back" type="button" @click="emit('back', makePatch())"><UiIcon name="back" /> 返回项目</button>
      <div class="engine-heading-copy"><h1>{{ details.label }}训练</h1><span>项目：{{ project.name }}</span></div>
      </div>
      <div class="engine-actions">
        <button v-if="desktop && details.engine_update_available" class="engine-update-button" type="button" :title="legacyTooltips.engineUpdate" @click="requestAction('at_engine_update')"><span class="update-arrow">↗</span> 引擎更新可用</button>
        <button v-if="desktop" class="engine-button" type="button" @click="save">保存修改</button>
        <button v-if="desktop" class="engine-button primary" type="button" @click="startTraining"><UiIcon name="play" /> 一键开始训练</button>
        <button v-else class="engine-button primary" type="button" @click="save">保存预览设置</button>
      </div>
    </header>

    <div class="engine-status-line">
      <span class="engine-status" :class="{ ready: details.engine_ready }">{{ details.engine_ready ? '训练引擎就绪' : '训练引擎未就绪' }}</span>
      <span class="engine-status" :class="{ ready: assetReady }">{{ assetReady ? '模型文件齐全' : `模型文件缺少 ${details.missing_models.length} 项` }}</span>
      <span class="engine-status">{{ details.gpu }}</span>
          <button class="engine-link" type="button" title="打开当前训练模式的模型文件夹。" @click="requestAction(modelAction)">打开模型目录</button>
    </div>

    <div class="engine-scroll-area">
      <div class="engine-scroll-content">
        <section class="engine-summary">
          <div class="summary-main">
            <span class="summary-label">{{ isVideo ? '视频数据目录' : '训练图片目录' }}</span>
            <strong :title="draft.raw_dir || undefined">{{ draft.raw_dir || (desktop ? '尚未选择数据目录' : '预览中：桌面模式会显示项目数据目录') }}</strong>
            <small v-if="currentDatasetHint" :title="currentDatasetHint">{{ currentDatasetHint }}</small>
          </div>
          <button class="engine-button compact" type="button" @click="browseDataset">选择文件夹</button>
          <div class="asset-copy">
            <span class="summary-label">模型文件位置</span>
            <strong :title="details.asset_dir || undefined">{{ details.asset_dir || '由引擎按配置管理' }}</strong>
            <small v-if="details.missing_models.length">缺少：{{ details.missing_models.join('、') }}</small>
          </div>
          <button class="engine-button compact" type="button" @click="requestAction(modelAction)">打开模型目录</button>
        </section>

        <div class="engine-card-grid">
          <section class="engine-card">
            <header class="engine-card-heading"><span>01</span><div><h2>数据与训练方式</h2><small>按当前模式显示适用项目</small></div></header>
            <div v-if="details.has_training_submode" class="engine-fields two-columns">
              <label class="engine-field" :title="legacyTooltips.atSubMode"><span>训练类型</span><select v-model="draft.at_sub_mode" class="engine-select" @change="markRoot('at_sub_mode')"><option value="character">人物（保留全部标签）</option><option value="style">画风（过滤人物标签）</option><option value="concept">概念</option></select></label>
              <label v-if="isConcept" class="engine-field" :title="details.concept_type_hints?.[draft.concept_type] || legacyTooltips.conceptType"><span>概念类型</span><select v-model="draft.concept_type" class="engine-select" @change="markRoot('concept_type')"><option value="form">形态/种族（美人鱼·半人马）</option><option value="outfit">服装（同款衣服）</option><option value="object">物品（道具/武器）</option><option value="bodypart">身体部位（异色瞳/翅膀）</option></select></label>
            </div>
            <div class="engine-fields two-columns spaced">
              <label v-if="!isVideo" class="engine-field" :title="legacyTooltips.stylePreset"><span>出图风格</span><select v-model="draft.style_preset" class="engine-select" @change="onStylePresetChange"><option>自定义</option><option>动漫</option><option>写实</option></select></label>
              <label class="engine-field" :title="legacyTooltips.trigger"><span>Trigger 触发词</span><input v-model="draft.trigger" class="engine-input" placeholder="可留空；建议使用少见的英文词" @input="markRoot('trigger')" /></label>
              <label v-if="isStyle" class="engine-field" :title="legacyTooltips.styleCaption"><span>画风描述词（可选）</span><input v-model="draft.style_caption" class="engine-input" placeholder="留空使用自动打标" @input="markRoot('style_caption')" /></label>
              <label v-if="supported('crop_ratio')" class="engine-field" :title="legacyTooltips.cropRatio"><span>预处理裁切比例</span><CropRatioField v-model="draft.crop_ratio" input-class="engine-input" @update:model-value="markParam('crop_ratio')" /></label>
              <label v-if="supported('reg_dir')" class="engine-field" :title="legacyTooltips.regDir"><span>正则数据集（可选）</span><input v-model="draft.reg_dir" class="engine-input" placeholder="选择正则图片文件夹" @input="markRoot('reg_dir')" /></label>
            </div>
            <p v-if="!isVideo" class="engine-hint">只微调学习率：动漫 ×0.85 更精细、写实 ×1.15 更自然；rank 等仍按模式自动。</p>
            <button v-if="details.has_training_submode && !isStyle" class="engine-switch" :title="legacyTooltips.strongBind" :class="{ active: draft.strong_bind }" type="button" role="switch" :aria-checked="draft.strong_bind" @click="draft.strong_bind = !draft.strong_bind; markParam('strong_bind')"><i></i><span><strong>强绑定</strong><small>自动把 trigger + 训练集 100% 一致的特征词固定到标签开头</small></span></button>
            <button v-if="isConcept" class="engine-check" :title="legacyTooltips.cleanConcept" :class="{ checked: draft.clean_concept }" type="button" role="checkbox" :aria-checked="draft.clean_concept" @click="draft.clean_concept = !draft.clean_concept; markParam('clean_concept')"><i></i><span>自动清洗概念标签（推荐）</span></button>
            <label v-if="supported('wd14_model') && !isVideo" class="engine-field spaced" :title="legacyTooltips.wd14Model"><span>自动打标模型</span><select v-model="draft.wd14_model" class="engine-select" @change="markParam('wd14_model')"><option value="swinv2-v3">swinv2-v3（推荐）</option><option value="moat-v2">moat-v2（旧版）</option></select></label>
            <button v-if="supported('overwrite') && !isVideo" class="engine-check" :title="legacyTooltips.overwrite" :class="{ checked: draft.overwrite }" type="button" role="checkbox" :aria-checked="draft.overwrite" @click="draft.overwrite = !draft.overwrite; markParam('overwrite')"><i></i><span>重新处理已存在的图片（改过标签后勾上，否则不生效）</span></button>
            <p v-if="currentTriggerHint" class="engine-hint">{{ currentTriggerHint }}</p>
          </section>

          <section class="engine-card">
            <header class="engine-card-heading"><span>02</span><div><h2>常用训练参数</h2><small>空白项沿用当前引擎预设</small></div></header>
            <div class="engine-param-grid">
              <label class="engine-field" :title="legacyTooltips.rank"><span>LoRA rank</span><input v-model="draft.rank" class="engine-input" type="number" min="1" placeholder="按模式预设" @input="markParam('rank')" /></label>
              <label class="engine-field" :title="legacyTooltips.alpha"><span>LoRA alpha</span><input v-model="draft.alpha" class="engine-input" type="number" min="1" placeholder="按模式预设" @input="markParam('alpha')" /></label>
              <label class="engine-field" :title="legacyTooltips.unet_lr"><span>学习率</span><input v-model="draft.unet_lr" class="engine-input" placeholder="按模式预设" @input="markParam('unet_lr')" /></label>
              <label v-if="supported('te_lr')" class="engine-field" :title="legacyTooltips.te_lr"><span>文本编码器学习率</span><input v-model="draft.te_lr" class="engine-input" placeholder="按模式预设" @input="markParam('te_lr')" /></label>
              <label class="engine-field" :title="legacyTooltips.resolution"><span>训练分辨率</span><input v-model="draft.resolution" class="engine-input" type="number" min="64" step="64" placeholder="按模式预设" @input="markParam('resolution')" /></label>
              <label v-if="supported('repeats')" class="engine-field" :title="legacyTooltips.repeats"><span>图片循环次数</span><input v-model="draft.repeats" class="engine-input" type="number" min="1" placeholder="按模式预设" @input="markParam('repeats')" /></label>
              <label v-if="supported('max_epochs')" class="engine-field" :title="legacyTooltips.maxEpochs"><span>最大 epoch</span><input v-model="draft.max_epochs" class="engine-input" type="number" min="1" placeholder="按模式预设" @input="markParam('max_epochs')" /></label>
              <label v-if="supported('video_steps')" class="engine-field" :title="legacyTooltips.videoSteps"><span>训练步数</span><input v-model="draft.video_steps" class="engine-input" type="number" min="1" placeholder="按模式预设" @input="markParam('video_steps')" /></label>
              <label v-if="supported('video_frames')" class="engine-field" :title="legacyTooltips.videoFrames"><span>帧数（17n+5）</span><input v-model="draft.video_frames" class="engine-input" type="number" min="5" step="17" placeholder="73" @input="markParam('video_frames')" /></label>
            </div>
            <p v-if="isVideo" class="engine-hint">H3 输入视频和同名 .txt 字幕；帧数需符合 17n+5 格式，具体视频准备工具仍由经典面板提供。</p>
          </section>
        </div>

        <section class="engine-card advanced-card">
          <header class="engine-card-heading advanced-heading"><span>03</span><div><h2>采样与高级参数</h2><small>显示此模式确实支持的选项</small></div></header>
          <div class="engine-advanced-grid">
            <label class="engine-field" :title="legacyTooltips.samplePreview"><span>训练中采样预览</span><select v-model="draft.sample_preview_mode" class="engine-select" @change="markParam('sample_preview')"><option value="auto">按显存使用默认设置</option><option value="on">开启</option><option value="off">关闭（减少额外耗时）</option></select></label>
            <label class="engine-field" :title="intervalTooltip('save_every')"><span>模型保存间隔（{{ intervalUnit('save_every') }}）</span><input v-model="draft.save_every" class="engine-input" type="number" min="0" placeholder="使用默认" @input="markParam('save_every')" /></label>
            <label class="engine-field" :title="intervalTooltip('sample_interval')"><span>采样预览间隔（{{ intervalUnit('sample_interval') }}）</span><input v-model="draft.sample_interval" class="engine-input" type="number" min="0" placeholder="使用默认" @input="markParam('sample_interval')" /></label>
            <label v-if="supported('optimizer')" class="engine-field" :title="legacyTooltips.optimizer"><span>优化器</span><select v-model="draft.optimizer" class="engine-select" @change="markParam('optimizer')"><option value="auto">自动</option><option value="adamw">AdamW</option><option value="adamw8bit">AdamW8bit</option><option value="lion">Lion</option></select></label>
            <label v-if="supported('quant_mode')" class="engine-field" :title="legacyTooltips.quantMode"><span>量化方式（Krea2/FLUX.2）</span><select v-model="draft.quant_mode" class="engine-select" @change="markParam('quant_mode')"><option value="auto">自动</option><option value="fp8">fp8</option><option value="int8">int8</option><option value="nf4">nf4</option></select></label>
            <label v-if="supported('blocks_to_swap')" class="engine-field" :title="legacyTooltips.blocksToSwap"><span>块交换数（Krea2/FLUX.2）</span><select v-model="draft.blocks_to_swap" class="engine-select" @change="markParam('blocks_to_swap')"><option value="">自动</option><option v-for="count in [0, 2, 4, 6, 8, 10, 12]" :key="count" :value="String(count)">{{ count }}</option></select></label>
            <label v-if="supported('sample_prompt')" class="engine-field wide-field" :title="legacyTooltips.samplePrompt"><span>采样预览提示词</span><input v-model="draft.sample_prompt" class="engine-input" placeholder="留空自动生成；填写后整句生效" @input="markParam('sample_prompt')" /></label>
            <label v-if="supported('noise_offset')" class="engine-field" :title="legacyTooltips.noiseOffset"><span>Noise offset</span><input v-model="draft.noise_offset" class="engine-input" @input="markParam('noise_offset')" /></label>
            <label v-if="supported('min_snr_gamma')" class="engine-field" :title="legacyTooltips.minSnrGamma"><span>Min-SNR gamma</span><input v-model="draft.min_snr_gamma" class="engine-input" @input="markParam('min_snr_gamma')" /></label>
            <button class="engine-utility" type="button" :title="legacyTooltips.resetPreset" @click="resetPreset">恢复预设</button>
            <button v-if="supported('compile')" class="engine-check" :title="legacyTooltips.compile" :class="{ checked: draft.compile }" type="button" role="checkbox" :aria-checked="draft.compile" @click="draft.compile = !draft.compile; markParam('compile')"><i></i><span>torch.compile 加速（实验性）</span></button>
            <button v-if="supported('amd_mode') && isAmdGpu" class="engine-check" :title="legacyTooltips.amdMode" :class="{ checked: draft.amd_mode }" type="button" role="checkbox" :aria-checked="draft.amd_mode" @click="draft.amd_mode = !draft.amd_mode; markParam('amd_mode')"><i></i><span>AMD 兼容模式（实验性）</span></button>
          </div>
        </section>

        <div class="engine-utility-row">
          <button class="engine-utility" type="button" :title="legacyTooltips.preprocess" @click="requestAction('preprocess')">数据预处理</button>
          <button class="engine-utility" type="button" :title="legacyTooltips.labelEditor" @click="requestAction('label_editor')">标签编辑器</button>
          <button class="engine-utility" type="button" :title="legacyTooltips.openOutput" @click="requestAction('output_dir')">打开输出目录</button>
          <button class="engine-utility" type="button" @click="requestAction('export_config')">导出配置</button>
          <button class="engine-utility" type="button" :title="legacyTooltips.readme" @click="requestAction('readme')">训练说明</button>
          <button v-if="mode === 'krea2' || mode === 'krea2_fz'" class="engine-utility" type="button" :title="legacyTooltips.krea2Guide" @click="requestAction('krea2_guide')">Krea2 使用引导</button>
          <button v-if="mode === 'flux2' || mode === 'flux2_fz'" class="engine-utility" type="button" :title="legacyTooltips.flux2Guide" @click="requestAction('flux2_guide')">FLUX.2 使用引导</button>
          <button v-if="isVideo" class="engine-utility" type="button" :title="legacyTooltips.h3Guide" @click="requestAction('h3_guide')">H3 使用引导</button>
          <button class="engine-utility" type="button" title="打开当前训练模式的模型文件夹。" @click="requestAction('open_models:' + mode)">打开模型目录</button>
          <button v-if="supported('amd_mode') && isAmdGpu" class="engine-utility" type="button" :title="legacyTooltips.amdMode" @click="requestAction('amd_env')">AMD 环境检查 / 安装引导</button>
          <template v-if="isVideo">
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
.engine-workspace{display:flex;flex:1;flex-direction:column;min-width:0;min-height:0;color:var(--text)}
.engine-toolbar{display:flex;flex:0 0 auto;align-items:center;justify-content:space-between;gap:14px;min-height:58px;padding:9px 24px 7px;border-bottom:1px solid var(--outline-subtle)}
.engine-heading,.engine-heading-copy,.engine-actions{display:flex;align-items:center}.engine-heading{gap:15px;min-width:0}.engine-heading-copy{gap:11px;min-width:0}.engine-heading-copy h1{margin:0;color:var(--tone-d1d4da);font-size:17px;font-weight:350;white-space:nowrap}.engine-heading-copy span{overflow:hidden;color:var(--hint);font-size:11px;text-overflow:ellipsis;white-space:nowrap}.engine-actions{gap:7px}.engine-update-button{display:inline-flex;align-items:center;gap:6px;min-height:31px;padding:0 10px;border:1px solid var(--tone-827047);border-radius:5px;color:var(--tone-d3bd8b);background:var(--tone-302c22);font-size:10px;white-space:nowrap;cursor:pointer;transition:background-color 140ms ease,border-color 140ms ease}.engine-update-button:hover{border-color:var(--tone-a18a59);background:var(--tone-393326)}.update-arrow{display:inline-block;animation:update-arrow-pulse 900ms ease-in-out infinite alternate}@keyframes update-arrow-pulse{from{transform:translateY(2px) rotate(-10deg);opacity:.68}to{transform:translateY(-2px) rotate(8deg);opacity:1}}
.engine-button,.engine-back{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:31px;padding:0 10px;border:1px solid var(--border);border-radius:5px;color:var(--tone-b3bac4);background:transparent;font-size:11px;white-space:nowrap;cursor:pointer;transition:background-color 140ms ease,border-color 140ms ease,color 140ms ease,transform 120ms var(--ease-out)}.engine-button:hover,.engine-back:hover{border-color:var(--tone-505660);color:var(--tone-d2d5db);background:var(--tone-292c34)}.engine-button:active,.engine-back:active{transform:scale(.985)}.engine-button .ui-icon,.engine-back .ui-icon{width:13px;height:13px}.engine-button.primary{border-color:transparent;color:var(--tone-e5e7eb);background:var(--tone-626f81)}.engine-button.primary:hover{background:var(--tone-6b7788)}.engine-button.compact{min-height:28px;padding:0 9px;font-size:10px}
.engine-status-line{display:flex;align-items:center;gap:7px;min-height:36px;padding:3px 24px 6px}.engine-status{display:inline-flex;align-items:center;min-height:22px;padding:0 8px;border:1px solid var(--tone-3b3e46);border-radius:4px;color:var(--tone-a9aeb6);background:var(--tone-262930);font-size:10px}.engine-status.ready{color:var(--tone-aab8ad)}.engine-link{padding:3px 2px;border:0;color:var(--tone-adb6c2);background:transparent;font-size:10px;cursor:pointer}.engine-link:hover{color:var(--tone-d1d5dc);text-decoration:underline}
.engine-scroll-area{flex:1;min-height:0;overflow:auto;scrollbar-color:var(--tone-4a4e56) transparent;scrollbar-width:thin}.engine-scroll-content{display:flex;flex-direction:column;gap:10px;padding:5px 25px 13px 24px}.engine-summary,.engine-card{min-width:0;border:1px solid var(--outline-subtle);border-radius:7px;background:var(--card)}.engine-summary{display:grid;grid-template-columns:minmax(0,1.2fr) auto minmax(0,1fr) auto;align-items:center;gap:10px;padding:10px 12px}.summary-main,.asset-copy{display:grid;min-width:0;gap:4px}.summary-label,.engine-field>span{color:var(--hint);font-size:10px}.summary-main strong,.asset-copy strong{overflow:hidden;color:var(--tone-c5cad1);font-size:11px;font-weight:350;text-overflow:ellipsis;white-space:nowrap}.summary-main small,.asset-copy small{overflow:hidden;color:var(--tone-888e97);font-size:9px;line-height:1.4;text-overflow:ellipsis}.engine-card-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px}.engine-card{padding:12px 13px 11px}.engine-card-heading{display:flex;align-items:center;gap:9px;min-height:25px;margin-bottom:10px}.engine-card-heading>span{color:var(--tone-8993a0);font-size:10px;letter-spacing:.04em}.engine-card-heading>div{display:grid;gap:2px}.engine-card-heading h2{margin:0;color:var(--tone-cbd0d7);font-size:13px;font-weight:400}.engine-card-heading small{color:var(--hint);font-size:9px}
.engine-fields{display:grid;gap:9px}.engine-fields.two-columns{grid-template-columns:repeat(2,minmax(0,1fr))}.engine-fields.spaced{margin-top:9px}.engine-field{display:grid;min-width:0;gap:5px}.engine-input,.engine-select{width:100%;min-width:0;height:30px;padding:0 9px;border:1px solid var(--tone-3d414a);border-radius:5px;color:var(--tone-c6cbd3);background:var(--tone-22252c);font-size:11px;font-weight:350}.engine-select{padding-right:24px;cursor:pointer}.engine-select option{color:var(--tone-cbd0d7);background:var(--tone-252830)}.engine-input::placeholder{color:var(--tone-707680)}.engine-param-grid{display:grid;grid-template-columns:repeat(4,minmax(82px,1fr));gap:8px}.engine-hint{margin:8px 0 0;color:var(--tone-898f99);font-size:10px;line-height:1.45;white-space:pre-line}
.engine-switch{display:flex;align-items:center;gap:8px;width:100%;margin-top:8px;padding:4px 0;border:0;color:inherit;background:transparent;text-align:left;cursor:pointer}.engine-switch>i{position:relative;width:27px;height:15px;flex:0 0 auto;border-radius:9px;background:var(--tone-454951);transition:background-color 150ms ease}.engine-switch>i:after{position:absolute;top:2px;left:2px;width:11px;height:11px;border-radius:50%;background:var(--tone-adb3bc);transition:transform 160ms var(--ease-out);content:''}.engine-switch.active>i{background:var(--tone-626f81)}.engine-switch.active>i:after{transform:translateX(12px)}.engine-switch>span{display:grid;gap:2px}.engine-switch strong{color:var(--tone-bfc4cc);font-size:11px;font-weight:400}.engine-switch small{color:var(--hint);font-size:9px}.engine-check{display:inline-flex;align-items:center;gap:7px;min-height:28px;padding:2px 3px;border:0;color:var(--tone-a7adb7);background:transparent;font-size:10px;text-align:left;cursor:pointer}.engine-check>i{display:grid;width:14px;height:14px;flex:0 0 auto;place-items:center;border:1px solid var(--tone-646a75);border-radius:3px;background:var(--tone-22252c);transition:border-color 130ms ease,background-color 130ms ease}.engine-check.checked>i{border-color:var(--tone-687689);background:var(--tone-626f81)}.engine-check.checked>i:after{width:6px;height:3px;border-bottom:1.4px solid var(--tone-e2e5e9);border-left:1.4px solid var(--tone-e2e5e9);transform:translateY(-1px) rotate(-45deg);content:''}.engine-check:hover{color:var(--tone-d0d4da)}
.advanced-heading{margin-bottom:9px}.engine-advanced-grid{display:grid;grid-template-columns:repeat(4,minmax(100px,1fr));align-items:end;gap:9px}.wide-field{grid-column:span 2}.engine-utility-row{display:flex;flex-wrap:wrap;gap:7px}.engine-utility{min-height:29px;padding:0 10px;border:1px solid var(--border);border-radius:5px;color:var(--tone-afb5bf);background:var(--tone-252830);font-size:10px;cursor:pointer;transition:border-color 130ms ease,color 130ms ease,background-color 130ms ease,transform 110ms ease-out}.engine-utility:hover{border-color:var(--tone-505660);color:var(--tone-d0d4da);background:var(--tone-2b2e36)}.engine-utility:active{transform:scale(.985)}.engine-footer-note{display:flex;align-items:center;gap:7px;margin:-2px 1px 0;color:var(--tone-818792);font-size:10px}.engine-footer-note i{width:5px;height:5px;border-radius:50%;background:var(--tone-929baa)}
@media(max-width:1180px){.engine-toolbar{align-items:flex-start;flex-direction:column}.engine-actions{flex-wrap:wrap}.engine-card-grid{grid-template-columns:1fr}.engine-param-grid{grid-template-columns:repeat(3,minmax(100px,1fr))}.engine-advanced-grid{grid-template-columns:repeat(3,minmax(100px,1fr))}.engine-summary{grid-template-columns:minmax(0,1fr) auto}.asset-copy{grid-column:1}}
@media(prefers-reduced-motion:reduce){.engine-button,.engine-back,.engine-switch>i,.engine-switch>i:after{transition:none}}
</style>
