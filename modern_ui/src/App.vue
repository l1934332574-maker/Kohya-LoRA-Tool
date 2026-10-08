<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import ModelTrainingChooser from './components/ModelTrainingChooser.vue'
import catalogData from '../../kohya_core/model_catalog.json'
import TrainingAssistant from './components/TrainingAssistant.vue'
import EngineSidebar from './components/EngineSidebar.vue'
import LogDock from './components/LogDock.vue'
import LogExportDialog from './components/LogExportDialog.vue'
import ProjectRow from './components/ProjectRow.vue'
import UiIcon from './components/UiIcon.vue'
import ModernQwenWorkspace from './components/ModernQwenWorkspace.vue'
import ModernKohyaWorkspace from './components/ModernKohyaWorkspace.vue'
import ModernEngineWorkspace from './components/ModernEngineWorkspace.vue'
import SliderWorkspace from './components/SliderWorkspace.vue'
import ModernTaskDialog from './components/ModernTaskDialog.vue'
import ModernTrainingDialog from './components/ModernTrainingDialog.vue'
import TrainingHistoryDialog from './components/TrainingHistoryDialog.vue'
import ModelDownloadDialog from './components/ModelDownloadDialog.vue'
import EnvironmentDialog from './components/EnvironmentDialog.vue'
import PromptReverseDialog from './components/PromptReverseDialog.vue'
import ModernHelpDialog from './components/ModernHelpDialog.vue'
import AppearanceDialog from './components/AppearanceDialog.vue'
import {
  loadBootstrap,
  type BootstrapData,
  type ModelChoice,
  type ModelCatalogData,
  type ProjectCard,
  type ProjectConfig,
  type QwenModelSaveResult,
  type QwenModelSelection,
  type QwenModelSetup,
  type ModeWorkspaceData,
  type GuideStep,
  type TrainingPlan,
  type AppearanceSettings,
  type AppearancePreset,
} from './bridge'

const data = ref<BootstrapData | null>(null)
const logs = ref<string[]>([])
const loading = ref(true)
const loadError = ref('')
const preview = ref(false)
const firstEngineModes = ['character', 'style', 'concept'] as const
type FirstEngineMode = typeof firstEngineModes[number]
const firstEngineBaseTypes = ['sd15', 'sdxl', 'flux', 'anima'] as const
type FirstEngineBaseType = typeof firstEngineBaseTypes[number]
const firstEngineSidebarModes: Record<FirstEngineBaseType, string> = {
  sd15: 'kohya_sd15',
  sdxl: 'kohya_sdxl',
  flux: 'kohya_flux',
  anima: 'kohya_anima',
}
const firstEngineTemplates: Record<FirstEngineBaseType, string> = {
  sd15: 'SD1.5',
  sdxl: 'SDXL',
  flux: 'FLUX.1',
  anima: 'Anima',
}
const firstEngineBaseLabels: Record<FirstEngineBaseType, string> = {
  sd15: 'SD 1.5（512px）',
  sdxl: 'SDXL 1.0（1024px）',
  flux: 'FLUX.1（1024px）',
  anima: 'Anima（1024px）',
}
const selectedMode = ref(firstEngineSidebarModes.sdxl)
const projectModeFilter = ref<string | null>(null)
const workspaceOpen = ref(false)
const workspaceKind = ref<'qwen' | 'kohya' | 'engine' | 'slider'>('qwen')
const workspaceProject = ref<ProjectCard | null>(null)
const workspaceConfig = ref<ProjectConfig | null>(null)
const assistantOpen = ref(false)
const promptReverseOpen = ref(false)
const agentBusy = ref(false)
const previewConfigs = ref<Record<string, ProjectConfig>>({})
const modeWorkspace = ref<ModeWorkspaceData | null>(null)
const qwenModelSetup = ref<QwenModelSetup | null>(null)
const activeWorkspaceRef = ref<{
  hasUnsavedChanges?: () => boolean
  startTraining: () => void
  save?: () => void
  guideAction?: (action: string) => Promise<ProjectConfig | null> | ProjectConfig | null
  openModelDialog?: () => void
} | null>(null)
const dialogOpen = ref(false)
const dialogKind = ref<'create' | 'rename'>('create')
const editingProject = ref<ProjectCard | null>(null)
const projectName = ref('')
const templateName = ref('自定义')
const createModeOverride = ref('')
const createChoice = ref<ModelChoice | undefined>()
const createModel = ref('sdxl')
const createGoal = ref('character')
const createChoiceAvailable = ref(true)
const busy = ref(false)
const formError = ref('')
const toast = ref('')
const logExportOpen = ref(false)
const logExportBusy = ref(false)
const logExportId = ref('')
const logExportError = ref('')
const setupDialogOpen = ref(false)
const setupAction = ref('')
const historyDialogOpen = ref(false)
const trainingDialogRef = ref<{ expand: () => void; attach: (id: string) => Promise<void> } | null>(null)
const setupDialogRef = ref<{ attach: (id: string) => Promise<void> } | null>(null)
const agentTaskTitle = ref('')
let seenAgentTaskId = ''
const trainingActive = ref(false)
const trainingDialogOpen = ref(false)
const trainingPlan = ref<TrainingPlan | null>(null)
const trainingProjectName = ref('')
const modelDialogOpen = ref(false)
const envDialogOpen = ref(false)
const helpDialogOpen = ref(false)
const helpDialogKind = ref<'readme' | 'mode'>('mode')
const helpDialogMode = ref('')
const appearanceDialogOpen = ref(false)
const appearanceSaving = ref(false)
const appearance = ref<AppearanceSettings>({
  theme: 'dark', background_path: '', background_source_path: '', background_opacity: 18, background_available: false,
  background_history: [], component_opacity: 100, idle_fade_enabled: false,
})
const appearanceImage = ref('')
const appearancePresets = ref<AppearancePreset[]>([])
const hiddenBuiltinPresetIds = ref<string[]>([])
const systemPrefersLight = ref(false)
const uiIdle = ref(false)
const nameInput = ref<HTMLInputElement | null>(null)
const importFileInput = ref<HTMLInputElement | null>(null)
const importedConfigJson = ref('')
const importedConfigPreview = ref<ProjectConfig | null>(null)
const importedConfigLabel = ref('')
let previousFocus: HTMLElement | null = null
let projectNameSuggestionRequest = 0
let uiIdleFadeTimer: number | undefined
const UI_IDLE_FADE_DELAY_MS = 45_000
const reservedPreviewProjectNames = new Set<string>()
let systemThemeQuery: MediaQueryList | null = null
const updateSystemTheme = (event: MediaQueryListEvent) => { systemPrefersLight.value = event.matches }
const activeTheme = computed(() => appearance.value.theme === 'system'
  ? (systemPrefersLight.value ? 'light' : 'dark')
  : appearance.value.theme)
const appShellStyle = computed(() => ({
  '--wallpaper-image': appearanceImage.value ? `url("${appearanceImage.value}")` : 'none',
  '--wallpaper-opacity': appearanceImage.value ? String(appearance.value.background_opacity / 100) : '0',
  '--ui-component-opacity': String(appearance.value.component_opacity / 100),
}) as Record<string, string>)

function scheduleUiIdleFade() {
  if (uiIdleFadeTimer !== undefined) window.clearTimeout(uiIdleFadeTimer)
  uiIdle.value = false
  if (!appearance.value.idle_fade_enabled) return
  uiIdleFadeTimer = window.setTimeout(() => {
    uiIdle.value = true
    uiIdleFadeTimer = undefined
  }, UI_IDLE_FADE_DELAY_MS)
}

function registerUiActivity() {
  scheduleUiIdleFade()
}

const projects = computed(() => data.value?.projects ?? [])
function projectMatchesSidebarMode(project: ProjectCard, mode: string) {
  if (mode.startsWith("model:")) return modelKeyForProject(project) === mode.slice(6)
  const baseType = firstEngineBaseTypeForSidebarMode(mode)
  if (baseType) return isKohyaProject(project) && project.base_type === baseType
  return mode === '_kohya' ? isKohyaProject(project) : project.mode === mode
}
const visibleProjects = computed(() => projectModeFilter.value
  ? projects.value.filter((project) => projectMatchesSidebarMode(project, projectModeFilter.value!))
  : projects.value)
const projectModeFilterLabel = computed(() => sidebarGroups.value
  .flatMap((group) => group.modes)
  .find((mode) => mode.key === projectModeFilter.value)?.label ?? '当前模型')
const templates = computed(() => data.value?.templates ?? [])
const catalog = computed<ModelCatalogData>(() => data.value?.model_catalog ?? { models: catalogData, gpu_vendor: 'unknown', gpu: '浏览器预览' })
const sidebarGroups = computed(() => [{label: '选择模型', modes: catalog.value.models.map(model => ({key: `model:${model.key}`, label: model.label}))}])
function modelKeyForProject(project: ProjectCard): string {
  if (isKohyaProject(project)) return project.base_type
  const modeMap: Record<string, string> = {anima_fz:'anima',sdxl_fz:'sdxl',krea2:'krea2',krea2_at:'krea2',krea2_fz:'krea2',flux2:'klein',flux2_fz:'klein',qwen_image:'qwen',qwen21_fz:'qwen',video:'h3',h3_fz:'h3',zimage:'zimage'}
  return modeMap[project.mode] || project.mode
}
const selectedNavModel = computed(() => workspaceProject.value ? `model:${modelKeyForProject(workspaceProject.value)}` : selectedMode.value.startsWith('model:') ? selectedMode.value : `model:${firstEngineBaseTypeForSidebarMode(selectedMode.value) || modelKeyForProject({mode:selectedMode.value,base_type:'sdxl'} as ProjectCard)}`)
function preferredModeForModel(key: string): string {
  const model = catalog.value.models.find(m => m.key === key)
  const choices = model?.variants.flatMap(v => v.engines) || []
  return (choices.find(e => e.recommended) || choices.find(e => catalog.value.gpu_vendor === 'unknown' || e.vendors.includes(catalog.value.gpu_vendor)) || choices[0])?.mode || 'character'
}
function onModelChoice(choice: ModelChoice, template: string, mode: string, goal: string) {
  createChoice.value = choice
  createChoiceAvailable.value = true
  templateName.value = template
  createModeOverride.value = firstEngineModes.includes(mode as FirstEngineMode) ? goal : ''
  createGoal.value = goal
}

const topActions = [
  { key: 'tools', icon: 'toolbox', label: '小工具', tip: '打开查看显存、清理显存/内存和缓存等训练辅助工具。' },
  { key: 'check_update', icon: 'refresh', label: '检查更新', tip: '检查 Kohya-LoRA 软件更新；训练引擎更新在对应训练引擎界面中处理。' },
  { key: 'output_dir', icon: 'folder', label: '输出目录', tip: '打开训练产物根目录，查看 LoRA、使用模板、参数报告和中间快照。' },
  { key: 'data_dir', icon: 'database', label: '数据目录', tip: '打开本机程序数据目录，查看项目配置、模型和缓存文件。' },
  { key: 'queue', icon: 'queue', label: '训练队列', tip: '选择多个项目，按顺序执行数据预处理和训练。' },
] as const
const trainActionLabel = computed(() => workspaceOpen.value ? '一键开始训练' : '打开新版训练页')
const guideSteps = computed(() => {
  if (workspaceKind.value !== 'slider' || !workspaceOpen.value) return modeWorkspace.value?.guide_steps ?? []
  const settings = workspaceConfig.value?.slider
  return [
    {id:'fizgig', label:'① 训练环境', button:'配置', action:'cmd_install_fizgig', check:'fizgig', tip:'Fizgig v7.0.1。', done:Boolean(modeWorkspace.value?.engine_ready)},
    {id:'base', label:'② 选择底模', button:'选择', action:'cmd_pick_model_type', check:'base', tip:'SDXL / 标准 28 层 Anima。', done:Boolean(workspaceConfig.value?.base_model)},
    {id:'goal', label:'③ 训练目标', button:'设置', action:'cmd_pick_raw', check:'goal', tip:'设置目标与数据来源。', done:Boolean(settings?.name && settings?.neutral)},
  ]
})
const guideLabel = computed(() => workspaceProject.value?.mode_label || modeWorkspace.value?.label || '')
const selectedGuideMode = computed(() => selectedMode.value.startsWith('model:') ? preferredModeForModel(selectedMode.value.slice(6)) : selectedMode.value === '_kohya'
  ? (projects.value.find(isKohyaProject)?.mode || 'character')
  : firstEngineBaseTypeForSidebarMode(selectedMode.value)
    ? (projects.value.find((project) => isKohyaProject(project)
      && project.base_type === firstEngineBaseTypeForSidebarMode(selectedMode.value))?.mode || 'character')
    : selectedMode.value)

// Keep standalone browser previews representative of the real mode registry.
// Desktop workspaces replace this demo payload with live values from modern_host.py.
const demoPresets: Record<string, Record<string, string>> = {
  style: { rank: '16', alpha: '8', unet_lr: '1.5e-4', te_lr: '7.5e-5', repeats: '5', max_epochs: '8', resolution: '512', noise_offset: '0.05', min_snr_gamma: '5' },
  character: { rank: '32', alpha: '16', unet_lr: '7e-5', te_lr: '4e-5', repeats: '3', max_epochs: '6', resolution: '512', noise_offset: '0.05', min_snr_gamma: '5' },
  concept: { rank: '32', alpha: '16', unet_lr: '1e-4', te_lr: '5e-5', repeats: '3', max_epochs: '8', resolution: '512', noise_offset: '0.05', min_snr_gamma: '5' },
  anima_fz: {rank:'16',alpha:'16',unet_lr:'1e-4',te_lr:'0',repeats:'2',max_epochs:'16',resolution:'512'},
  sdxl_fz: {rank:'16',alpha:'16',unet_lr:'1e-4',te_lr:'0',repeats:'2',max_epochs:'16',resolution:'512'},
  krea2: { rank: '32', alpha: '32', unet_lr: '1e-4', te_lr: '1e-4', repeats: '2', max_epochs: '16', resolution: '512' },
  krea2_at: { rank: '32', alpha: '32', unet_lr: '1e-4', te_lr: '1e-4', repeats: '2', max_epochs: '8', resolution: '512' },
  krea2_fz: { rank: '32', alpha: '32', unet_lr: '1e-4', te_lr: '1e-4', repeats: '2', max_epochs: '16', resolution: '512' },
  qwen21_fz: { rank: '8', alpha: '8', unet_lr: '1e-4', te_lr: '1e-4', repeats: '1', max_epochs: '30', resolution: '512', fizgig_qwen_preset: 'auto' },
  h3_fz: { rank: '8', alpha: '8', unet_lr: '2e-4', te_lr: '1e-4', repeats: '1', max_epochs: '50', resolution: '512', video_frames: '56', sample_interval: '5' },
  flux2: { rank: '32', alpha: '32', unet_lr: '1e-4', te_lr: '1e-4', repeats: '2', max_epochs: '16', resolution: '512' },
  flux2_fz: { rank: '32', alpha: '32', unet_lr: '1e-4', te_lr: '1e-4', repeats: '2', max_epochs: '16', resolution: '512' },
  video: { rank: '32', alpha: '32', unet_lr: '2e-4', te_lr: '1e-4', repeats: '1', max_epochs: '20', resolution: '512', video_steps: '2000', video_frames: '73' },
  qwen_image: { rank: '16', alpha: '16', unet_lr: '1e-4', te_lr: '1e-4', repeats: '1', max_epochs: '20', resolution: '512', video_steps: '2000' },
  zimage: { rank: '16', alpha: '16', unet_lr: '1e-4', te_lr: '1e-4', repeats: '1', max_epochs: '20', resolution: '512', video_steps: '2000' },
}


const demoQuantModes: Record<string, string[]> = {
  anima_fz: ['auto','bf16','int8','nf4'],
  sdxl_fz: ['auto','bf16','int8','nf4'],
  krea2: ['auto', 'fp8', 'int8', 'nf4'],
  flux2: ['auto', 'fp8', 'int8', 'nf4'],
  krea2_fz: ['auto', 'fp8', 'int8', 'nf4', 'bf16'],
  flux2_fz: ['auto', 'fp8', 'nf4', 'bf16'],
  qwen21_fz: ['auto', 'bf16', 'int8', 'nf4'],
  h3_fz: ['auto', 'int8', 'nf4', 'hqq'],
}

function setActiveWorkspace(instance: unknown) {
  activeWorkspaceRef.value = instance as {
    startTraining: () => void
  save?: () => void
    guideAction?: (action: string) => Promise<ProjectConfig | null> | ProjectConfig | null
    openModelDialog?: () => void
  } | null
}

function isKohyaProject(project: ProjectCard) {
  return (project.mode === 'character' || project.mode === 'style' || project.mode === 'concept') && project.base_type !== 'qwen_image'
}

function firstEngineBaseTypeForSidebarMode(mode: string): FirstEngineBaseType | undefined {
  return firstEngineBaseTypes.find((baseType) => firstEngineSidebarModes[baseType] === mode)
}

function firstEngineSidebarModeForBaseType(baseType: string) {
  return firstEngineBaseTypes.includes(baseType as FirstEngineBaseType)
    ? firstEngineSidebarModes[baseType as FirstEngineBaseType]
    : firstEngineSidebarModes.sdxl
}

function templateForBaseType(baseType: FirstEngineBaseType) {
  const name = firstEngineTemplates[baseType]
  return templates.value.find((item) => item.name === name && item.base_type === baseType)?.name
    ?? templates.value.find((item) => item.base_type === baseType && firstEngineModes.includes(item.mode as FirstEngineMode))?.name
    ?? templates.value.find((item) => item.name === name)?.name
    ?? templates.value.find((item) => item.name === '自定义')?.name
}

function isQwenProject(project: ProjectCard) {
  return project.mode === 'qwen_image' || project.mode === 'zimage' || project.base_type === 'qwen_image'
}

function isModernProject(project: ProjectCard) {
  return isKohyaProject(project) || isQwenProject(project) || Boolean(data.value?.modes.some((item) => item.key === project.mode))
}

function templateForMode(mode: string) {
  return templates.value.find((item) => item.mode === mode)?.name
}

function modeOverrideForSelectedTemplate(): FirstEngineMode | undefined {
  if (!firstEngineModes.includes(createModeOverride.value as FirstEngineMode)) return undefined
  const selectedTemplate = templates.value.find((item) => item.name === templateName.value)
  return selectedTemplate && firstEngineModes.includes(selectedTemplate.mode as FirstEngineMode)
    ? createModeOverride.value as FirstEngineMode
    : undefined
}

function demoModeWorkspace(mode: string): ModeWorkspaceData {
  const template = templates.value.find((item) => item.mode === mode)
  const preset = demoPresets[mode] ?? {}
  const stepBased = ['video', 'qwen_image', 'zimage'].includes(mode)
  const usesEpochs = ['krea2_fz', 'flux2_fz', 'qwen21_fz', 'h3_fz', 'anima_fz', 'sdxl_fz'].includes(mode)
  const supports: Record<string, boolean> = {
    rank: true, alpha: true, unet_lr: true, te_lr: false, repeats: !stepBased,
    max_epochs: !stepBased, resolution: true, save_every: true, sample_interval: true,
    video_steps: stepBased, video_frames: ['video', 'h3_fz'].includes(mode), optimizer: !['krea2_fz', 'flux2_fz', 'qwen21_fz', 'h3_fz', 'anima_fz', 'sdxl_fz'].includes(mode),
    strong_bind: true, clean_concept: true, sample_preview: true, compile: ['krea2', 'flux2', 'krea2_fz'].includes(mode),
    global_pos: ['style', 'character', 'concept'].includes(mode), global_neg: ['style', 'character', 'concept'].includes(mode),
    crop_ratio: true, sample_prompt: true, noise_offset: false, min_snr_gamma: false,
    quant_mode: ['krea2', 'flux2', 'krea2_fz', 'flux2_fz', 'qwen21_fz', 'h3_fz', 'anima_fz', 'sdxl_fz'].includes(mode),
    blocks_to_swap: ['krea2', 'flux2', 'krea2_fz', 'flux2_fz'].includes(mode),
    // ★ 2026-09-27 新增：批大小 / 梯度检查点（用户诉求「训练器能改 bs 和梯度检查点」）
    //   第一引擎（画风/人物/概念）与第二引擎的 Krea2 / FLUX.2 都真读它们；
    //   Fizgig（第四引擎）走 yaml 且固定开启，不显示
    batch_size: ['style', 'character', 'concept', 'krea2', 'flux2'].includes(mode),
    gc: ['style', 'character', 'concept', 'krea2', 'flux2'].includes(mode),
    wd14_model: mode !== 'video', overwrite: mode !== 'video',
    amd_mode: mode === 'krea2_at',
  }
  const demoGuideSpecs: Record<string, Array<[string, string, string, string, string]>> = {
    style: [['env', '① 环境准备', '去准备', 'cmd_env', '安装 Git 和 Python（只需一次，全部项目通用）。'], ['kohya', '② 安装训练内核', '去安装', 'cmd_install', '安装 Kohya 训练内核（画风/人物模式需要，只需一次）。'], ['base', '③ 选择模型类型', '去设置', 'cmd_pick_model_type', '选择底模文件并确认模型类型；自动识别不准时可手动指定。'], ['raw', '④ 选择图片文件夹', '去选文件夹', 'cmd_pick_raw', '选择原始图片文件夹（jpg/png/webp 等）。']],
    character: [['env', '① 环境准备', '去准备', 'cmd_env', '安装 Git 和 Python（只需一次，全部项目通用）。'], ['kohya', '② 安装训练内核', '去安装', 'cmd_install', '安装 Kohya 训练内核（画风/人物模式需要，只需一次）。'], ['base', '③ 选择模型类型', '去设置', 'cmd_pick_model_type', '选择底模文件并确认模型类型；建议和出图用的底模同系列。'], ['raw', '④ 选择图片文件夹', '去选文件夹', 'cmd_pick_raw', '选择同一人物的图片文件夹（15~30 张）。']],
    concept: [['env', '① 环境准备', '去准备', 'cmd_env', '安装 Git 和 Python（只需一次，全部项目通用）。'], ['kohya', '② 安装训练内核', '去安装', 'cmd_install', '安装 Kohya 训练内核（概念模式需要，只需一次）。'], ['base', '③ 选择模型类型', '去设置', 'cmd_pick_model_type', '选择底模文件并确认模型类型；自动识别不准时可手动指定。'], ['raw', '④ 选择图片文件夹', '去选文件夹', 'cmd_pick_raw', '准备 15~30 张同一形态/种族的图片。']],
    krea2: [['env', '① 环境准备', '去准备', 'cmd_env', '安装 Git 和 Python（只需一次）。'], ['musubi', '② 安装第二引擎', '去安装', 'cmd_install_musubi', '安装第二引擎 musubi-tuner。'], ['krea2_models', '③ 下载 Krea2 模型', '去下载', 'cmd_dl_krea2_models', '检查并获取 Krea2 RAW、VAE 和文本编码器。'], ['raw', '④ 选择图片文件夹', '去选文件夹', 'cmd_pick_raw', '选择 15~30 张人物或风格图片。']],
    krea2_fz: [['env', '① 环境准备', '去准备', 'cmd_env', '安装 Git 和 Python（只需一次）。'], ['fizgig', '② 安装第四引擎', '去安装', 'cmd_install_fizgig', '安装第四引擎 Fizgig。'], ['krea2_models', '③ 下载 Krea2 模型', '去下载', 'cmd_dl_krea2_models', '检查并获取 Krea2 RAW、VAE 和文本编码器。'], ['raw', '④ 选择图片文件夹', '去选文件夹', 'cmd_pick_raw', '选择 15~30 张人物或风格图片。']],
    krea2_at: [['env', '① 环境准备', '去准备', 'cmd_env', '安装 Git 和 Python（只需一次）。'], ['at', '② 安装第三引擎', '去安装', 'cmd_install_at', '安装第三引擎 AI Toolkit。'], ['krea2_at_models', '③ 下载 Krea2 模型', '去下载', 'cmd_dl_krea2_models', '设置 Krea 2 RAW；已有文本编码器和 VAE 可指定本地文件。'], ['raw', '④ 选择图片文件夹', '去选文件夹', 'cmd_pick_raw', '选择 15~30 张人物或风格图片。']],
    flux2: [['env', '① 环境准备', '去准备', 'cmd_env', '安装 Git 和 Python（只需一次）。'], ['musubi', '② 安装第二引擎', '去安装', 'cmd_install_musubi', '安装第二引擎 musubi-tuner。'], ['flux2_models', '③ 下载 FLUX.2 模型', '去下载', 'cmd_dl_flux2_models', '检查 FLUX.2 的 DiT、文本编码器和 VAE。'], ['raw', '④ 选择图片文件夹', '去选文件夹', 'cmd_pick_raw', '选择 15~30 张人物或风格图片。']],
    flux2_fz: [['env', '① 环境准备', '去准备', 'cmd_env', '安装 Git 和 Python（只需一次）。'], ['fizgig', '② 安装第四引擎', '去安装', 'cmd_install_fizgig', '安装第四引擎 Fizgig。'], ['flux2_fz_models', '③ 下载 Klein 9B 模型', '去下载', 'cmd_dl_flux2_models', '检查 Klein 9B DiT、文本编码器和 VAE。'], ['raw', '④ 选择图片文件夹', '去选文件夹', 'cmd_pick_raw', '选择 15~30 张人物或风格图片。']],
    qwen21_fz: [['env', '① 环境准备', '去准备', 'cmd_env', '安装 Git 和 Python（只需一次）。'], ['fizgig', '② 安装第四引擎', '去安装', 'cmd_install_fizgig', '安装第四引擎 Fizgig。'], ['qwen21_fz_models', '③ 下载 Qwen-Image-2.1 模型', '去下载', 'cmd_dl_qwen21_fz_models', 'DiT、VAE、文本编码器、训练适配器必需；speed LoRA 可选。'], ['raw', '④ 选择图片文件夹', '去选文件夹', 'cmd_pick_raw', '至少准备 5 张图片；可选人物、画风或概念训练类型。']],
    h3_fz: [['env', '① 环境准备', '去准备', 'cmd_env', '安装 Git 和 Python（只需一次）。'], ['fizgig', '② 安装第四引擎', '去安装', 'cmd_install_fizgig', '安装第四引擎 Fizgig。'], ['h3_fz_models', '③ 下载 H3 Fizgig 模型', '去下载', 'cmd_dl_h3_fz_models', '官方 int8 DiT、文本编码器、视频 VAE 必需；独立音频需音频 VAE，可选适配器和 Turbo LoRA。'], ['raw', '④ 选择混合媒体文件夹', '去选文件夹', 'cmd_pick_raw', '图片、视频和音频可放在同一目录或子目录；每个媒体都需要同名 .txt。']],
    video: [['env', '① 环境准备', '去准备', 'cmd_env', '安装 Git 和 Python（只需一次）。'], ['at', '② 安装第三引擎', '去安装', 'cmd_install_at', '安装第三引擎 AI Toolkit。'], ['h3_models', '③ 下载 H3 模型', '去下载', 'cmd_dl_h3_models', '检查 H3 主模型、文本编码器和视频 VAE。'], ['raw', '④ 选择视频文件夹', '去选文件夹', 'cmd_pick_raw', '选择包含 mp4 视频和同名 txt 字幕的数据集文件夹。']],
    qwen_image: [['env', '① 环境准备', '去准备', 'cmd_env', '安装 Git 和 Python（只需一次）。'], ['at', '② 安装第三引擎', '去安装', 'cmd_install_at', '安装第三引擎 AI Toolkit。'], ['at_model', '③ Qwen-Image 模型', '查看说明', 'cmd_at_model_help', '查看模型选择、显存和本地组件说明。'], ['raw', '④ 选择图片文件夹', '去选文件夹', 'cmd_pick_raw', '选择原始图片文件夹（15~30 张人物/风格图片）。']],
    zimage: [['env', '① 环境准备', '去准备', 'cmd_env', '安装 Git 和 Python（只需一次）。'], ['at', '② 安装第三引擎', '去安装', 'cmd_install_at', '安装第三引擎 AI Toolkit。'], ['at_model', '③ Z-Image 模型', '查看说明', 'cmd_at_model_help', '查看模型选择、显存和本地组件说明。'], ['raw', '④ 选择图片文件夹', '去选文件夹', 'cmd_pick_raw', '选择原始图片文件夹（15~30 张人物/风格图片）。']],
  }
  const guide_steps = (demoGuideSpecs[mode] ?? []).map(([id, label, button, action, tip]) => ({ id, label, button, action, check: id, tip, done: false }))
  return {
    ok: true, mode, label: template?.mode_label || mode,
    dataset_hint: '准备与当前训练模式匹配的数据集后再继续。',
    trigger_hint: '使用独特的触发词；该模式的详细说明会在桌面模式中读取。',
    dataset_hints: { style: '画风图集建议包含多个主体与姿态。', character: '人物图集使用同一主体的清晰图片。', concept: '概念图集保持概念一致，并混合其他主体属性。' },
    trigger_hints: { style: '为画风设置独特的 trigger。', character: '为人物设置独特的 trigger。', concept: '为概念设置独特的 trigger。' },
    engine_ready: false, engine_update_available: false, engine_key: '', gpu: '预览', gpu_vendor: 'unknown', missing_models: ['桌面模式会在打开项目时读取真实模型状态。'],
    asset_dir: '', supports, quant_modes: demoQuantModes[mode] ?? [], interval_units: { save_every: usesEpochs || ['krea2', 'flux2'].includes(mode) ? 'epochs' : 'steps', sample_interval: usesEpochs ? 'epochs' : 'steps' },
    interval_hints: mode === 'h3_fz' ? { sample_interval: '填 N = 每 N 轮采样；留空沿用 H3 预设（当前默认 5 轮），填 0 按图集大小估算。训练开始时可能额外采样。' } : undefined,
    defaults: preset, presets: { [mode]: { sdxl: preset } }, is_video: ['video', 'h3_fz'].includes(mode), is_step_based: stepBased,
    has_training_submode: ['krea2', 'krea2_at', 'krea2_fz', 'qwen21_fz', 'flux2', 'flux2_fz'].includes(mode),
    guide_steps,
  }
}

function appendLog(message: string) {
  logs.value.push(message)
  if (logs.value.length > 3000) logs.value.splice(0, logs.value.length - 3000)
}

function showToast(message: string) {
  toast.value = message
  window.setTimeout(() => {
    if (toast.value === message) toast.value = ''
  }, 2600)
}

function normalizeImportedConfig(raw: unknown): ProjectConfig {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('配置文件内容不是有效的 JSON 对象。')
  const source = raw as Record<string, unknown>
  const modes = new Set(['style', 'character', 'concept', 'krea2', 'krea2_at', 'krea2_fz', 'qwen21_fz', 'h3_fz', 'anima_fz', 'sdxl_fz', 'flux2', 'flux2_fz', 'video', 'qwen_image', 'zimage'])
  const baseTypes = new Set(['sd15', 'sdxl', 'flux', 'anima'])
  const mode = typeof source.mode === 'string' && modes.has(source.mode) ? source.mode : 'character'
  const requestedBaseType = typeof source.base_type === 'string' ? source.base_type : ''
  const params = source.params && typeof source.params === 'object' && !Array.isArray(source.params)
    ? { ...(source.params as Record<string, unknown>) }
    : {}
  if (typeof source.sample_prompt === 'string' && source.sample_prompt.trim()) params.sample_prompt = source.sample_prompt
  return {
    mode,
    base_type: baseTypes.has(requestedBaseType) ? requestedBaseType : 'sdxl',
    base_model: typeof source.base_model === 'string' ? source.base_model.replace(/\\/g, '/').split('/').pop() || '' : '',
    at_sub_mode: typeof source.at_sub_mode === 'string' ? source.at_sub_mode : 'character',
    concept_type: typeof source.concept_type === 'string' ? source.concept_type : 'form',
    trigger: typeof source.trigger === 'string' ? source.trigger : '',
    global_pos: typeof source.global_pos === 'string' ? source.global_pos : '',
    global_neg: typeof source.global_neg === 'string' ? source.global_neg : '',
    style_caption: typeof source.style_caption === 'string' ? source.style_caption : '',
    unet_only: typeof source.unet_only === 'boolean' ? source.unet_only : false,
    params,
  }
}

async function readImportConfig(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    if (file.size > 2 * 1024 * 1024) throw new Error('配置文件不能超过 2 MB。')
    const raw = (await file.text()).replace(/^\uFEFF/, '')
    const parsed = normalizeImportedConfig(JSON.parse(raw))
    importedConfigJson.value = raw
    importedConfigPreview.value = parsed
    const matched = templates.value.find((item) => item.mode === parsed.mode && (!item.base_type || item.base_type === parsed.base_type))
      ?? templates.value.find((item) => item.mode === parsed.mode)
    if (matched) templateName.value = matched.name
    const modeLabel = matched?.mode_label || parsed.mode
    importedConfigLabel.value = `${file.name} · ${modeLabel} · ${Object.keys(parsed.params ?? {}).length} 项参数`
    formError.value = ''
  } catch (error) {
    importedConfigJson.value = ''
    importedConfigPreview.value = null
    importedConfigLabel.value = ''
    formError.value = error instanceof Error ? error.message : '配置文件读取失败。'
  } finally {
    input.value = ''
  }
}

function clearImportedConfig() {
  importedConfigJson.value = ''
  importedConfigPreview.value = null
  importedConfigLabel.value = ''
}

function nextPreviewProjectName() {
  const base = data.value?.default_project_name ?? '新项目'
  const taken = new Set([
    ...projects.value.map((project) => project.name.toLocaleLowerCase()),
    ...[...reservedPreviewProjectNames].map((name) => name.toLocaleLowerCase()),
  ])
  let candidate = base
  let suffix = 2
  while (taken.has(candidate.toLocaleLowerCase())) {
    candidate = `${base}_${suffix}`
    suffix += 1
  }
  reservedPreviewProjectNames.add(candidate)
  return candidate
}

function openCreate(preselectedTemplate?: string, preselectedMode?: FirstEngineMode) {
  dialogKind.value = 'create'
  editingProject.value = null
  createModeOverride.value = preselectedMode ?? ''
  createChoice.value = undefined
  createGoal.value = preselectedMode || 'character'
  createModel.value = selectedNavModel.value.slice(6) || 'sdxl'
  const fallbackName = preview.value ? nextPreviewProjectName() : data.value?.default_project_name ?? ''
  projectName.value = fallbackName
  templateName.value = preselectedTemplate ?? templates.value.find((item) => item.name === '自定义')?.name ?? templates.value[0]?.name ?? '自定义'
  clearImportedConfig()
  formError.value = ''
  dialogOpen.value = true

  const requestId = ++projectNameSuggestionRequest
  const api = window.pywebview?.api
  const suggestName = api?.suggest_project_name
  if (!preview.value && api && typeof suggestName === 'function') {
    void suggestName.call(api).then((result) => {
      if (result.ok && result.name && requestId === projectNameSuggestionRequest
          && dialogOpen.value && dialogKind.value === 'create' && projectName.value === fallbackName) {
        projectName.value = result.name
      }
    }).catch(() => {})
  }
}

function openCreateForSelectedMode() {
  if (!projectModeFilter.value) return openCreate()
  const mode = projectModeFilter.value
  if (mode.startsWith('model:')) return openCreate()
  const baseType = firstEngineBaseTypeForSidebarMode(mode)
  if (baseType) return openCreate(templateForBaseType(baseType))
  if (mode === '_kohya') return openCreate()
  const firstMode = firstEngineModes.includes(mode as FirstEngineMode) ? mode as FirstEngineMode : undefined
  openCreate(firstMode ? undefined : templateForMode(mode), firstMode)
}

function openRename(project: ProjectCard) {
  dialogKind.value = 'rename'
  editingProject.value = project
  projectName.value = project.name
  formError.value = ''
  clearImportedConfig()
  dialogOpen.value = true
}

async function saveDialog() {
  if (dialogKind.value === 'create' && !importedConfigJson.value && !createChoiceAvailable.value) { formError.value='这个模型版本尚未接入当前显卡，请选择其他版本。'; return }
  const name = projectName.value.trim()
  if (!name) {
    formError.value = '请填写项目名称。'
    return
  }
  busy.value = true
  formError.value = ''
  try {
    if (preview.value || !window.pywebview?.api) {
      if (dialogKind.value === 'rename' && editingProject.value) {
        const previousName = editingProject.value.name
        data.value!.projects = projects.value.map((item) => item.name === editingProject.value!.name ? { ...item, name } : item)
        if (previewConfigs.value[previousName]) {
          previewConfigs.value = { ...previewConfigs.value, [name]: previewConfigs.value[previousName] }
          delete previewConfigs.value[previousName]
        }
        appendLog(`[项目] 已重命名「${previousName}」→「${name}」`)
      } else {
        const duplicate = projects.value.some((item) => item.name.toLocaleLowerCase() === name.toLocaleLowerCase())
        if (duplicate) {
          formError.value = '同名项目已存在，请从列表中打开它。'
          return
        }
        const template = templates.value.find((item) => item.name === templateName.value)
        const imported = importedConfigPreview.value
        const mode = String(imported?.mode ?? (createGoal.value === 'slider' ? `${createChoice.value?.model || 'sdxl'}_fz` : modeOverrideForSelectedTemplate() || template?.mode || 'character'))
        const baseType = String(imported?.base_type ?? (createGoal.value === 'slider' ? createChoice.value?.model || 'sdxl' : template?.base_type ?? (mode === 'qwen_image' ? 'qwen_image' : 'sdxl')))
        const matchingTemplate = templates.value.find((item) => item.mode === mode && (!item.base_type || item.base_type === baseType))
          ?? templates.value.find((item) => item.mode === mode)
          ?? template
        const qwenTemplate = mode === 'qwen_image' || mode === 'zimage' || baseType === 'qwen_image'
        const firstEngineLabel = ({ character: '人物 LoRA', style: '画风 LoRA', concept: '概念 LoRA' } as Record<string, string>)[mode]
        const baseTypeLabel = ({ sdxl: 'SDXL 1.0（1024px）', sd15: 'SD1.5（512px）', flux: 'FLUX.1（1024px）', anima: 'Anima（1024px）' } as Record<string, string>)[baseType]
        const project: ProjectCard = {
          name,
          updated: new Date().toISOString().replace('T', ' ').slice(0, 19),
          mode,
          training_kind: createGoal.value === 'slider' ? 'slider' : 'standard',
          mode_label: createGoal.value === 'slider' ? '概念滑块 LoRA' : firstEngineLabel ?? matchingTemplate?.mode_label ?? mode,
          base_type: baseType,
          base_type_label: qwenTemplate ? (mode === 'zimage' ? 'Z-Image' : 'Qwen-Image') : baseTypeLabel ?? baseType,
          raw_dir: '',
          base_model: String(imported?.base_model ?? ''),
        }
        previewConfigs.value = { ...previewConfigs.value, [name]: imported ?? {
          mode, base_type: baseType, at_sub_mode: createGoal.value, model_choice: createChoice.value,
          training_kind: createGoal.value === 'slider' ? 'slider' : 'standard',
          params: mode.endsWith('_fz') ? { fizgig_version: 'v7.0.1' } : {},
        } }
        data.value!.projects = [project, ...projects.value]
        appendLog(imported
          ? `[项目] 已在预览中创建「${name}」，并载入 ${importedConfigLabel.value || '导入配置'}。`
          : `[项目] 已在预览中创建「${name}」（模板：${templateName.value}）。`)
        await openProject(project)
      }
    } else if (dialogKind.value === 'rename' && editingProject.value) {
      const result = await window.pywebview.api.rename_project(editingProject.value.name, name)
      if (!result.ok) {
        formError.value = result.error ?? '项目重命名失败。'
        return
      }
      data.value!.projects = await window.pywebview.api.list_projects()
      appendLog(result.log ?? `[项目] 已重命名为「${name}」`)
    } else {
      const result = await window.pywebview.api.create_project(
        name,
        templateName.value,
        importedConfigJson.value || undefined,
        importedConfigJson.value ? undefined : modeOverrideForSelectedTemplate(),
        importedConfigJson.value ? undefined : createChoice.value,
        createGoal.value,
      )
      if (!result.ok) {
        formError.value = result.error ?? '项目创建失败。'
        return
      }
      data.value!.projects = await window.pywebview.api.list_projects()
      appendLog(importedConfigJson.value
        ? `[项目] 已新建项目「${name}」并导入配置。`
        : `[项目] 已新建项目「${name}」（模板：${templateName.value}）`)
      const project = data.value!.projects.find((item) => item.name === name)
      if (project && isModernProject(project)) await openProject(project)
      else showToast('项目已创建，但该训练模式暂未接入新版训练页。')
    }
    dialogOpen.value = false
    showToast(dialogKind.value === 'create' ? `「${name}」已创建` : `项目已改名为「${name}」`)
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '项目操作失败。'
  } finally {
    busy.value = false
  }
}

async function openProject(project: ProjectCard) {
  if (preview.value || !window.pywebview?.api) {
    projectModeFilter.value = null
    workspaceProject.value = project
    workspaceConfig.value = previewConfigs.value[project.name] ?? null
    qwenModelSetup.value = null
    modeWorkspace.value = null
    workspaceOpen.value = true
    if (project.training_kind === 'slider' || workspaceConfig.value?.training_kind === 'slider') {
      workspaceKind.value = 'slider'
      selectedMode.value = project.mode
      modeWorkspace.value = demoModeWorkspace(project.mode)
    } else if (isQwenProject(project)) {
      workspaceKind.value = 'qwen'
      selectedMode.value = project.mode
      modeWorkspace.value = demoModeWorkspace(project.mode)
      appendLog(`[预览] 已打开「${project.name}」的 ${project.mode === 'zimage' ? 'Z-Image' : 'Qwen-Image'} 工作区预览；设置只保留在本次预览会话。`)
    } else if (isKohyaProject(project)) {
      workspaceKind.value = 'kohya'
      selectedMode.value = firstEngineSidebarModeForBaseType(project.base_type)
      modeWorkspace.value = demoModeWorkspace(project.mode)
      appendLog(`[预览] 已打开「${project.name}」的 Kohya LoRA 工作区视觉预览；设置只保留在本次预览会话。`)
    } else {
      workspaceKind.value = 'engine'
      selectedMode.value = project.mode
      modeWorkspace.value = demoModeWorkspace(project.mode)
      appendLog(`[预览] 已打开「${project.name}」的 ${modeWorkspace.value.label} 工作区预览；设置只保留在本次预览会话。`)
    }
    return
  }
  if (!window.pywebview?.api) {
    showToast('桌面工作区接口尚未就绪。')
    return
  }
  workspaceOpen.value = false
  try {
    const loaded = await window.pywebview.api.load_project_config(project.name)
    if (!loaded.ok || !loaded.config) {
      showToast(loaded.error ?? '读取项目配置失败。')
      return
    }
    let nextKind: 'qwen' | 'kohya' | 'engine' | 'slider'
    let nextDetails: ModeWorkspaceData | null = null
    let nextModelSetup: QwenModelSetup | null = null
    if (isQwenProject(project)) {
      const [modelSetup, details] = await Promise.all([
        window.pywebview.api.get_qwen_model_setup(project.mode === 'zimage' ? 'zimage' : 'qwen_image'),
        window.pywebview.api.get_mode_workspace(project.mode, project.name),
      ])
      if (!modelSetup.ok) {
        showToast(modelSetup.error ?? '读取 AI Toolkit 模型设置失败。')
        return
      }
      if (!details.ok) {
        showToast(details.error ?? '读取训练模式信息失败。')
        return
      }
      nextKind = 'qwen'
      nextModelSetup = modelSetup
      nextDetails = details
    } else {
      const details = await window.pywebview.api.get_mode_workspace(project.mode, project.name)
      if (!details.ok) {
        showToast(details.error ?? '读取训练模式信息失败。')
        return
      }
      nextKind = loaded.config.training_kind === 'slider' ? 'slider' : isKohyaProject(project) ? 'kohya' : 'engine'
      nextDetails = details
    }
    workspaceProject.value = project
    workspaceConfig.value = loaded.config
    modeWorkspace.value = nextDetails
    qwenModelSetup.value = nextModelSetup
    workspaceKind.value = nextKind
    selectedMode.value = isKohyaProject(project) ? firstEngineSidebarModeForBaseType(project.base_type) : project.mode
    projectModeFilter.value = null
    workspaceOpen.value = true
    appendLog(nextKind === 'qwen'
      ? `[项目] 已在新版训练页打开「${project.name}」的 ${project.mode === 'zimage' ? 'Z-Image' : 'Qwen-Image'} 设置。`
      : nextKind === 'kohya'
        ? `[项目] 已在新版训练页打开「${project.name}」。`
        : `[项目] 已在新版训练页打开「${project.name}」的 ${nextDetails?.label} 模式。`)
  } catch (error) {
    showToast(error instanceof Error ? `读取项目失败：${error.message}` : '读取项目失败。')
  }
}

function assistantCanUseProject() {
  return !activeWorkspaceRef.value?.hasUnsavedChanges?.()
}
async function refreshAssistantProject(name: string) {
  if (!name || !window.pywebview?.api) return
  if (data.value) data.value.projects = await window.pywebview.api.list_projects()
  const project = projects.value.find(item => item.name === name)
  if (!project || !workspaceOpen.value || workspaceProject.value?.name !== name || !assistantCanUseProject()) return
  const [loaded, details, modelSetup] = await Promise.all([window.pywebview.api.load_project_config(name), window.pywebview.api.get_mode_workspace(project.mode, name), isQwenProject(project) ? window.pywebview.api.get_qwen_model_setup(project.mode === 'zimage' ? 'zimage' : 'qwen_image') : Promise.resolve(null)])
  if (workspaceProject.value?.name !== name || !assistantCanUseProject()) return
  if (loaded.ok && loaded.config) { workspaceProject.value = project; workspaceConfig.value = loaded.config }
  if (details.ok) modeWorkspace.value = details
  if (modelSetup?.ok) qwenModelSetup.value = modelSetup
}
async function openAssistantProject(name: string) {
  if (!name) {
    if (!assistantCanUseProject()) return showToast('请先保存当前页面的修改，再返回新项目对话。')
    returnHome()
    return
  }
  if (!window.pywebview?.api) return
  if (data.value) data.value.projects = await window.pywebview.api.list_projects()
  const project = projects.value.find(item => item.name === name)
  if (project && isModernProject(project)) await openProject(project)
}
async function openAgentCreatedProject(name: string) {
  if (!name || workspaceOpen.value || !window.pywebview?.api) return
  if (data.value) data.value.projects = await window.pywebview.api.list_projects()
  const project = projects.value.find(item => item.name === name)
  if (project && isModernProject(project) && !workspaceOpen.value) await openProject(project)
}
async function openAgentTask(id: string, project = '', force = true) {
  const api = window.pywebview?.api
  if (!api || !id) return
  const task = await api.get_task_status(id, 0)
  if (!task.ok) { if (force) showToast(task.error || '任务记录已经不存在。'); return }
  if (!force && id === seenAgentTaskId) return
  seenAgentTaskId = id
  if (task.kind === 'training') {
    setupDialogOpen.value = false
    trainingProjectName.value = task.project_name || project
    trainingPlan.value = task.plan || null
    trainingDialogOpen.value = true
    await nextTick()
    await trainingDialogRef.value?.attach(id)
  } else {
    agentTaskTitle.value = task.title || '助手执行任务'
    setupAction.value = task.kind === 'preprocess' ? 'preprocess' : 'agent_task'
    setupDialogOpen.value = true
    await nextTick()
    await setupDialogRef.value?.attach(id)
  }
}
let agentOwnerTimer: ReturnType<typeof setTimeout> | undefined
let agentOwnerDisposed = false
let pollingAgentOwner = false
async function pollAgentOwnership() {
  if (agentOwnerDisposed || pollingAgentOwner || preview.value || !window.pywebview?.api) return
  pollingAgentOwner = true
  agentOwnerTimer = undefined
  try {
    const value = await window.pywebview.api.get_agent_state()
    const run = value.run
    const active = Boolean(value.active_project) || ['running', 'waiting_user', 'waiting_task'].includes(run?.status || '')
    agentBusy.value = active
    if (run?.task_id && (active || run.task_active) && run.task_id !== seenAgentTaskId) await openAgentTask(run.task_id, run.project, false)
    if ((active || run?.task_active) && !agentOwnerDisposed && !agentOwnerTimer) agentOwnerTimer = setTimeout(pollAgentOwnership, 1500)
  } catch {
    // Retain ownership until the backend state is known; closing a panel must not unlock an active run.
    if (agentBusy.value && !agentOwnerDisposed) agentOwnerTimer = setTimeout(pollAgentOwnership, 3000)
  } finally { pollingAgentOwner = false }
}
watch(agentBusy, (active) => {
  if (active && !agentOwnerTimer && !agentOwnerDisposed) agentOwnerTimer = setTimeout(pollAgentOwnership, 1500)
})

async function saveKohyaConfig(patch: ProjectConfig) {
  if (!workspaceProject.value) return false
  if (preview.value || !window.pywebview?.api) {
    const name = workspaceProject.value.name
    const current = previewConfigs.value[name] ?? workspaceConfig.value ?? {}
    const next: ProjectConfig = {
      ...current,
      ...patch,
      params: { ...(current.params ?? {}), ...(patch.params ?? {}) },
    }
    previewConfigs.value = { ...previewConfigs.value, [name]: next }
    workspaceConfig.value = next
    const updatedProject: ProjectCard = {
      ...workspaceProject.value,
      mode: String(next.mode || workspaceProject.value.mode),
      base_type: String(next.base_type || workspaceProject.value.base_type),
      updated: new Date().toISOString().replace('T', ' ').slice(0, 19),
    }
    const updatedModeLabel = ({ character: '人物 LoRA', style: '画风 LoRA', concept: '概念 LoRA' } as Record<string, string>)[updatedProject.mode]
    if (updatedModeLabel) updatedProject.mode_label = updatedModeLabel
    if (firstEngineBaseTypes.includes(updatedProject.base_type as FirstEngineBaseType)) {
      updatedProject.base_type_label = firstEngineBaseLabels[updatedProject.base_type as FirstEngineBaseType]
    }
    workspaceProject.value = updatedProject
    if (isKohyaProject(updatedProject)) selectedMode.value = firstEngineSidebarModeForBaseType(updatedProject.base_type)
    data.value!.projects = projects.value.map((project) => project.name === name
      ? updatedProject
      : project)
    appendLog(`[预览] 已暂存「${name}」的设置；仅当前浏览器会话有效。`)
    showToast('预览设置已暂存；刷新页面后会清空')
    return true
  }
  try {
    const result = await window.pywebview.api.save_project_config(workspaceProject.value.name, patch)
    if (!result.ok) {
      showToast(result.error ?? '保存项目配置失败。')
      return false
    }
    const loaded = await window.pywebview.api.load_project_config(workspaceProject.value.name)
    if (loaded.ok && loaded.config) workspaceConfig.value = loaded.config
    data.value!.projects = await window.pywebview.api.list_projects()
    await refreshGuideState()
    appendLog(`[项目] 已保存「${workspaceProject.value.name}」的配置。`)
    showToast('项目配置已保存')
    return true
  } catch (error) {
    showToast(error instanceof Error ? `保存项目配置失败：${error.message}` : '保存项目配置失败。')
    return false
  }
}

async function saveQwenModel(selection: QwenModelSelection): Promise<QwenModelSaveResult> {
  if (!window.pywebview?.api) return { ok: false, error: '本机模型设置接口不可用。' }
  try {
    const result = await window.pywebview.api.save_qwen_model_setup(selection)
    if (!result.ok) {
      showToast(result.error ?? '保存 Qwen-Image 模型设置失败。')
      return { ok: false, error: result.error }
    }
    qwenModelSetup.value = result
    await refreshGuideState()
    appendLog('[模型] 已保存 Qwen-Image 模型设置。')
    showToast('Qwen-Image 模型设置已保存')
    return { ok: true, setup: result }
  } catch (error) {
    const message = error instanceof Error ? error.message : '保存 Qwen-Image 模型设置失败。'
    showToast(message)
    return { ok: false, error: message }
  }
}

async function startModernTraining(patch: ProjectConfig) {
  if (trainingActive.value) {
    trainingDialogRef.value?.expand()
    return showToast('当前已有训练任务；已返回训练进度。')
  }
  if (trainingDialogOpen.value) {
    trainingDialogOpen.value = false
    await nextTick()
  }
  const project = workspaceProject.value
  const api = window.pywebview?.api
  if (!project) return showToast('请先打开一个项目。')
  if (preview.value || !api) return showToast('训练需要在新版训练页的 Windows 桌面版中运行；浏览器预览不会启动本机训练。')
  if (Object.keys(patch).length && !(await saveKohyaConfig(patch))) return
  try {
    const result = await api.prepare_training(project.name)
    if (!result.ok || !result.plan) {
      appendLog(`[训练预检] ${result.error ?? '检查未通过。'}`)
      showToast(result.error ?? '训练前检查未通过。')
      return
    }
    trainingProjectName.value = project.name
    trainingPlan.value = result.plan
    trainingDialogOpen.value = true
  } catch (error) {
    const message = error instanceof Error ? error.message : '训练前检查失败。'
    appendLog(`[训练预检] ${message}`)
    showToast(message)
  }
}

async function chooseWorkspacePath(kind: 'folder' | 'model', currentPath = '', memoryKey = ''): Promise<string | null> {
  if (!window.pywebview?.api || preview.value) return null
  try {
    const result = await window.pywebview.api.choose_path(kind, currentPath, memoryKey)
    if (!result.ok) showToast(result.error ?? '选择路径失败。')
    return result.path || null
  } catch (error) {
    showToast(error instanceof Error ? error.message : '选择路径失败。')
    return null
  }
}

async function restoredTrainingSettings() {
  const name = workspaceProject.value?.name
  if (name && window.pywebview?.api) {
    const result = await window.pywebview.api.load_project_config(name)
    if (result.ok && result.config) workspaceConfig.value = result.config
    await refreshGuideState()
  }
}

async function refreshGuideState() {
  if (preview.value || !window.pywebview?.api) return
  const mode = workspaceProject.value?.mode || selectedGuideMode.value
  const projectName = workspaceProject.value?.name || ''
  try {
    const [details, latestProjects, catalog] = await Promise.all([
      window.pywebview.api.get_mode_workspace(mode, projectName),
      window.pywebview.api.list_projects(),
      window.pywebview.api.get_model_catalog(),
    ])
    data.value!.model_catalog = catalog
    if (details.ok && (!workspaceOpen.value || workspaceProject.value?.mode === mode)) modeWorkspace.value = details
    data.value!.projects = latestProjects
    if (workspaceProject.value) {
      workspaceProject.value = latestProjects.find((item) => item.name === workspaceProject.value?.name) ?? workspaceProject.value
      if (isKohyaProject(workspaceProject.value)) selectedMode.value = firstEngineSidebarModeForBaseType(workspaceProject.value.base_type)
    }
  } catch (error) {
    appendLog(`[引导] 刷新步骤状态失败：${error instanceof Error ? error.message : String(error)}`)
  }
}

async function refreshHomeGuide(mode = selectedGuideMode.value) {
  if (workspaceOpen.value) return
  if (preview.value || !window.pywebview?.api) {
    modeWorkspace.value = demoModeWorkspace(mode)
    return
  }
  try {
    const details = await window.pywebview.api.get_mode_workspace(mode)
    if (details.ok && !workspaceOpen.value) modeWorkspace.value = details
  } catch (error) {
    appendLog(`[引导] 读取模式步骤失败：${error instanceof Error ? error.message : String(error)}`)
  }
}

async function onGuideAction(step: GuideStep) {
  const action = step.action
  const mode = workspaceProject.value?.mode || selectedGuideMode.value
  if (action === 'cmd_env' || action === 'cmd_install' || action === 'cmd_install_musubi' || action === 'cmd_install_at' || action === 'cmd_install_fizgig') {
    setupAction.value = action
    agentTaskTitle.value = ''
    setupDialogOpen.value = true
    return
  }
  if (action === 'cmd_dl_krea2_models' || action === 'cmd_dl_flux2_models' || action === 'cmd_dl_h3_models' || action === 'cmd_dl_qwen21_fz_models' || action === 'cmd_dl_h3_fz_models' || action === 'cmd_dl_anima_fz_models' || action === 'cmd_dl_sdxl_fz_models') {
    modelDialogOpen.value = true
    return
  }
  if (action === 'cmd_at_model_help') {
    openHelp('mode', mode)
    return
  }
  if (action === 'cmd_pick_raw' || action === 'cmd_pick_model_type') {
    if (!workspaceProject.value) {
      const selectedBaseType = firstEngineBaseTypeForSidebarMode(selectedMode.value)
      const targetMode = selectedBaseType ? selectedMode.value : mode
      const existing = projects.value.some((project) => projectMatchesSidebarMode(project, targetMode))
      if (existing) {
        projectModeFilter.value = targetMode
        showToast('请先从项目列表明确选择要设置的项目。')
      } else {
        openCreate(selectedBaseType
          ? templateForBaseType(selectedBaseType)
          : firstEngineModes.includes(mode as FirstEngineMode) ? undefined : templateForMode(mode),
        selectedBaseType ? undefined : firstEngineModes.includes(mode as FirstEngineMode) ? mode as FirstEngineMode : undefined)
        showToast('先创建并打开项目，再设置底模或数据集文件夹。')
      }
      return
    }
    const patch = await activeWorkspaceRef.value?.guideAction?.(action)
    if (patch && Object.keys(patch).length) await saveKohyaConfig(patch)
    return
  }
  showToast(step.tip || '该引导步骤暂未接入新版训练页。')
}

function openHelp(kind: 'readme' | 'mode', mode = workspaceProject.value?.mode || selectedGuideMode.value) {
  helpDialogKind.value = kind
  helpDialogMode.value = mode === '_kohya' ? (workspaceProject.value?.mode || 'character') : mode
  helpDialogOpen.value = true
}

async function removeProject(project: ProjectCard) {
  if (!window.confirm(`确定删除项目「${project.name}」吗？\n项目配置将被删除；图集数据和 output 中的训练产物会保留。`)) return
  if (preview.value || !window.pywebview?.api) {
    data.value!.projects = projects.value.filter((item) => item.name !== project.name)
    const nextConfigs = { ...previewConfigs.value }
    delete nextConfigs[project.name]
    previewConfigs.value = nextConfigs
    appendLog(`[项目] 已从预览列表移除「${project.name}」（仅当前页面有效）`)
    return
  }
  const result = await window.pywebview.api.delete_project(project.name)
  if (!result.ok) {
    showToast(result.error ?? '删除项目失败。')
    return
  }
  data.value!.projects = await window.pywebview.api.list_projects()
  appendLog(result.log ?? `[项目] 已删除项目「${project.name}」；数据集和训练产物保留。`)
  showToast(`已删除「${project.name}」的项目配置`)
}

async function exportLog(action = 'export_log', projectName?: string) {
  if (logExportBusy.value) { logExportOpen.value = true; return }
  const api = window.pywebview?.api
  if (preview.value || !api) { showToast('请在桌面版导出日志；浏览器预览不会生成文件。'); return }
  logExportId.value = ''
  logExportError.value = ''
  logExportBusy.value = true
  logExportOpen.value = true
  try {
    const result = await api.run_action(action, projectName || workspaceProject.value?.name)
    if (!result.ok || !result.export_id) throw new Error(result.error || '无法开始日志导出，请重试。')
    logExportId.value = result.export_id
  } catch (error) {
    logExportError.value = error instanceof Error ? error.message : '无法开始日志导出，请重试。'
    logExportBusy.value = false
  }
}

function logExportCompleted(path: string) {
  appendLog(`[诊断] 运行日志已导出：${path}`)
  if (!logExportOpen.value) showToast(`运行日志已导出：${path}`)
}

async function runAction(action: string, projectName?: string) {
  if (action === 'prompt_reverse') { promptReverseOpen.value = true; return }
  if (action === 'export_log' || action === 'export_diagnostics') { await exportLog(action, projectName); return }
  if (action === 'train') {
    if (preview.value && workspaceOpen.value) {
      activeWorkspaceRef.value?.startTraining()
      return
    }
    if (workspaceOpen.value) {
      activeWorkspaceRef.value?.startTraining()
      return
    }
    if (visibleProjects.value.length) showToast('请先从项目列表明确选择要训练的项目。')
    else openCreateForSelectedMode()
    return
  }
  if (action === 'env_locations') {
    envDialogOpen.value = true
    return
  }
  if (preview.value || !window.pywebview?.api) {
    showToast('浏览器预览中，这个操作不会触碰本机数据。')
    return
  }
  const result = await window.pywebview.api.run_action(action, projectName || (['export_log', 'export_diagnostics'].includes(action) ? workspaceProject.value?.name : undefined))
  if (result.log) appendLog(result.log)
  if (!result.ok) showToast(result.error ?? '操作失败。')
  else if (result.message) showToast(result.message)
}

async function chooseAppearanceBackground(): Promise<string | null> {
  const api = window.pywebview?.api
  if (!api) {
    showToast('请选择 Windows 桌面版中的图片；浏览器预览不会访问本机文件。')
    return null
  }
  try {
    const result = await api.choose_path('image', appearance.value.background_source_path || '', 'appearance_background')
    if (!result.ok) showToast(result.error ?? '选择背景图片失败。')
    return result.ok && result.path ? result.path : null
  } catch (error) {
    showToast(error instanceof Error ? error.message : '选择背景图片失败。')
    return null
  }
}

async function getAppearanceImagePreview(path: string, thumbnail = false): Promise<string | null> {
  const api = window.pywebview?.api
  if (preview.value) return /^\/themes\/(dark|light)\.png$/.test(path) ? path : null
  if (!api) return null
  try {
    const result = await api.get_appearance_image_preview(path, thumbnail)
    if (!result.ok || !result.data_url) {
      if (!thumbnail) showToast(result.error ?? '无法读取这张图片，请重新选择。')
      return null
    }
    return result.data_url
  } catch (error) {
    if (!thumbnail) showToast(error instanceof Error ? error.message : '无法读取这张图片。')
    return null
  }
}

async function loadAppearancePresets() {
  const api = window.pywebview?.api
  if (preview.value) {
    const builtins: AppearancePreset[] = [
      { id: 'builtin-dark', name: '深色示例', built_in: true, theme: 'dark', background_path: '/themes/dark.png', background_opacity: 90, component_opacity: 80, idle_fade_enabled: true, available: true },
      { id: 'builtin-light', name: '浅色示例', built_in: true, theme: 'light', background_path: '/themes/light.png', background_opacity: 90, component_opacity: 80, idle_fade_enabled: true, available: true },
    ]
    appearancePresets.value = [
      ...builtins.filter((preset) => !hiddenBuiltinPresetIds.value.includes(preset.id)),
      ...appearancePresets.value.filter((preset) => !preset.built_in),
    ]
    return
  }
  if (!api) return
  try {
    const result = await api.get_appearance_presets()
    if (result?.ok && result.presets) {
      appearancePresets.value = result.presets
      hiddenBuiltinPresetIds.value = result.hidden_builtin_ids ?? []
    }
  } catch (error) {
    appendLog(`[外观] 无法读取主题方案：${error instanceof Error ? error.message : '未知错误'}`)
  }
}

function openAppearanceDialog() {
  appearanceDialogOpen.value = true
  void loadAppearancePresets()
}

async function deleteAppearancePreset(id: string) {
  if (preview.value || !window.pywebview?.api) {
    appearancePresets.value = appearancePresets.value.filter((preset) => preset.id !== id)
    if (id.startsWith('builtin-')) hiddenBuiltinPresetIds.value = [...hiddenBuiltinPresetIds.value, id]
    return
  }
  try {
    const result = await window.pywebview.api.delete_appearance_preset(id)
    if (!result?.ok) return showToast(result?.error ?? '删除主题失败。')
    appearancePresets.value = result.presets ?? []
    hiddenBuiltinPresetIds.value = result.hidden_builtin_ids ?? []
  } catch (error) {
    showToast(error instanceof Error ? error.message : '删除主题失败。')
  }
}

async function restoreAppearanceBuiltinPresets() {
  if (preview.value || !window.pywebview?.api) {
    hiddenBuiltinPresetIds.value = []
    await loadAppearancePresets()
    return
  }
  try {
    const result = await window.pywebview.api.restore_appearance_builtin_presets()
    if (!result?.ok) return showToast(result?.error ?? '恢复内置主题失败。')
    appearancePresets.value = result.presets ?? []
    hiddenBuiltinPresetIds.value = result.hidden_builtin_ids ?? []
  } catch (error) {
    showToast(error instanceof Error ? error.message : '恢复内置主题失败。')
  }
}

async function saveAppearance(next: AppearanceSettings, presetName = '') {
  if (appearanceSaving.value) return
  appearanceSaving.value = true
  try {
    if (preview.value || !window.pywebview?.api) {
      appearance.value = { ...next }
      if (presetName) appearancePresets.value = [...appearancePresets.value, {
        id: `preview-${Date.now()}`, name: presetName, built_in: false, theme: next.theme,
        background_path: next.background_path, background_source_path: next.background_source_path,
        background_opacity: next.background_opacity, component_opacity: next.component_opacity,
        idle_fade_enabled: next.idle_fade_enabled, available: true,
      }]
      appearanceImage.value = /^\/themes\/(dark|light)\.png$/.test(next.background_path) ? next.background_path : ''
      appearanceDialogOpen.value = false
      scheduleUiIdleFade()
      showToast('预览设置已应用；桌面版会保存背景图片。')
      return
    }
    const saved = await window.pywebview.api.set_appearance_settings(
      next.theme,
      next.background_path,
      next.background_opacity,
      next.component_opacity,
      next.idle_fade_enabled,
      next.background_history.map((entry) => entry.path),
      next.background_source_path || next.background_path,
      next.background_data_url ?? '',
    )
    if (!saved.ok) {
      showToast(saved.error ?? '外观设置保存失败。')
      return
    }
    appearance.value = saved.settings ?? next
    if (presetName) {
      const presetResult = await window.pywebview.api.save_appearance_preset(presetName)
      if (!presetResult?.ok) {
        showToast(presetResult?.error ?? '当前外观已保存，但主题方案保存失败。')
        return
      }
      appearancePresets.value = presetResult.presets ?? []
    }
    scheduleUiIdleFade()
    appearanceImage.value = ''
    if (appearance.value.background_path) {
      const image = await window.pywebview.api.get_appearance_background()
      if (image.ok && image.data_url) appearanceImage.value = image.data_url
      else showToast(image.error ?? '背景图片无法读取，已保存主题设置。')
    }
    appearanceDialogOpen.value = false
    appendLog('[外观] 已保存新版训练页显示设置。')
    if (!appearance.value.background_path) showToast('外观设置已保存。')
  } catch (error) {
    showToast(error instanceof Error ? error.message : '外观设置保存失败。')
  } finally {
    appearanceSaving.value = false
  }
}

async function loadAppearanceSettings() {
  const api = window.pywebview?.api
  if (!api) return
  try {
    const loaded = await api.get_appearance_settings()
    if (!loaded.ok || !loaded.settings) return
    appearance.value = loaded.settings
    if (appearance.value.background_path) {
      const image = await api.get_appearance_background()
      if (image.ok && image.data_url) appearanceImage.value = image.data_url
      else appendLog(`[外观] 背景图片不可用：${image.error ?? '文件无法读取。'}`)
    }
  } catch (error) {
    appendLog(`[外观] 无法读取显示设置：${error instanceof Error ? error.message : '未知错误'}`)
  }
}

async function runWorkspaceAction(action: string, patch?: ProjectConfig) {
  if (action === 'cmd_install_fizgig' || action === 'fizgig_engine_update' || action === 'fizgig_engine_rollback') {
    if (patch && Object.keys(patch).length && (await saveKohyaConfig(patch)) === false) return
    setupAction.value = action
    agentTaskTitle.value = ''
    setupDialogOpen.value = true
    return
  }
  if (action === 'cmd_dl_anima_fz_models' || action === 'cmd_dl_sdxl_fz_models') { modelDialogOpen.value=true; return }
  if (action === 'training_history') { historyDialogOpen.value = true; return }
  if (!workspaceProject.value) return showToast('请先打开一个项目。')
  if (patch && Object.keys(patch).length && (await saveKohyaConfig(patch)) === false) return
  if (action === 'preprocess') {
    if (preview.value || !window.pywebview?.api) return showToast('浏览器预览中，这个操作不会触碰本机数据。')
    setupAction.value = 'preprocess'
    agentTaskTitle.value = ''
    setupDialogOpen.value = true
    return
  }
  if (action === 'output_dir') return runAction(action, workspaceProject.value.name)
  if (action === 'readme') return openHelp('readme', workspaceProject.value.mode)
  if (action === 'at_model_help' || action === 'krea2_guide' || action === 'flux2_guide' || action === 'h3_guide') {
    return openHelp('mode', workspaceProject.value.mode)
  }
  if (preview.value || !window.pywebview?.api) {
    showToast('浏览器预览中，这个操作不会触碰本机数据。')
    return
  }
  const result = await window.pywebview.api.run_action(action, workspaceProject.value.name)
  if (result.log) appendLog(result.log)
  if (!result.ok) showToast(result.error ?? '无法打开该功能。')
  else if (result.message) showToast(result.message)
}

function chooseMode(mode: string) {
  selectedMode.value = mode
  if (workspaceOpen.value && workspaceProject.value
      && projectMatchesSidebarMode(workspaceProject.value, mode)) return
  workspaceOpen.value = false
  workspaceProject.value = null
  workspaceConfig.value = null
  qwenModelSetup.value = null
  modeWorkspace.value = null
  projectModeFilter.value = mode
  const targetMode = mode.startsWith("model:") ? preferredModeForModel(mode.slice(6)) : mode === '_kohya' ? selectedGuideMode.value : mode
  void refreshHomeGuide(targetMode)
  if (visibleProjects.value.length) showToast('请选择要打开的项目；选择模型不会改变已有项目的引擎。')
  else openCreateForSelectedMode()
}

function returnHome() {
  projectModeFilter.value = null
  workspaceOpen.value = false
  workspaceProject.value = null
  workspaceConfig.value = null
  qwenModelSetup.value = null
  modeWorkspace.value = null
  void refreshHomeGuide()
}

async function returnWorkspace(patch?: ProjectConfig) {
  const keys = Object.keys(patch ?? {})
  const hasChanges = keys.some((key) => key !== 'mode') || (
    keys.includes('mode') && patch?.mode !== workspaceProject.value?.mode
  )
  if (hasChanges && patch && !(await saveKohyaConfig(patch))) return
  returnHome()
}

function onKeydown(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's' && workspaceOpen.value) {
    event.preventDefault()
    activeWorkspaceRef.value?.save?.()
    return
  }
  registerUiActivity()
  if (event.key === 'Escape' && appearanceDialogOpen.value) {
    appearanceDialogOpen.value = false
    return
  }
  if (event.key === 'Escape' && dialogOpen.value) dialogOpen.value = false
}

function reloadStartup() { window.location.reload() }

async function startupRecovery(action: 'open_ui_startup_report' | 'use_classic_ui') {
  const api = window.pywebview?.api
  if (!api?.[action]) {
    loadError.value = '本机连接不可用，请退出软件后通过经典界面入口启动。启动诊断保存在数据目录的 logs 文件夹。'
    return
  }
  try {
    const result = await api[action]()
    if (!result.ok) loadError.value = result.error || '操作未完成。'
  } catch {
    loadError.value = '本机连接未响应，请先退出软件，再从经典界面入口启动。'
  }
}

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('pointermove', registerUiActivity, { passive: true })
  window.addEventListener('pointerdown', registerUiActivity, { passive: true })
  window.addEventListener('wheel', registerUiActivity, { passive: true })
  window.addEventListener('focusin', registerUiActivity)
  systemThemeQuery = window.matchMedia('(prefers-color-scheme: light)')
  systemPrefersLight.value = systemThemeQuery.matches
  systemThemeQuery.addEventListener('change', updateSystemTheme)
  try {
    const loaded = await loadBootstrap()
    data.value = loaded.data
    preview.value = loaded.preview
    const firstEngineProject = projects.value.find(isKohyaProject)
    selectedMode.value = firstEngineProject
      ? firstEngineSidebarModeForBaseType(firstEngineProject.base_type)
      : firstEngineSidebarModes.sdxl
    logs.value = [...loaded.data.logs]
    if (!loaded.preview) { await loadAppearanceSettings(); void pollAgentOwnership() }
    scheduleUiIdleFade()
    if (loaded.preview) modeWorkspace.value = demoModeWorkspace('character')
    else await refreshHomeGuide(firstEngineProject?.mode || 'character')
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '无法连接桌面程序。'
    window.__kohyaStartup?.report('page_error', loadError.value)
  } finally {
    loading.value = false
  }
})

watch(dialogOpen, (isOpen) => {
  if (isOpen) {
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    nextTick(() => nameInput.value?.focus())
  } else {
    nextTick(() => previousFocus?.focus())
  }
})

onUnmounted(() => {
  agentOwnerDisposed = true
  if (agentOwnerTimer) clearTimeout(agentOwnerTimer)
  if (uiIdleFadeTimer !== undefined) window.clearTimeout(uiIdleFadeTimer)
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('pointermove', registerUiActivity)
  window.removeEventListener('pointerdown', registerUiActivity)
  window.removeEventListener('wheel', registerUiActivity)
  window.removeEventListener('focusin', registerUiActivity)
  systemThemeQuery?.removeEventListener('change', updateSystemTheme)
})

watch(() => appearance.value.idle_fade_enabled, scheduleUiIdleFade)
</script>

<template>
  <div
    class="app-shell"
    :data-theme="activeTheme"
    :data-wallpaper="appearanceImage ? 'true' : 'false'"
    :data-ui-idle="uiIdle ? 'true' : 'false'"
    @pointerenter="registerUiActivity"
    :style="appShellStyle"
  >
    <TrainingAssistant v-if="assistantOpen" :desktop="!preview" :project-name="workspaceOpen ? workspaceProject?.name || '' : ''" :can-use-project="assistantCanUseProject" @close="assistantOpen = false" @changed="refreshAssistantProject" @created-project="openAgentCreatedProject" @open-project="openAssistantProject" @open-task="(id) => openAgentTask(id)" @active="agentBusy = $event" />
    <EngineSidebar
      :groups="sidebarGroups"
      :selected-mode="selectedNavModel"
      :train-label="trainActionLabel"
      :status-text="projects.length ? '✓ 选择项目后进入新版训练页' : '新建项目后开始配置训练'"
      :workspace-active="workspaceOpen"
      :assistant-open="assistantOpen"
      :assistant-busy="agentBusy"
      :guide-label="guideLabel"
      :guide-steps="guideSteps"
      @toggle-assistant="assistantOpen = !assistantOpen"
      @choose-mode="chooseMode"
      @action="runAction"
      @guide-action="onGuideAction"
    />

    <main class="right-shell" :aria-busy="agentBusy">
      <div class="right-content">
      <Transition name="view" mode="out-in">
      <SliderWorkspace
        v-if="!loading && !loadError && workspaceOpen && workspaceProject && workspaceKind === 'slider'"
        :key="`slider-workspace-${workspaceProject.name}`" :project="workspaceProject" :config="workspaceConfig"
        :details="modeWorkspace" :desktop="!preview" :choose-path="chooseWorkspacePath" :ref="setActiveWorkspace"
        @back="returnWorkspace" @notify="showToast" @save="saveKohyaConfig" @train="startModernTraining" @classic-action="runWorkspaceAction"
      />
      <ModernQwenWorkspace
        v-else-if="!loading && !loadError && workspaceOpen && workspaceProject && workspaceKind === 'qwen'"
        :key="`workspace-${workspaceProject.name}`"
        :project="workspaceProject"
        :mode="workspaceProject.mode === 'zimage' ? 'zimage' : 'qwen_image'"
        :config="workspaceConfig"
        :desktop="!preview"
        :model-setup="qwenModelSetup"
        :details="modeWorkspace"
        :choose-path="chooseWorkspacePath"
        :save-model="saveQwenModel"
        :ref="setActiveWorkspace"
        @back="returnWorkspace"
        @notify="showToast"
        @save="saveKohyaConfig"
        @train="startModernTraining"
        @classic-action="runWorkspaceAction"
      />
      <ModernKohyaWorkspace
        v-else-if="!loading && !loadError && workspaceOpen && workspaceProject && workspaceKind === 'kohya'"
        :key="`kohya-workspace-${workspaceProject.name}`"
        :project="workspaceProject"
        :config="workspaceConfig"
        :details="modeWorkspace"
        :ref="setActiveWorkspace"
        :desktop="!preview"
        :choose-path="chooseWorkspacePath"
        @back="returnWorkspace"
        @notify="showToast"
        @save="saveKohyaConfig"
        @train="startModernTraining"
        @classic-action="runWorkspaceAction"
      />
      <ModernEngineWorkspace
        v-else-if="!loading && !loadError && workspaceOpen && workspaceProject && workspaceKind === 'engine' && modeWorkspace"
        :key="`engine-workspace-${workspaceProject.name}-${workspaceProject.mode}`"
        :project="workspaceProject"
        :mode="workspaceProject.mode"
        :config="workspaceConfig"
        :details="modeWorkspace"
        :ref="setActiveWorkspace"
        :desktop="!preview"
        :choose-path="chooseWorkspacePath"
        @back="returnWorkspace"
        @notify="showToast"
        @save="saveKohyaConfig"
        @train="startModernTraining"
        @classic-action="runWorkspaceAction"
      />
      <div v-else-if="!loading && !loadError" key="home" class="home-view">
        <header class="project-toolbar">
          <h1>
            <UiIcon name="home" /> 我的项目
            <small
              class="app-version"
              v-if="data?.version"
              :title="preview ? '浏览器界面预览' : '当前应用版本'"
            >{{ preview ? data.version : `版本 ${data.version}` }}</small>
          </h1>
          <div class="toolbar-actions">
            <button v-for="action in topActions" :key="action.key" class="toolbar-button" type="button" :title="action.tip" @click="runAction(action.key)">
              <UiIcon :name="action.icon" />{{ action.label }}
            </button>
            <button class="toolbar-button" type="button" @click="historyDialogOpen = true">训练记录</button>
            <button class="toolbar-button appearance-button" type="button" title="新版训练页外观设置" aria-label="新版训练页外观设置" @click="openAppearanceDialog"><UiIcon name="settings" /></button>
            <button class="toolbar-button new-project" type="button" title="创建新的训练项目；可以从模式模板开始，也可以新建自定义项目。" @click="openCreateForSelectedMode()"><UiIcon name="plus" /> 新建项目</button>
          </div>
        </header>
        <div class="project-hint">
          {{ projectModeFilter ? `请选择 ${projectModeFilterLabel} 的项目；选择模型不会自动打开其他项目。` : '每个项目保存一套完整的训练配置（模式 / 底模 / 数据集 / 触发词 / 全部参数），下次直接打开续用。' }}
          <button v-if="projectModeFilter" class="small-button" type="button" @click="projectModeFilter = null">显示全部项目</button>
        </div>
        <section class="project-list" aria-label="项目列表">
          <TransitionGroup v-if="visibleProjects.length" name="project-list">
            <ProjectRow
              v-for="project in visibleProjects"
              :key="project.name"
              :project="project"
              @open="openProject"
              @rename="openRename"
              @remove="removeProject"
            />
          </TransitionGroup>
          <div v-else-if="projectModeFilter" class="empty-projects">
            <strong>这个模型还没有项目</strong>
            <span>新建项目后再选择图片和标签。</span>
            <button class="small-button primary" type="button" @click="openCreateForSelectedMode()">新建项目</button>
          </div>
          <div v-else class="empty-projects">
            <strong>还没有项目</strong>
            <span>点右上角「新建项目」开始，训练配置会保存在本机。</span>
            <button class="small-button primary" type="button" @click="openCreateForSelectedMode()">新建项目</button>
          </div>
        </section>
      </div>
      <div v-else-if="loading" key="loading" class="loading-state"><span class="loader"></span>正在连接本机工作区…</div>
      <div v-else key="error" class="error-state">
        <strong>无法连接桌面工作区</strong><span>{{ loadError }}</span>
        <div class="startup-recovery-actions">
          <button class="small-button" type="button" @click="reloadStartup">重新加载页面</button>
          <button class="small-button" type="button" @click="startupRecovery('open_ui_startup_report')">打开启动诊断</button>
          <button class="small-button" type="button" @click="startupRecovery('use_classic_ui')">改用经典界面</button>
        </div>
      </div>
      </Transition>
      </div>
      <LogDock v-if="!loading && !loadError" :entries="logs" :exporting="logExportBusy" @export="runAction('export_log')" />
      <span v-if="preview && !workspaceOpen" class="preview-pill">界面预览 · 不写入项目 / 不启动训练</span>
    </main>

    <ModernTaskDialog
      ref="setupDialogRef"
      :open="setupDialogOpen"
      :title="agentTaskTitle || (setupAction === 'preprocess' ? '数据预处理' : setupAction === 'cmd_env' ? '环境准备（Git / Python）' : setupAction === 'cmd_install' ? '安装 Kohya 训练内核' : setupAction === 'cmd_install_musubi' ? '安装第二引擎 · musubi' : setupAction === 'cmd_install_at' ? '安装第三引擎 · AI Toolkit' : setupAction === 'fizgig_engine_rollback' ? '回退 Fizgig 活动版本' : setupAction === 'fizgig_engine_update' ? '更新 Fizgig v7.0.1' : '安装 Fizgig v7.0.1')"
      :action="setupAction"
      :description="setupAction === 'agent_task' ? '助手已启动此任务；这里显示软件的实际执行进度与日志。' : setupAction === 'preprocess' ? '调用现有预处理器处理当前项目图集和标签；只预处理，不启动训练。' : setupAction === 'cmd_env' ? '检测并准备 Git 与兼容版本的 Python。此项通常只需要完成一次。' : '安装过程会复用现有训练内核安装逻辑；已安装的部分会检测并复用。'"
      :project-name="workspaceProject?.name ?? ''"
      @close="setupDialogOpen = false"
      @finished="refreshGuideState"
      @notify="showToast"
    />
    <LogExportDialog
      :open="logExportOpen"
      :export-id="logExportId"
      :start-error="logExportError"
      @close="logExportOpen = false"
      @pending="logExportBusy = $event"
      @completed="logExportCompleted"
      @notify="showToast"
      @retry="exportLog()"
    />
    <TrainingHistoryDialog :open="historyDialogOpen" :project-name="workspaceProject?.name || ''" @close="historyDialogOpen = false" @restored="restoredTrainingSettings" @notify="showToast" />
    <ModernTrainingDialog
      ref="trainingDialogRef"
      :open="trainingDialogOpen"
      :project-name="trainingProjectName"
      :plan="trainingPlan"
      @close="trainingDialogOpen = false"
      @active="trainingActive = $event"
      @finished="refreshGuideState"
      @notify="showToast"
    />
    <ModelDownloadDialog
      :open="modelDialogOpen"
      :mode="workspaceProject?.mode ?? selectedGuideMode"
      @close="modelDialogOpen = false"
      @changed="refreshGuideState"
      @notify="showToast"
    />
    <PromptReverseDialog :open="promptReverseOpen" :desktop="!preview" @close="promptReverseOpen = false" @notify="showToast" />
    <EnvironmentDialog
      :open="envDialogOpen"
      :choose-path="chooseWorkspacePath"
      @close="envDialogOpen = false"
      @changed="refreshGuideState"
      @notify="showToast"
    />
    <ModernHelpDialog
      :open="helpDialogOpen"
      :kind="helpDialogKind"
      :mode="helpDialogMode"
      :mode-label="modeWorkspace?.label || guideLabel || helpDialogMode"
      :steps="guideSteps"
      :details="modeWorkspace"
      @close="helpDialogOpen = false"
    />
    <AppearanceDialog
      :open="appearanceDialogOpen"
      :settings="appearance"
      :presets="appearancePresets"
      :hidden-builtin-count="hiddenBuiltinPresetIds.length"
      :desktop="!preview"
      :saving="appearanceSaving"
      :choose-background="chooseAppearanceBackground"
      :get-background-preview="getAppearanceImagePreview"
      @close="appearanceDialogOpen = false"
      @save="saveAppearance"
      @delete-preset="deleteAppearancePreset"
      @restore-builtin-presets="restoreAppearanceBuiltinPresets"
    />

    <Transition name="dialog">
      <div v-if="dialogOpen" class="dialog-backdrop" @dblclick.self="dialogOpen = false">
        <section class="project-dialog" role="dialog" aria-modal="true" :aria-labelledby="dialogKind === 'create' ? 'dialog-title-create' : 'dialog-title-rename'">
          <header class="dialog-header">
            <h2 :id="dialogKind === 'create' ? 'dialog-title-create' : 'dialog-title-rename'">{{ dialogKind === 'create' ? '新建项目' : '重命名项目' }}</h2>
            <button class="dialog-close" type="button" aria-label="关闭" @click="dialogOpen = false">×</button>
          </header>
          <template v-if="dialogKind === 'create'">
            <ModelTrainingChooser v-if="!importedConfigLabel" :catalog="catalog" :initial-model="createModel" :initial-goal="createGoal" @choose="onModelChoice" @valid="createChoiceAvailable = $event" />
            <p v-else class="template-note">保留导入配置中的模型、引擎版本和参数。</p>
            <div class="import-config-row">
              <input ref="importFileInput" class="import-config-input" type="file" accept=".json,application/json" @change="readImportConfig" />
              <div class="import-config-actions">
                <button class="small-button" type="button" title="从 Kohya-LoRA 导出的 JSON 文件导入模式、底模架构和训练参数。" @click="importFileInput?.click()">导入配置 JSON</button>
                <button v-if="importedConfigLabel" class="small-button" type="button" @click="clearImportedConfig">移除</button>
              </div>
              <span v-if="importedConfigLabel" class="imported-config-label">已选择：{{ importedConfigLabel }}</span>
              <small>导入的配置会覆盖上方模板；数据集路径不会带入。桌面版会写入项目，浏览器预览只保留在本次会话。</small>
            </div>
          </template>
          <label class="field-label" for="project-name">项目名称</label>
          <input id="project-name" ref="nameInput" v-model="projectName" class="dialog-input" maxlength="80" @keydown.enter="saveDialog" />
          <p v-if="formError" class="form-error">{{ formError }}</p>
          <footer class="dialog-actions">
            <button class="small-button" type="button" @click="dialogOpen = false">取消</button>
            <button class="small-button primary" type="button" :disabled="busy" @click="saveDialog">{{ busy ? '正在保存…' : dialogKind === 'create' ? '创建并打开' : '保存名称' }}</button>
          </footer>
        </section>
      </div>
    </Transition>

    <Transition name="toast"><div v-if="toast" class="toast-message">{{ toast }}</div></Transition>
  </div>
</template>

<style scoped>
.project-toolbar h1 .app-version {
  display: inline-flex;
  align-items: center;
  margin-left: 2px;
  padding: 2px 6px;
  border: 1px solid var(--border);
  border-radius: 5px;
  color: var(--hint);
  background: color-mix(in srgb, var(--bg) 50%, transparent);
  font-size: 10px;
  font-weight: 400;
  line-height: 1.4;
  letter-spacing: 0;
}
</style>

<style scoped>
</style>
