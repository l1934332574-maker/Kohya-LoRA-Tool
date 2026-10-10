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
    { heading: '选择训练底模', body: '第一引擎的底模架构必须与底模文件本身一致。所有模式默认从 512px 起步；SDXL 可自行提高到 1024px，推荐 16G 显存；FLUX.1 和 Anima 需要各自配套的组件。出图时也应使用与 LoRA 同系列的底模。' },
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
    qwen21_fz: [
      'Qwen-Image-2.1 使用第四引擎 Fizgig；模型放在 models/qwen_image21。DiT、VAE、文本编码器和 Fizgig 训练适配器是训练必需项；speed LoRA 仅用于预览，可选。',
      '建议准备至少 5 张图片，选择人物、画风或概念训练类型。训练默认 512px，可自行调高；官方 Fast、Standard、Style 预设分别控制 rank 与学习率，Auto 会按训练类型选择。',
      '训练适配器、速度 LoRA 的来源链接可能受网络环境影响；模型窗口提供应用内断点下载和浏览器手动下载入口。',
    ],
    h3_fz: [
      'MiniMax H3 Fizgig 是图片、视频、音频混合训练模式，模型放在 models/minimax_h3。必须使用官方 int8 DiT、文本编码器和视频 VAE；独立音频文件需要音频 VAE。带声音的视频没有音频 VAE 时会忽略声音，只训练画面。训练适配器和 Turbo LoRA 可选。',
      '将图片、视频和音频放在同一原始目录或其子目录，每个媒体文件配同名 .txt 描述。点「扫描媒体和字幕」只检查文件和字幕，不会整理、移动、转码或生成字幕；缺少字幕会阻止训练。MP4 必须为 24fps、帧数符合 17n+5、宽高为 32 的倍数；带音轨时必须为 32kHz 立体声。扫描不检查这些格式，实际格式校验在 Fizgig 缓存阶段完成。视频没有 audio VAE 时会忽略其中的声音；独立音频训练必须提供 audio VAE。',
      '默认 rank 8、alpha 8、学习率 2e-4、50 轮、512 分辨率；56 帧设置只控制预览采样，不会裁剪训练视频。AMD ROCm 是实验性兼容通道，训练兼容性尚未验证。',
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
      '默认训练底模为 Tongyi-MAI/Z-Image（Base 原版）。可使用完整 Diffusers 目录，也可分别指定底模、Qwen3-4B 文本编码器和 16 通道 VAE。',
      '默认模型目录中的 transformer 是主模型分片，text_encoder 与 vae 是配套组件。单个分片不等于完整底模；ComfyUI 单文件加载请使用 Comfy-Org/z_image 的 z_image_bf16.safetensors，搭配 qwen_3_4b.safetensors 与 ae.safetensors。',
      '先用 Z-Image Base 工作流验证 LoRA，保持底模、提示词、种子和采样设置一致，再对比不同权重。第三方 Turbo 版本的效果需要单独验证；不应仅凭权重大小判断训练质量。',
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
        <nav v-if="kind === 'mode' && mode === 'zimage'" class="reference-links" aria-label="Z-Image 出图资源">
          <a href="https://huggingface.co/Comfy-Org/z_image/tree/main/split_files" target="_blank" rel="noopener noreferrer">官方 ComfyUI 模型与组件 ↗</a>
          <a href="https://docs.comfy.org/tutorials/image/z-image/z-image" target="_blank" rel="noopener noreferrer">Base 出图工作流 ↗</a>
        </nav>
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
.reference-links{display:flex;flex-wrap:wrap;gap:8px 16px;padding:12px 2px;font-size:11px}.reference-links a{color:var(--tone-b8bec8);text-underline-offset:3px}
</style>
