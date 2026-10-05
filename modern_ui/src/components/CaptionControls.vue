<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import type { CaptionReport, CaptionServiceSettings, ModernTaskStatus } from '../bridge'

const props = defineProps<{ projectName: string; directory: string; desktop: boolean; method: string; language: string; length: string }>()
const emit = defineEmits<{ 'update:method': [value: string]; 'update:language': [value: string]; 'update:length': [value: string] }>()
const settings = reactive<CaptionServiceSettings>({ provider: 'compatible', base_url: 'http://127.0.0.1:1234/v1', model: '', unload_after: true, has_key: false })
const apiKey = ref('')
const clearKey = ref(false)
const serviceOpen = ref(false)
const message = ref('')
const settingsDirty = ref(false)
const saving = ref(false)
const allowRemote = ref(false)
const overwriteText = ref(false)
const taskId = ref('')
const task = ref<ModernTaskStatus | null>(null)
const report = ref<CaptionReport | null>(null)
const busy = ref(false)
const thumbnails = ref<Record<string, string>>({})
const taskDirectory = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
const remote = computed(() => {
  try { return !['localhost', '127.0.0.1', '[::1]', '::1'].includes(new URL(settings.base_url).hostname.toLowerCase()) }
  catch { return true }
})
const percentage = computed(() => task.value?.progress == null ? null : Math.round(task.value.progress * 100))
const resultItems = computed(() => report.value?.items.filter((item) => item.status !== 'existing').slice(0, 30) || [])
function serviceChanged() { settingsDirty.value = true; allowRemote.value = false }

async function loadSettings() {
  if (!props.desktop || !window.pywebview?.api) return
  try {
    const result = await window.pywebview.api.get_caption_service()
    if (result.ok && result.settings) Object.assign(settings, result.settings)
    else message.value = result.error || '无法读取服务设置。'
    if (result.task?.project_name === props.projectName) {
      taskId.value = result.task.id
      taskDirectory.value = props.directory
      busy.value = ['running', 'awaiting_review'].includes(result.task.status)
      void poll()
    }
  } catch { message.value = '图片描述接口尚未就绪，请重新启动本地新版界面。' }
}
async function saveService() {
  if (!props.desktop || !window.pywebview?.api || saving.value) return
  saving.value = true
  try {
    const result = await window.pywebview.api.save_caption_service({ ...settings, api_key: apiKey.value, clear_key: clearKey.value })
    if (!result.ok) { message.value = result.error || '保存失败。'; return }
    if (result.settings) Object.assign(settings, result.settings)
    apiKey.value = ''; clearKey.value = false; settingsDirty.value = false
    message.value = '服务设置已保存；请先生成预览确认模型能描述图片。'
  } catch { message.value = '服务设置保存失败。' }
  finally { saving.value = false }
}
async function poll() {
  if (disposed || !taskId.value || !window.pywebview?.api) return
  try {
    const status = await window.pywebview.api.get_task_status(taskId.value)
    if (!status.ok) { busy.value = false; message.value = status.error || '任务已结束或被替换。'; return }
    task.value = status
    busy.value = ['running', 'awaiting_review'].includes(status.status || '')
    if (!busy.value) {
      message.value = status.message || ''
      const result = await window.pywebview.api.get_caption_report(taskId.value)
      report.value = result.ok ? result.report || null : null
      if (report.value?.directory) taskDirectory.value = report.value.directory
      if (report.value && taskDirectory.value) void loadThumbnails().catch(() => {})
      return
    }
  } catch { message.value = '暂时无法读取进度，可稍后重新打开此项目查看。' }
  if (!disposed) timer = setTimeout(() => { void poll() }, 1000)
}
async function loadThumbnails() {
  const api = window.pywebview?.api
  if (!api || disposed) return
  const id = taskId.value
  const catalog = await api.inspect_dataset(taskDirectory.value)
  if (!catalog.ok || !catalog.preview_token) return
  for (const item of resultItems.value.slice(0, 3)) {
    const image = await api.get_dataset_preview(catalog.preview_token, item.name)
    if (disposed || id !== taskId.value) return
    if (image.ok && image.data_url) thumbnails.value[item.name] = image.data_url
  }
}
async function start(preview: boolean, retry = false) {
  if (!props.desktop || !window.pywebview?.api) { message.value = '界面预览不会调用模型服务或写文件。'; return }
  if (settingsDirty.value || apiKey.value || clearKey.value) { message.value = '请先保存描述服务设置。'; serviceOpen.value = true; return }
  if (!props.directory) { message.value = '请先选择原始图片文件夹。'; return }
  if (remote.value && !allowRemote.value) { message.value = '请先确认允许把图片发送到所选在线服务。'; return }
  const oldId = taskId.value
  busy.value = true
  try {
    const result = await window.pywebview.api.start_caption_task(props.projectName, {
      directory: props.directory, language: props.language, length: props.length,
      preview, replace: overwriteText.value, allow_remote: allowRemote.value,
      retry_task_id: retry ? oldId : '',
    })
    if (!result.ok || !result.task_id) { busy.value = false; message.value = result.error || '任务未启动。'; return }
    taskId.value = result.task_id; taskDirectory.value = props.directory; task.value = null; report.value = null; thumbnails.value = {}; message.value = ''
    if (timer) clearTimeout(timer)
    void poll()
  } catch { busy.value = false; message.value = '无法启动描述任务。' }
}
async function stop() {
  if (!taskId.value || !window.pywebview?.api) return
  const result = await window.pywebview.api.cancel_task(taskId.value)
  message.value = result.ok ? '已请求停止；已发出的服务请求可能仍在执行，返回后不会再写文本。' : result.error || '停止失败。'
}
onMounted(() => { void loadSettings() })
onUnmounted(() => { disposed = true; if (timer) clearTimeout(timer) })
</script>

<template>
  <section class="caption-controls" aria-label="图片标签与描述">
    <label class="caption-field"><span>图片标签与描述</span><select :value="method" :disabled="busy" @change="emit('update:method', ($event.target as HTMLSelectElement).value)"><option value="wd14">关键词标签（WD14）</option><option value="natural">自然语言描述</option><option value="existing">使用已有文本（不自动生成）</option></select></label>
    <p v-if="method === 'wd14'">使用下方 WD14 模型生成关键词。中文与英文自然语言描述可切换到另一种生成方式。</p>
    <p v-else-if="method === 'existing'">不调用描述服务或 WD14。请准备同名 .txt；自然语言文本请选择“自然语言描述”，以跳过关键词处理。</p>
    <template v-else>
      <div class="caption-fields"><label class="caption-field"><span>描述语言</span><select :value="language" :disabled="busy" @change="emit('update:language', ($event.target as HTMLSelectElement).value)"><option value="zh">中文</option><option value="en">英文</option></select></label><label class="caption-field"><span>描述长度</span><select :value="length" :disabled="busy" @change="emit('update:length', ($event.target as HTMLSelectElement).value)"><option value="brief">简短（1–2句）</option><option value="detailed">详细（3–5句）</option></select></label></div>
      <p>先预览最多 3 张，不写文件；同一次运行中，图片、模型与选项未变时，批量会复用预览描述；批量生成写入原图旁的同名 .txt。训练只读取这些文本，不自动调用服务。自然语言不执行关键词清洗或强绑定，触发词独立添加到首行。</p>
      <details :open="serviceOpen" @toggle="serviceOpen = ($event.target as HTMLDetailsElement).open">
        <summary>描述服务设置 <span>{{ settings.model || '尚未设置模型' }}</span></summary>
        <div class="caption-fields"><label class="caption-field"><span>接口类型</span><select v-model="settings.provider" :disabled="busy" @change="serviceChanged"><option value="compatible">兼容视觉接口（本地或在线）</option><option value="ollama">Ollama 本地服务</option></select></label><label class="caption-field"><span>视觉模型名称</span><input v-model="settings.model" :disabled="busy" placeholder="填写服务实际提供的视觉模型名" @input="serviceChanged" /></label></div>
        <label class="caption-field"><span>服务地址</span><input v-model="settings.base_url" :disabled="busy" :placeholder="settings.provider === 'ollama' ? 'http://127.0.0.1:11434' : 'http://127.0.0.1:1234/v1'" @input="serviceChanged" /></label>
        <p>兼容接口填写以 /v1 等为结尾的基础地址，服务必须支持图片输入；Ollama 填写本机根地址。这里填写看图模型名称，不是 Anima 或 Qwen-Image 等训练底模。此功能不会安装或下载模型。</p>
        <label v-if="settings.provider === 'compatible'" class="caption-field"><span>API 密钥（可选，Windows 用户加密保存）</span><input v-model="apiKey" type="password" autocomplete="off" :disabled="busy" :placeholder="settings.has_key ? '已保存，留空继续使用；修改地址会清除旧密钥' : '本地无鉴权服务可留空'" /></label>
        <label v-if="settings.has_key" class="caption-check"><input v-model="clearKey" type="checkbox" :disabled="busy" />清除已保存的密钥</label>
        <label v-if="settings.provider === 'ollama'" class="caption-check"><input v-model="settings.unload_after" type="checkbox" :disabled="busy" @change="serviceChanged" />描述完成后请求卸载本次模型</label>
        <p v-else>通用接口不保证自动卸载本地模型；训练前请在模型服务中释放显存。</p>
        <button type="button" :disabled="busy || saving || !desktop" @click="saveService">{{ saving ? '保存中…' : '保存服务设置' }}</button>
      </details>
      <label v-if="remote" class="caption-check remote-notice"><input v-model="allowRemote" type="checkbox" :disabled="busy" />允许把本次图片发送到上述在线服务（可能产生 API 费用）</label>
      <label class="caption-check"><input v-model="overwriteText" type="checkbox" :disabled="busy" />重新生成已有文本，并备份原文件（默认只补缺失）</label>
      <p v-if="overwriteText">原文本备份在图集的 .caption_backups 文件夹；不会覆盖原图。</p>
      <div class="caption-actions"><button type="button" :disabled="busy || saving" @click="start(true)">先预览 3 张</button><button type="button" :disabled="busy || saving" @click="start(false)">{{ overwriteText ? '重新生成并备份' : '批量补齐描述' }}</button><button v-if="report?.failed" type="button" :disabled="busy" @click="start(Boolean(report.preview), true)">只重试失败图片</button><button v-if="busy" type="button" @click="stop">停止</button></div>
      <p v-if="busy" role="status">{{ task?.detail || '正在准备…' }}{{ percentage == null ? '' : ` · ${percentage}%` }}</p>
      <p v-if="report?.directory && report.directory !== directory">结果来自：{{ report.directory }}，当前文件夹已变化。</p>
      <p v-if="report">{{ report.preview ? '预览结果（未写文件）' : `写入 ${report.written} · 保留已有 ${report.skipped}` }} · 失败 {{ report.failed }}。文本是否适合底模仍需人工检查，支持中文不代表训练一定更好。</p>
      <div v-if="resultItems.length" class="caption-results"><article v-for="item in resultItems" :key="item.name"><strong>{{ item.name }}</strong><img v-if="thumbnails[item.name]" :src="thumbnails[item.name]" :alt="item.name" /><p :class="{ error: item.status === 'failed' }">{{ item.error || item.caption }}</p></article><p v-if="(report?.items.length || 0) > 30">页面最多展示 30 项；全部结果与失败信息保存在本地描述任务报告。</p></div>
    </template>
    <p v-if="message" class="caption-message" role="status">{{ message }}</p>
  </section>
</template>

<style scoped>
.caption-controls { display:grid; gap:9px; margin:12px 0; padding:12px; background:var(--bg); border:1px solid var(--border); border-radius:6px; color:var(--text); font-size:12px; }
.caption-controls p { margin:0; color:var(--hint); line-height:1.6; overflow-wrap:anywhere; }
.caption-fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
.caption-field { display:grid; gap:6px; min-width:0; }
input:not([type=checkbox]), select { box-sizing:border-box; width:100%; padding:8px; background:var(--bg); color:var(--text); border:1px solid var(--border); border-radius:4px; font:inherit; }
.caption-check { display:flex; gap:7px; align-items:flex-start; line-height:1.6; }
.caption-actions { display:flex; flex-wrap:wrap; gap:8px; }
button { padding:7px 10px; border:1px solid var(--border); border-radius:4px; background:var(--bg); color:var(--text); font:inherit; cursor:pointer; }
button:disabled { opacity:.5; cursor:default; }
summary { cursor:pointer; padding:6px 0; }
summary span { color:var(--hint); margin-left:8px; }
details[open] { display:grid; gap:10px; }
.caption-results { max-height:360px; overflow:auto; display:grid; gap:10px; }
.caption-results article { padding:9px; border:1px solid var(--border); border-radius:4px; }
.caption-results img { display:block; max-width:100%; max-height:180px; object-fit:contain; margin:6px 0; border-radius:4px; }
.caption-results strong { display:block; margin-bottom:6px; overflow-wrap:anywhere; }
.caption-results .error, .caption-message, .remote-notice { color:var(--tone-d4b06a); }
button:focus-visible, input:focus-visible, select:focus-visible, summary:focus-visible { outline:2px solid var(--tone-78869b); outline-offset:2px; }
@media(max-width:600px) { .caption-fields { grid-template-columns:1fr; } }
</style>
