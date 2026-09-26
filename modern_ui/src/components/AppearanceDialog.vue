<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { AppearanceSettings } from '../bridge'

interface CropRect { x: number; y: number; width: number; height: number }
interface CropDrag { mode: 'create' | 'move' | 'resize'; handle?: string; startX: number; startY: number; origin: CropRect }

const props = defineProps<{
  open: boolean
  settings: AppearanceSettings
  desktop: boolean
  saving: boolean
  chooseBackground: () => Promise<string | null>
  getBackgroundPreview: (path: string, thumbnail?: boolean) => Promise<string | null>
}>()
const emit = defineEmits<{
  close: []
  save: [settings: AppearanceSettings]
}>()

const draft = ref<AppearanceSettings>({ ...props.settings })
const backgroundName = computed(() => fileName(draft.value.background_source_path || draft.value.background_path))
const historyPreviews = ref<Record<string, string>>({})
const historyPreviewFailed = ref<Record<string, boolean>>({})
const activeBackgroundPreview = ref('')
const cropOpen = ref(false)
const cropSourcePath = ref('')
const cropPreviewUrl = ref('')
const cropDataUrl = ref('')
const cropError = ref('')
const cropRect = ref<CropRect>({ x: 0, y: 0, width: 1, height: 1 })
const cropSelectionMode = ref(false)
const cropBounds = ref<HTMLElement | null>(null)
const cropImage = ref<HTMLImageElement | null>(null)
let cropDrag: CropDrag | null = null
let historyLoadToken = 0

const cropSelectionStyle = computed(() => ({
  left: `${cropRect.value.x * 100}%`,
  top: `${cropRect.value.y * 100}%`,
  width: `${cropRect.value.width * 100}%`,
  height: `${cropRect.value.height * 100}%`,
}))

function fileName(path: string) {
  return path.split(/[\\/]/).filter(Boolean).pop() || path
}

function isSavedCurrentCrop(path: string) {
  const sourcePath = props.settings.background_source_path || props.settings.background_path
  return Boolean(sourcePath && path === sourcePath && props.settings.background_path !== sourcePath)
}

async function loadHistoryPreviews() {
  const token = ++historyLoadToken
  historyPreviews.value = {}
  historyPreviewFailed.value = {}
  activeBackgroundPreview.value = ''
  if (!props.desktop) return
  const entries = draft.value.background_history.filter((entry) => entry.available)
  const activePath = draft.value.background_path
  const sourcePath = draft.value.background_source_path || activePath
  const hasActiveCrop = Boolean(activePath && sourcePath && activePath !== sourcePath)
  const [loaded, activePreview] = await Promise.all([
    Promise.all(entries.map(async (entry) => {
      const image = await props.getBackgroundPreview(entry.path, true)
      return [entry.path, image] as const
    })),
    hasActiveCrop ? props.getBackgroundPreview(activePath, true) : Promise.resolve(null),
  ])
  if (token !== historyLoadToken) return
  activeBackgroundPreview.value = activePreview ?? ''
  const previews: Record<string, string> = {}
  const failed: Record<string, boolean> = {}
  for (const [path, image] of loaded) {
    if (image) previews[path] = image
    else failed[path] = true
  }
  historyPreviews.value = previews
  historyPreviewFailed.value = failed
}

watch(() => props.open, (open) => {
  if (open) {
    draft.value = { ...props.settings, background_source_path: props.settings.background_source_path || props.settings.background_path }
    cropDataUrl.value = ''
    cropSelectionMode.value = false
    void loadHistoryPreviews()
  } else {
    historyLoadToken += 1
    cropOpen.value = false
  }
})

async function selectBackground() {
  if (props.saving) return
  const selected = await props.chooseBackground()
  if (!selected) return
  const preview = await props.getBackgroundPreview(selected)
  if (!preview) return
  cropSourcePath.value = selected
  cropPreviewUrl.value = preview
  cropRect.value = { x: 0, y: 0, width: 1, height: 1 }
  cropSelectionMode.value = false
  cropError.value = ''
  cropOpen.value = true
}

function selectHistory(entry: AppearanceSettings['background_history'][number]) {
  const preserveCurrentCrop = isSavedCurrentCrop(entry.path)
  if (props.saving || (!entry.available && !preserveCurrentCrop)
    || (historyPreviewFailed.value[entry.path] && !(preserveCurrentCrop && activeBackgroundPreview.value))) return
  draft.value.background_path = preserveCurrentCrop ? props.settings.background_path : entry.path
  draft.value.background_source_path = entry.path
  draft.value.background_available = preserveCurrentCrop ? props.settings.background_available : true
  cropDataUrl.value = ''
}

function startCropSelection() {
  cropSelectionMode.value = true
  cropError.value = '在图片上拖动，画出要显示的区域。'
}

function selectFullImage() {
  cropSelectionMode.value = false
  cropRect.value = { x: 0, y: 0, width: 1, height: 1 }
  cropError.value = ''
}

function removeHistory(path: string) {
  if (props.saving) return
  draft.value.background_history = draft.value.background_history.filter((entry) => entry.path !== path)
  if ((draft.value.background_source_path || draft.value.background_path) === path) clearBackground()
}

function clearBackground() {
  draft.value.background_path = ''
  draft.value.background_source_path = ''
  draft.value.background_available = false
  cropDataUrl.value = ''
}

function cropPoint(event: PointerEvent) {
  const bounds = cropBounds.value?.getBoundingClientRect()
  if (!bounds || !bounds.width || !bounds.height) return null
  return {
    x: Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
    y: Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)),
  }
}

function beginCrop(event: PointerEvent) {
  if (event.button !== 0 || !cropBounds.value) return
  const point = cropPoint(event)
  if (!point) return
  const target = event.target as HTMLElement
  const handle = target.dataset.cropHandle
  const insideSelection = Boolean(target.closest('.crop-selection'))
  cropDrag = {
    mode: cropSelectionMode.value ? 'create' : handle ? 'resize' : insideSelection ? 'move' : 'create',
    handle,
    startX: point.x,
    startY: point.y,
    origin: { ...cropRect.value },
  }
  cropBounds.value.setPointerCapture(event.pointerId)
  if (cropDrag.mode === 'create') cropRect.value = { x: point.x, y: point.y, width: 0, height: 0 }
  event.preventDefault()
}

function updateCrop(event: PointerEvent) {
  if (!cropDrag) return
  const point = cropPoint(event)
  if (!point) return
  const deltaX = point.x - cropDrag.startX
  const deltaY = point.y - cropDrag.startY
  const origin = cropDrag.origin
  if (cropDrag.mode === 'create') {
    const x = Math.min(cropDrag.startX, point.x)
    const y = Math.min(cropDrag.startY, point.y)
    cropRect.value = { x, y, width: Math.abs(deltaX), height: Math.abs(deltaY) }
    return
  }
  if (cropDrag.mode === 'move') {
    cropRect.value = {
      ...origin,
      x: Math.max(0, Math.min(1 - origin.width, origin.x + deltaX)),
      y: Math.max(0, Math.min(1 - origin.height, origin.y + deltaY)),
    }
    return
  }
  const right = origin.x + origin.width
  const bottom = origin.y + origin.height
  let left = origin.x
  let top = origin.y
  let nextRight = right
  let nextBottom = bottom
  if (cropDrag.handle?.includes('w')) left = Math.max(0, Math.min(right - 0.04, origin.x + deltaX))
  if (cropDrag.handle?.includes('e')) nextRight = Math.min(1, Math.max(left + 0.04, right + deltaX))
  if (cropDrag.handle?.includes('n')) top = Math.max(0, Math.min(bottom - 0.04, origin.y + deltaY))
  if (cropDrag.handle?.includes('s')) nextBottom = Math.min(1, Math.max(top + 0.04, bottom + deltaY))
  cropRect.value = { x: left, y: top, width: nextRight - left, height: nextBottom - top }
}

function finishCrop() {
  const wasCreating = cropDrag?.mode === 'create'
  cropDrag = null
  if (wasCreating) cropSelectionMode.value = false
  if (cropRect.value.width < 0.04 || cropRect.value.height < 0.04) {
    cropError.value = '请拖出一个有效的裁切区域。'
    cropRect.value = { x: 0, y: 0, width: 1, height: 1 }
  }
}

function confirmCrop() {
  const image = cropImage.value
  if (!image || !image.naturalWidth || !image.naturalHeight) {
    cropError.value = '图片还没有载入完成，请稍后再试。'
    return
  }
  const usesWholeImage = cropRect.value.x <= 0.001 && cropRect.value.y <= 0.001
    && cropRect.value.width >= 0.999 && cropRect.value.height >= 0.999
  if (usesWholeImage) {
    draft.value.background_path = cropSourcePath.value
    draft.value.background_source_path = cropSourcePath.value
    draft.value.background_available = true
    cropDataUrl.value = ''
    cropOpen.value = false
    return
  }
  const sourceX = Math.floor(cropRect.value.x * image.naturalWidth)
  const sourceY = Math.floor(cropRect.value.y * image.naturalHeight)
  const sourceWidth = Math.max(1, Math.floor(cropRect.value.width * image.naturalWidth))
  const sourceHeight = Math.max(1, Math.floor(cropRect.value.height * image.naturalHeight))
  const scale = Math.min(1, 2560 / Math.max(sourceWidth, sourceHeight))
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(sourceWidth * scale))
  canvas.height = Math.max(1, Math.round(sourceHeight * scale))
  const context = canvas.getContext('2d')
  if (!context) {
    cropError.value = '无法处理这张图片，请换一张图片再试。'
    return
  }
  context.fillStyle = '#20232a'
  context.fillRect(0, 0, canvas.width, canvas.height)
  context.drawImage(image, sourceX, sourceY, sourceWidth, sourceHeight, 0, 0, canvas.width, canvas.height)
  let dataUrl = canvas.toDataURL('image/webp', 0.9)
  if (!dataUrl.startsWith('data:image/webp,')) dataUrl = canvas.toDataURL('image/jpeg', 0.88)
  const encoded = dataUrl.slice(dataUrl.indexOf(',') + 1)
  const padding = encoded.endsWith('==') ? 2 : encoded.endsWith('=') ? 1 : 0
  if (Math.floor(encoded.length * 3 / 4) - padding > 8 * 1024 * 1024) {
    dataUrl = canvas.toDataURL('image/jpeg', 0.78)
    const retry = dataUrl.slice(dataUrl.indexOf(',') + 1)
    const retryPadding = retry.endsWith('==') ? 2 : retry.endsWith('=') ? 1 : 0
    if (Math.floor(retry.length * 3 / 4) - retryPadding > 8 * 1024 * 1024) {
      cropError.value = '裁切后的图片仍超过 8 MB，请缩小裁切范围。'
      return
    }
  }
  draft.value.background_path = cropSourcePath.value
  draft.value.background_source_path = cropSourcePath.value
  draft.value.background_available = true
  cropDataUrl.value = dataUrl
  cropOpen.value = false
}

function cancelCrop() {
  cropOpen.value = false
  cropError.value = ''
}

function save() {
  if (props.saving) return
  emit('save', { ...draft.value, ...(cropDataUrl.value ? { background_data_url: cropDataUrl.value } : {}) })
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
              <small v-if="draft.background_path && !draft.background_available" class="appearance-missing">当前图片不可用，请重新选择或移除。</small>
              <small v-else>{{ desktop ? '图片按显现程度与主题底色混合；界面卡片保留文字对比度。' : '浏览器预览不读取本机图片；桌面版可选择背景。' }}</small>
            </div>
            <button class="appearance-button" type="button" :disabled="!desktop || saving" @click="selectBackground">选择图片</button>
            <button v-if="draft.background_path" class="appearance-button subtle" type="button" :disabled="saving" @click="clearBackground">移除</button>
          </div>
          <label class="appearance-field opacity-field" :class="{ disabled: !draft.background_path }">
            <span>背景显现程度 <b>{{ draft.background_opacity }}%</b></span>
            <input v-model.number="draft.background_opacity" type="range" min="0" max="100" step="1" :disabled="!draft.background_path" />
            <small>0% 使用主题底色，100% 显示选定背景；此数值只调透明度，不叠加暗色遮罩。</small>
          </label>
          <div v-if="draft.background_history.length" class="appearance-history">
            <div class="appearance-history-title">最近使用的图片</div>
            <div class="appearance-history-gallery">
              <div v-for="entry in draft.background_history" :key="entry.path" class="appearance-history-card">
              <button
                class="appearance-history-select"
                type="button"
                :disabled="saving || ((!entry.available || historyPreviewFailed[entry.path]) && !(isSavedCurrentCrop(entry.path) && activeBackgroundPreview))"
                :title="entry.path"
                :aria-label="`选择背景图片 ${fileName(entry.path)}`"
                :class="{ selected: (draft.background_source_path || draft.background_path) === entry.path }"
                @click="selectHistory(entry)"
              >
                <img
                  v-if="isSavedCurrentCrop(entry.path) && activeBackgroundPreview"
                  :src="activeBackgroundPreview"
                  alt=""
                />
                <img v-else-if="historyPreviews[entry.path]" :src="historyPreviews[entry.path]" alt="" />
                <span v-else class="appearance-history-placeholder" aria-hidden="true">{{ entry.available && !historyPreviewFailed[entry.path] ? '载入中' : '图片不可用' }}</span>
                <small v-if="(draft.background_source_path || draft.background_path) === entry.path" class="appearance-history-current">当前</small>
                <small v-if="isSavedCurrentCrop(entry.path)" class="appearance-history-cropped">已裁切</small>
              </button>
              <button class="appearance-history-remove" type="button" :disabled="saving" :aria-label="`移除历史图片 ${fileName(entry.path)}`" title="从历史中移除" @click="removeHistory(entry.path)">×</button>
              <span class="appearance-history-name">{{ fileName(entry.path) }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="appearance-section">
          <div class="appearance-section-heading"><span>界面组件</span><small>悬停或键盘聚焦时恢复完整显示</small></div>
          <label class="appearance-field opacity-field">
            <span>未交互时组件透明度 <b>{{ draft.component_opacity }}%</b></span>
            <input v-model.number="draft.component_opacity" type="range" min="0" max="100" step="1" />
            <small>鼠标移入对应区域，或用键盘聚焦区域内控件时，会恢复为 100%。</small>
          </label>
          <label class="appearance-switch">
            <input v-model="draft.idle_fade_enabled" type="checkbox" role="switch" />
            <span class="appearance-switch-track" aria-hidden="true"><i></i></span>
            <span class="appearance-switch-copy"><strong>长时间静止时渐隐</strong><small>45 秒没有鼠标或键盘活动后渐隐；弹窗与训练状态保持可见。</small></span>
          </label>
        </div>

        <p class="appearance-note">裁切后会在本机保存一份背景副本，原图保留；图片不会上传，也不会改变训练数据。</p>
        <footer class="appearance-actions">
          <button class="appearance-button subtle" type="button" :disabled="saving" @click="emit('close')">取消</button>
          <button class="appearance-button primary" type="button" :disabled="saving" @click="save">{{ saving ? '正在保存…' : '保存设置' }}</button>
        </footer>
      </section>
    </div>
  </Transition>
  <Transition name="appearance">
    <div v-if="cropOpen" class="appearance-crop-backdrop">
      <section class="appearance-crop-dialog" role="dialog" aria-modal="true" aria-labelledby="crop-title">
        <header class="appearance-header">
          <div><span class="appearance-kicker">背景图片</span><h2 id="crop-title">选择显示区域</h2></div>
          <button class="appearance-close" type="button" aria-label="取消裁切" @click="cancelCrop">×</button>
        </header>
        <p class="crop-instructions">默认使用整张图片。点击“框选区域”后，在图片上拖动选择；选好后可移动选框或拖动四角调整。</p>
        <div class="crop-toolbar">
          <button class="appearance-button" type="button" :class="{ selected: cropSelectionMode }" @click="startCropSelection">框选区域</button>
          <button class="appearance-button" type="button" :class="{ selected: !cropSelectionMode && cropRect.width === 1 && cropRect.height === 1 }" @click="selectFullImage">使用整张图片</button>
        </div>
        <div class="crop-stage">
          <div
            ref="cropBounds"
            class="crop-bounds"
            @pointerdown="beginCrop"
            @pointermove="updateCrop"
            @pointerup="finishCrop"
            @pointercancel="finishCrop"
          >
            <img ref="cropImage" :src="cropPreviewUrl" alt="待裁切背景图" draggable="false" />
            <div class="crop-selection" :style="cropSelectionStyle">
              <i class="crop-handle north-west" data-crop-handle="nw"></i>
              <i class="crop-handle north-east" data-crop-handle="ne"></i>
              <i class="crop-handle south-west" data-crop-handle="sw"></i>
              <i class="crop-handle south-east" data-crop-handle="se"></i>
            </div>
          </div>
        </div>
        <p class="crop-error" aria-live="polite">{{ cropError }}</p>
        <footer class="appearance-actions">
          <button class="appearance-button subtle" type="button" @click="cancelCrop">取消</button>
          <button class="appearance-button primary" type="button" @click="confirmCrop">使用此区域</button>
        </footer>
      </section>
    </div>
  </Transition>
</template>

<style scoped>
.appearance-backdrop { position: fixed; inset: 0; z-index: 42; display: grid; place-items: center; padding: 18px; background: rgb(10 12 16 / 48%); }
.appearance-dialog { display: grid; width: min(100%, 640px); max-height: min(90vh, 760px); gap: 16px; padding: 18px; overflow-y: auto; border: 1px solid var(--border); border-radius: 8px; color: var(--text); background: var(--card); box-shadow: 0 16px 44px rgb(0 0 0 / 24%); }
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
.appearance-missing { color: var(--tone-c6a8aa) !important; }
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
.appearance-history { display: grid; gap: 6px; overflow: hidden; }
.appearance-history-title { margin-bottom: 2px; color: var(--hint); font-size: 10px; }
.appearance-history-gallery { display: flex; align-items: flex-start; gap: 9px; overflow-x: auto; padding: 1px 1px 7px; scrollbar-width: thin; }
.appearance-history-card { position: relative; display: grid; flex: 0 0 86px; gap: 5px; }
.appearance-history-select { position: relative; display: grid; width: 86px; height: 86px; place-items: center; overflow: hidden; padding: 0; border: 1px solid var(--border); border-radius: 5px; color: var(--hint); background: var(--bg); cursor: pointer; transition: border-color 130ms ease, transform 130ms ease; }
.appearance-history-select img { display: block; width: 100%; height: 100%; object-fit: cover; }
.appearance-history-select.selected { border: 2px solid var(--accent); }
.appearance-history-select:hover:not(:disabled) { border-color: var(--tone-7f8997); transform: translateY(-1px); }
.appearance-history-select:disabled { opacity: .68; cursor: not-allowed; }
.appearance-history-placeholder { display: grid; width: 100%; height: 100%; place-items: center; padding: 6px; color: var(--hint); font-size: 9px; text-align: center; }
.appearance-history-current { position: absolute; right: 4px; bottom: 4px; padding: 2px 5px; border-radius: 3px; color: var(--tone-f0f1f3); background: rgb(25 28 33 / 75%); font-size: 8px; }
.appearance-history-cropped { position: absolute; top: 4px; left: 4px; padding: 2px 4px; border-radius: 3px; color: var(--tone-f0f1f3); background: rgb(25 28 33 / 75%); font-size: 8px; }
.appearance-history-name { overflow: hidden; color: var(--hint); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.appearance-history-remove { position: absolute; top: 3px; right: 3px; width: 20px; height: 20px; border: 0; border-radius: 4px; color: var(--tone-f0f1f3); background: rgb(25 28 33 / 72%); font-size: 14px; line-height: 18px; opacity: 0; cursor: pointer; transition: opacity 120ms ease; }
.appearance-history-card:hover .appearance-history-remove,.appearance-history-remove:focus-visible { opacity: 1; }
.appearance-history-remove:hover:not(:disabled) { background: rgb(25 28 33 / 92%); }
.appearance-history-remove:disabled { cursor: not-allowed; }
.appearance-switch { display: flex; align-items: center; gap: 9px; cursor: pointer; }
.appearance-switch > input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.appearance-switch-track { display: flex; flex: 0 0 auto; align-items: center; width: 30px; height: 17px; padding: 2px; border: 1px solid var(--border); border-radius: 9px; background: var(--bg); transition: background-color 140ms ease, border-color 140ms ease; }
.appearance-switch-track i { width: 11px; height: 11px; border-radius: 50%; background: var(--hint); transition: transform 140ms ease, background-color 140ms ease; }
.appearance-switch > input:checked + .appearance-switch-track { border-color: var(--accent); background: var(--accent); }
.appearance-switch > input:checked + .appearance-switch-track i { transform: translateX(12px); background: var(--tone-f0f1f3); }
.appearance-switch > input:focus-visible + .appearance-switch-track { outline: 2px solid var(--tone-7f8997); outline-offset: 2px; }
.appearance-switch-copy { display: grid; gap: 3px; }
.appearance-switch-copy strong { color: var(--text); font-size: 11px; font-weight: 400; }
.appearance-switch-copy small { color: var(--hint); font-size: 10px; line-height: 1.4; }
.appearance-note { margin: -2px 0 0; color: var(--hint); font-size: 10px; line-height: 1.45; }
.appearance-actions { display: flex; justify-content: flex-end; gap: 7px; }
.appearance-enter-active,.appearance-leave-active { transition: opacity 150ms ease; }
.appearance-enter-active .appearance-dialog,.appearance-leave-active .appearance-dialog { transition: transform 170ms var(--ease-out), opacity 150ms ease; }
.appearance-enter-from,.appearance-leave-to { opacity: 0; }
.appearance-enter-from .appearance-dialog,.appearance-leave-to .appearance-dialog { opacity: 0; transform: translateY(5px) scale(.99); }
.appearance-crop-backdrop { position: fixed; inset: 0; z-index: 46; display: grid; place-items: center; padding: 18px; background: rgb(10 12 16 / 64%); }
.appearance-crop-dialog { display: grid; width: min(100%, 620px); max-height: min(92vh, 720px); gap: 12px; padding: 18px; overflow-y: auto; border: 1px solid var(--border); border-radius: 8px; color: var(--text); background: var(--card); box-shadow: 0 18px 52px rgb(0 0 0 / 34%); }
.crop-instructions { margin: 0; color: var(--sub); font-size: 11px; line-height: 1.5; }
.crop-toolbar { display: flex; flex-wrap: wrap; gap: 6px; }
.crop-toolbar .selected { border-color: var(--accent); color: var(--text); background: var(--card-hover); }
.crop-stage { display: grid; width: 100%; height: min(48vh, 360px); min-height: 160px; box-sizing: border-box; place-items: center; overflow: hidden; padding: 12px; border: 1px solid var(--border); border-radius: 5px; background: #17191d; }
.crop-bounds { position: relative; display: inline-block; max-width: 100%; max-height: 100%; touch-action: none; user-select: none; cursor: crosshair; }
.crop-bounds img { display: block; max-width: min(100%, 580px); max-height: min(42vh, 340px); object-fit: contain; pointer-events: none; }
.crop-selection { position: absolute; border: 1px solid #fff; outline: 1px solid rgb(0 0 0 / 55%); box-shadow: 0 0 0 9999px rgb(0 0 0 / 48%); cursor: move; touch-action: none; }
.crop-handle { position: absolute; width: 11px; height: 11px; border: 1px solid #fff; border-radius: 2px; background: var(--accent); }
.crop-handle.north-west { top: -5px; left: -5px; cursor: nwse-resize; }
.crop-handle.north-east { top: -5px; right: -5px; cursor: nesw-resize; }
.crop-handle.south-west { bottom: -5px; left: -5px; cursor: nesw-resize; }
.crop-handle.south-east { right: -5px; bottom: -5px; cursor: nwse-resize; }
.crop-error { min-height: 14px; margin: 0; color: var(--tone-c6a8aa); font-size: 10px; }
@media (prefers-reduced-motion: reduce) {
  .appearance-button, .appearance-switch-track, .appearance-switch-track i { transition-duration: .01ms; }
  .appearance-history-select,.appearance-history-remove { transition-duration: .01ms; }
}
@media (max-width: 560px) {
  .appearance-backdrop,.appearance-crop-backdrop { padding: 8px; }
  .appearance-dialog,.appearance-crop-dialog { max-height: 96vh; padding: 13px; }
  .appearance-file-row { flex-wrap: wrap; }
  .appearance-file-copy { flex-basis: 100%; }
  .crop-stage { min-height: 180px; }
  .crop-bounds img { max-width: min(100%, 480px); }
}
@media (max-height: 640px) {
  .appearance-crop-dialog { max-height: 96vh; }
  .crop-stage { height: 38vh; min-height: 132px; }
  .crop-bounds img { max-height: 32vh; }
}
</style>
