<script setup lang="ts">
import UiIcon from './UiIcon.vue'
import { legacyTooltips } from '../legacyTooltips'
import type { GuideStep } from '../bridge'

export interface EngineGroup {
  label: string
  modes: Array<{ key: string; label: string }>
}

const emit = defineEmits<{
  chooseMode: [mode: string]
  action: [name: string]
  guideAction: [step: GuideStep]
}>()
defineProps<{
  groups: EngineGroup[]
  selectedMode: string
  statusText: string
  trainLabel: string
  workspaceActive: boolean
  guideLabel: string
  guideSteps: GuideStep[]
}>()
const modeTips: Record<string, string> = {
  _kohya: '第一引擎（kohya）：画风 / 人物 / 概念在新版训练页的「训练类型」里切换。',
  krea2: '第二引擎 musubi：Krea 2 图像 LoRA；需准备 models/krea2 中的 RAW、VAE 与文本编码器。',
  flux2: '第二引擎 musubi：FLUX.2 图像 LoRA；使用 models/flux2 中的模型组件。',
  video: '第三引擎 AI Toolkit：MiniMax H3 视频 LoRA；使用视频和同名字幕文件。',
  krea2_at: '第三引擎 AI Toolkit：Krea2 图像 LoRA。',
  qwen_image: '第三引擎 AI Toolkit：Qwen-Image LoRA；支持 2512、2.1 和指定本地组件。',
  zimage: '第三引擎 AI Toolkit：Z-Image LoRA；支持快跑档和按步训练。',
  krea2_fz: '第四引擎 Fizgig：Krea2 图像 LoRA，提供 NVIDIA / AMD 通道。',
  flux2_fz: '第四引擎 Fizgig：FLUX.2 Klein 9B 图像 LoRA，提供 NVIDIA / AMD 通道。',
}
</script>

<template>
  <aside class="sidebar">
    <div class="brand-row">
      <span class="brand-mark" aria-hidden="true"></span>
      <span>Kohya-LoRA</span>
    </div>

    <nav class="engine-nav" aria-label="训练引擎">
      <section v-for="group in groups" :key="group.label" class="engine-group">
        <h2>{{ group.label }}</h2>
        <div class="engine-buttons" :class="{ single: group.modes.length === 1 }">
          <button
            v-for="mode in group.modes"
            :key="mode.key"
            class="engine-button"
            :class="{ selected: selectedMode === mode.key }"
            type="button"
            :title="modeTips[mode.key] || mode.label"
            @click="emit('chooseMode', mode.key)"
          >{{ mode.label }}</button>
        </div>
      </section>
    </nav>

    <div class="sidebar-spacer"></div>
    <section v-if="guideSteps.length" class="sidebar-guide-panel" aria-label="新手引导">
      <header class="sidebar-guide-heading">
        <strong>新手引导</strong>
        <span>{{ guideLabel }}</span>
      </header>
      <button
        v-for="step in guideSteps"
        :key="step.id"
        class="guide-step"
        :class="{ done: step.done, pending: !step.done }"
        type="button"
        :title="step.tip"
        @click="emit('guideAction', step)"
      >
        <span class="guide-dot" aria-hidden="true"></span>
        <span class="guide-step-label">{{ step.label }}</span>
        <span class="guide-step-check" :aria-label="step.done ? '已完成' : '未完成'">{{ step.done ? '✓' : '·' }}</span>
        <span class="guide-step-button">{{ step.button }}</span>
      </button>
    </section>
    <p v-else class="sidebar-guide">新建项目并选择训练模式后，这里会显示对应的四步引导。</p>
    <button class="sidebar-action secondary" type="button" title="Python / Git 不想装在系统盘？这里可以自己选文件夹，工具会识别并校验；放在别的盘或整合包文件夹里，重装系统后也能继续用。" @click="emit('action', 'env_locations')">
      <UiIcon name="settings" /> 环境位置（自带 Python / Git）
    </button>
    <button class="sidebar-action primary" type="button" :title="legacyTooltips.oneClickTrain" @click="emit('action', 'train')">
      <UiIcon name="play" /> {{ trainLabel }}
    </button>
    <p class="sidebar-status">{{ statusText }}</p>
  </aside>
</template>
