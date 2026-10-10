<script setup lang="ts">
import { computed, ref } from 'vue'
import type { MultiCharacterSettings, MultiCharacterScan } from '../bridge'
import DatasetInspection from './DatasetInspection.vue'
const props = defineProps<{
  modelValue: MultiCharacterSettings; projectName: string; desktop: boolean;
  choosePath: (kind: 'folder' | 'model', currentPath?: string, memoryKey?: string) => Promise<string | null>;
}>()
const emit = defineEmits<{ 'update:modelValue': [value: MultiCharacterSettings]; notify: [message: string] }>()
const inspection = ref<MultiCharacterScan | null>(null)
const inspecting = ref(false)
const error = ref('')
const roleCount = computed(() => props.modelValue.roles.length)
const newId = () => 'r_' + crypto.randomUUID().replace(/-/g, '').slice(0, 12)
function change(apply: (settings: MultiCharacterSettings) => void) {
  const value: MultiCharacterSettings = JSON.parse(JSON.stringify(props.modelValue))
  apply(value); inspection.value = null; error.value = ''; emit('update:modelValue', value)
}
function addRole() {
  const id = newId()
  change(s => s.roles.push({ id, name: `角色 ${s.roles.length + 1}`, trigger: 'char_' + id.slice(2, 10), directory: '', description: '' }))
}
function removeRole(id: string) {
  change(s => {
    s.roles = s.roles.filter(r => r.id !== id)
    s.groups.forEach(g => { g.members = g.members.filter(m => m.role_id !== id); g.reviewed = false })
    s.targets.forEach(t => { t.role_ids = t.role_ids.filter(r => r !== id) })
  })
}
function field(index: number, key: 'name' | 'trigger' | 'description' | 'directory', event: Event) {
  change(s => { s.roles[index]![key] = (event.target as HTMLInputElement).value; s.groups.forEach(g => { g.reviewed = false }) })
}
async function browse(kind: 'role' | 'group', index: number) {
  const row = kind === 'role' ? props.modelValue.roles[index] : props.modelValue.groups[index]
  if (!row) return
  const id = row.id
  const folder = await props.choosePath('folder', row.directory, `multi_${kind}`)
  if (folder) change(s => {
    const selected = (kind === 'role' ? s.roles : s.groups).find(r => r.id === id)
    if (selected) selected.directory = folder
    if (kind === 'group') s.groups.forEach(g => { if (g.id === id) g.reviewed = false })
  })
}
function addGroup() {
  change(s => s.groups.push({ id: newId(), name: `同框组 ${s.groups.length + 1}`, directory: '', members: [], caption: '', reviewed: false }))
}
function groupField(index: number, key: 'name' | 'directory' | 'caption', event: Event) {
  change(s => { s.groups[index]![key] = (event.target as HTMLInputElement).value; s.groups[index]!.reviewed = false })
}
function member(group: number, roleId: string, event: Event) {
  change(s => {
    const g = s.groups[group]!
    g.members = g.members.filter(m => m.role_id !== roleId)
    if ((event.target as HTMLInputElement).checked) g.members.push({ role_id: roleId, position: '' })
    g.reviewed = false
  })
}
function position(group: number, roleId: string, event: Event) {
  change(s => { s.groups[group]!.members.find(m => m.role_id === roleId)!.position = (event.target as HTMLInputElement).value; s.groups[group]!.reviewed = false })
}
function toggleTarget(index: number, roleId: string, event: Event) {
  change(s => {
    const t = s.targets[index]!
    t.role_ids = t.role_ids.filter(r => r !== roleId)
    if ((event.target as HTMLInputElement).checked) t.role_ids.push(roleId)
  })
}
function roleName(id: string) { return props.modelValue.roles.find(r => r.id === id)?.name || id }
async function inspect() {
  if (!props.desktop || !window.pywebview?.api) return emit('notify', '浏览器预览不能检查本机素材。')
  inspecting.value = true; error.value = ''
  const snapshot = JSON.stringify(props.modelValue)
  try {
    const result = await window.pywebview.api.inspect_multi_character(props.projectName, props.modelValue)
    if (snapshot !== JSON.stringify(props.modelValue)) return
    if (!result.ok) error.value = result.error || '素材检查失败。'
    else inspection.value = result
  } catch (e) { error.value = e instanceof Error ? e.message : '素材检查失败。' }
  finally { inspecting.value = false }
}
</script>

<template>
  <section class="multi-panel">
    <header class="multi-heading"><div><span class="eyebrow">多角色 LoRA · 实验性</span><h2>角色与同框素材</h2><p>每个角色使用独立触发词。先验证单人身份，再验证同框组合。</p></div><span class="count">{{ roleCount }} 个角色</span></header>
    <section class="multi-section">
      <header><h3>01 角色库</h3><button type="button" @click="addRole">＋ 添加角色</button></header>
      <p v-if="!roleCount" class="empty">添加至少两个角色，并分别选择单人素材。</p>
      <div class="role-grid">
        <article v-for="(role, i) in modelValue.roles" :key="role.id" class="role-card">
          <header><strong>{{ role.name || `角色 ${i+1}` }}</strong><button class="text-button" type="button" @click="removeRole(role.id)">移除</button></header>
          <div class="fields"><label>名称<input :value="role.name" @input="field(i, 'name', $event)" /></label><label>触发词<input :value="role.trigger" spellcheck="false" @input="field(i, 'trigger', $event)" /></label></div>
          <label>单人素材目录<div class="path"><input :value="role.directory" placeholder="图片与同名 .txt" @input="field(i, 'directory', $event)" /><button type="button" @click="browse('role', i)">选择</button></div></label>
          <label>角色描述<textarea :value="role.description" placeholder="缺少逐图标签时使用；建议描述身份、外观和服装" rows="2" @input="field(i, 'description', $event)"></textarea></label>
          <details v-if="role.directory"><summary>查看原图与标签</summary><DatasetInspection :directory="role.directory" :desktop="desktop" :natural="true" :keep-captions="true" /></details>
        </article>
      </div>
      <label class="check"><input type="checkbox" :checked="modelValue.balance" @change="change(s => { s.balance = ($event.target as HTMLInputElement).checked })" />适度均衡角色采样<span>少样本角色最多增加到 3 倍，不替代补充素材。</span></label>
    </section>
    <section class="multi-section">
      <header><h3>02 同框素材</h3><button type="button" :disabled="roleCount < 2" @click="addGroup">＋ 添加同框组</button></header>
      <p class="hint">同组图片应包含相同角色。站位不同请分组，或为每张图准备准确的身份与位置描述。</p>
      <p v-if="!modelValue.groups.length" class="empty">尚无同框素材；可以训练分别调用角色，同框效果待验证。</p>
      <article v-for="(group, i) in modelValue.groups" :key="group.id" class="group-card">
        <header><input :value="group.name" aria-label="同框组名称" @input="groupField(i,'name',$event)" /><button class="text-button" type="button" @click="change(s => { s.groups.splice(i,1) })">移除</button></header>
        <label>素材目录<div class="path"><input :value="group.directory" @input="groupField(i,'directory',$event)" /><button type="button" @click="browse('group',i)">选择</button></div></label>
        <div class="role-chips"><label v-for="role in modelValue.roles" :key="role.id"><input type="checkbox" :checked="group.members.some(m => m.role_id===role.id)" @change="member(i,role.id,$event)" />{{ role.name }}</label></div>
        <div class="fields"><label v-for="m in group.members" :key="m.role_id">{{ roleName(m.role_id) }}的位置<input :value="m.position" placeholder="例如 on the left；已有逐图标签时可留空" @input="position(i,m.role_id,$event)" /></label></div>
        <label>场景／动作描述<textarea :value="group.caption" placeholder="缺少逐图标签时，与上方角色位置共同生成描述" rows="2" @input="groupField(i,'caption',$event)"></textarea></label>
        <details v-if="group.directory"><summary>查看原图与标签</summary><DatasetInspection :directory="group.directory" :desktop="desktop" :natural="true" :keep-captions="true" /></details>
        <label class="check"><input type="checkbox" :checked="group.reviewed" @change="change(s => { s.groups[i]!.reviewed = ($event.target as HTMLInputElement).checked })" />已确认这组每张图的身份与标注位置一致</label>
      </article>
    </section>
    <section class="multi-section">
      <header><h3>03 目标组合</h3><button type="button" :disabled="roleCount < 2" @click="change(s => s.targets.push({role_ids:[],prompt:''}))">＋ 添加组合</button></header>
      <p class="hint">按勾选顺序生成默认站位，也可填写完整提示词。没有对应同框素材的组合会标记为待验证。</p>
      <article v-for="(target, i) in modelValue.targets" :key="i" class="target-card">
        <header><strong>{{ target.role_ids.map(roleName).join(' ＋ ') || '选择至少两个角色' }}</strong><button class="text-button" type="button" @click="change(s => { s.targets.splice(i,1) })">移除</button></header>
        <div class="role-chips"><label v-for="role in modelValue.roles" :key="role.id"><input type="checkbox" :checked="target.role_ids.includes(role.id)" @change="toggleTarget(i,role.id,$event)" />{{ role.name }}</label></div>
        <textarea :value="target.prompt" placeholder="验证提示词（可选）；留空按勾选顺序生成从左到右的站位" rows="2" @input="change(s => { s.targets[i]!.prompt = ($event.target as HTMLTextAreaElement).value })"></textarea>
      </article>
      <p v-if="!modelValue.targets.length" class="empty">添加希望验证的同框组合。</p>
    </section>
    <footer class="multi-footer"><span>训练参数沿用当前模型。默认生成最多 6 条采样提示词，完整验证提示词保存到输出目录。</span><button type="button" :disabled="inspecting || !desktop" @click="inspect">{{ inspecting ? '检查中…' : '检查素材与标签' }}</button></footer>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <div v-if="inspection" class="inspection" role="status">
      <strong>{{ inspection.images }} 张原图 · 均衡后 {{ inspection.training_images }} 个训练样本</strong>
      <div v-for="row in inspection.roles" :key="row.id" class="inspection-row"><span>{{ row.name }}</span><span>{{ row.images }} 张 · {{ row.existing_captions }} 份已有标签 · 采样 ×{{ row.sampling_copies }}</span></div>
      <p v-for="warning in inspection.warnings" :key="warning" class="hint">{{ warning }}</p>
      <details><summary>查看验证提示词</summary><p v-for="(item,i) in inspection.validation" :key="i" class="prompt">{{ item.prompt }}</p></details>
    </div>
  </section>
</template>
<style scoped>
.multi-panel{padding:22px;background:var(--card);border:1px solid var(--border);border-radius:14px;min-width:0;margin-bottom:20px;color:var(--text)}.multi-heading,.multi-section>header,.role-card>header,.group-card>header,.target-card>header,.multi-footer{display:flex;justify-content:space-between;align-items:center;gap:12px}.multi-heading h2{font-size:20px;margin:5px 0}.eyebrow,.count{color:var(--hint);font-size:12px}.multi-heading p,.hint,.empty,.multi-footer>span{font-size:12px;line-height:1.7;color:var(--hint);margin:7px 0}.multi-section{padding-top:20px;margin-top:18px;border-top:1px solid var(--border)}h3{font-size:14px;margin:0}.role-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:12px;margin:14px 0}.role-card,.group-card,.target-card{display:grid;gap:12px;min-width:0;border:1px solid var(--border);border-radius:10px;padding:15px;background:var(--bg)}.group-card,.target-card{margin:12px 0}.role-card>header strong,.target-card strong{font-size:13px}.fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}label{display:grid;gap:6px;font-size:12px;min-width:0}input:not([type=checkbox]),textarea{width:100%;min-width:0;box-sizing:border-box;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:9px;font:inherit;line-height:1.5}textarea{resize:vertical}.path{display:flex;gap:8px;min-width:0}.path input{flex:1}button{flex-shrink:0;padding:8px 11px;background:var(--card);border:1px solid var(--border);border-radius:6px;color:var(--text);font:inherit;font-size:12px;cursor:pointer}button:disabled{opacity:.5;cursor:default}.text-button{padding:3px 0;border:0;background:transparent;color:var(--hint)}.check{display:flex;align-items:center;gap:8px;flex-wrap:wrap;line-height:1.6}.check span{color:var(--hint)}.role-chips{display:flex;flex-wrap:wrap;gap:8px}.role-chips label{display:flex;align-items:center;padding:6px 9px;border:1px solid var(--border);border-radius:6px}.multi-footer{padding-top:20px;align-items:flex-start}.error{font-size:13px;color:var(--warning,#e5ad6c);line-height:1.6;white-space:pre-wrap}.inspection{display:grid;gap:8px;padding:14px;margin-top:14px;background:var(--bg);border-radius:8px;font-size:12px}.inspection-row{display:flex;justify-content:space-between;gap:10px;color:var(--hint)}summary{font-size:12px;color:var(--hint);cursor:pointer}.prompt{overflow-wrap:anywhere;line-height:1.7}details{min-width:0}input:focus-visible,textarea:focus-visible,button:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}@media(max-width:650px){.multi-panel{padding:15px}.fields{grid-template-columns:1fr}.multi-footer{flex-direction:column}.inspection-row{flex-direction:column;gap:3px}}
</style>
