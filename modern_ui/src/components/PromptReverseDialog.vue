<script setup lang="ts">
import { computed, nextTick, onUnmounted, reactive, ref, watch } from 'vue'
import type { CaptionServiceSettings, PromptReverseReport } from '../bridge'
import UiIcon from './UiIcon.vue'

const props = defineProps<{ open: boolean; desktop: boolean }>()
const emit = defineEmits<{ close: []; notify: [message: string] }>()
const dialogRef = ref<HTMLElement | null>(null)
let previousFocus: HTMLElement | null = null
const path = ref('')
const method = ref<'natural' | 'wd14'>('wd14')
const language = ref<'zh' | 'en'>('zh')
const length = ref<'brief' | 'detailed'>('brief')
const wd14Model = ref('swinv2-v3')
const threshold = ref(.35)
const settings = reactive<CaptionServiceSettings>({ provider:'compatible', base_url:'http://127.0.0.1:1234/v1', model:'', unload_after:true })
const apiKey = ref('')
const dirty = ref(false)
const saving = ref(false)
const allowRemote = ref(false)
const taskId = ref('')
const busy = ref(false)
const starting = ref(false)
const exporting = ref(false)
const message = ref('')
const detail = ref('')
const progress = ref<number | null>(null)
const report = ref<PromptReverseReport | null>(null)
const edits = ref<Record<string,string>>({})
const thumbnails = ref<Record<string,string>>({})
const page = ref(0)
const outputPath = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
let revision = 0
const pageSize = 12
const pageCount = computed(() => Math.max(1, Math.ceil((report.value?.items.length || 0) / pageSize)))
const visible = computed(() => (report.value?.items || []).slice(page.value * pageSize, (page.value + 1) * pageSize))
const generated = computed(() => (report.value?.items || []).filter(item => item.status === 'generated'))
const remote = computed(() => {
  try { return !['localhost','127.0.0.1','[::1]','::1'].includes(new URL(settings.base_url).hostname.toLowerCase()) }
  catch { return true }
})
function serviceChanged() { dirty.value = true; allowRemote.value = false }
function stopPolling() { if (timer) clearTimeout(timer); timer = undefined }
function handleKeys(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); emit('close'); return }
  if (event.key !== 'Tab' || !dialogRef.value) return
  const controls = [...dialogRef.value.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea,summary')].filter(el => el.getClientRects().length)
  const first = controls[0], last = controls[controls.length - 1]
  if (!first || !last) { event.preventDefault(); dialogRef.value.focus(); return }
  if (event.shiftKey && (document.activeElement === first || document.activeElement === dialogRef.value)) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialogRef.value)) { event.preventDefault(); first.focus() }
}

async function poll() {
  const api = window.pywebview?.api
  if (!api || !props.open || !taskId.value) return
  const current = revision
  try {
    const result = await api.get_prompt_reverse(taskId.value)
    if (current !== revision || !props.open) return
    if (result.report) {
      report.value = result.report
      for (const item of result.report.items) if (item.caption !== undefined && edits.value[item.name] === undefined) edits.value[item.name] = item.caption
      if (page.value >= pageCount.value) page.value = pageCount.value - 1
    }
    busy.value = result.task?.status === 'running'
    detail.value = result.task?.detail || ''
    progress.value = result.task?.progress ?? null
    message.value = result.task?.message || result.report?.error || ''
    if (!busy.value) { void loadThumbnails(); return }
  } catch { message.value = '进度暂时无法读取，关闭后重新打开工具可继续查看。' }
  if (props.open && current === revision) timer = setTimeout(() => { void poll() }, 1000)
}
async function loadThumbnails() {
  const api = window.pywebview?.api
  if (!api || !taskId.value || !props.open) return
  const id = taskId.value
  for (const item of visible.value) {
    if (thumbnails.value[item.name]) continue
    try {
      const result = await api.get_prompt_reverse_image(id, item.name)
      if (id !== taskId.value || !props.open) return
      if (result.data_url) thumbnails.value[item.name] = result.data_url
    } catch { /* A missing thumbnail does not hide the generated text. */ }
  }
}
async function choose(kind: 'image' | 'folder') {
  const api = window.pywebview?.api
  if (!props.desktop || !api) { message.value = '请在桌面版选择本机图片。'; return }
  try {
    const result = await api.choose_path(kind, path.value, 'prompt_reverse_input')
    if (result.ok && result.path) path.value = result.path
    else if (result.error) message.value = result.error
  } catch { message.value = '文件选择器暂时不可用。' }
}
async function saveService() {
  const api = window.pywebview?.api
  if (!api || saving.value) return
  saving.value = true
  try {
    const result = await api.save_caption_service({ ...settings, api_key:apiKey.value })
    if (!result.ok) { message.value = result.error || '服务设置保存失败。'; return }
    if (result.settings) Object.assign(settings, result.settings)
    apiKey.value = ''; dirty.value = false; message.value = '视觉服务设置已保存。'
  } catch { message.value = '服务设置保存失败。' }
  finally { saving.value = false }
}
async function start() {
  const api = window.pywebview?.api
  if (!props.desktop || !api) { message.value = '浏览器预览不会调用模型或写文件。'; return }
  if (starting.value || busy.value) return
  if (!path.value.trim()) { message.value = '请选择一张图片或图片文件夹。'; return }
  if (method.value === 'natural' && (dirty.value || apiKey.value)) { message.value = '请先保存视觉服务设置。'; return }
  if (method.value === 'natural' && remote.value && !allowRemote.value) { message.value = '请确认允许发送图片到所选在线视觉服务。'; return }
  starting.value = true
  try {
    const result = await api.start_prompt_reverse({ path:path.value, method:method.value, language:language.value, length:length.value,
      wd14_model:wd14Model.value, threshold:threshold.value, allow_remote:allowRemote.value })
    if (!result.ok || !result.task_id) { message.value = result.error || '反推未启动。'; return }
    revision++; stopPolling(); taskId.value = result.task_id; report.value = null; edits.value = {}; thumbnails.value = {}; page.value = 0
    busy.value = true; message.value = '正在准备反推…'; detail.value = ''; progress.value = null; void poll()
  } catch { message.value = '无法启动反推，请重新打开本地新版界面。' }
  finally { starting.value = false }
}
async function stop() {
  if (!window.pywebview?.api || !taskId.value) return
  const result = await window.pywebview.api.cancel_task(taskId.value)
  message.value = result.ok ? '正在停止…' : result.error || '停止失败。'
}
async function copy(text: string) {
  try { await navigator.clipboard.writeText(text); emit('notify','提示词已复制。') }
  catch { message.value = '无法访问剪贴板，请选中文本后手动复制。' }
}
async function exportText() {
  const api = window.pywebview?.api
  if (!api || exporting.value || !generated.value.length) return
  exporting.value = true
  try {
    const chosen = await api.choose_path('folder', outputPath.value, 'prompt_reverse_output')
    if (!chosen.ok || !chosen.path) { if (chosen.error) message.value = chosen.error; return }
    const result = await api.export_prompt_reverse(taskId.value, generated.value.map(item => ({ name:item.name, caption:edits.value[item.name] ?? item.caption ?? '' })), chosen.path)
    if (!result.ok) { message.value = result.error || '导出失败。'; return }
    outputPath.value = result.directory || chosen.path
    message.value = `已导出 ${result.written} 个 TXT：${outputPath.value}`
    emit('notify', message.value)
  } catch { message.value = '导出失败，请检查输出文件夹权限。' }
  finally { exporting.value = false }
}
watch(() => props.open, async open => {
  revision++; stopPolling()
  if (!open) { previousFocus?.focus(); return }
  previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  await nextTick(); dialogRef.value?.focus()
  if (!props.desktop || !window.pywebview?.api) return
  const current = revision
  try {
    const service = await window.pywebview.api.get_caption_service()
    if (current !== revision || !props.open) return
    if (service.settings && !dirty.value) Object.assign(settings,service.settings)
    const result = await window.pywebview.api.get_prompt_reverse(taskId.value)
    if (current !== revision || !props.open) return
    if (result.task_id) { taskId.value = result.task_id; void poll() }
  } catch { message.value = '反推接口暂时不可用，请重启本地新版界面。' }
})
watch(page, () => { void loadThumbnails() })
onUnmounted(() => { revision++; stopPolling() })
</script>

<template>
  <Transition name="dialog">
    <div v-if="open" class="dialog-backdrop" @keydown="handleKeys">
      <section ref="dialogRef" class="reverse-dialog" tabindex="-1" role="dialog" aria-modal="true" aria-labelledby="reverse-title">
        <header><div><h2 id="reverse-title">反推提示词</h2><p>选择图片，生成可编辑的画面描述或关键词 · 无需训练项目</p></div><button type="button" class="icon-button" aria-label="关闭反推工具" @click="emit('close')"><UiIcon name="close" /></button></header>
        <main class="reverse-layout">
          <section class="reverse-options" aria-label="反推设置">
            <label>图片或文件夹<input v-model="path" :disabled="busy || starting" placeholder="选择一张图片，或粘贴图片文件夹路径" /></label>
            <div class="actions"><button type="button" :disabled="busy || starting" @click="choose('image')">选择图片</button><button type="button" :disabled="busy || starting" @click="choose('folder')">选择文件夹</button></div>
            <p>文件夹包含子文件夹，一次最多 500 张。原图和旁边已有的标签文件均保留。</p>
            <label>生成方式<select v-model="method" :disabled="busy || starting"><option value="wd14">英文关键词 · 本地 WD14</option><option value="natural">中文 / 英文描述 · 视觉模型</option></select></label>
            <template v-if="method === 'wd14'">
              <label>打标模型<select v-model="wd14Model" :disabled="busy"><option value="swinv2-v3">swinv2-v3（推荐）</option><option value="moat-v2">moat-v2</option></select></label>
              <label>关键词阈值<input v-model.number="threshold" type="number" min="0.01" max="0.99" step="0.05" :disabled="busy" /></label>
              <p>适合提取标签式提示词。阈值越低，关键词越多；首次使用可能下载 WD14 模型并补齐本地依赖。</p>
            </template>
            <template v-else>
              <div class="fields"><label>语言<select v-model="language" :disabled="busy"><option value="zh">中文</option><option value="en">英文</option></select></label><label>描述长度<select v-model="length" :disabled="busy"><option value="brief">简短</option><option value="detailed">详细</option></select></label></div>
              <details :open="!settings.model"><summary>视觉服务设置 <small>{{ settings.model || '尚未配置' }}</small></summary>
                <label>接口类型<select v-model="settings.provider" :disabled="busy" @change="serviceChanged"><option value="compatible">兼容视觉接口</option><option value="ollama">Ollama 本地服务</option></select></label>
                <label>地址<input v-model="settings.base_url" :disabled="busy" @input="serviceChanged" /></label>
                <label>视觉模型名称<input v-model="settings.model" :disabled="busy" placeholder="支持图片输入的模型名称" @input="serviceChanged" /></label>
                <label v-if="settings.provider === 'compatible'">API 密钥<input v-model="apiKey" type="password" autocomplete="off" :disabled="busy" :placeholder="settings.has_key ? '已保存，留空继续使用' : '无鉴权的本地服务可留空'" @input="serviceChanged" /></label>
                <label v-if="settings.provider === 'ollama'" class="check"><input v-model="settings.unload_after" type="checkbox" :disabled="busy" @change="serviceChanged" />完成后请求卸载模型</label>
                <p>与训练页的图片描述服务共用设置；文字聊天模型不一定支持图片。密钥在 Windows 用户下加密保存。</p>
                <button type="button" :disabled="busy || saving || !desktop" @click="saveService">{{ saving ? '保存中…' : '保存视觉服务' }}</button>
              </details>
              <label v-if="remote" class="check"><input v-model="allowRemote" type="checkbox" :disabled="busy" />允许将所选图片发送到上述在线视觉服务，可能产生 API 费用</label>
              <p v-else>图片发送到本机视觉服务。此入口不会自动下载视觉模型；训练前请在服务中检查显存释放。</p>
            </template>
            <button class="primary" type="button" :disabled="busy || starting || saving || !path.trim()" @click="start">{{ busy ? '正在反推…' : starting ? '正在启动…' : '开始反推' }}</button>
            <div v-if="busy" class="running" role="status"><p>{{ detail || '正在准备模型或等待视觉服务…' }}</p><progress v-if="progress !== null" :value="progress" max="1"></progress><button type="button" @click="stop">停止反推</button><small>关闭窗口后，已启动的任务会继续执行。</small></div>
          </section>
          <section class="reverse-results" aria-label="反推结果">
            <div class="result-heading"><strong>反推结果 <small v-if="report">{{ report.generated }} / {{ report.total }} 张{{ report.failed ? ` · ${report.failed} 张失败` : '' }}</small></strong><div class="actions"><button type="button" :disabled="!generated.length" @click="copy(generated.map(item => edits[item.name] || item.caption || '').join('\n\n'))">复制全部</button><button type="button" :disabled="busy || exporting || !generated.length" @click="exportText">{{ exporting ? '导出中…' : '导出 TXT' }}</button></div></div>
            <div v-if="!report?.items.length" class="empty"><UiIcon name="image" /><h3>从图片开始</h3><p>生成后可以逐张查看、编辑和复制。导出时选择独立文件夹，每张图片对应一个 TXT。</p></div>
            <article v-for="item in visible" :key="item.name" class="result-card"><img v-if="thumbnails[item.name]" :src="thumbnails[item.name]" :alt="item.name" /><div><header><strong>{{ item.name }}</strong><button v-if="item.status === 'generated'" type="button" @click="copy(edits[item.name] || '')">复制</button></header><textarea v-if="item.status === 'generated'" v-model="edits[item.name]" :readonly="busy" rows="5" maxlength="8192" :aria-label="`${item.name} 的提示词`"></textarea><p v-else class="error">{{ item.error }}</p></div></article>
            <div v-if="pageCount > 1" class="pagination"><button :disabled="page === 0" @click="page--">上一页</button><span>{{ page + 1 }} / {{ pageCount }}</span><button :disabled="page + 1 >= pageCount" @click="page++">下一页</button></div>
          </section>
        </main>
        <footer><p v-if="message" class="feedback" role="status">{{ message }}</p><p>反推根据可见画面生成描述，无法还原原始提示词、负面词、底模、LoRA 或种子；相同提示词也不保证复现原图。</p></footer>
      </section>
    </div>
  </Transition>
</template>
<style scoped>
.reverse-dialog{width:min(1120px,calc(100vw - 36px));max-height:92vh;display:flex;flex-direction:column;color:var(--text);background:var(--card);border:1px solid var(--border);border-radius:12px;box-shadow:0 20px 80px #0005;overflow:hidden}.reverse-dialog>header{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:20px 24px;border-bottom:1px solid var(--border)}h2{margin:0;font-size:21px}p{margin:0;color:var(--hint);font-size:12px;line-height:1.7;overflow-wrap:anywhere}.reverse-dialog>header p{margin-top:5px}.reverse-layout{display:grid;grid-template-columns:320px minmax(0,1fr);min-height:0;overflow:auto}.reverse-options{display:flex;flex-direction:column;gap:13px;padding:20px;border-right:1px solid var(--border);background:var(--bg)}label{display:grid;gap:7px;font-size:12px}input:not([type=checkbox]),select,textarea{box-sizing:border-box;width:100%;min-width:0;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--text);padding:9px;font:inherit}textarea{resize:vertical;line-height:1.65}.fields{display:grid;grid-template-columns:1fr 1fr;gap:12px}button{border:1px solid var(--border);border-radius:6px;background:var(--card);color:var(--text);padding:8px 11px;font:inherit;font-size:12px;cursor:pointer}button:hover:enabled{border-color:var(--hint)}button:disabled{opacity:.5;cursor:default}.primary{background:var(--accent);color:var(--tone-f0f1f3)}.actions{display:flex;gap:8px;flex-wrap:wrap}.check{display:flex;align-items:flex-start;gap:8px;line-height:1.6}.check input{flex:none;accent-color:var(--accent);margin-top:3px}summary{cursor:pointer;font-size:12px;padding:7px 0}details[open]{display:grid;gap:12px}small{font-size:11px;color:var(--hint)}.running{display:grid;gap:9px}progress{width:100%;accent-color:var(--accent)}.reverse-results{min-width:0;padding:20px;display:flex;flex-direction:column;gap:14px}.result-heading{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;font-size:13px}.result-heading small{display:block;margin-top:5px}.empty{min-height:280px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;text-align:center}.empty svg{width:36px;height:36px;color:var(--hint)}.empty h3{margin:0;font-size:16px}.empty p{max-width:340px}.result-card{display:flex;align-items:start;gap:14px;padding:12px;border:1px solid var(--border);border-radius:8px}.result-card>img{width:110px;height:140px;object-fit:contain;border-radius:5px;background:var(--bg)}.result-card>div{min-width:0;flex:1}.result-card header{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:9px}.result-card strong{font-size:12px;overflow-wrap:anywhere}.pagination{display:flex;align-items:center;justify-content:center;gap:14px;font-size:12px}.reverse-dialog>footer{padding:12px 20px;border-top:1px solid var(--border)}.feedback{color:var(--text);margin-bottom:6px}.error{color:var(--tone-d4b06a)}.icon-button{padding:7px;display:grid;place-items:center}.icon-button svg{width:18px;height:18px}button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}@media(max-width:760px){.reverse-layout{grid-template-columns:1fr}.reverse-options{border-right:0;border-bottom:1px solid var(--border)}.result-card>img{width:80px;height:100px}.reverse-dialog>header{padding:15px}}
</style>
