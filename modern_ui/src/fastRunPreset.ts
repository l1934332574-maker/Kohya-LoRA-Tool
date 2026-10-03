/** Training plans describe supported changes; resolution, quantization and sampling remain independent. */
export type TrainingProfile = 'smoke' | 'quick' | 'memory' | 'standard' | 'speed' | 'long'
export const trainingProfiles: { key: TrainingProfile; label: string; description: string }[] = [
  { key: 'smoke', label: '先跑通流程', description: '用 1 轮或引擎最低 100 步检查数据、模型与训练入口；用于排错，不用于判断最终效果。' },
  { key: 'quick', label: '快速试效果', description: '使用较小 rank，减少重复和轮数/步数；先观察是否学到目标特征。' },
  { key: 'memory', label: '降低显存占用', description: '使用较小 rank、批大小 1，并启用支持的省显存设置；训练量恢复当前模式的标准预设，每步可能更慢，不保证任何显卡都能运行。' },
  { key: 'standard', label: '标准训练（推荐起点）', description: '恢复当前模式的 rank、alpha 和训练量预设，显存设置交给引擎自动选择；学习率仍保留当前值。' },
  { key: 'speed', label: '加快每步速度', description: '关闭支持的梯度检查点、块交换和额外省显存档；训练量恢复当前模式的标准预设，需要更多显存；不通过减少轮数来提速。' },
  { key: 'long', label: '增加训练量', description: '按模式预设增加约 50% 轮数或步数；不自动增加 rank 或学习率，需结合采样判断是否学过头。' },
]

export function fastRunNumber(current: string, limit: number): string {
  const value = Number(current)
  return String(Number.isFinite(value) && value > 0 ? Math.min(Math.floor(value), limit) : limit)
}
export function fastRunEpochs(mode: string): number { return mode === 'h3_fz' || mode === 'qwen21_fz' ? 6 : 8 }

export const profileFieldLabels: Record<string, string> = {
  rank: 'LoRA rank', alpha: 'LoRA alpha', batch_size: '批大小', gc: '梯度检查点',
  repeats: '图片重复次数', max_epochs: '训练轮数', video_steps: '总训练步数',
  compile: '模型编译', unet_only: '只训练 UNet', fast_tier: '额外省显存档',
  blocks_to_swap: '块交换数量', fizgig_qwen_preset: 'Fizgig 官方预设',
}
export const profileFieldKeys = Object.keys(profileFieldLabels)
export function profileValue(key: string, value: unknown): string {
  if (value === '' || value === undefined || value === null || value === 'auto') return '自动 / 模式默认'
  if (typeof value === 'boolean') return value ? '开启' : '关闭'
  if (key === 'fast_tier') return value === 'on' ? '开启' : '关闭'
  if (key === 'fizgig_qwen_preset') return ({ fast: 'Fast（官方固定 rank/alpha；学习率自适应）', standard: 'Standard', style: 'Style' } as Record<string, string>)[String(value)] || String(value)
  return String(value)
}
export function sameProfileValue(a: unknown, b: unknown): boolean {
  if ((a === '' || a === 'auto' || a == null) && (b === '' || b === 'auto' || b == null)) return true
  return String(a) === String(b) || (a !== '' && b !== '' && a != null && b != null && Number.isFinite(Number(a)) && Number.isFinite(Number(b)) && Number(a) === Number(b))
}

/** Every plan writes the full supported set, preventing residual settings when changing plans. */
export function trainingProfileChanges(
  draft: object, mode: string, profile: TrainingProfile, supported: (key: string) => boolean,
  defaults: Record<string, unknown> = {},
): Record<string, string | boolean> {
  const current = draft as Record<string, unknown>
  const changes: Record<string, string | boolean> = {}
  const set = (key: string, value: string | boolean) => {
    if (key in current && supported(key)) changes[key] = value
  }
  const number = (key: string, fallback: number) => {
    const value = Number(defaults[key])
    return Number.isFinite(value) && value > 0 ? Math.floor(value) : fallback
  }
  const rank = number('rank', 16)
  // Qwen 2.1's official preset owns rank/alpha/LR; do not present edits that its CLI ignores.
  if (mode !== 'qwen21_fz') { set('rank', String(rank)); set('alpha', String(number('alpha', rank))) }
  set('repeats', String(number('repeats', 1)))
  set('max_epochs', String(number('max_epochs', 8)))
  set('video_steps', String(number('video_steps', 2000)))
  set('batch_size', '1')
  set('gc', 'auto')
  set('compile', false)
  set('unet_only', Boolean(defaults.unet_only))
  set('blocks_to_swap', '')
  set('fast_tier', 'auto')
  if (mode === 'qwen21_fz') set('fizgig_qwen_preset', 'auto')
  if (['smoke', 'quick', 'memory'].includes(profile)) {
    if (mode === 'qwen21_fz') set('fizgig_qwen_preset', 'fast')
    else { set('rank', String(Math.min(rank, 8))); set('alpha', String(Math.min(number('alpha', rank), Math.min(rank, 8)))) }
    set('gc', '开启')
    set('unet_only', true)
    // The AI Toolkit "fast" switch actually enables layer offloading, not faster steps.
    if (profile === 'memory') set('fast_tier', 'on')
    if (profile !== 'memory') {
      set('repeats', '1')
      set('max_epochs', profile === 'smoke' ? '1' : String(Math.min(number('max_epochs', 8), 4)))
      set('video_steps', profile === 'smoke' ? '100' : String(Math.min(number('video_steps', 2000), 400)))
    }
  } else if (profile === 'speed') {
    set('gc', '关闭')
    set('blocks_to_swap', '0')
    set('fast_tier', 'off')
  } else if (profile === 'long') {
    set('max_epochs', String(Math.ceil(number('max_epochs', 8) * 1.5)))
    set('video_steps', String(Math.min(mode === 'video' ? 3000 : 6000, Math.ceil(number('video_steps', 2000) * 1.5))))
  }
  return changes
}
