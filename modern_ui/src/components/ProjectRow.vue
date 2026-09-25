<script setup lang="ts">
import { computed } from 'vue'
import type { ProjectCard } from '../bridge'

const props = defineProps<{ project: ProjectCard }>()
const emit = defineEmits<{
  open: [project: ProjectCard]
  rename: [project: ProjectCard]
  remove: [project: ProjectCard]
}>()

const summary = computed(() => {
  const project = props.project
  return [
    `${project.mode_label} · ${project.base_type_label || project.base_type || '底模未设置'}`,
    project.raw_dir ? `图集: ${project.raw_dir}` : '',
    project.updated ? `更新: ${project.updated}` : '',
  ].filter(Boolean).join('  |  ')
})
</script>

<template>
  <article class="project-row">
    <div class="project-copy">
      <h2 :title="project.name">{{ project.name }}</h2>
      <p :title="summary">{{ summary }}</p>
    </div>
    <div class="project-actions">
      <button class="small-button primary" type="button" title="打开项目并恢复其训练配置。" @click="emit('open', project)">打开</button>
      <button class="small-button" type="button" title="修改项目名称；项目配置和训练产物不会因此移动。" @click="emit('rename', project)">重命名</button>
      <button class="small-button danger" type="button" title="删除项目配置；图集数据和 output 中的训练产物会保留。" @click="emit('remove', project)">删除</button>
    </div>
  </article>
</template>
