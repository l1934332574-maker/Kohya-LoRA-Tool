/** 快跑档只改训练耗时和显存相关项；分辨率始终由用户决定。 */
export function fastRunNumber(current: string, limit: number): string {
  const value = Number(current)
  return String(Number.isFinite(value) && value > 0 ? Math.min(Math.floor(value), limit) : limit)
}

export function fastRunEpochs(mode: string): number {
  return mode === 'h3_fz' || mode === 'qwen21_fz' ? 6 : 8
}
