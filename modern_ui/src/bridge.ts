export interface ModelChoice { model: string; variant: string; engine: string }
export interface ModelEngineChoice { key: string; label: string; mode: string; template: string; vendors: string[]; reason: string; experimental: boolean; recommended?: boolean; supported?: boolean; installed?: boolean; status?: string }
export interface ModelVariant { key: string; label: string; note: string; preferred: Record<string, string | undefined>; engines: ModelEngineChoice[] }
export interface ModelCatalogData { models: Array<{ key: string; label: string; variants: ModelVariant[] }>; gpu_vendor: string; gpu: string }

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
  model_catalog?: ModelCatalogData
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

export interface DatasetSummary {
  ok: boolean
  images?: number
  captioned?: number
  empty_captions?: number
  missing_captions?: number
  keep_user_captions?: boolean
  preview_token?: string
  preview_images?: string[]
  next_offset?: number | null
  source_kind?: string
  error?: string
}

export interface TrainingRunSummary {
  id: string; project_name: string; mode: string; mode_label: string; started: number;
  ended?: number; status: string; message: string; metrics?: TrainingMetrics; resume_path?: string;
}
export interface TrainingRun extends TrainingRunSummary {
  config: ProjectConfig; normalized_params: Record<string, unknown>;
  loss_history?: TrainingMetricPoint[]; logs?: string[];
}

export interface ModernTaskSample {
  ok: boolean
  error?: string
  available?: boolean
  name?: string
  version?: string
  data_url?: string
  warning?: string
  width?: number
  height?: number
}

export interface TrainingSampleEntry { name: string; version: string; modified: number; bytes: number }

export interface CaptionServiceSettings {
  provider: 'compatible' | 'ollama'; base_url: string; model: string; unload_after: boolean; has_key?: boolean;
}
export interface CaptionReport {
  preview: boolean; directory?: string; total: number; written: number; skipped: number; failed: number;
  items: Array<{ name: string; status: string; caption?: string; error?: string }>;
}

export interface PromptReverseItem { name: string; status: string; caption?: string; error?: string }
export interface PromptReverseReport {
  task_id: string; directory: string; path: string; method: 'natural' | 'wd14'; language: 'zh' | 'en'; length: 'brief' | 'detailed';
  status: string; total: number; generated: number; failed: number; items: PromptReverseItem[]; error?: string;
}

export interface AssistantResult {
  ok: boolean; error?: string; id?: string; project?: string; status?: string; answer?: string;
  changes?: Array<{ key: string; label: string; before: unknown; after: unknown }>;
  applied?: boolean; undone?: boolean;
}

export interface AgentMessage {
  id: string; role: 'user' | 'assistant' | 'tool' | 'system'; content: string;
  status?: 'streaming' | 'complete'; kind?: string; tool?: string; choices?: string[]; question_id?: string;
}
export interface AgentPlan {
  fields: Array<{ key: string; label: string; value: unknown }>;
  warnings: string[]; changes: Array<Record<string, unknown>>;
}
export interface AgentResult { ok: boolean; status: string; message: string; error?: string }
export interface AgentRun {
  id: string; project: string; status: string; phase?: string; goal: string; detail: string;
  question: string; question_id?: string; question_kind?: string; choices: string[]; path_kind?: 'folder' | 'model' | null;
  revision: number; messages: AgentMessage[]; pause_explicit?: boolean; created_project?: boolean; plan?: AgentPlan | null; result?: AgentResult | null;
  task_id?: string; task_active?: boolean; progress?: number | null;
  policy?: Record<string, boolean>;
  environment?: { version?: string; gpu?: { name?: string; vram_gb?: number | null }; installed?: Record<string, boolean>; project?: unknown; modes?: unknown[] };
  catalog?: Array<{ name: string; title: string; description: string; arguments: Record<string, string> }>;
  events: Array<{ kind: string; title: string; time: number; result: unknown }>;
}

export interface DesktopApi {
  report_ui_startup(stage: string, detail?: string): Promise<{ ok: boolean }>
  open_ui_startup_report(): Promise<{ ok: boolean; error?: string; path?: string }>
  use_classic_ui(): Promise<{ ok: boolean; error?: string }>
  get_agent_environment(): Promise<{ ok: boolean; error?: string; environment?: AgentRun['environment'] }>
  start_agent(project: string, options: { goal: string; execute: boolean; allow_remote: boolean; allow_install: boolean; allow_download: boolean; allow_remote_images: boolean; auto_review: boolean; allow_auto_train?: boolean }): Promise<{ ok: boolean; error?: string; id?: string }>
  get_agent_state(project?: string): Promise<{ ok: boolean; error?: string; run?: AgentRun | null; active_project?: string | null; active_run_id?: string | null }>
  send_agent_message(id: string, text: string): Promise<{ ok: boolean; error?: string }>
  reply_agent(id: string, answer: string, question_id?: string): Promise<{ ok: boolean; error?: string }>
  control_agent(id: string, action: 'pause' | 'resume' | 'takeover'): Promise<{ ok: boolean; error?: string }>
  pick_agent_path(id: string, kind: 'folder' | 'model', path?: string): Promise<{ ok: boolean; error?: string; cancelled?: boolean; path?: string }>
  stop_agent(id: string, stop_task: boolean): Promise<{ ok: boolean; error?: string }>
  start_prompt_reverse(options: { path: string; method: 'natural' | 'wd14'; language: 'zh' | 'en'; length: 'brief' | 'detailed'; wd14_model: string; threshold: number; allow_remote: boolean }): Promise<{ ok: boolean; task_id?: string; error?: string }>
  get_prompt_reverse(task_id?: string): Promise<{ ok: boolean; task_id: string; report?: PromptReverseReport | null; task?: { id: string; status: string; message: string; detail: string; progress: number | null } | null }>
  get_prompt_reverse_image(task_id: string, name: string): Promise<{ ok: boolean; data_url?: string; error?: string }>
  export_prompt_reverse(task_id: string, items: Array<{ name: string; caption: string }>, directory: string): Promise<{ ok: boolean; directory?: string; written?: number; error?: string }>
  get_caption_service(): Promise<{ ok: boolean; settings?: CaptionServiceSettings; task?: { id: string; status: string; project_name: string }; error?: string }>
  save_caption_service(settings: CaptionServiceSettings & { api_key?: string; clear_key?: boolean }): Promise<{ ok: boolean; settings?: CaptionServiceSettings; error?: string }>
  start_caption_task(project_name: string, options: { directory: string; language: string; length: string; preview: boolean; replace: boolean; allow_remote: boolean; retry_task_id?: string }): Promise<{ ok: boolean; task_id?: string; error?: string }>
  get_caption_report(task_id: string): Promise<{ ok: boolean; report?: CaptionReport; error?: string }>
  list_training_runs(project_name?: string): Promise<{ ok: boolean; runs?: TrainingRunSummary[]; error?: string }>
  get_training_run(run_id: string): Promise<{ ok: boolean; run?: TrainingRun; error?: string }>
  restore_training_run(run_id: string, project_name: string): Promise<{ ok: boolean; error?: string }>
  inspect_dataset(directory: string): Promise<DatasetSummary>
  inspect_task_dataset(task_id: string): Promise<DatasetSummary>
  list_dataset_preview(token: string, offset?: number): Promise<{ ok: boolean; images?: string[]; next_offset?: number | null; error?: string }>
  get_dataset_preview(token: string, name: string): Promise<{ ok: boolean; data_url?: string; name?: string; width?: number; height?: number; caption?: string; error?: string }>
  get_assistant_service(): Promise<{ ok: boolean; error?: string; settings?: CaptionServiceSettings; request?: { id: string; project: string; status: string } | null }>
  save_assistant_service(settings: CaptionServiceSettings & { api_key?: string; clear_key?: boolean }): Promise<{ ok: boolean; error?: string; settings?: CaptionServiceSettings }>
  start_assistant_request(project: string, options: { question: string; include_logs: boolean; allow_remote: boolean }): Promise<{ ok: boolean; error?: string; id?: string }>
  get_assistant_result(id: string): Promise<AssistantResult>
  stop_assistant_request(id: string): Promise<{ ok: boolean; error?: string }>
  apply_assistant_proposal(id: string, undo: boolean): Promise<{ ok: boolean; error?: string }>
  bootstrap(): Promise<BootstrapData>
  suggest_project_name(): Promise<{ ok: boolean; name?: string; error?: string }>
  list_projects(): Promise<ProjectCard[]>
  create_project(name: string, templateName: string, configJson?: string, modeOverride?: string, modelChoice?: ModelChoice, trainingType?: string): Promise<CreateProjectResult>
  rename_project(oldName: string, newName: string): Promise<{ ok: boolean; error?: string; log?: string }>
  delete_project(name: string): Promise<{ ok: boolean; error?: string; log?: string }>
  open_project(name: string): Promise<{ ok: boolean; error?: string }>
  load_project_config(name: string): Promise<{ ok: boolean; error?: string; config?: ProjectConfig }>
  save_project_config(name: string, patch: ProjectConfig): Promise<{ ok: boolean; error?: string; project?: ProjectCard | null }>
  choose_path(kind: 'folder' | 'model' | 'image', current_path?: string, memory_key?: string): Promise<{ ok: boolean; error?: string; cancelled?: boolean; path?: string }>
  get_appearance_settings(): Promise<{ ok: boolean; settings?: AppearanceSettings; error?: string }>
  get_appearance_presets(): Promise<{ ok: boolean; presets?: AppearancePreset[]; hidden_builtin_ids?: string[]; error?: string }>
  save_appearance_preset(name: string): Promise<{ ok: boolean; presets?: AppearancePreset[]; error?: string }>
  delete_appearance_preset(id: string): Promise<{ ok: boolean; presets?: AppearancePreset[]; hidden_builtin_ids?: string[]; error?: string }>
  restore_appearance_builtin_presets(): Promise<{ ok: boolean; presets?: AppearancePreset[]; hidden_builtin_ids?: string[]; error?: string }>
  set_appearance_settings(
    theme: AppearanceSettings['theme'],
    background_path: string,
    background_opacity: number,
    component_opacity?: number,
    idle_fade_enabled?: boolean,
    background_history?: string[],
    background_source_path?: string,
    background_data_url?: string,
  ): Promise<{ ok: boolean; settings?: AppearanceSettings; error?: string }>
  get_appearance_background(): Promise<{ ok: boolean; data_url?: string; error?: string }>
  get_appearance_image_preview(path: string, thumbnail?: boolean): Promise<{ ok: boolean; data_url?: string; error?: string }>
  get_qwen_model_setup(mode?: 'qwen_image' | 'zimage'): Promise<QwenModelSetup>
  save_qwen_model_setup(selection: QwenModelSelection): Promise<QwenModelSetup>
  prepare_training(project_name: string): Promise<{ ok: boolean; error?: string; plan?: TrainingPlan }>
  start_training(project_name: string, use_resume?: boolean): Promise<{ ok: boolean; task_id?: string; error?: string }>
  continue_training(task_id: string): Promise<{ ok: boolean; error?: string }>
  start_preprocess_task(project_name: string): Promise<{ ok: boolean; task_id?: string; error?: string }>
  get_model_catalog(): Promise<ModelCatalogData>
  get_mode_workspace(mode: string, project_name?: string): Promise<ModeWorkspaceData>
  inspect_base_model(path: string): Promise<{ ok: boolean; base_type?: string; error?: string }>
  start_setup_task(action: string): Promise<{ ok: boolean; task_id?: string; error?: string }>
  get_task_status(task_id: string, after?: number): Promise<ModernTaskStatus>
  list_task_samples(task_id: string, offset?: number): Promise<{ ok: boolean; samples?: TrainingSampleEntry[]; total?: number; next_offset?: number | null; error?: string }>
  get_task_sample(task_id: string, after?: string, full?: boolean, name?: string): Promise<ModernTaskSample>
  cancel_task(task_id: string): Promise<{ ok: boolean; error?: string }>
  get_model_downloads(mode: string): Promise<ModelDownloadList>
  start_model_download(mode: string, key: string): Promise<{ ok: boolean; task_id?: string; error?: string }>
  get_env_locations(): Promise<EnvLocations>
  set_env_location(kind: 'python' | 'git', directory: string): Promise<EnvLocations>
  reset_env_locations(): Promise<EnvLocations>
  get_log_export_status(export_id: string): Promise<LogExportStatus>
  open_log_export(export_id: string, target: 'file' | 'folder'): Promise<{ ok: boolean; error?: string }>
  run_action(action: string, project_name?: string): Promise<{ ok: boolean; error?: string; message?: string; log?: string; export_id?: string }>
}

export interface LogExportStatus {
  ok: boolean
  id?: string
  status?: 'running' | 'completed' | 'failed'
  path?: string
  error?: string
}

export interface AppearanceSettings {
  theme: 'dark' | 'light' | 'system'
  background_path: string
  background_source_path: string
  background_opacity: number
  background_available: boolean
  background_history: AppearanceBackgroundHistoryEntry[]
  component_opacity: number
  idle_fade_enabled: boolean
  background_data_url?: string
}

export interface AppearancePreset {
  id: string
  name: string
  built_in: boolean
  theme: AppearanceSettings['theme']
  background_path: string
  background_source_path?: string
  background_opacity: number
  component_opacity: number
  idle_fade_enabled: boolean
  available: boolean
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

export interface TrainingMetrics {
  step: number
  total: number
  loss: number | null
  speed: number
}

export interface TrainingMetricPoint { step: number; loss: number }

export interface ModernTaskStatus {
  ok: boolean
  kind?: string
  project_name?: string
  plan?: TrainingPlan
  error?: string
  id?: string
  title?: string
  status?: 'running' | 'awaiting_review' | 'completed' | 'failed' | 'cancelled'
  message?: string
  progress?: number | null
  eta_seconds?: number | null
  detail?: string
  logs?: string[]
  next_offset?: number
  metrics?: TrainingMetrics | null
  loss_history?: TrainingMetricPoint[]
  sampling_status?: { status?: string; reason?: string; disabled?: boolean }
  effective_params?: Record<string, unknown>
}

export interface TrainingPlan {
  config_supports?: Record<string, boolean>
  save_interval_unit?: string
  save_interval_effective?: number
  sampling_rule?: { enabled: boolean; reason: string; cadence: string; unit: string }
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
  data_count?: number
  data_label?: string
  data_unit?: string
  media_summary?: Record<string, unknown> | null
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
  config_summary?: Record<string, unknown>
  execution_summary?: Array<{ label: string; value: string }>
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
  fizgig_version?: string
  fizgig_versions?: string[]
  fizgig_target_version?: string
  model_choice?: ModelChoice
  engine_key: string
  gpu: string
  gpu_vendor: string
  missing_models: string[]
  asset_dir: string
  supports: Record<string, boolean>
  quant_modes?: string[]
  interval_units: Record<string, string>
  interval_hints?: Record<string, string>
  defaults: Record<string, string>
  presets?: Record<string, Record<string, Record<string, unknown>>>
  is_video: boolean
  is_step_based: boolean
  has_training_submode: boolean
  data_count?: number
  data_label?: string
  data_unit?: string
  media_summary?: Record<string, unknown> | null
  guide_steps?: GuideStep[]
}

declare global {
  interface Window {
    pywebview?: { api: DesktopApi }
    __kohyaStartup?: { mounted(): void; fail(detail: string): void; report(stage: string, detail?: string): void }
  }
}

const demoTemplates: ProjectTemplate[] = [
  { name: '自定义', mode: 'character', mode_label: '人物 LoRA', base_type: 'sdxl', note: '从人物 + SDXL 起步，进入训练页后可切换训练模式、底模和参数。' },
  { name: 'SD1.5', mode: 'character', mode_label: '人物 LoRA', base_type: 'sd15', note: '使用 SD1.5 底模，默认人物训练；进入训练页后可切换人物、画风或概念模式。' },
  { name: 'SDXL', mode: 'character', mode_label: '人物 LoRA', base_type: 'sdxl', note: '使用 SDXL 底模，默认人物训练；进入训练页后可切换人物、画风或概念模式。' },
  { name: 'FLUX.1', mode: 'character', mode_label: '人物 LoRA', base_type: 'flux', note: '使用第一引擎 FLUX.1 底模，默认人物训练；进入训练页后可切换人物、画风或概念模式。' },
  { name: 'Anima', mode: 'character', mode_label: '人物 LoRA', base_type: 'anima', note: '使用 Anima 底模，默认人物训练；进入训练页后可切换人物、画风或概念模式。' },
  { name: 'Krea 2（musubi）', mode: 'krea2', mode_label: 'Krea 2', base_type: 'sdxl', note: '第二引擎图像训练；保存与采样间隔可分别按轮次或步数设置。' },
  { name: 'FLUX.2（musubi）', mode: 'flux2', mode_label: 'FLUX.2', base_type: 'sdxl', note: '第二引擎 FLUX.2 图像训练。' },
  { name: '视频 LoRA（H3）', mode: 'video', mode_label: '视频 H3', base_type: 'sdxl', note: '使用视频数据、训练步数与帧数设置。' },
  { name: 'Krea2（AI Toolkit）', mode: 'krea2_at', mode_label: 'Krea2 AI Toolkit', base_type: 'sdxl', note: '第三引擎 Krea2 训练。' },
  { name: 'Qwen-Image', mode: 'qwen_image', mode_label: 'Qwen-Image', base_type: 'qwen_image', note: '可选 Qwen-Image-2.1 或 2512；新版训练页支持指定本地组件。' },
  { name: 'Z-Image', mode: 'zimage', mode_label: 'Z-Image', base_type: 'zimage', note: '第三引擎图像训练，按总训练步数运行。' },
  { name: 'Krea2（Fizgig）', mode: 'krea2_fz', mode_label: 'Krea2 Fizgig', base_type: 'sdxl', note: '第四引擎 Krea2 图像训练。' },
  { name: 'FLUX.2 Klein 9B（Fizgig）', mode: 'flux2_fz', mode_label: 'Klein 9B', base_type: 'sdxl', note: '第四引擎 Klein 9B 图像训练。' },
  { name: 'Qwen-Image-2.1（Fizgig）', mode: 'qwen21_fz', mode_label: 'Qwen-Image-2.1 Fizgig', base_type: 'sdxl', note: '第四引擎 Qwen-Image-2.1；支持官方训练预设和 AMD 实验通道。' },
  { name: 'MiniMax H3 全模态（Fizgig）', mode: 'h3_fz', mode_label: 'MiniMax H3 Fizgig', base_type: 'sdxl', note: '第四引擎 H3 图片、视频、音频混合训练；同一目录或子目录中的每个媒体文件都需同名字幕。' },
]

const demoEngineGroups: EngineGroup[] = [
  { label: '第一引擎 · kohya', modes: [{ key: '_kohya', label: 'LoRA' }] },
  { label: '第二引擎 · musubi', modes: [{ key: 'krea2', label: 'Krea2' }, { key: 'flux2', label: 'FLUX.2' }] },
  { label: '第三引擎 · ai-toolkit', modes: [{ key: 'video', label: '视频H3' }, { key: 'krea2_at', label: 'Krea2AT' }, { key: 'qwen_image', label: 'Qwen' }, { key: 'zimage', label: 'Z-Image' }] },
  { label: '第四引擎 · fizgig', modes: [{ key: 'krea2_fz', label: 'Krea2F' }, { key: 'flux2_fz', label: 'Klein9B' }, { key: 'qwen21_fz', label: 'Qwen2.1F' }, { key: 'h3_fz', label: 'H3-F' }] },
]

export async function waitForDesktopBridge(timeoutMs = 15000): Promise<boolean> {
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
  const desktopExpected = navigator.userAgent.includes('KohyaLoRA-Desktop/') || Boolean(window.pywebview)
  // Browser previews have no desktop API. Only the installed host waits for it.
  const ready = await waitForDesktopBridge(desktopExpected ? 15000 : 1800)
  if (ready && window.pywebview?.api) {
    let timer: number | undefined
    try {
      const data = await Promise.race([
        window.pywebview.api.bootstrap(),
        new Promise<never>((_resolve, reject) => {
          timer = window.setTimeout(() => {
            window.__kohyaStartup?.report('bootstrap_timeout', '工作区信息请求超过 20 秒')
            reject(new Error('本机工作区未在 20 秒内响应。请打开启动诊断，或重新加载页面。'))
          }, 20000)
        }),
      ])
      window.__kohyaStartup?.report('workspace_connected')
      return { data, preview: false }
    } finally {
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }
  if (desktopExpected || window.pywebview) {
    window.__kohyaStartup?.report('bridge_timeout', '15 秒内未建立本机连接')
    throw new Error('页面已打开，但本机连接未建立。请打开启动诊断，或改用经典界面。')
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
