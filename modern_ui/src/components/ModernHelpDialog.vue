<script setup lang="ts">
import { computed } from 'vue'
import type { GuideStep, ModeWorkspaceData } from '../bridge'

const props = defineProps<{
  open: boolean
  kind: 'readme' | 'mode'
  mode: string
  modeLabel: string
  steps: GuideStep[]
  details: ModeWorkspaceData | null
}>()
const emit = defineEmits<{ close: [] }>()

const title = computed(() => props.kind === 'readme' ? '新手教学 & 常见问题' : `${props.modeLabel} · 使用说明`)
const sections = computed(() => {
  if (props.kind === 'readme') return [
    { heading: '准备数据集', body: '人物模式建议准备 15~30 张同一个人的图，尽量覆盖不同角度和服装；画风模式建议准备 20~60 张不同主体但画风一致的图片。图片越清晰越好，太小、模糊或重复的图片会在预处理时过滤。' },
    { heading: '选择训练底模', body: '第一引擎的底模架构必须与底模文件本身一致。SD1.5 显存要求较低；SDXL 使用 1024 分辨率，推荐 16G 显存；FLUX.1 和 Anima 需要各自配套的组件。出图时也应使用与 LoRA 同系列的底模。' },
    { heading: '填写触发词', body: '触发词是训练后在提示词里唤起人物或概念的专属词。建议选少见的英文词，例如 my_oc01，避免使用 girl 这类常见词。' },
    { heading: '开始训练', body: '按左侧新手引导完成环境、训练内核、模型和数据集设置。点击「一键开始训练」后，工具会按当前模式预处理数据并进入训练；训练产物保存在 output 文件夹。' },
    { heading: '常见问题', body: '显存不足时，可按当前模式使用低显存预设、降低分辨率或关闭训练采样预览。训练中途停止后，只有已经写入快照的进度才能续训。LoRA 效果不理想时，先确认出图底模系列、触发词和数据集标签是否匹配。WD14 自动标签可在标签编辑器中检查和修改。' },
  ]

  const allTips = props.steps.map((step) => `${step.label.replace(/^\d+、?\s*/, '')}：${step.tip}`).filter(Boolean)
  const modeBody: Record<string, string[]> = {
    krea2: [
      'Krea 2 使用 RAW 底模训练；Turbo 是推理版本。训练完成后，LoRA 可用于 Krea 2 系列出图。',
      '模型通常包含 RAW、Qwen-Image VAE 和 Qwen3-VL 文本编码器；当前模式的模型窗口会标出本机已有文件和缺少文件，并支持断点续传。',
      '建议准备 15~30 张同一人物或风格的图片，设置独特的 Trigger。训练会先缓存模型组件，再进行 LoRA 训练。',
    ],
    krea2_at: [
      'AI Toolkit 模式使用 Krea 2 RAW 权重；已有的文本编码器和 VAE 会优先复用，缺少的组件会在训练准备阶段按需获取。',
      '建议准备 15~30 张同一人物或风格的图片，并填写独特的 Trigger。训练产物会保存在当前项目的 output 文件夹。',
    ],
    krea2_fz: [
      'Fizgig 模式与其他引擎使用独立训练环境，支持 NVIDIA 和 AMD 路径。Krea 2 模型文件仍放在 models/krea2。',
      '使用 RAW 底模训练，建议准备 15~30 张同一人物或风格的图片，并填写独特的 Trigger。',
    ],
    flux2: [
      'FLUX.2 musubi 模式使用 Klein 4B base 底模，需要 DiT、Qwen3-4B 文本编码器和 VAE。文件会放在 models/flux2。',
      '建议准备 15~30 张同一人物或风格的图片。8G 显存会自动使用省显存配置，速度较慢；12G 以上更合适。',
    ],
    flux2_fz: [
      'Klein 9B 使用 Fizgig 引擎和 fp8 base 权重，需要 Klein 9B DiT、Qwen3-8B 文本编码器和 VAE；模型目录为 models/flux2。',
      '建议准备 15~30 张图片。训练产物适用于 FLUX.2 Klein 系列；显存较低时会启用量化或块交换，速度会降低。',
    ],
    video: [
      'H3 视频 LoRA 使用视频文件和同名 .txt 字幕。建议准备 3~10 段、每段约 3~10 秒的同角色或同风格视频。',
      'H3 主模型可以选择 int8 或 nvfp4 版本其中之一；还需要文本编码器和视频 VAE。当前工具暂未开放 H3 的 AMD 训练路径。',
      'AI 自动视频描述首次使用需下载描述模型；也可以先生成占位字幕，再手动修改成准确的画面描述。',
    ],
    qwen_image: [
      '选择 Qwen-Image-2512 或 Qwen-Image-2.1 后，模型架构会自动匹配。已有模型可以指定本地目录；2.1 单文件权重也可分别指定现成的文本编码器和 VAE。',
      '建议准备至少 15 张清晰图片。人物或概念训练可填写专属 Trigger。训练模型未在本地准备时，会在训练流程需要时按需下载。',
      '模型与组件选择在工作区的「选择训练模型」窗口中完成；本说明不会改动项目设置。',
    ],
    zimage: [
      'Z-Image 是第三引擎的图像训练模式。可使用默认模型，也可选择已存在的 Diffusers 模型目录。',
      '建议准备至少 15 张清晰图片。8G 显存可用快跑预设，12G 起步、16G 更舒适。模型按需下载到本机数据目录。',
    ],
  }
  const tips = allTips.length ? allTips : [props.details?.dataset_hint || '准备与当前训练模式匹配的数据集。']
  return [
    { heading: '按步骤准备', body: tips.join('\n\n') },
    ...(modeBody[props.mode] ?? []).map((body, index) => ({ heading: index === 0 ? '当前模式说明' : '训练建议', body })),
    ...(props.details?.trigger_hint ? [{ heading: 'Trigger 提示', body: props.details.trigger_hint }] : []),
    ...(props.details?.dataset_hint ? [{ heading: '数据集提示', body: props.details.dataset_hint }] : []),
  ]
})
</script>

<template>
  <Transition name="dialog">
    <div v-if="open" class="help-backdrop" @click.self="emit('close')">
      <section class="help-dialog" role="dialog" aria-modal="true" aria-labelledby="help-title">
        <header class="help-header">
          <div><span class="help-kicker">Kohya-LoRA 使用帮助</span><h2 id="help-title">{{ title }}</h2></div>
          <button class="help-close" type="button" aria-label="关闭" @click="emit('close')">×</button>
        </header>
        <div class="help-scroll">
          <section v-for="section in sections" :key="section.heading" class="help-section">
            <h3>{{ section.heading }}</h3>
            <p>{{ section.body }}</p>
          </section>
        </div>
        <footer><button class="help-done" type="button" @click="emit('close')">知道了</button></footer>
      </section>
    </div>
  </Transition>
</template>

<style scoped>
.help-backdrop { position: fixed; inset: 0; z-index: 33; display: grid; place-items: center; padding: 20px; background: rgb(10 12 16 / 52%); }
.help-dialog { display: flex; width: min(100%, 700px); max-height: min(84vh, 790px); flex-direction: column; padding: 18px; border: 1px solid var(--tone-41464f); border-radius: 8px; background: var(--tone-272a32); box-shadow: 0 16px 44px rgb(0 0 0 / 32%); }
.help-header { display: flex; justify-content: space-between; gap: 12px; padding-bottom: 12px; border-bottom: 1px solid var(--tone-393d46); }
.help-kicker { color: var(--tone-858a93); font-size: 10px; }
.help-header h2 { margin: 3px 0 0; color: var(--tone-cbd0d7); font-size: 17px; font-weight: 350; }
.help-close { width: 29px; height: 29px; border: 0; border-radius: 5px; color: var(--tone-999da6); background: transparent; font-size: 22px; cursor: pointer; }
.help-close:hover { color: var(--tone-d0d3d9); background: var(--tone-32363e); }
.help-scroll { min-height: 0; padding: 3px 4px 2px 0; overflow-y: auto; scrollbar-color: var(--tone-555a64) transparent; scrollbar-width: thin; }
.help-section { padding: 11px 2px 3px; }
.help-section h3 { margin: 0 0 5px; color: var(--tone-b8bec8); font-size: 12px; font-weight: 400; }
.help-section p { margin: 0; color: var(--tone-979ea8); font-size: 11px; line-height: 1.65; white-space: pre-line; }
.help-dialog footer { display: flex; justify-content: flex-end; padding-top: 12px; border-top: 1px solid var(--tone-393d46); }
.help-done { min-width: 76px; min-height: 30px; border: 1px solid transparent; border-radius: 4px; color: var(--tone-eff0f2); background: var(--tone-626f81); font-size: 10px; cursor: pointer; }
.help-done:hover { background: var(--tone-6a7789); }
.dialog-enter-active, .dialog-leave-active { transition: opacity 140ms ease; }
.dialog-enter-active .help-dialog, .dialog-leave-active .help-dialog { transition: opacity 140ms ease, transform 170ms var(--ease-out); }
.dialog-enter-from, .dialog-leave-to { opacity: 0; }
.dialog-enter-from .help-dialog, .dialog-leave-to .help-dialog { opacity: 0; transform: translateY(5px) scale(.99); }
</style>
