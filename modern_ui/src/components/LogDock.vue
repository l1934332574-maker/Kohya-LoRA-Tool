<script setup lang="ts">
import UiIcon from './UiIcon.vue'

defineProps<{ entries: string[] }>()
const emit = defineEmits<{ export: [] }>()
</script>

<template>
  <section class="log-dock" aria-label="运行日志">
    <header class="log-header">
      <h2>运行日志</h2>
      <button class="small-button" type="button" title="将当前运行日志导出为文本文件，便于排查问题或反馈。" @click="emit('export')"><UiIcon name="export" /> 导出日志</button>
    </header>
    <div class="log-content" role="log" aria-live="polite" aria-relevant="additions text">
      <p v-for="(entry, index) in entries" :key="`${index}-${entry}`" class="log-line">{{ entry }}</p>
    </div>
  </section>
</template>
