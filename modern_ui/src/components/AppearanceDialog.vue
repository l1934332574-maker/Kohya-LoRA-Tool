<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { AppearanceSettings } from '../bridge'

const props = defineProps<{
  open: boolean
  settings: AppearanceSettings
  desktop: boolean
  saving: boolean
  chooseBackground: () => Promise<string | null>
}>()
const emit = defineEmits<{
  close: []
  save: [settings: AppearanceSettings]
}>()

const draft = ref<AppearanceSettings>({ ...props.settings })
const backgroundName = computed(() => draft.value.background_path.split(/[\\/]/).filter(Boolean).pop() || '')

watch(() => props.open, (open) => {
  if (open) draft.value = { ...props.settings }
})

async function selectBackground() {
  if (props.saving) return
  const selected = await props.chooseBackground()
  if (selected) draft.value.background_path = selected
}

function save() {
  if (props.saving) return
  emit('save', { ...draft.value })
}
</script>

<template>
  <Transition name="appearance">
    <div v-if="open" class="appearance-backdrop" @pointerdown.self="emit('close')">
      <section class="appearance-dialog" role="dialog" aria-modal="true" aria-labelledby="appearance-title">
        <header class="appearance-header">
          <div><span class="appearance-kicker">显示与个性化</span><h2 id="appearance-title">外观设置</h2></div>
          <button class="appearance-close" type="button" aria-label="关闭" @click="emit('close')">×</button>
        </header>

        <label class="appearance-field">
          <span>颜色主题</span>
          <select v-model="draft.theme" class="appearance-select">
            <option value="dark">深色</option>
            <option value="light">浅色</option>
            <option value="system">跟随 Windows 设置</option>
          </select>
          <small>只影响新版训练页；旧版工具窗口保持原有外观。</small>
        </label>

        <div class="appearance-section">
          <div class="appearance-section-heading"><span>背景图片</span><small>可选 · 仅在本机显示</small></div>
          <div class="appearance-file-row">
            <div class="appearance-file-copy">
              <strong>{{ backgroundName || '未选择背景图片' }}</strong>
              <small>{{ desktop ? '建议使用较暗、细节较少的图片，避免干扰训练参数阅读。' : '浏览器预览不读取本机图片；桌面版可选择背景。' }}</small>
            </div>
            <button class="appearance-button" type="button" :disabled="!desktop || saving" @click="selectBackground">选择图片</button>
            <button v-if="draft.background_path" class="appearance-button subtle" type="button" :disabled="saving" @click="draft.background_path = ''">移除</button>
          </div>
          <label class="appearance-field opacity-field" :class="{ disabled: !draft.background_path }">
            <span>背景显现程度 <b>{{ draft.background_opacity }}%</b></span>
            <input v-model.number="draft.background_opacity" type="range" min="0" max="100" step="1" :disabled="!draft.background_path" />
            <small>较低的显现程度更利于看清文字和训练日志。</small>
          </label>
        </div>

        <p class="appearance-note">背景图片保存在设置中引用的本机路径里，不会上传，也不会改变训练数据。</p>
        <footer class="appearance-actions">
          <button class="appearance-button subtle" type="button" :disabled="saving" @click="emit('close')">取消</button>
          <button class="appearance-button primary" type="button" :disabled="saving" @click="save">{{ saving ? '正在保存…' : '保存设置' }}</button>
        </footer>
      </section>
    </div>
  </Transition>
</template>

<style scoped>
.appearance-backdrop { position: fixed; inset: 0; z-index: 42; display: grid; place-items: center; padding: 18px; background: rgb(10 12 16 / 48%); }
.appearance-dialog { display: grid; width: min(100%, 470px); gap: 16px; padding: 18px; border: 1px solid var(--border); border-radius: 8px; color: var(--text); background: var(--card); box-shadow: 0 16px 44px rgb(0 0 0 / 24%); }
.appearance-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.appearance-header h2 { margin: 3px 0 0; color: var(--text); font-size: 17px; font-weight: 350; }
.appearance-kicker { color: var(--hint); font-size: 10px; }
.appearance-close { width: 29px; height: 29px; border: 0; border-radius: 5px; color: var(--sub); background: transparent; font-size: 21px; cursor: pointer; }
.appearance-close:hover { color: var(--text); background: var(--card-hover); }
.appearance-field { display: grid; gap: 6px; color: var(--sub); font-size: 11px; }
.appearance-field small,.appearance-section-heading small,.appearance-file-copy small { color: var(--hint); font-size: 10px; line-height: 1.45; }
.appearance-select { width: 100%; height: 34px; padding: 0 9px; border: 1px solid var(--border); border-radius: 5px; color: var(--text); background: var(--bg); }
.appearance-section { display: grid; gap: 10px; padding: 12px; border: 1px solid var(--border); border-radius: 6px; background: color-mix(in srgb, var(--bg) 44%, var(--card)); }
.appearance-section-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; color: var(--text); font-size: 11px; }
.appearance-file-row { display: flex; align-items: center; gap: 7px; min-width: 0; }
.appearance-file-copy { display: grid; flex: 1; min-width: 0; gap: 3px; }
.appearance-file-copy strong { overflow: hidden; color: var(--text); font-size: 11px; font-weight: 400; text-overflow: ellipsis; white-space: nowrap; }
.appearance-button { min-height: 30px; padding: 0 10px; border: 1px solid var(--border); border-radius: 5px; color: var(--sub); background: transparent; font-size: 10px; cursor: pointer; transition: border-color 130ms ease, color 130ms ease, background-color 130ms ease, transform 110ms ease-out; }
.appearance-button:hover:not(:disabled) { border-color: var(--tone-505660); color: var(--text); background: var(--card-hover); }
.appearance-button:active:not(:disabled) { transform: scale(.985); }
.appearance-button:disabled { opacity: .55; cursor: not-allowed; }
.appearance-button.primary { border-color: transparent; color: var(--tone-f0f1f3); background: var(--accent); }
.appearance-button.primary:hover:not(:disabled) { background: var(--accent-hover); }
.appearance-button.subtle { border-color: transparent; }
.opacity-field { padding-top: 2px; }
.opacity-field span { display: flex; align-items: center; justify-content: space-between; }
.opacity-field b { color: var(--text); font-weight: 400; }
.opacity-field input { width: 100%; margin: 2px 0; accent-color: var(--accent); }
.opacity-field.disabled { opacity: .52; }
.appearance-note { margin: -2px 0 0; color: var(--hint); font-size: 10px; line-height: 1.45; }
.appearance-actions { display: flex; justify-content: flex-end; gap: 7px; }
.appearance-enter-active,.appearance-leave-active { transition: opacity 150ms ease; }
.appearance-enter-active .appearance-dialog,.appearance-leave-active .appearance-dialog { transition: transform 170ms var(--ease-out), opacity 150ms ease; }
.appearance-enter-from,.appearance-leave-to { opacity: 0; }
.appearance-enter-from .appearance-dialog,.appearance-leave-to .appearance-dialog { opacity: 0; transform: translateY(5px) scale(.99); }
</style>
