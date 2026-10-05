<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'

const props = defineProps<{ open: boolean; exportId: string; startError: string }>()
const emit = defineEmits<{ close: []; pending: [value: boolean]; completed: [path: string]; notify: [message: string]; retry: [] }>()
const panel = ref<HTMLElement | null>(null)
const pathInput = ref<HTMLTextAreaElement | null>(null)
const status = ref<'running' | 'completed' | 'failed'>('running')
const path = ref('')
const error = ref('')
const actionMessage = ref('')
const opening = ref(false)
const failure = computed(() => props.startError || error.value)
let previousFocus: HTMLElement | null = null
let timer: ReturnType<typeof setTimeout> | undefined
let generation = 0
let disposed = false

async function poll(id: string, version: number) {
  try {
    const api = window.pywebview?.api
    if (!api) throw new Error('无法连接本机服务，请查看运行日志或重新导出。')
    const result = await api.get_log_export_status(id)
    if (disposed || version !== generation) return
    if (!result.ok) throw new Error(result.error || '无法读取导出状态，请查看运行日志。')
    if (result.status === 'completed' && result.path) {
      status.value = 'completed'
      path.value = result.path
      emit('pending', false)
      emit('completed', result.path)
    } else if (result.status === 'failed') {
      status.value = 'failed'
      error.value = result.error || '日志导出失败，请重新导出。'
      emit('pending', false)
      if (!props.open) emit('notify', error.value)
    } else if (result.status === 'running') {
      timer = setTimeout(() => void poll(id, version), 800)
    } else {
      throw new Error('收到的导出状态不完整，请查看运行日志或重新导出。')
    }
  } catch (exception) {
    if (disposed || version !== generation) return
    status.value = 'failed'
    error.value = exception instanceof Error ? exception.message : '无法读取导出状态，请查看运行日志。'
    emit('pending', false)
    if (!props.open) emit('notify', error.value)
  }
}

watch(() => [props.exportId, props.startError], () => {
  const version = ++generation
  if (timer) clearTimeout(timer)
  status.value = props.startError ? 'failed' : 'running'
  path.value = ''; error.value = ''; actionMessage.value = ''
  if (props.exportId && !props.startError) { emit('pending', true); void poll(props.exportId, version) }
}, { immediate: true })

watch(() => props.open, async (open) => {
  if (open) {
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    panel.value?.focus()
  } else {
    await nextTick()
    if (previousFocus?.isConnected) previousFocus.focus()
  }
})

async function openResult(target: 'file' | 'folder') {
  if (opening.value || status.value !== 'completed') return
  opening.value = true; actionMessage.value = ''
  try {
    const api = window.pywebview?.api
    if (!api) throw new Error('无法连接本机服务，请复制路径后手动打开。')
    const result = await api.open_log_export(props.exportId, target)
    actionMessage.value = result.ok ? (target === 'file' ? '已请求打开日志文件。' : '已请求在文件夹中定位日志。') : result.error || '无法打开，请复制路径后手动打开。'
  } catch (exception) {
    actionMessage.value = exception instanceof Error ? exception.message : '无法打开，请复制路径后手动打开。'
  } finally { opening.value = false }
}

async function copyPath() {
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(path.value)
    else {
      pathInput.value?.focus(); pathInput.value?.select()
      if (!document.execCommand('copy')) throw new Error('copy unavailable')
    }
    actionMessage.value = '保存路径已复制。'
  } catch {
    pathInput.value?.focus(); pathInput.value?.select()
    actionMessage.value = '请按 Ctrl+C 复制已选中的路径。'
  }
}

function handleKey(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); emit('close') }
  else if (event.key === 'Tab') {
    const controls = panel.value?.querySelectorAll<HTMLElement>('button:not(:disabled), textarea')
    if (!controls?.length) return
    const first = controls[0]!, last = controls[controls.length - 1]!
    if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.value)) { event.preventDefault(); last.focus() }
    else if (!event.shiftKey && (document.activeElement === last || document.activeElement === panel.value)) { event.preventDefault(); first.focus() }
  }
}

onUnmounted(() => { disposed = true; generation++; if (timer) clearTimeout(timer) })
</script>

<template>
    <Transition name="dialog">
      <div v-if="open" class="dialog-backdrop log-export-backdrop" @click.self="emit('close')" @keydown="handleKey">
        <section ref="panel" class="project-dialog log-export-dialog" role="dialog" aria-modal="true" aria-labelledby="log-export-title" tabindex="-1">
          <header class="dialog-header">
            <h2 id="log-export-title">导出日志</h2>
            <button type="button" class="dialog-close" aria-label="关闭导出日志窗口" @click="emit('close')">×</button>
          </header>
          <div role="status" aria-live="polite">
            <template v-if="failure">
              <h3>日志导出未完成</h3>
              <p class="export-error">{{ failure }}</p>
            </template>
            <template v-else-if="status === 'completed'">
              <h3>运行日志已导出</h3>
              <p>将这个 TXT 文件发给维护者，方便排查问题。文件包含运行日志和环境信息。</p>
            </template>
            <template v-else>
              <h3>正在收集日志与环境信息…</h3>
              <progress aria-label="正在导出日志"></progress>
              <p>环境检查可能需要一些时间。关闭此窗口后仍会继续生成，可点击“查看导出进度”回来查看。</p>
            </template>
          </div>
          <template v-if="status === 'completed' && path">
            <label class="field-label" for="log-export-path">实际保存位置</label>
            <textarea id="log-export-path" ref="pathInput" class="dialog-input export-path" :value="path" readonly rows="2" @focus="pathInput?.select()"></textarea>
            <div class="export-tools">
              <button class="small-button primary" type="button" :disabled="opening" @click="openResult('file')">打开文件</button>
              <button class="small-button" type="button" :disabled="opening" @click="openResult('folder')">打开所在文件夹</button>
              <button class="small-button" type="button" @click="copyPath">复制路径</button>
            </div>
          </template>
          <p v-if="actionMessage" class="action-message" role="status">{{ actionMessage }}</p>
          <footer class="dialog-actions">
            <button v-if="failure" class="small-button primary" type="button" @click="emit('retry')">重新导出</button>
            <button class="small-button" type="button" @click="emit('close')">{{ status === 'running' && !failure ? '后台继续' : '关闭' }}</button>
          </footer>
        </section>
      </div>
    </Transition>
</template>

<style scoped>
.log-export-backdrop { z-index: 90; }
.log-export-dialog { width: min(100%, 600px); max-height: calc(100dvh - 40px); overflow-y: auto; }
.log-export-dialog h3 { margin: 0 0 10px; font-size: 16px; color: var(--text); }
.log-export-dialog p { margin: 10px 0; color: var(--sub); font-size: 13px; line-height: 1.7; overflow-wrap: anywhere; }
.log-export-dialog progress { width: 100%; height: 6px; accent-color: var(--text); }
.export-path { display: block; padding: 9px 10px; resize: vertical; font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
.export-tools { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.log-export-dialog .export-error { color: var(--tone-c99ea4); }
.log-export-dialog .action-message { margin-bottom: 0; }
@media (prefers-reduced-motion: reduce) { .dialog-enter-active .log-export-dialog, .dialog-leave-active .log-export-dialog { transition: none; } }
</style>
