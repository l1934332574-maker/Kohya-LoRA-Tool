<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

const props = defineProps<{
  modelValue: string
  inputClass: string
  placeholder?: string
}>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const presets = [
  { label: '不裁切（保比例）', value: '' },
  { label: '1:1 正方形', value: '1:1' },
  { label: '3:4 竖图', value: '3:4' },
  { label: '4:3 横图', value: '4:3' },
  { label: '9:16 竖图', value: '9:16' },
  { label: '16:9 横图', value: '16:9' },
]
const labelByValue = new Map(presets.map(({ label, value }) => [value, label]))
const valueByLabel = new Map(presets.map(({ label, value }) => [label, value]))
const root = ref<HTMLElement | null>(null)
const menuOpen = ref(false)
const editing = ref(false)
const displayValue = ref(toDisplay(props.modelValue))
const buttonLabel = computed(() => menuOpen.value ? '收起裁切比例选项' : '选择常用裁切比例')

function toDisplay(value: string) {
  return labelByValue.get(value) ?? value
}

function toStoredValue(value: string) {
  const trimmed = value.trim()
  return valueByLabel.get(trimmed) ?? trimmed
}

watch(() => props.modelValue, (value) => {
  if (!editing.value) displayValue.value = toDisplay(value)
})

function updateFromInput(event: Event) {
  const value = (event.target as HTMLInputElement).value
  displayValue.value = value
  emit('update:modelValue', toStoredValue(value))
}

function finishEditing() {
  const value = toStoredValue(displayValue.value)
  emit('update:modelValue', value)
  editing.value = false
  displayValue.value = toDisplay(value)
}

function choosePreset(value: string) {
  emit('update:modelValue', value)
  displayValue.value = toDisplay(value)
  menuOpen.value = false
}

function closeOnOutsidePointer(event: PointerEvent) {
  if (root.value && !root.value.contains(event.target as Node)) menuOpen.value = false
}

onMounted(() => document.addEventListener('pointerdown', closeOnOutsidePointer))
onUnmounted(() => document.removeEventListener('pointerdown', closeOnOutsidePointer))
</script>

<template>
  <span ref="root" class="crop-ratio-control">
    <input
      :class="inputClass"
      :value="displayValue"
      :placeholder="placeholder || '默认不裁切；可输入自定义比例，如 2:3'"
      title="可从常用比例中选择，也可以直接输入自定义宽高比，例如 2:3"
      aria-label="预处理裁切比例"
      @focus="editing = true"
      @input="updateFromInput"
      @blur="finishEditing"
      @keydown.esc="menuOpen = false"
    />
    <button
      class="crop-ratio-toggle"
      type="button"
      :aria-label="buttonLabel"
      :aria-expanded="menuOpen"
      title="选择常用裁切比例"
      @click.stop="menuOpen = !menuOpen"
    >
      <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg>
    </button>
    <div v-if="menuOpen" class="crop-ratio-menu" role="listbox" aria-label="常用裁切比例">
      <button
        v-for="preset in presets"
        :key="preset.label"
        class="crop-ratio-option"
        type="button"
        role="option"
        :aria-selected="props.modelValue === preset.value"
        @click="choosePreset(preset.value)"
      >
        <span>{{ preset.label }}</span>
        <small v-if="preset.value">{{ preset.value }}</small>
      </button>
      <p class="crop-ratio-custom-hint">也可在输入框中直接填写自定义比例</p>
    </div>
  </span>
</template>

<style>
.crop-ratio-control { position: relative; display: block; width: 100%; min-width: 0; }
.crop-ratio-control > input.kohya-input,
.crop-ratio-control > input.engine-input,
.crop-ratio-control > input.qwen-input {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  padding: 0 31px 0 9px !important;
  border: 1px solid #3d414a;
  border-radius: 5px;
  color: #c6cbd3;
  background: #22252c;
  font-size: 11px;
  font-weight: 350;
  appearance: none;
}
.crop-ratio-control > input.kohya-input,
.crop-ratio-control > input.engine-input { height: 30px; }
.crop-ratio-control > input.qwen-input { height: 31px; }
.crop-ratio-control > input.kohya-input::placeholder,
.crop-ratio-control > input.engine-input::placeholder,
.crop-ratio-control > input.qwen-input::placeholder { color: #707680; }
.crop-ratio-control > input.kohya-input:focus,
.crop-ratio-control > input.engine-input:focus,
.crop-ratio-control > input.qwen-input:focus { outline: none; border-color: #596273; }
.crop-ratio-toggle { position: absolute; top: 50%; right: 3px; display: grid; width: 23px; height: 23px; place-items: center; padding: 0; transform: translateY(-50%); border: 0; border-radius: 4px; color: #9da4af; background: transparent; cursor: pointer; }
.crop-ratio-toggle:hover { color: #c7cbd2; background: rgb(255 255 255 / 5%); }
.crop-ratio-toggle svg { width: 13px; height: 13px; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; transition: transform 150ms ease; }
.crop-ratio-toggle[aria-expanded="true"] svg { transform: rotate(180deg); }
.crop-ratio-menu { position: absolute; z-index: 50; top: calc(100% + 4px); right: 0; left: 0; max-height: 220px; padding: 4px; overflow: auto; border: 1px solid #424751; border-radius: 5px; background: #252830; box-shadow: 0 8px 20px rgb(0 0 0 / 26%); }
.crop-ratio-option { display: flex; align-items: center; justify-content: space-between; width: 100%; min-height: 27px; padding: 4px 7px; border: 0; border-radius: 3px; color: #c4c9d1; background: transparent; font-size: 10px; font-weight: 350; text-align: left; cursor: pointer; }
.crop-ratio-option:hover, .crop-ratio-option[aria-selected="true"] { color: #e0e3e8; background: #343943; }
.crop-ratio-option small { color: #858d99; font-size: 9px; }
.crop-ratio-custom-hint { margin: 4px 6px 2px; padding-top: 5px; border-top: 1px solid #383d46; color: #858b95; font-size: 9px; line-height: 1.4; }
</style>
