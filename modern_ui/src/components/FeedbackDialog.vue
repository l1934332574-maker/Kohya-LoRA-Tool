<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()
const panel = ref<HTMLElement | null>(null)
const groupInput = ref<HTMLInputElement | null>(null)
const copyStatus = ref('')
let previousFocus: HTMLElement | null = null

watch(() => props.open, async (open) => {
  if (open) {
    previousFocus = document.activeElement as HTMLElement | null
    copyStatus.value = ''
    await nextTick()
    panel.value?.focus()
  } else {
    previousFocus?.focus()
  }
})

async function copyGroup() {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText('602396066')
    } else {
      groupInput.value?.focus()
      groupInput.value?.select()
      if (!document.execCommand('copy')) throw new Error('copy unavailable')
    }
    copyStatus.value = '群号已复制'
  } catch {
    groupInput.value?.focus()
    groupInput.value?.select()
    copyStatus.value = '请按 Ctrl+C 复制群号'
  }
}

function handleKey(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    emit('close')
  } else if (event.key === 'Tab') {
    const controls = panel.value?.querySelectorAll<HTMLElement>('button, input')
    if (!controls?.length) return
    const first = controls[0]!
    const last = controls[controls.length - 1]!
    if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.value)) {
      event.preventDefault(); last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus()
    }
  }
}
</script>

<template>
  <Transition name="dialog">
    <div v-if="open" class="dialog-backdrop" @click.self="emit('close')" @keydown="handleKey">
      <section ref="panel" class="project-dialog feedback-dialog" role="dialog" aria-modal="true" aria-labelledby="feedback-title" tabindex="-1">
        <header class="dialog-header">
          <h2 id="feedback-title">反馈与交流</h2>
          <button class="dialog-close" type="button" aria-label="关闭反馈窗口" @click="emit('close')">×</button>
        </header>
        <p class="feedback-intro">遇到问题、提出建议，或分享使用经验，欢迎加入 QQ 群。</p>
        <label class="field-label" for="feedback-group">反馈交流 QQ 群</label>
        <div class="feedback-group">
          <input id="feedback-group" ref="groupInput" class="dialog-input" value="602396066" readonly @focus="groupInput?.select()" />
          <button class="small-button" type="button" @click="copyGroup">复制群号</button>
        </div>
        <p class="feedback-note">反馈安装或训练问题时，请附上报错截图和“导出日志”生成的 TXT，方便定位。</p>
        <p class="feedback-status" role="status">{{ copyStatus }}</p>
      </section>
    </div>
  </Transition>
</template>

<style scoped>
.feedback-dialog { max-width: 400px; }
.feedback-intro { color: var(--sub); font-size: 13px; line-height: 1.7; }
.feedback-group { display: flex; align-items: center; gap: 10px; }
.feedback-group input { min-width: 0; font-size: 20px; letter-spacing: 2px; }
.feedback-group button { flex-shrink: 0; }
.feedback-note { margin-top: 16px; color: var(--hint); font-size: 12px; line-height: 1.7; }
.feedback-status { min-height: 18px; margin-bottom: 0; color: var(--sub); font-size: 12px; }
</style>
