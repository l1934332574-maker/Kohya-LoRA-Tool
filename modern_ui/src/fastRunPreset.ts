/** 快跑档只改训练耗时和显存相关项；分辨率始终由用户决定。 */
export function fastRunNumber(current: string, limit: number): string {
  const value = Number(current)
  return String(Number.isFinite(value) && value > 0 ? Math.min(Math.floor(value), limit) : limit)
}

export function fastRunEpochs(mode: string): number {
  return mode === 'h3_fz' || mode === 'qwen21_fz' ? 6 : 8
}

export type TrainingProfile = 'quick' | 'memory' | 'speed'

/** Return supported draft changes; never change resolution or explicit quantization. */
export function trainingProfileChanges(
  draft: object, mode: string, profile: TrainingProfile, supported: (key: string) => boolean,
): Record<string, string | boolean> {
  const current = draft as Record<string, unknown>
  const changes: Record<string, string | boolean> = { sample_preview_mode: 'off' }
  const set = (key: string, value: string | boolean) => {
    if (key in current && supported(key)) changes[key] = value
  }
  set('compile', false)
  if (profile !== 'speed') {
    if (mode === 'qwen21_fz') set('fizgig_qwen_preset', 'fast')
    else { set('rank', fastRunNumber(String(current.rank || ''), 8)); set('alpha', fastRunNumber(String(current.alpha || ''), Number(changes.rank || current.rank || 8))) }
    set('batch_size', '1')
    set('gc', '开启')
    set('unet_only', true)
  }
  if (profile === 'quick') {
    set('repeats', '1')
    if (supported('max_epochs')) set('max_epochs', fastRunNumber(String(current.max_epochs || ''), fastRunEpochs(mode)))
    else set('video_steps', fastRunNumber(String(current.video_steps || ''), 600))
    set('fast_tier', 'on')
  } else if (profile === 'speed') {
    set('gc', '关闭')
    set('blocks_to_swap', '0')
    set('fast_tier', 'on')
  }
  return changes
}
