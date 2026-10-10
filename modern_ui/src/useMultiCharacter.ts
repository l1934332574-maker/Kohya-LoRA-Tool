import { computed, ref, watch, type Ref } from 'vue'
import type { ProjectConfig, MultiCharacterSettings } from './bridge'

export function importedMultiSettings(value: unknown): MultiCharacterSettings {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('多角色配置格式无效。')
  const data = value as Record<string, unknown>
  const rows = (key: string) => {
    const items = data[key] ?? []
    if (!Array.isArray(items) || items.length > 128 || items.some(row => !row || typeof row !== 'object' || Array.isArray(row))) throw new Error('多角色列表格式无效。')
    return items as Array<Record<string, unknown>>
  }
  const text = (value: unknown) => {
    if (value === undefined) return ''
    if (typeof value !== 'string' || value.length > 4096 || value.includes('\0')) throw new Error('多角色字段格式无效。')
    return value.trim()
  }
  const roles = rows('roles').map(row => ({ id: text(row.id), name: text(row.name), trigger: text(row.trigger), directory: '', description: text(row.description) }))
  const ids = new Set(roles.map(r => r.id))
  if (ids.size !== roles.length || roles.some(r => !/^[a-zA-Z0-9_-]{1,64}$/.test(r.id))) throw new Error('角色 ID 无效或重复。')
  const triggers = roles.map(r => r.trigger.toLowerCase()).filter(Boolean)
  if (new Set(triggers).size !== triggers.length || roles.some(r => r.trigger && !/^[a-zA-Z][a-zA-Z0-9_]{2,63}$/.test(r.trigger))) throw new Error('角色触发词无效或重复。')
  const roleIds = (value: unknown) => {
    if (!Array.isArray(value) || value.some(id => typeof id !== 'string' || !ids.has(id)) || new Set(value).size !== value.length) throw new Error('组合引用了未知或重复角色。')
    return value as string[]
  }
  const groups = rows('groups').map(row => {
    const members = row.members ?? []
    if (!Array.isArray(members) || members.some(m => !m || typeof m !== 'object' || Array.isArray(m))) throw new Error('同框角色格式无效。')
    roleIds(members.map(m => m.role_id))
    return { id: text(row.id), name: text(row.name), directory: '', caption: text(row.caption), reviewed: false,
      members: members.map(m => ({ role_id: text(m.role_id), position: text(m.position) })) }
  })
  const groupIds = new Set(groups.map(g => g.id))
  if (groupIds.size !== groups.length || groups.some(g => ids.has(g.id) || !/^[a-zA-Z0-9_-]{1,64}$/.test(g.id))) throw new Error('同框组 ID 无效或重复。')
  const targets = rows('targets').map(row => ({ role_ids: roleIds(row.role_ids ?? []), prompt: text(row.prompt) }))
  if (data.balance !== undefined && typeof data.balance !== 'boolean') throw new Error('角色采样开关无效。')
  return { roles, groups, targets, balance: data.balance !== false }
}

export function useMultiCharacter(config: () => ProjectConfig | null | undefined, dirty: Set<string>) {
  const isMulti = computed(() => config()?.training_kind === 'multi_character')
  const multiSettings: Ref<MultiCharacterSettings> = ref({ roles: [], groups: [], targets: [], balance: true })
  watch(config, (value) => {
    const settings = value?.multi_character
    multiSettings.value = settings ? JSON.parse(JSON.stringify(settings)) : { roles: [], groups: [], targets: [], balance: true }
  }, { immediate: true, deep: true })
  function updateMulti(value: MultiCharacterSettings) {
    multiSettings.value = value
    dirty.add('multi_character')
  }
  function multiPatch(patch: ProjectConfig) {
    if (!isMulti.value) return patch
    return {
      ...patch, training_kind: 'multi_character' as const, multi_character: multiSettings.value,
      at_sub_mode: 'character', trigger: '',
      params: { ...patch.params, strong_bind: false, clean_concept: false, keep_user_captions: true, caption_method: 'existing', crop_ratio: '' },
    }
  }
  return { isMulti, multiSettings, updateMulti, multiPatch }
}
