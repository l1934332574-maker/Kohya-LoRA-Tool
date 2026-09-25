const WD14_MODELS = new Set(['swinv2-v3', 'moat-v2'])

/** Keep older project files on the same recommended auto-tagging model as new projects. */
export function normalizeWd14Model(value: unknown): string {
  const model = String(value ?? '').trim()
  return WD14_MODELS.has(model) ? model : 'swinv2-v3'
}
