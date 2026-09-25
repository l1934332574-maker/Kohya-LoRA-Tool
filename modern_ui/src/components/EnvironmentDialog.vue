<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import UiIcon from './UiIcon.vue'
import type { EnvLocations } from '../bridge'

const props = defineProps<{
  open: boolean
  choosePath: (kind: 'folder' | 'model') => Promise<string | null>
}>()
const emit = defineEmits<{
  close: []
  changed: []
  notify: [message: string]
}>()

const state = ref<EnvLocations | null>(null)
const busy = ref(false)
const error = ref('')
const configured = computed(() => state.value?.configured ?? {})

async function refresh() {
  if (!window.pywebview?.api) { error.value = '环境位置设置需要在桌面版运行。'; return }
  busy.value = true
  error.value = ''
  try {
    const result = await window.pywebview.api.get_env_locations()
    state.value = result
    if (!result.ok) error.value = result.error ?? '读取环境位置失败。'
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '读取环境位置失败。'
  } finally { busy.value = false }
}

async function choose(kind: 'python' | 'git') {
  const directory = await props.choosePath('folder')
  if (!directory || !window.pywebview?.api) return
  busy.value = true
  error.value = ''
  try {
    const result = await window.pywebview.api.set_env_location(kind, directory)
    if (!result.ok) error.value = result.error ?? '保存环境路径失败。'
    else {
      state.value = result
      emit('changed')
      emit('notify', kind === 'python' ? '已更新 Python 环境位置' : '已更新 Git 环境位置')
    }
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '保存环境路径失败。'
  } finally { busy.value = false }
}

async function reset() {
  if (!window.pywebview?.api) return
  busy.value = true
  error.value = ''
  try {
    const result = await window.pywebview.api.reset_env_locations()
    if (!result.ok) error.value = result.error ?? '恢复自动查找失败。'
    else {
      state.value = result
      emit('changed')
      emit('notify', 'Python 和 Git 已恢复自动查找')
    }
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '恢复自动查找失败。'
  } finally { busy.value = false }
}

watch(() => props.open, (open) => { if (open) void refresh() })
</script>

<template>
  <Transition name="dialog">
    <div v-if="open" class="environment-backdrop" @click.self="emit('close')">
      <section class="environment-dialog" role="dialog" aria-modal="true" aria-labelledby="environment-title">
        <header class="environment-header">
          <div><span class="environment-kicker">本机工具链</span><h2 id="environment-title">环境位置（自带 Python / Git）</h2></div>
          <button class="environment-close" type="button" aria-label="关闭" @click="emit('close')">×</button>
        </header>
        <p class="environment-description">如果 Python 或 Git 装在其他磁盘、整合包目录里，可以指定所在文件夹。软件会扫描并校验；精简版 Python（缺少 venv）不会被保存为可用环境。</p>
        <div class="environment-item">
          <div class="environment-item-icon"><UiIcon name="settings" /></div>
          <div class="environment-copy"><strong>Python</strong><span>{{ state?.python?.path || '未找到可用的 Python' }}<template v-if="state?.python?.version"> · {{ state.python.version }}</template></span><small>{{ configured.python_exe || configured.python_dir ? '当前使用自定义位置' : '当前由软件自动查找' }}</small></div>
          <button class="environment-button" type="button" :disabled="busy" @click="choose('python')">选择文件夹</button>
        </div>
        <div class="environment-item">
          <div class="environment-item-icon"><UiIcon name="settings" /></div>
          <div class="environment-copy"><strong>Git</strong><span>{{ state?.git?.path || '未找到 Git' }}</span><small>{{ configured.git_exe ? '当前使用自定义位置' : '当前由软件自动查找' }}</small></div>
          <button class="environment-button" type="button" :disabled="busy" @click="choose('git')">选择文件夹</button>
        </div>
        <p v-if="error" class="environment-error">{{ error }}</p>
        <footer class="environment-footer">
          <button class="environment-button" type="button" :disabled="busy" @click="reset">恢复自动查找</button>
          <button class="environment-button primary" type="button" @click="emit('close')">完成</button>
        </footer>
      </section>
    </div>
  </Transition>
</template>

<style scoped>
.environment-backdrop { position: fixed; inset: 0; z-index: 32; display: grid; place-items: center; padding: 20px; background: rgb(10 12 16 / 52%); }
.environment-dialog { width: min(100%, 600px); padding: 18px; border: 1px solid var(--tone-41464f); border-radius: 8px; background: var(--tone-272a32); box-shadow: 0 16px 44px rgb(0 0 0 / 32%); }
.environment-header { display: flex; justify-content: space-between; gap: 12px; }
.environment-kicker { color: var(--tone-858a93); font-size: 10px; }
.environment-header h2 { margin: 3px 0 0; color: var(--tone-cbd0d7); font-size: 17px; font-weight: 350; }
.environment-close { width: 29px; height: 29px; border: 0; border-radius: 5px; color: var(--tone-999da6); background: transparent; font-size: 22px; cursor: pointer; }
.environment-close:hover { color: var(--tone-d0d3d9); background: var(--tone-32363e); }
.environment-description { margin: 11px 0 14px; color: var(--tone-9ea4ae); font-size: 11px; line-height: 1.55; }
.environment-item { display: flex; align-items: center; gap: 10px; min-width: 0; margin-top: 7px; padding: 10px; border: 1px solid var(--tone-373b44); border-radius: 5px; background: var(--tone-23262d); }
.environment-item-icon { display: grid; width: 30px; height: 30px; flex: 0 0 auto; place-items: center; border: 1px solid var(--tone-3c424b); border-radius: 5px; color: var(--tone-9ea7b4); }
.environment-copy { display: grid; flex: 1; min-width: 0; gap: 3px; }
.environment-copy strong { color: var(--tone-bdc2cb); font-size: 11px; font-weight: 400; }
.environment-copy span { overflow: hidden; color: var(--tone-9299a4); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.environment-copy small { color: var(--tone-777e89); font-size: 9px; }
.environment-button { min-height: 29px; padding: 0 9px; border: 1px solid var(--tone-3c424b); border-radius: 4px; color: var(--tone-b9bec7); background: transparent; font-size: 10px; cursor: pointer; }
.environment-button:hover:not(:disabled) { border-color: var(--tone-575e69); background: var(--tone-2d3139); }
.environment-button:disabled { opacity: .5; cursor: wait; }
.environment-button.primary { border-color: transparent; color: var(--tone-f0f1f3); background: var(--tone-626f81); }
.environment-error { margin: 9px 0 0; color: var(--tone-c69da1); font-size: 10px; white-space: pre-line; }
.environment-footer { display: flex; justify-content: flex-end; gap: 7px; margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--tone-373b44); }
.dialog-enter-active, .dialog-leave-active { transition: opacity 140ms ease; }
.dialog-enter-active .environment-dialog, .dialog-leave-active .environment-dialog { transition: opacity 140ms ease, transform 170ms var(--ease-out); }
.dialog-enter-from, .dialog-leave-to { opacity: 0; }
.dialog-enter-from .environment-dialog, .dialog-leave-to .environment-dialog { opacity: 0; transform: translateY(5px) scale(.99); }
</style>
