<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps<{ text: string; image?: string; readonly?: boolean }>()
const emit = defineEmits<{ change: [text: string] }>()
const selected = ref(0)
const svg = ref<SVGSVGElement | null>(null)
const unitsPerPixel = ref(1)
interface LayoutDraft { width: number; height: number; items: Array<{caption: string; label: string; bbox: number[]}>; bbox_format: string }
type Handle = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w'
const data = computed<LayoutDraft | null>(() => { try { const value: LayoutDraft = JSON.parse(props.text); return value.width > 0 && value.height > 0 && Array.isArray(value.items) && value.items.every(item => Array.isArray(item.bbox) && item.bbox.length === 4 && item.bbox.every(Number.isFinite)) && value.bbox_format === 'xyxy' ? value : null } catch { return null } })
const item = computed(() => data.value?.items[selected.value])
const handles = computed(() => {
  if (!item.value) return []
  const [left, top, right, bottom] = item.value.bbox
  const middleX = (left + right) / 2, middleY = (top + bottom) / 2
  return [
    { name:'n' as Handle, x:middleX, y:top }, { name:'e' as Handle, x:right, y:middleY },
    { name:'s' as Handle, x:middleX, y:bottom }, { name:'w' as Handle, x:left, y:middleY },
    { name:'nw' as Handle, x:left, y:top }, { name:'ne' as Handle, x:right, y:top },
    { name:'se' as Handle, x:right, y:bottom }, { name:'sw' as Handle, x:left, y:bottom },
  ]
})
let drag: { x: number; y: number; box: number[]; handle: Handle | null; pointer: number; index: number } | null = null
let observer: ResizeObserver | undefined
function updateScale() {
  const matrix = svg.value?.getScreenCTM()
  if (matrix) unitsPerPixel.value = 1 / Math.hypot(matrix.a, matrix.b)
}
onMounted(() => {
  observer = new ResizeObserver(updateScale)
  if (svg.value) observer.observe(svg.value)
  updateScale()
})
onBeforeUnmount(() => observer?.disconnect())
watch(svg, (current, previous) => {
  if (previous) observer?.unobserve(previous)
  if (current) { observer?.observe(current); updateScale() }
})
watch(data, value => { if (value && selected.value >= value.items.length) selected.value = 0 })
function update(index: number, box: number[]) {
  if (props.readonly || !data.value) return
  const value = JSON.parse(props.text)
  value.items[index].bbox = box
  emit('change', JSON.stringify(value, null, 2))
}
function point(event: PointerEvent) {
  const element = svg.value
  const matrix = element?.getScreenCTM()
  if (!element || !matrix) return null
  const position = element.createSVGPoint()
  position.x = event.clientX; position.y = event.clientY
  return position.matrixTransform(matrix.inverse())
}
function down(event: PointerEvent, index: number, handle: Handle | null = null) {
  selected.value = index
  if (props.readonly || !data.value || event.button !== 0) return
  const position = point(event)
  if (!position) return
  drag = { x:position.x, y:position.y, box:[...data.value.items[index].bbox], handle, pointer:event.pointerId, index }
  svg.value?.setPointerCapture(event.pointerId)
}
function move(event: PointerEvent) {
  if (!drag || !data.value || event.pointerId !== drag.pointer) return
  const position = point(event)
  if (!position) return
  const [x1,y1,x2,y2] = drag.box
  const dx = Math.round(position.x-drag.x), dy = Math.round(position.y-drag.y)
  if (drag.handle) {
    const handle = drag.handle
    const left = handle.includes('w') ? Math.max(0,Math.min(x2-1,x1+dx)) : x1
    const right = handle.includes('e') ? Math.min(data.value.width,Math.max(x1+1,x2+dx)) : x2
    const top = handle.includes('n') ? Math.max(0,Math.min(y2-1,y1+dy)) : y1
    const bottom = handle.includes('s') ? Math.min(data.value.height,Math.max(y1+1,y2+dy)) : y2
    update(drag.index, [left,top,right,bottom])
  } else {
    const mx = Math.min(data.value.width-x2,Math.max(-x1,dx)), my = Math.min(data.value.height-y2,Math.max(-y1,dy))
    update(drag.index,[x1+mx,y1+my,x2+mx,y2+my])
  }
}
function stop(event: PointerEvent) {
  if (!drag || event.pointerId !== drag.pointer) return
  const pointer = drag.pointer
  drag = null
  if (svg.value?.hasPointerCapture(pointer)) svg.value.releasePointerCapture(pointer)
}
function coordinate(index: number, event: Event) {
  if (!item.value || !data.value) return
  const box = [...item.value.bbox], value = Number((event.target as HTMLInputElement).value)
  if (!Number.isFinite(value)) return
  box[index] = Math.min(index % 2 ? data.value.height : data.value.width,Math.max(0,value))
  if (box[0] < box[2] && box[1] < box[3]) update(selected.value,box)
}
</script>

<template>
  <div v-if="data" class="layout-preview">
    <svg ref="svg" :viewBox="`0 0 ${data.width} ${data.height}`" @pointermove="move" @pointerup="stop" @pointercancel="stop" @lostpointercapture="drag=null">
      <image v-if="image" :href="image" width="100%" height="100%" />
      <g v-for="(region,index) in data.items" :key="index">
        <rect :x="region.bbox[0]" :y="region.bbox[1]" :width="region.bbox[2]-region.bbox[0]" :height="region.bbox[3]-region.bbox[1]" :class="{selected:selected===index}" @pointerdown.stop.prevent="down($event,index)" />
        <text :x="region.bbox[0]+3" :y="region.bbox[1]+16" font-size="14">{{ index+1 }} · {{ region.label }}</text>
      </g>
      <g v-if="item" class="selected-overlay">
        <rect class="outline" :x="item.bbox[0]" :y="item.bbox[1]" :width="item.bbox[2]-item.bbox[0]" :height="item.bbox[3]-item.bbox[1]" />
        <g v-if="!readonly" v-for="handle in handles" :key="handle.name" :class="`handle handle-${handle.name}`" @pointerdown.stop.prevent="down($event,selected,handle.name)">
          <circle class="hit" :cx="handle.x" :cy="handle.y" :r="12 * unitsPerPixel" />
          <circle class="dot" :cx="handle.x" :cy="handle.y" :r="5 * unitsPerPixel" />
        </g>
      </g>
    </svg>
    <small>点击框或从下方选择区域；拖动框可移动，拖动边缘和角上的圆点可调整大小。</small>
    <template v-if="item">
      <select v-model.number="selected" aria-label="选择要调整的区域"><option v-for="(region,index) in data.items" :key="index" :value="index">{{ index+1 }} · {{ region.caption }}</option></select>
      <div class="coordinates"><label v-for="(label,index) in ['左','上','右','下']" :key="label">{{ label }}<input type="number" :value="item.bbox[index]" :disabled="readonly" @change="coordinate(index,$event)"></label></div>
    </template>
  </div>
  <p v-else class="invalid">布局 JSON 尚不完整，请在文本框中修正后预览。</p>
</template>

<style scoped>
.layout-preview{display:grid;gap:8px}.layout-preview svg{width:100%;max-height:420px;background:#111;touch-action:none;user-select:none;overflow:visible}image{pointer-events:none}rect{fill:#67c9aa22;stroke:#67c9aa;stroke-width:2;vector-effect:non-scaling-stroke;cursor:move}rect.selected{stroke:#ffcd63}.outline{fill:none;stroke:#ffcd63;stroke-width:2;pointer-events:none}text{fill:white;paint-order:stroke;stroke:#111;stroke-width:3px;pointer-events:none}.hit{fill:transparent;stroke:none}.dot{fill:#ffcd63;stroke:#292929;stroke-width:1.5;vector-effect:non-scaling-stroke;pointer-events:none}.handle-n,.handle-s{cursor:ns-resize}.handle-e,.handle-w{cursor:ew-resize}.handle-nw,.handle-se{cursor:nwse-resize}.handle-ne,.handle-sw{cursor:nesw-resize}.coordinates{display:flex;gap:6px}.coordinates label{width:25%;font-size:11px}input,select{width:100%;min-width:0;padding:5px;border:1px solid var(--border);background:var(--card);color:inherit;border-radius:4px}small,.invalid{font-size:12px;color:var(--sub)}
</style>
