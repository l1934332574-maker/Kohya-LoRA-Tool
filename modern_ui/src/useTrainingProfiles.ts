import { computed, ref, watch } from 'vue'
import { sameProfileValue, trainingProfileChanges, trainingProfiles, type TrainingProfile } from './fastRunPreset'

export function useTrainingProfiles(
  draft: object, dirty: Set<string>, options: () => { mode: string; defaults: Record<string, unknown>; supported: (key: string) => boolean },
  notify: (message: string) => void, context: () => unknown,
) {
  const current = draft as Record<string, unknown>
  const profileUndo = ref<{ values: Record<string, unknown>; applied: Record<string, unknown>; dirty: Record<string, boolean> } | null>(null)
  const profileDefaults = computed(() => options().defaults)
  const profileSupported = (key: string) => options().supported(key)
  const dirtyKey = (key: string) => ['unet_only', 'fast_tier'].includes(key) ? key : `params.${key}`
  watch(context, () => { profileUndo.value = null }, { deep: true })
  function applyProfile(profile: TrainingProfile) {
    const { mode, defaults, supported } = options()
    const targets = trainingProfileChanges(draft, mode, profile, supported, defaults)
    const changes = Object.fromEntries(Object.entries(targets).filter(([key, value]) => !sameProfileValue(current[key], value)))
    if (!Object.keys(changes).length) return notify('当前设置已符合这个方案。')
    profileUndo.value = {
      applied: changes,
      values: Object.fromEntries(Object.keys(changes).map((key) => [key, current[key]])),
      dirty: Object.fromEntries(Object.keys(changes).map((key) => [dirtyKey(key), dirty.has(dirtyKey(key))])),
    }
    for (const [key, value] of Object.entries(changes)) { current[key] = value; dirty.add(dirtyKey(key)) }
    notify(`已应用“${trainingProfiles.find((item) => item.key === profile)?.label}”，修改 ${Object.keys(changes).length} 项。请保存或在开训前确认设置。`)
  }
  function undoProfile() {
    if (!profileUndo.value) return
    let retained = 0
    for (const [key, value] of Object.entries(profileUndo.value.values)) {
      if (!sameProfileValue(current[key], profileUndo.value.applied[key])) { retained++; continue }
      current[key] = value
      const path = dirtyKey(key)
      if (profileUndo.value.dirty[path]) dirty.add(path); else dirty.delete(path)
    }
    profileUndo.value = null
    notify(retained ? `已撤销方案，保留了应用后手动调整的 ${retained} 项参数。` : '已恢复应用方案前的参数和修改状态。')
  }
  return { profileUndo, profileDefaults, profileSupported, applyProfile, undoProfile }
}
