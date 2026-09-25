<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import EngineSidebar from './components/EngineSidebar.vue'
import LogDock from './components/LogDock.vue'
import ProjectRow from './components/ProjectRow.vue'
import UiIcon from './components/UiIcon.vue'
import ModernQwenWorkspace from './components/ModernQwenWorkspace.vue'
import ModernKohyaWorkspace from './components/ModernKohyaWorkspace.vue'
import ModernEngineWorkspace from './components/ModernEngineWorkspace.vue'
import ModernTaskDialog from './components/ModernTaskDialog.vue'
import ModernTrainingDialog from './components/ModernTrainingDialog.vue'
import ModelDownloadDialog from './components/ModelDownloadDialog.vue'
import EnvironmentDialog from './components/EnvironmentDialog.vue'
import ModernHelpDialog from './components/ModernHelpDialog.vue'
import AppearanceDialog from './components/AppearanceDialog.vue'
import {
  loadBootstrap,
  type BootstrapData,
  type ProjectCard,
  type ProjectConfig,
  type QwenModelSaveResult,
  type QwenModelSelection,
  type QwenModelSetup,
  type ModeWorkspaceData,
  type GuideStep,
  type TrainingPlan,
  type AppearanceSettings,
} from './bridge'

const data = ref<BootstrapData | null>(null)
const logs = ref<string[]>([])
const loading = ref(true)
const loadError = ref('')
const preview = ref(false)
const selectedMode = ref('_kohya')
const workspaceOpen = ref(false)
const workspaceKind = ref<'qwen' | 'kohya' | 'engine'>('qwen')
const workspaceProject = ref<ProjectCard | null>(null)
const workspaceConfig = ref<ProjectConfig | null>(null)
const previewConfigs = ref<Record<string, ProjectConfig>>({})
const modeWorkspace = ref<ModeWorkspaceData | null>(null)
const qwenModelSetup = ref<QwenModelSetup | null>(null)
const activeWorkspaceRef = ref<{
  startTraining: () => void
  guideAction?: (action: string) => Promise<ProjectConfig | null> | ProjectConfig | null
  openModelDialog?: () => void
} | null>(null)
const dialogOpen = ref(false)
const dialogKind = ref<'create' | 'rename'>('create')
const editingProject = ref<ProjectCard | null>(null)
const projectName = ref('')
const templateName = ref('自定义')
const busy = ref(false)
const formError = ref('')
const toast = ref('')
const setupDialogOpen = ref(false)
const setupAction = ref('')
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
const appearance = ref<AppearanceSettings>({ theme: 'dark', background_path: '', background_opacity: 18 })
const appearanceImage = ref('')
const systemPrefersLight = ref(false)
const nameInput = ref<HTMLInputElement | null>(null)
const importFileInput = ref<HTMLInputElement | null>(null)
const importedConfigJson = ref('')
const importedConfigPreview = ref<ProjectConfig | null>(null)
const importedConfigLabel = ref('')
let previousFocus: HTMLElement | null = null
let projectNameSuggestionRequest = 0
const reservedPreviewProjectNames = new Set<string>()
let systemThemeQuery: MediaQueryList | null = null
const updateSystemTheme = (event: MediaQueryListEvent) => { systemPrefersLight.value = event.matches }
const activeTheme = computed(() => appearance.value.theme === 'system'
  ? (systemPrefersLight.value ? 'light' : 'dark')
  : appearance.value.theme)
const appShellStyle = computed(() => ({
  '--wallpaper-image': appearanceImage.value ? `url("${appearanceImage.value}")` : 'none',
  '--wallpaper-opacity': appearanceImage.value ? String(appearance.value.background_opacity / 100) : '0',
}) as Record<string, string>)

const projects = computed(() => data.value?.projects ?? [])
const templates = computed(() => data.value?.templates ?? [])
const topActions = [
  { key: 'tools', icon: 'toolbox', label: '小工具', tip: '打开查看显存、清理显存/内存和缓存等训练辅助工具。' },
  { key: 'check_update', icon: 'refresh', label: '检查更新', tip: '检查 Kohya-LoRA 软件更新；训练引擎更新在对应训练引擎界面中处理。' },
  { key: 'output_dir', icon: 'folder', label: '输出目录', tip: '打开训练产物根目录，查看 LoRA、使用模板、参数报告和中间快照。' },
  { key: 'data_dir', icon: 'database', label: '数据目录', tip: '打开本机程序数据目录，查看项目配置、模型和缓存文件。' },
  { key: 'queue', icon: 'queue', label: '训练队列', tip: '选择多个项目，按顺序执行数据预处理和训练。' },
] as const
const trainActionLabel = computed(() => workspaceOpen.value ? '一键开始训练' : '打开新版训练页')
const guideSteps = computed(() => modeWorkspace.value?.guide_steps ?? [])
const guideLabel = computed(() => workspaceProject.value?.mode_label || modeWorkspace.value?.label || '')
const selectedGuideMode = computed(() => selectedMode.value === '_kohya'
  ? (projects.value.find(isKohyaProject)?.mode || 'character')
  : selectedMode.value)

// Keep standalone browser previews representative of the real mode registry.
// Desktop workspaces replace this demo payload with live values from modern_host.py.
const demoPresets: Record<string, Record<string, string>> = {
  style: { rank: '16', alpha: '8', unet_lr: '1.5e-4', te_lr: '7.5e-5', repeats: '5', max_epochs: '8', resolution: '1024', noise_offset: '0.05', min_snr_gamma: '5' },
  character: { rank: '32', alpha: '16', unet_lr: '7e-5', te_lr: '4e-5', repeats: '3', max_epochs: '6', resolution: '1024', noise_offset: '0.05', min_snr_gamma: '5' },
  concept: { rank: '32', alpha: '16', unet_lr: '1e-4', te_lr: '5e-5', repeats: '3', max_epochs: '8', resolution: '1024', noise_offset: '0.05', min_snr_gamma: '5' },
  krea2: { rank: '32', alpha: '32', unet_lr: '1e-4', te_lr: '1e-4', repeats: '2', max_epochs: '16', resolution: '1024' },
  krea2_at: { rank: '32', alpha: '32', unet_lr: '1e-4', te_lr: '1e-4', repeats: '2', max_epochs: '8', resolution: '1024' },
  krea2_fz: { rank: '32', alpha: '32', unet_lr: '1e-4', te_lr: '1e-4', repeats: '2', max_epochs: '16', resolution: '512' },
  flux2: { rank: '32', alpha: '32', unet_lr: '1e-4', te_lr: '1e-4', repeats: '2', max_epochs: '16', resolution: '1024' },
  flux2_fz: { rank: '32', alpha: '32', unet_lr: '1e-4', te_lr: '1e-4', repeats: '2', max_epochs: '16', resolution: '768' },
  video: { rank: '32', alpha: '32', unet_lr: '2e-4', te_lr: '1e-4', repeats: '1', max_epochs: '20', resolution: '1280', video_steps: '2000', video_frames: '73' },
  qwen_image: { rank: '16', alpha: '16', unet_lr: '1e-4', te_lr: '1e-4', repeats: '1', max_epochs: '20', resolution: '1024', video_steps: '2000' },
  zimage: { rank: '16', alpha: '16', unet_lr: '1e-4', te_lr: '1e-4', repeats: '1', max_epochs: '20', resolution: '1024', video_steps: '2000' },
}

function setActiveWorkspace(instance: unknown) {
  activeWorkspaceRef.value = instance as {
    startTraining: () => void
    guideAction?: (action: string) => Promise<ProjectConfig | null> | ProjectConfig | null
    openModelDialog?: () => void
  } | null
}

function isKohyaProject(project: ProjectCard) {
  return (project.mode === 'character' || project.mode === 'style' || project.mode === 'concept') && project.base_type !== 'qwen_image'
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

function previewProject(mode: string): ProjectCard {
  const template = templates.value.find((item) => item.mode === mode)
  const qwen = mode === 'qwen_image'
  return {
    name: `${template?.mode_label || mode} 新版训练页预览`, updated: '', mode,
    mode_label: template?.mode_label || mode,
    base_type: template?.base_type || (qwen ? 'qwen_image' : 'sdxl'),
    base_type_label: qwen ? 'Qwen-Image' : template?.mode_label || mode,
    raw_dir: '', base_model: '',
  }
}

function demoModeWorkspace(mode: string): ModeWorkspaceData {
  const template = templates.value.find((item) => item.mode === mode)
  const preset = demoPresets[mode] ?? {}
  const stepBased = ['video', 'qwen_image', 'zimage'].includes(mode)
  const usesEpochs = ['krea2_fz', 'flux2_fz'].includes(mode)
  const supports: Record<string, boolean> = {
    rank: true, alpha: true, unet_lr: true, te_lr: false, repeats: !stepBased,
    max_epochs: !stepBased, resolution: true, save_every: true, sample_interval: true,
    video_steps: stepBased, video_frames: mode === 'video', optimizer: !['krea2_fz', 'flux2_fz'].includes(mode),
    strong_bind: true, clean_concept: true, sample_preview: true, compile: ['krea2', 'flux2', 'krea2_fz'].includes(mode),
    global_pos: ['style', 'character', 'concept'].includes(mode), global_neg: ['style', 'character', 'concept'].includes(mode),
    crop_ratio: true, sample_prompt: true, noise_offset: false, min_snr_gamma: false,
    quant_mode: ['krea2', 'flux2', 'krea2_fz', 'flux2_fz'].includes(mode),
    blocks_to_swap: ['krea2', 'flux2', 'krea2_fz', 'flux2_fz'].includes(mode),
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
    asset_dir: '', supports, interval_units: { save_every: usesEpochs || ['krea2', 'flux2'].includes(mode) ? 'epochs' : 'steps', sample_interval: usesEpochs ? 'epochs' : 'steps' },
    defaults: preset, presets: { [mode]: { sdxl: preset } }, is_video: mode === 'video', is_step_based: stepBased,
    has_training_submode: ['krea2', 'krea2_at', 'krea2_fz', 'flux2', 'flux2_fz'].includes(mode),
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
  const modes = new Set(['style', 'character', 'concept', 'krea2', 'krea2_at', 'krea2_fz', 'flux2', 'flux2_fz', 'video', 'qwen_image', 'zimage'])
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

function openCreate(preselectedTemplate?: string) {
  dialogKind.value = 'create'
  editingProject.value = null
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

function openRename(project: ProjectCard) {
  dialogKind.value = 'rename'
  editingProject.value = project
  projectName.value = project.name
  formError.value = ''
  clearImportedConfig()
  dialogOpen.value = true
}

async function saveDialog() {
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
        const mode = String(imported?.mode ?? template?.mode ?? 'character')
        const baseType = String(imported?.base_type ?? template?.base_type ?? (mode === 'qwen_image' ? 'qwen_image' : 'sdxl'))
        const matchingTemplate = templates.value.find((item) => item.mode === mode && (!item.base_type || item.base_type === baseType))
          ?? templates.value.find((item) => item.mode === mode)
          ?? template
        const qwenTemplate = mode === 'qwen_image' || mode === 'zimage' || baseType === 'qwen_image'
        const project: ProjectCard = {
          name,
          updated: new Date().toISOString().replace('T', ' ').slice(0, 19),
          mode,
          mode_label: matchingTemplate?.mode_label ?? mode,
          base_type: baseType,
          base_type_label: qwenTemplate ? (mode === 'zimage' ? 'Z-Image' : 'Qwen-Image') : baseType === 'sdxl' ? 'SDXL 1.0（1024px）' : baseType,
          raw_dir: '',
          base_model: String(imported?.base_model ?? ''),
        }
        if (imported) previewConfigs.value = { ...previewConfigs.value, [name]: imported }
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
      const result = await window.pywebview.api.create_project(name, templateName.value, importedConfigJson.value || undefined)
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
    workspaceProject.value = project
    workspaceConfig.value = previewConfigs.value[project.name] ?? null
    qwenModelSetup.value = null
    modeWorkspace.value = null
    workspaceOpen.value = true
    if (isQwenProject(project)) {
      workspaceKind.value = 'qwen'
      selectedMode.value = project.mode
      modeWorkspace.value = demoModeWorkspace(project.mode)
      appendLog(`[预览] 已打开「${project.name}」的 ${project.mode === 'zimage' ? 'Z-Image' : 'Qwen-Image'} 工作区预览；设置只保留在本次预览会话。`)
    } else if (isKohyaProject(project)) {
      workspaceKind.value = 'kohya'
      selectedMode.value = '_kohya'
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
    let nextKind: 'qwen' | 'kohya' | 'engine'
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
      nextKind = isKohyaProject(project) ? 'kohya' : 'engine'
      nextDetails = details
    }
    workspaceProject.value = project
    workspaceConfig.value = loaded.config
    modeWorkspace.value = nextDetails
    qwenModelSetup.value = nextModelSetup
    workspaceKind.value = nextKind
    selectedMode.value = nextKind === 'kohya' ? '_kohya' : project.mode
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
    data.value!.projects = projects.value.map((project) => project.name === name
      ? { ...project, updated: new Date().toISOString().replace('T', ' ').slice(0, 19) }
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

async function chooseWorkspacePath(kind: 'folder' | 'model'): Promise<string | null> {
  if (!window.pywebview?.api || preview.value) return null
  try {
    const result = await window.pywebview.api.choose_path(kind)
    if (!result.ok) showToast(result.error ?? '选择路径失败。')
    return result.path || null
  } catch (error) {
    showToast(error instanceof Error ? error.message : '选择路径失败。')
    return null
  }
}

async function refreshGuideState() {
  if (preview.value || !window.pywebview?.api) return
  const mode = workspaceProject.value?.mode || selectedGuideMode.value
  const projectName = workspaceProject.value?.name || ''
  try {
    const [details, latestProjects] = await Promise.all([
      window.pywebview.api.get_mode_workspace(mode, projectName),
      window.pywebview.api.list_projects(),
    ])
    if (details.ok && (!workspaceOpen.value || workspaceProject.value?.mode === mode)) modeWorkspace.value = details
    data.value!.projects = latestProjects
    if (workspaceProject.value) workspaceProject.value = latestProjects.find((item) => item.name === workspaceProject.value?.name) ?? workspaceProject.value
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
    setupDialogOpen.value = true
    return
  }
  if (action === 'cmd_dl_krea2_models' || action === 'cmd_dl_flux2_models' || action === 'cmd_dl_h3_models') {
    modelDialogOpen.value = true
    return
  }
  if (action === 'cmd_at_model_help') {
    openHelp('mode', mode)
    return
  }
  if (action === 'cmd_pick_raw' || action === 'cmd_pick_model_type') {
    if (!workspaceProject.value) {
      const existing = projects.value.find((project) => project.mode === mode || (mode === 'character' && isKohyaProject(project)))
      if (existing) {
        await openProject(existing)
        await nextTick()
        const patch = await activeWorkspaceRef.value?.guideAction?.(action)
        if (patch && Object.keys(patch).length) await saveKohyaConfig(patch)
      } else {
        openCreate(mode === 'character' && selectedMode.value === '_kohya' ? undefined : templateForMode(mode))
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

function openHelp(kind: 'readme' | 'mode', mode = workspaceProject.value?.mode || selectedMode.value) {
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

async function runAction(action: string) {
  if (action === 'train') {
    if (preview.value && workspaceOpen.value) {
      activeWorkspaceRef.value?.startTraining()
      return
    }
    if (workspaceOpen.value) {
      activeWorkspaceRef.value?.startTraining()
      return
    }
    const project = selectedMode.value === '_kohya'
      ? projects.value.find(isKohyaProject)
      : projects.value.find((item) => item.mode === selectedMode.value)
    if (project) void openProject(project)
    else openCreate(selectedMode.value === '_kohya' ? templates.value.find((item) => item.name === '自定义')?.name : templateForMode(selectedMode.value))
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
  const result = await window.pywebview.api.run_action(action)
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
    const result = await api.choose_path('image')
    if (!result.ok) showToast(result.error ?? '选择背景图片失败。')
    return result.ok && result.path ? result.path : null
  } catch (error) {
    showToast(error instanceof Error ? error.message : '选择背景图片失败。')
    return null
  }
}

async function saveAppearance(next: AppearanceSettings) {
  if (appearanceSaving.value) return
  appearanceSaving.value = true
  try {
    if (preview.value || !window.pywebview?.api) {
      appearance.value = { ...next }
      appearanceImage.value = ''
      appearanceDialogOpen.value = false
      showToast('预览设置已应用；桌面版会保存背景图片。')
      return
    }
    const saved = await window.pywebview.api.set_appearance_settings(
      next.theme, next.background_path, next.background_opacity,
    )
    if (!saved.ok) {
      showToast(saved.error ?? '外观设置保存失败。')
      return
    }
    appearance.value = saved.settings ?? next
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
  if (!workspaceProject.value) return showToast('请先打开一个项目。')
  if (patch && Object.keys(patch).length && (await saveKohyaConfig(patch)) === false) return
  if (action === 'preprocess') {
    if (preview.value || !window.pywebview?.api) return showToast('浏览器预览中，这个操作不会触碰本机数据。')
    setupAction.value = 'preprocess'
    setupDialogOpen.value = true
    return
  }
  if (action === 'output_dir') return runAction(action)
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
  if (preview.value || !window.pywebview?.api) {
    modeWorkspace.value = demoModeWorkspace(mode === '_kohya' ? selectedGuideMode.value : mode)
    if (mode === '_kohya') {
      workspaceProject.value = projects.value.find(isKohyaProject) ?? {
        name: '人物 LoRA 新版训练页预览', updated: '', mode: 'character', mode_label: '人物 LoRA',
        base_type: 'sdxl', base_type_label: 'SDXL 1.0（1024px）', raw_dir: '', base_model: '',
      }
      workspaceConfig.value = previewConfigs.value[workspaceProject.value.name] ?? null
      qwenModelSetup.value = null
      modeWorkspace.value = demoModeWorkspace(workspaceProject.value.mode)
      workspaceKind.value = 'kohya'
      workspaceOpen.value = true
      return
    }
    const project = projects.value.find((item) => item.mode === mode) ?? previewProject(mode)
    workspaceProject.value = project
    workspaceConfig.value = previewConfigs.value[project.name] ?? null
    qwenModelSetup.value = null
    if (mode === 'qwen_image' || mode === 'zimage') {
      workspaceKind.value = 'qwen'
      modeWorkspace.value = demoModeWorkspace(mode)
    } else {
      workspaceKind.value = 'engine'
      modeWorkspace.value = demoModeWorkspace(mode)
    }
    workspaceOpen.value = true
    return
  }
  void refreshHomeGuide(mode === '_kohya' ? selectedGuideMode.value : mode)
  if (mode === '_kohya') {
    const project = projects.value.find(isKohyaProject)
    if (project) void openProject(project)
    else openCreate(templates.value.find((item) => item.name === '自定义')?.name)
    return
  }
  if (mode === 'qwen_image' || mode === 'zimage') {
    const project = projects.value.find((item) => item.mode === mode)
    if (project) void openProject(project)
    else openCreate(templateForMode(mode))
    return
  }
  const project = projects.value.find((item) => item.mode === mode)
  if (project) void openProject(project)
  else openCreate(templateForMode(mode))
}

function returnHome() {
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
  if (event.key === 'Escape' && appearanceDialogOpen.value) {
    appearanceDialogOpen.value = false
    return
  }
  if (event.key === 'Escape' && dialogOpen.value) dialogOpen.value = false
}

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  systemThemeQuery = window.matchMedia('(prefers-color-scheme: light)')
  systemPrefersLight.value = systemThemeQuery.matches
  systemThemeQuery.addEventListener('change', updateSystemTheme)
  try {
    const loaded = await loadBootstrap()
    data.value = loaded.data
    preview.value = loaded.preview
    logs.value = [...loaded.data.logs]
    if (!loaded.preview) await loadAppearanceSettings()
    if (loaded.preview) modeWorkspace.value = demoModeWorkspace('character')
    else await refreshHomeGuide(projects.value.find(isKohyaProject)?.mode || 'character')
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '无法连接桌面程序。'
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
  window.removeEventListener('keydown', onKeydown)
  systemThemeQuery?.removeEventListener('change', updateSystemTheme)
})
</script>

<template>
  <div class="app-shell" :data-theme="activeTheme" :data-wallpaper="appearanceImage ? 'true' : 'false'" :style="appShellStyle">
    <EngineSidebar
      :groups="data?.engine_groups ?? []"
      :selected-mode="selectedMode"
      :train-label="trainActionLabel"
      :status-text="projects.length ? '✓ 选择项目后进入新版训练页' : '新建项目后开始配置训练'"
      :workspace-active="workspaceOpen"
      :guide-label="guideLabel"
      :guide-steps="guideSteps"
      @choose-mode="chooseMode"
      @action="runAction"
      @guide-action="onGuideAction"
    />

    <main class="right-shell">
      <Transition name="view" mode="out-in">
      <ModernQwenWorkspace
        v-if="!loading && !loadError && workspaceOpen && workspaceProject && workspaceKind === 'qwen'"
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
          <h1><UiIcon name="home" /> 我的项目</h1>
          <div class="toolbar-actions">
            <button v-for="action in topActions" :key="action.key" class="toolbar-button" type="button" :title="action.tip" @click="runAction(action.key)">
              <UiIcon :name="action.icon" />{{ action.label }}
            </button>
            <button class="toolbar-button appearance-button" type="button" title="新版训练页外观设置" aria-label="新版训练页外观设置" @click="appearanceDialogOpen = true"><UiIcon name="settings" /></button>
            <button class="toolbar-button new-project" type="button" title="创建新的训练项目；可以从模式模板开始，也可以新建自定义项目。" @click="openCreate()"><UiIcon name="plus" /> 新建项目</button>
          </div>
        </header>
        <div class="project-hint">每个项目保存一套完整的训练配置（模式 / 底模 / 数据集 / 触发词 / 全部参数），下次直接打开续用。</div>
        <section class="project-list" aria-label="项目列表">
          <TransitionGroup v-if="projects.length" name="project-list">
            <ProjectRow
              v-for="project in projects"
              :key="project.name"
              :project="project"
              @open="openProject"
              @rename="openRename"
              @remove="removeProject"
            />
          </TransitionGroup>
          <div v-else class="empty-projects">
            <strong>还没有项目</strong>
            <span>点右上角「新建项目」开始，训练配置会保存在本机。</span>
            <button class="small-button primary" type="button" @click="openCreate()">新建项目</button>
          </div>
        </section>
      </div>
      <div v-else-if="loading" key="loading" class="loading-state"><span class="loader"></span>正在连接本机工作区…</div>
      <div v-else key="error" class="error-state"><strong>无法连接桌面工作区</strong><span>{{ loadError }}</span></div>
      </Transition>
      <LogDock v-if="!loading && !loadError" :entries="logs" @export="runAction('export_log')" />
      <span v-if="preview && !workspaceOpen" class="preview-pill">界面预览 · 不写入项目 / 不启动训练</span>
    </main>

    <ModernTaskDialog
      :open="setupDialogOpen"
      :title="setupAction === 'preprocess' ? '数据预处理' : setupAction === 'cmd_env' ? '环境准备（Git / Python）' : setupAction === 'cmd_install' ? '安装 Kohya 训练内核' : setupAction === 'cmd_install_musubi' ? '安装第二引擎 · musubi' : setupAction === 'cmd_install_at' ? '安装第三引擎 · AI Toolkit' : '安装第四引擎 · Fizgig'"
      :action="setupAction"
      :description="setupAction === 'preprocess' ? '调用现有预处理器处理当前项目图集和标签；只预处理，不启动训练。' : setupAction === 'cmd_env' ? '检测并准备 Git 与兼容版本的 Python。此项通常只需要完成一次。' : '安装过程会复用现有训练内核安装逻辑；已安装的部分会检测并复用。'"
      :project-name="workspaceProject?.name ?? ''"
      @close="setupDialogOpen = false"
      @finished="refreshGuideState"
      @notify="showToast"
    />
    <ModernTrainingDialog
      :open="trainingDialogOpen"
      :project-name="trainingProjectName"
      :plan="trainingPlan"
      @close="trainingDialogOpen = false"
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
      :desktop="!preview"
      :saving="appearanceSaving"
      :choose-background="chooseAppearanceBackground"
      @close="appearanceDialogOpen = false"
      @save="saveAppearance"
    />

    <Transition name="dialog">
      <div v-if="dialogOpen" class="dialog-backdrop" @click.self="dialogOpen = false">
        <section class="project-dialog" role="dialog" aria-modal="true" :aria-labelledby="dialogKind === 'create' ? 'dialog-title-create' : 'dialog-title-rename'">
          <header class="dialog-header">
            <h2 :id="dialogKind === 'create' ? 'dialog-title-create' : 'dialog-title-rename'">{{ dialogKind === 'create' ? '新建项目' : '重命名项目' }}</h2>
            <button class="dialog-close" type="button" aria-label="关闭" @click="dialogOpen = false">×</button>
          </header>
          <template v-if="dialogKind === 'create'">
            <label class="field-label" for="project-template">选择预设模板</label>
            <select id="project-template" v-model="templateName" class="dialog-select">
              <option v-for="template in templates" :key="template.name" :value="template.name">{{ template.name }}</option>
            </select>
            <p class="template-note">{{ templates.find((item) => item.name === templateName)?.note ?? '模板只设置训练模式和底模类型。' }}</p>
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
