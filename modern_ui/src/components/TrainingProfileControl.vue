<script setup lang="ts">
import { ref } from 'vue'
import type { TrainingProfile } from '../fastRunPreset'
defineProps<{ canUndo: boolean }>()
const emit = defineEmits<{ apply: [profile: TrainingProfile]; undo: [] }>()
const profile = ref<TrainingProfile>('quick')
</script>

<template>
  <div class="training-profile">
    <select v-model="profile" aria-label="训练档位">
      <option value="quick">快跑试训</option>
      <option value="memory">省显存</option>
      <option value="speed">速度优先（显存充足）</option>
    </select>
    <button type="button" @click="emit('apply', profile)">应用档位</button>
    <button v-if="canUndo" type="button" @click="emit('undo')">撤销</button>
    <small>{{ profile === 'quick' ? '减少训练量；分辨率不变' : profile === 'memory' ? '减少模型参数与批大小；训练量不变' : '优先关闭支持的检查点和交换；需要更多显存' }}</small>
  </div>
</template>

<style scoped>
.training-profile { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-start; gap: 7px; margin: 9px 0 12px; padding: 9px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg); }
select { flex:1; min-width:140px; max-width:260px; }
select,button { min-height: 28px; padding: 3px 7px; border: 1px solid var(--border); border-radius: 4px; color: var(--text); background: var(--bg); font: inherit; font-size: 11px; }
button { cursor: pointer; }small { flex-basis: 100%; color: var(--hint); font-size: 11px; text-align: left; }
select:focus-visible,button:focus-visible { outline: 2px solid var(--tone-78869b); outline-offset: 2px; }
</style>
