export interface ProjectCard {
  name: string
  updated: string
  mode: string
  mode_label: string
  base_type: string
  base_type_label: string
  raw_dir: string
  base_model: string
}

export interface ProjectTemplate {
  name: string
  mode: string
  mode_label: string
  base_type?: string
  note: string
}

export interface BootstrapData {
  schema_version: number
  app_name: string
  version: string
  default_project_name: string
  modes: Array<{ key: string; label: string }>
  templates: ProjectTemplate[]
  projects: ProjectCard[]
  engine_groups: EngineGroup[]
  logs: string[]
}

export interface EngineGroup {
  label: string
  modes: Array<{ key: string; label: string }>
}

export interface CreateProjectResult {
  ok: boolean
  exists?: boolean
  error?: string
  project?: ProjectCard | null
}

export interface ProjectConfig {
  [key: string]: unknown
  params?: Record<string, unknown>
}

export interface QwenModelChoice {
  key: string
  label: string
  model_id: string
  arch: string
  size?: string
  hint?: string
  min_vram?: number
  rec_vram?: number
  resident_vram?: number
  default?: boolean
}

export interface QwenModelSetup {
  ok: boolean
  choices: QwenModelChoice[]
  settings: Record<string, string | number>
  active: Partial<QwenModelChoice>
  selected_key: string
  source: 'local' | 'download'
  auto_components?: { text_encoder_path?: string; vae_path?: string }
  gpu_vendor?: string
  error?: string
}

export interface QwenModelSelection {
  mode?: 'qwen_image' | 'zimage'
  key: string
  source: 'local' | 'download'
  local_dir?: string
  text_encoder_path?: string
  vae_path?: string
}

export interface QwenModelSaveResult {
  ok: boolean
  error?: string
  setup?: QwenModelSetup
}

export interface DesktopApi {
  bootstrap(): Promise<BootstrapData>
  suggest_project_name(): Promise<{ ok: boolean; name?: string; error?: string }>
  list_projects(): Promise<ProjectCard[]>
  create_project(name: string, templateName: string, configJson?: string): Promise<CreateProjectResult>
  rename_project(oldName: string, newName: string): Promise<{ ok: boolean; error?: string; log?: string }>
  delete_project(name: string): Promise<{ ok: boolean; error?: string; log?: string }>
  open_project(name: string): Promise<{ ok: boolean; error?: string }>
  load_project_config(name: string): Promise<{ ok: boolean; error?: string; config?: ProjectConfig }>
  save_project_config(name: string, patch: ProjectConfig): Promise<{ ok: boolean; error?: string; project?: ProjectCard | null }>
  choose_path(kind: 'folder' | 'model' | 'image'): Promise<{ ok: boolean; error?: string; cancelled?: boolean; path?: string }>
  get_appearance_settings(): Promise<{ ok: boolean; settings?: AppearanceSettings; error?: string }>
  set_appearance_settings(
    theme: AppearanceSettings['theme'],
    background_path: string,
    background_opacity: number,
    component_opacity?: number,
    idle_fade_enabled?: boolean,
    background_history?: string[],
  ): Promise<{ ok: boolean; settings?: AppearanceSettings; error?: string }>
  get_appearance_background(): Promise<{ ok: boolean; data_url?: string; error?: string }>
  get_qwen_model_setup(mode?: 'qwen_image' | 'zimage'): Promise<QwenModelSetup>
  save_qwen_model_setup(selection: QwenModelSelection): Promise<QwenModelSetup>
  prepare_training(project_name: string): Promise<{ ok: boolean; error?: string; plan?: TrainingPlan }>
  start_training(project_name: string, use_resume?: boolean): Promise<{ ok: boolean; task_id?: string; error?: string }>
  continue_training(task_id: string): Promise<{ ok: boolean; error?: string }>
  start_preprocess_task(project_name: string): Promise<{ ok: boolean; task_id?: string; error?: string }>
  get_mode_workspace(mode: string, project_name?: string): Promise<ModeWorkspaceData>
  inspect_base_model(path: string): Promise<{ ok: boolean; base_type?: string; error?: string }>
  start_setup_task(action: string): Promise<{ ok: boolean; task_id?: string; error?: string }>
  get_task_status(task_id: string, after?: number): Promise<ModernTaskStatus>
  cancel_task(task_id: string): Promise<{ ok: boolean; error?: string }>
  get_model_downloads(mode: string): Promise<ModelDownloadList>
  start_model_download(mode: string, key: string): Promise<{ ok: boolean; task_id?: string; error?: string }>
  get_env_locations(): Promise<EnvLocations>
  set_env_location(kind: 'python' | 'git', directory: string): Promise<EnvLocations>
  reset_env_locations(): Promise<EnvLocations>
  run_action(action: string, project_name?: string): Promise<{ ok: boolean; error?: string; message?: string; log?: string }>
}

export interface AppearanceSettings {
  theme: 'dark' | 'light' | 'system'
  background_path: string
  background_opacity: number
  background_available: boolean
  background_history: AppearanceBackgroundHistoryEntry[]
  component_opacity: number
  idle_fade_enabled: boolean
}

export interface AppearanceBackgroundHistoryEntry {
  path: string
  available: boolean
}

export interface GuideStep {
  id: string
  label: string
  button: string
  check: string
  action: string
  tip: string
  done: boolean
}

export interface ModernTaskStatus {
  ok: boolean
  error?: string
  id?: string
  title?: string
  status?: 'running' | 'awaiting_review' | 'completed' | 'failed' | 'cancelled'
  message?: string
  progress?: number | null
  detail?: string
  logs?: string[]
  next_offset?: number
}

export interface TrainingPlan {
  project_name: string
  mode: string
  mode_label: string
  training_engine?: 'kohya' | 'musubi' | 'ai_toolkit' | 'fizgig'
  engine_label?: string
  model_label: string
  model_path: string
  model_download_required: boolean
  model_size: string
  raw_dir: string
  image_count: number
  min_images: number
  training_type: string
  training_target?: string
  schedule_label?: string
  schedule_value?: string
  rank: number
  alpha: number
  learning_rate: string
  resolution: number
  steps: number
  trigger: string
  gpu_vendor: string
  vram_gb?: number | null
  warnings: string[]
  resume_path: string
}

export interface ModelDownloadItem {
  key: string
  filename: string
  label: string
  url: string
  path: string
  present: boolean
  required: boolean
  required_group: string
  optional: boolean
  part_size: number
}

export interface ModelDownloadList {
  ok: boolean
  error?: string
  mode?: string
  title?: string
  description?: string
  asset_dir?: string
  note?: string
  items?: ModelDownloadItem[]
}

export interface EnvLocations {
  ok: boolean
  error?: string
  configured?: { python_dir?: string; python_exe?: string; git_exe?: string }
  python?: { path: string; version: string; custom: boolean }
  git?: { path: string; custom: boolean }
}

export interface ModeWorkspaceData {
  ok: boolean
  error?: string
  mode: string
  label: string
  dataset_hint: string
  dataset_hints?: Record<string, string>
  trigger_hint: string
  trigger_hints?: Record<string, string>
  concept_type_hints?: Record<string, string>
  engine_ready: boolean
  engine_update_available?: boolean
  engine_key: string
  gpu: string
  gpu_vendor: string
  missing_models: string[]
  asset_dir: string
  supports: Record<string, boolean>
  interval_units: Record<string, string>
  defaults: Record<string, string>
  presets?: Record<string, Record<string, Record<string, unknown>>>
  is_video: boolean
  is_step_based: boolean
  has_training_submode: boolean
  guide_steps?: GuideStep[]
}

declare global {
  interface Window {
    pywebview?: { api: DesktopApi }
  }
}

const demoTemplates: ProjectTemplate[] = [
  { name: '自定义', mode: 'character', mode_label: '人物 LoRA', base_type: 'sdxl', note: '从空白项目开始，之后可切换人物、画风或概念模式。' },
  { name: '人物 LoRA（SDXL）', mode: 'character', mode_label: '人物 LoRA', base_type: 'sdxl', note: '训练人物、角色和主体特征。' },
  { name: '画风 LoRA（SDXL）', mode: 'style', mode_label: '画风 LoRA', base_type: 'sdxl', note: '保留整体画风，自动弱化人物标签。' },
  { name: '概念 LoRA（SDXL）', mode: 'concept', mode_label: '概念 LoRA', base_type: 'sdxl', note: '训练形态、服装、物品或身体部位等概念。' },
  { name: 'Krea 2（musubi）', mode: 'krea2', mode_label: 'Krea 2', base_type: 'sdxl', note: '第二引擎图像训练；保存与采样间隔可分别按轮次或步数设置。' },
  { name: 'FLUX.2（musubi）', mode: 'flux2', mode_label: 'FLUX.2', base_type: 'sdxl', note: '第二引擎 FLUX.2 图像训练。' },
  { name: '视频 LoRA（H3）', mode: 'video', mode_label: '视频 H3', base_type: 'sdxl', note: '使用视频数据、训练步数与帧数设置。' },
  { name: 'Krea2（AI Toolkit）', mode: 'krea2_at', mode_label: 'Krea2 AI Toolkit', base_type: 'sdxl', note: '第三引擎 Krea2 训练。' },
  { name: 'Qwen-Image', mode: 'qwen_image', mode_label: 'Qwen-Image', base_type: 'qwen_image', note: '可选 Qwen-Image-2.1 或 2512；新版训练页支持指定本地组件。' },
  { name: 'Z-Image', mode: 'zimage', mode_label: 'Z-Image', base_type: 'zimage', note: '第三引擎图像训练，按总训练步数运行。' },
  { name: 'Krea2（Fizgig）', mode: 'krea2_fz', mode_label: 'Krea2 Fizgig', base_type: 'sdxl', note: '第四引擎 Krea2 图像训练。' },
  { name: 'FLUX.2 Klein 9B（Fizgig）', mode: 'flux2_fz', mode_label: 'Klein 9B', base_type: 'sdxl', note: '第四引擎 Klein 9B 图像训练。' },
]

const demoEngineGroups: EngineGroup[] = [
  { label: '第一引擎 · kohya', modes: [{ key: '_kohya', label: 'LoRA' }] },
  { label: '第二引擎 · musubi', modes: [{ key: 'krea2', label: 'Krea2' }, { key: 'flux2', label: 'FLUX.2' }] },
  { label: '第三引擎 · ai-toolkit', modes: [{ key: 'video', label: '视频H3' }, { key: 'krea2_at', label: 'Krea2AT' }, { key: 'qwen_image', label: 'Qwen' }, { key: 'zimage', label: 'Z-Image' }] },
  { label: '第四引擎 · fizgig', modes: [{ key: 'krea2_fz', label: 'Krea2F' }, { key: 'flux2_fz', label: 'Klein9B' }] },
]

export async function waitForDesktopBridge(timeoutMs = 1800): Promise<boolean> {
  const isReady = () => typeof window.pywebview?.api?.bootstrap === 'function'
  if (isReady()) return true
  return new Promise((resolve) => {
    let done = false
    const finish = (ready: boolean) => {
      if (done) return
      done = true
      window.removeEventListener('pywebviewready', onReady)
      window.clearTimeout(timer)
      resolve(ready)
    }
    const onReady = () => finish(isReady())
    const timer = window.setTimeout(() => finish(isReady()), timeoutMs)
    window.addEventListener('pywebviewready', onReady, { once: true })
  })
}

export async function loadBootstrap(): Promise<{ data: BootstrapData; preview: boolean }> {
  const ready = await waitForDesktopBridge()
  if (ready && window.pywebview?.api) {
    return { data: await window.pywebview.api.bootstrap(), preview: false }
  }
  return {
    preview: true,
    data: {
      schema_version: 1,
      app_name: 'Kohya-LoRA Studio',
      version: '界面预览',
      default_project_name: '项目_0924_1200',
      modes: [],
      templates: demoTemplates,
      engine_groups: demoEngineGroups,
      logs: [
        '欢迎使用 Kohya-LoRA 一键训练工具',
        '按左侧新手引导顺序操作，打开项目后再开始训练。',
        '浏览器预览模式：项目和日志只在当前页面有效。',
      ],
      projects: [
        { name: '角色概念测试', updated: '2026-09-22 20:14', mode: 'character', mode_label: '人物 LoRA', base_type: 'sdxl', base_type_label: 'SDXL 1.0（1024px）', raw_dir: '', base_model: '' },
        { name: '概念模式示例', updated: '2026-09-21 18:40', mode: 'concept', mode_label: '概念 LoRA', base_type: 'sdxl', base_type_label: 'SDXL 1.0（1024px）', raw_dir: '', base_model: '' },
        { name: '水彩插画风格', updated: '2026-09-19 16:42', mode: 'style', mode_label: '画风 LoRA', base_type: 'sd15', base_type_label: 'SD 1.5（512px）', raw_dir: '', base_model: '' },
        { name: 'Qwen 人像实验', updated: '2026-09-17 09:28', mode: 'qwen_image', mode_label: 'Qwen-Image', base_type: 'qwen_image', base_type_label: 'Qwen-Image', raw_dir: '', base_model: '' },
      ],
    },
  }
}
