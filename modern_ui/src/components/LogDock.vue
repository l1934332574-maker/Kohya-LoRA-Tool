<script setup lang="ts">
import UiIcon from './UiIcon.vue'
import FeedbackDialog from './FeedbackDialog.vue'
import { ref } from 'vue'

const feedbackOpen = ref(false)

defineProps<{ entries: string[]; exporting?: boolean }>()
const emit = defineEmits<{ export: [] }>()
</script>

<template>
  <section class="log-dock" aria-label="运行日志">
    <header class="log-header">
      <h2>运行日志</h2>
      <button class="small-button" type="button" title="导出完整日志与环境信息；完成后显示保存位置，可打开文件或复制路径。" @click="emit('export')"><UiIcon name="export" /> {{ exporting ? '查看导出进度' : '导出日志' }}</button>
      <button class="feedback-button" type="button" title="反馈与交流" aria-label="反馈与交流" @click="feedbackOpen = true"><UiIcon name="feedback" /></button>
    </header>
    <div class="log-content" role="log" aria-live="polite" aria-relevant="additions text">
      <p v-for="(entry, index) in entries" :key="`${index}-${entry}`" class="log-line">{{ entry }}</p>
    </div>
  </section>
  <FeedbackDialog :open="feedbackOpen" @close="feedbackOpen = false" />
</template>

<style scoped>
.feedback-button { display: grid; place-items: center; width: 28px; height: 28px; padding: 0; border: 0; border-radius: 5px; color: var(--hint); background: transparent; cursor: pointer; }
.feedback-button:hover, .feedback-button:focus-visible { color: var(--text); background: var(--tone-2e3239); }
</style>
