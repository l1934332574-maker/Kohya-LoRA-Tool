<script setup lang="ts">
import { computed } from 'vue'
import type { TrainingMetricPoint, TrainingMetrics } from '../bridge'

const props = defineProps<{ metrics?: TrainingMetrics | null; history?: TrainingMetricPoint[] }>()
const points = computed(() => (props.history || []).filter((point) => Number.isFinite(point.loss) && Number.isFinite(point.step)))
const bounds = computed(() => {
  const values = points.value.map((point) => point.loss)
  return { low: Math.min(...values), high: Math.max(...values) }
})
const curve = computed(() => {
  const first = points.value[0]?.step || 0
  const last = points.value.at(-1)?.step || first
  const span = Math.max(bounds.value.high - bounds.value.low, .000001)
  return points.value.map((point) => `${8 + (point.step - first) / Math.max(last - first, 1) * 624},${92 - (point.loss - bounds.value.low) / span * 80}`).join(' ')
})
</script>

<template>
  <section v-if="metrics" class="training-metrics" aria-label="训练指标">
    <div class="metric-grid">
      <div><small>训练步数</small><strong>{{ metrics.step }} / {{ metrics.total || '待统计' }}</strong></div>
      <div><small>当前 Loss</small><strong>{{ metrics.loss != null ? metrics.loss.toFixed(5) : '等待数据' }}</strong></div>
      <div><small>每步耗时</small><strong>{{ metrics.speed > 0 ? `${(1 / metrics.speed).toFixed(2)} 秒` : '等待数据' }}</strong></div>
    </div>
    <template v-if="points.length > 1">
      <svg class="loss-chart" viewBox="0 0 640 104" role="img" :aria-label="`Loss 趋势，最低 ${bounds.low.toFixed(5)}，最高 ${bounds.high.toFixed(5)}`">
        <path d="M8 12H632 M8 52H632 M8 92H632" class="chart-grid" />
        <polyline :points="curve" class="chart-line" />
      </svg>
      <div class="chart-labels"><span>Step {{ points[0]?.step }}</span><span>Loss {{ bounds.low.toFixed(4) }}–{{ bounds.high.toFixed(4) }}</span><span>Step {{ points.at(-1)?.step }}</span></div>
    </template>
    <p v-else>训练开始后显示 Loss 趋势。</p>
    <p>Loss 是训练误差，不是画质分数；没有统一的“合格值”。请结合固定条件的采样对比，不能仅凭 Loss 越低选择成品。</p>
  </section>
</template>

<style scoped>
.training-metrics { padding: 10px; border: 1px solid var(--tone-373b44); border-radius: 5px; background: var(--tone-22252c); }
.metric-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.metric-grid div { display: grid; gap: 4px; }
small,.chart-labels,p { color: var(--tone-9299a4); font-size: 10px; }
strong { color: var(--tone-c1c6cf); font-size: 12px; font-weight: 450; font-variant-numeric: tabular-nums; }
.loss-chart { display: block; width: 100%; height: 100px; margin-top: 8px; }
.chart-grid { fill: none; stroke: var(--tone-373b44); stroke-width: 1; }
.chart-line { fill: none; stroke: var(--tone-8fb0c9); stroke-width: 1.6; vector-effect: non-scaling-stroke; }
.chart-labels { display: flex; justify-content: space-between; gap: 8px; }
p { margin: 8px 0 0; }
@media (max-width: 560px) { .metric-grid { grid-template-columns: 1fr; } }
</style>
