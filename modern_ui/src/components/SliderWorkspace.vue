<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { ModeWorkspaceData, ProjectCard, ProjectConfig, SliderSettings } from '../bridge'
import SliderSampleStrip from './SliderSampleStrip.vue'
const props = defineProps<{ project: ProjectCard; config?: ProjectConfig | null; details?: ModeWorkspaceData | null; desktop: boolean;
  choosePath: (kind: 'folder' | 'model', currentPath?: string, memoryKey?: string) => Promise<string | null> }>()
const emit = defineEmits<{ back: [patch: ProjectConfig]; notify: [message: string]; save: [patch: ProjectConfig]; train: [patch: ProjectConfig]; classicAction: [action: string, patch?: ProjectConfig] }>()
const defaults: SliderSettings = { schema_version: 1, purpose: 'bidirectional', source: 'text', name: '', neutral: '', positive: '', negative: '', effect: '',
  positive_dir: '', negative_dir: '', pairs: [], preset: 'trial', steps: 768, rank: 8, alpha: 8, learning_rate: .00005, resolution: 512, seed: 42,
  guidance: 1, diff_weight: .75, precision: 'auto', validation_prompts: '', sample_steps: 25, cfg: 4.5 }
const draft = reactive<SliderSettings>({ ...defaults })
const base = ref('')
const saved = ref('')
const checking = ref(false)
const pairError = ref('')
const positiveFiles = ref<string[]>([])
const negativeFiles = ref<string[]>([])
const pairingNote = ref('')
const pairsChecked = ref(false)
const view = ref<{ positive: string; negative: string } | null>(null)
const pairImages = ref<{ positive: string; negative: string }>({ positive: '', negative: '' })
const kinds = [{ key: 'bidirectional', label: '双向变化', note: '正负权重分别控制两端状态。' }, { key: 'reduce', label: '减弱效果', note: '正权重越大，抑制越强。' }, { key: 'enhance', label: '增强效果', note: '正权重越大，增强越强。' }] as const
const positiveLabel = computed(() => draft.purpose === 'reduce' ? '效果减弱图像' : draft.purpose === 'enhance' ? '效果增强图像' : '正向图像')
const negativeLabel = computed(() => draft.purpose === 'bidirectional' ? '负向图像' : '基准图像')
const patch = computed<ProjectConfig>(() => ({ training_kind: 'slider', base_model: base.value, unet_only: true,
  slider: JSON.parse(JSON.stringify(draft)), params: { fizgig_version: 'v7.0.1' } }))
const unsaved = computed(() => JSON.stringify(patch.value) !== saved.value)
const requestedSteps = computed(() => draft.preset === 'trial' ? 128 : draft.preset === 'formal' ? 768 : draft.steps)
const missing = computed(() => !base.value ? '请选择底模' : !draft.name.trim() ? '请填写滑块名称' : !draft.neutral.trim() ? '请填写基准提示词' :
  draft.source === 'pairs' ? !draft.positive_dir || !draft.negative_dir ? '请选择两端图像目录' : '' :
  draft.purpose === 'bidirectional' ? !draft.positive.trim() || !draft.negative.trim() ? '请填写两端完整提示词' : '' : !draft.effect.trim() ? '请填写目标效果' : '')
let hydrating = false
function hydrate() {
  hydrating = true
  Object.assign(draft, { ...defaults, ...(props.config?.slider || {}), pairs: [...(props.config?.slider?.pairs || [])] })
  base.value = String(props.config?.base_model || '')
  saved.value = JSON.stringify(patch.value)
  hydrating = false
}
watch(() => props.config, hydrate, { immediate: true })
watch([() => draft.positive_dir, () => draft.negative_dir], () => {
  if (hydrating) return
  draft.pairs = []; pairsChecked.value = false; positiveFiles.value = []; negativeFiles.value = []; pairError.value = ''; pairingNote.value = ''
}, { flush: 'sync' })
async function browse(kind: 'model' | 'positive' | 'negative') {
  const current = kind === 'model' ? base.value : draft[kind === 'positive' ? 'positive_dir' : 'negative_dir']
  const path = await props.choosePath(kind === 'model' ? 'model' : 'folder', current, 'slider_' + kind)
  if (!path) return
  if (kind === 'model') base.value = path
  else { draft[kind === 'positive' ? 'positive_dir' : 'negative_dir'] = path; await Promise.resolve(); if (draft.positive_dir && draft.negative_dir) void checkPairs() }
}
async function checkPairs() {
  if (!window.pywebview?.api || checking.value) return
  checking.value = true
  try {
    const response = await window.pywebview.api.inspect_slider_pairs(props.project.name, JSON.parse(JSON.stringify(draft)))
    positiveFiles.value = response.positive_files || []
    negativeFiles.value = response.negative_files || []
    if (!response.ok) { pairError.value = response.error || '图片配对检查失败'; pairsChecked.value = false; return }
    draft.pairs = response.pairs || []
    pairsChecked.value = true
    pairError.value = ''
    pairingNote.value = `${response.train_count || 0} 对训练 · ${response.holdout_count || 0} 对验证。 ${(response.warnings || []).join(' ')}`
  } catch (exc) { pairError.value = exc instanceof Error ? exc.message : '无法检查图片对。' }
  finally { checking.value = false }
}
function addPair() { draft.pairs.push({ positive: positiveFiles.value[0] || '', negative: negativeFiles.value[0] || '' }); pairsChecked.value = false }
async function showPair(pair: { positive: string; negative: string }) {
  const api = window.pywebview?.api
  if (!api) return
  view.value = pair
  pairImages.value = { positive: '', negative: '' }
  try {
    for (const side of ['positive', 'negative'] as const) {
      const listing = await api.inspect_dataset(draft[side === 'positive' ? 'positive_dir' : 'negative_dir'])
      if (!listing.preview_token) continue
      const result = await api.get_dataset_preview(listing.preview_token, pair[side])
      if (view.value === pair && result.ok) pairImages.value[side] = result.data_url || ''
    }
  } catch (exc) { emit('notify', exc instanceof Error ? exc.message : '无法读取图片对。') }
}
function startTraining() {
  if (missing.value) return emit('notify', missing.value)
  if (!props.desktop) return emit('notify', '浏览器仅预览界面；训练请使用桌面程序。')
  emit('train', patch.value)
}
defineExpose({ hasUnsavedChanges: () => unsaved.value, startTraining, save: () => emit('save', patch.value),
  guideAction: async (action: string) => {
    if (action === 'cmd_pick_model_type') await browse('model')
    else if (action === 'cmd_pick_raw') document.getElementById('slider-goal-panel')?.scrollIntoView({ block: 'start' })
    else emit('classicAction', action, patch.value)
    return patch.value
  }, openModelDialog: () => browse('model') })
</script>

<template>
  <div class="slider-workspace">
    <header class="workspace-header"><button type="button" @click="emit('back', patch)">← 返回项目</button><div><h1>概念滑块 LoRA</h1><span>{{ project.name }} · {{ project.base_type === 'anima' ? 'Anima · 标准 28 层' : 'SDXL' }}</span></div><button type="button" @click="emit('classicAction', 'export_config', patch)">导出配置</button><button type="button" :disabled="!unsaved" @click="emit('save', patch)">{{ unsaved ? '保存设置' : '设置已保存' }}</button></header>
    <div class="intro"><p>通过文字或图片对定义变化方向，以 LoRA 权重调节强度。</p><span>实验性功能 · GPU 实训待验证</span></div>
    <div class="model-bar"><div><span>训练底模</span><strong>{{ base ? base.split(/[\\/]/).pop() : '未选择底模' }}</strong><small>{{ base || (project.base_type === 'anima' ? '标准 28 层 Anima · 需配置文本编码器与 VAE' : '完整 SDXL safetensors 底模') }}</small></div><button type="button" @click="browse('model')">选择底模</button><button type="button" @click="emit('classicAction', project.base_type === 'anima' ? 'cmd_dl_anima_fz_models' : 'cmd_dl_sdxl_fz_models', patch)">获取模型</button><button type="button" @click="emit('classicAction', 'cmd_install_fizgig', patch)">配置环境</button><button v-if="project.base_type === 'anima'" type="button" @click="emit('classicAction', 'anima_components', patch)">配置 Anima 组件</button></div>
    <div class="workspace-columns">
      <div class="left-flow">
        <section id="slider-goal-panel" class="panel"><header><span class="step">01</span><h2>训练目标</h2></header>
          <label>滑块名称<input v-model="draft.name" placeholder="概念或属性名称"></label>
          <fieldset class="purpose"><legend>调节方式</legend><label v-for="kind in kinds" :key="kind.key" :class="{ selected: draft.purpose === kind.key }"><input v-model="draft.purpose" type="radio" name="slider-purpose" :value="kind.key"><strong>{{ kind.label }}</strong><small>{{ kind.note }}</small></label></fieldset>
          <div class="direction"><span>{{ draft.purpose === 'bidirectional' ? '−1 · 负向' : '0 · 底模基线' }}</span><span v-if="draft.purpose === 'bidirectional'" title="权重为 0 时停用 LoRA">0 · 底模基线</span><span>{{ draft.purpose === 'reduce' ? '+1 · 减弱' : draft.purpose === 'enhance' ? '+1 · 增强' : '+1 · 正向' }}</span></div>
        </section>
        <section class="panel"><header><span class="step">02</span><h2>训练数据</h2></header>
          <div class="segmented" role="group" aria-label="数据来源"><button type="button" :aria-pressed="draft.source==='text'" @click="draft.source='text'">文字指导 · 无需图片</button><button type="button" :aria-pressed="draft.source==='pairs'" @click="draft.source='pairs'">图片对</button></div>
          <label>基准提示词<textarea v-model="draft.neutral" rows="2" placeholder="主体、构图、风格等共有内容"></textarea><small>{{ draft.source === 'text' ? '除目标属性外，两端内容保持一致。' : '两端图像共用的训练提示词。' }}</small></label>
          <template v-if="draft.source==='text'">
            <div v-if="draft.purpose==='bidirectional'" class="two-fields"><label>负向提示词<textarea v-model="draft.negative" rows="3" placeholder="共有内容 + 负向状态（完整提示词）"></textarea></label><label>正向提示词<textarea v-model="draft.positive" rows="3" placeholder="共有内容 + 正向状态（完整提示词）"></textarea></label></div>
            <label v-else>目标效果<input v-model="draft.effect" placeholder="需要调节的属性"></label>
          </template>
          <template v-else>
            <div class="two-fields"><label>{{ negativeLabel }}<div class="path-field"><input v-model="draft.negative_dir" placeholder="选择文件夹"><button type="button" @click="browse('negative')">选择</button></div></label><label>{{ positiveLabel }}<div class="path-field"><input v-model="draft.positive_dir" placeholder="选择文件夹"><button type="button" @click="browse('positive')">选择</button></div></label></div>
            <p>同名文件自动配对，扩展名可不同；两端应保持主体与构图一致。</p>
            <div class="pair-actions"><button type="button" :disabled="checking || !draft.positive_dir || !draft.negative_dir" @click="checkPairs">{{ checking ? '正在检查…' : '检查图片配对' }}</button><button type="button" :disabled="!positiveFiles.length || !negativeFiles.length" @click="addPair">添加配对</button><span v-if="pairsChecked">检查完成</span></div>
            <div v-if="draft.pairs.length" class="pair-list"><div class="pair-head"><span>{{ negativeLabel }}</span><span>{{ positiveLabel }}</span><span></span></div><div v-for="(pair,index) in draft.pairs" :key="index" class="pair-row"><select v-model="pair.negative" aria-label="负端图片" @change="pairsChecked=false"><option v-for="name in negativeFiles" :key="name" :value="name">{{ name }}</option></select><select v-model="pair.positive" aria-label="正端图片" @change="pairsChecked=false"><option v-for="name in positiveFiles" :key="name" :value="name">{{ name }}</option></select><button type="button" @click="showPair(pair)">查看</button><button type="button" :aria-label="`移除第 ${index+1} 对`" @click="draft.pairs.splice(index,1);pairsChecked=false">×</button></div></div>
            <p v-if="pairingNote">{{ pairingNote }}</p><p v-if="pairError" role="status" class="feedback">{{ pairError }}</p>
            <small>同步中心裁剪，原图保留。</small>
          </template>
        </section>
        <section class="panel"><header><span class="step">03</span><h2>训练配置</h2></header>
          <fieldset class="training-options"><legend class="sr-only">训练量</legend><label v-for="item in [{key:'trial',label:'试训',note:'128 步'}, {key:'formal',label:'正式训练',note:'768 步'}, {key:'custom',label:'自定义',note:'手动设置步数'}]" :key="item.key" :class="{selected:draft.preset===item.key}"><input v-model="draft.preset" type="radio" name="slider-preset" :value="item.key"><strong>{{ item.label }}</strong><small>{{ item.note }}</small></label></fieldset>
          <div class="two-fields"><label>训练分辨率<select v-model.number="draft.resolution"><option :value="256">256</option><option :value="512">512 · 默认</option><option :value="768">768</option><option :value="1024">1024</option></select></label><label v-if="draft.preset==='custom'">目标步数<input v-model.number="draft.steps" type="number" min="32" max="10000"></label></div>
          <p>目标 {{ requestedSteps }} 步，按完整轮次取整。</p>
          <details class="advanced"><summary>高级参数</summary><div class="advanced-fields"><label>LoRA Rank<input v-model.number="draft.rank" type="number" min="1" max="128"></label><label>LoRA Alpha<input v-model.number="draft.alpha" type="number" min=".1" max="128" step=".1"></label><label>学习率（固定）<input v-model.number="draft.learning_rate" type="number" min=".0000001" max=".001" step=".00001"></label><label>底模精度<select v-model="draft.precision"><option value="auto">自动</option><option value="bf16">BF16</option><option value="int8">INT8</option><option value="nf4">NF4</option></select></label><label>随机种子<input v-model.number="draft.seed" type="number" min="0" max="2147483646"></label><label>采样步数<input v-model.number="draft.sample_steps" type="number" min="10" max="60"></label><label>采样 CFG<input v-model.number="draft.cfg" type="number" min="1" max="12" step=".5"></label><label v-if="draft.source==='text'">方向指导强度<input v-model.number="draft.guidance" type="number" min=".1" max="5" step=".1"></label><label v-else>差异区域权重<input v-model.number="draft.diff_weight" type="number" min="0" max="1" step=".1"></label></div><label>验证提示词<textarea v-model="draft.validation_prompts" rows="3" placeholder="每行一条，最多 4 条；使用不同场景或构图"></textarea><small>仅用于采样验证；留空采用远景与特写构图。</small></label></details>
          <div class="launch"><span>{{ missing || '确认训练配置后启动' }}</span><button class="primary" type="button" :disabled="Boolean(missing)" @click="startTraining">{{ draft.preset==='trial' ? '开始试训' : '开始训练' }}</button></div>
        </section>
      </div>
      <aside class="result-column"><SliderSampleStrip :project-name="project.name" :desktop="desktop"/><div class="quality-note"><details><summary>使用说明</summary><ul><li>权重 0 停用 LoRA，使用底模基线。</li><li>文字模式依赖底模已有概念；自定义视觉效果可使用图片对。</li><li>每次从头训练；试训结束时采样，正式训练定期采样。</li><li>比较变化方向、内容保持及跨场景效果；损失值仅供参考。</li></ul></details><button type="button" @click="emit('classicAction','output_dir',patch)">打开输出目录</button></div></aside>
    </div>
    <Teleport to="body"><div v-if="view" class="pair-preview" role="dialog" aria-modal="true" aria-label="图片对预览" @click.self="view=null" @keydown.esc="view=null"><div><header><strong>对照图片</strong><button type="button" autofocus @click="view=null">关闭</button></header><div class="pair-images"><figure v-for="side in ['negative','positive'] as const" :key="side"><img v-if="pairImages[side]" :src="pairImages[side]" :alt="side==='negative' ? negativeLabel : positiveLabel"><figcaption>{{ side==='negative' ? negativeLabel : positiveLabel }}</figcaption></figure></div></div></div></Teleport>
  </div>
</template>

<style scoped>
.slider-workspace{
  flex:1 1 0;
  width:100%;
  min-width:0;
  min-height:0;
  max-width:1600px;
  margin:0 auto;
  padding:20px 24px 28px;
  overflow-x:hidden;
  overflow-y:auto;
  scrollbar-gutter:stable;
  scrollbar-color:var(--tone-555a64) transparent;
  scrollbar-width:thin;
  color:var(--text);
}
.slider-workspace::-webkit-scrollbar{width:10px}
.slider-workspace::-webkit-scrollbar-thumb{border:2px solid var(--bg);border-radius:8px;background:var(--tone-4d5159)}
.workspace-header{display:flex;align-items:center;gap:18px;margin-bottom:24px}.workspace-header>div{flex:1;min-width:0}.workspace-header h1{font-size:24px;line-height:1.3;margin:0 0 5px;font-weight:600}.workspace-header span{font-size:13px;color:var(--hint)}button,input,textarea,select{font:inherit;color:var(--text);background:var(--bg);border:1px solid var(--border);border-radius:8px;font-size:13px}button{padding:10px 14px;cursor:pointer;flex:none;min-height:38px}button:hover:not(:disabled){border-color:var(--accent)}button:disabled{opacity:.55;cursor:default}input:not([type=radio]),textarea,select{width:100%;padding:11px 12px;min-width:0;box-sizing:border-box}textarea{resize:vertical;line-height:1.6}.intro{margin-bottom:20px;padding-left:16px;border-left:3px solid var(--accent)}.intro p{margin:0 0 6px}.intro>span{font-size:12px;color:var(--hint)}p,small{color:var(--hint);line-height:1.7;font-size:13px}p{margin:0}.model-bar{display:flex;align-items:center;gap:10px;padding:16px 20px;margin-bottom:22px;background:var(--card);border:1px solid var(--border);border-radius:12px;flex-wrap:wrap}.model-bar>div{flex:1;min-width:240px;display:grid;gap:5px}.model-bar span{font-size:12px;color:var(--hint)}.model-bar strong{font-size:14px;font-weight:500}.model-bar small{overflow-wrap:anywhere;font-size:11px}.workspace-columns{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(340px,.9fr);gap:22px;align-items:start}.left-flow{display:grid;gap:18px;min-width:0}.panel{display:grid;gap:17px;padding:24px;border:1px solid var(--border);border-radius:16px;background:var(--card);min-width:0}.panel>header{display:flex;align-items:center;gap:12px}h2{font-size:17px;font-weight:550;margin:0}.step{color:var(--hint);font-size:12px;font-variant-numeric:tabular-nums}label{display:grid;gap:8px;font-size:13px;min-width:0}label small{font-size:12px}.purpose,.training-options{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;border:0;padding:0;margin:0}.purpose legend{font-size:13px;margin-bottom:10px}.purpose label,.training-options label{display:grid;grid-template-columns:16px 1fr;gap:7px;padding:13px 12px;border:1px solid var(--border);border-radius:10px;cursor:pointer;align-items:center}.purpose small,.training-options small{grid-column:1/-1;font-size:11px}.purpose strong,.training-options strong{font-size:13px;font-weight:500}.selected{border-color:var(--accent)!important;background:var(--bg)}input[type=radio]{margin:0;accent-color:var(--accent)}.direction{display:flex;justify-content:space-between;gap:10px;padding:12px 14px;background:var(--bg);border-radius:8px;font-size:12px}.direction span:nth-child(2){color:var(--hint)}.two-fields{display:grid;grid-template-columns:1fr 1fr;gap:14px}.segmented{display:flex;gap:8px;flex-wrap:wrap}.segmented [aria-pressed=true]{border-color:var(--accent);background:var(--bg)}.path-field{display:flex;gap:7px}.path-field input{flex:1;width:0}.advanced{border-top:1px solid var(--border);padding-top:14px}.advanced summary{cursor:pointer;font-size:13px}.advanced-fields{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:18px 0}.launch{display:flex;align-items:center;justify-content:space-between;gap:12px;border-top:1px solid var(--border);padding-top:18px}.launch span{font-size:12px;color:var(--hint)}.primary{background:var(--accent);color:var(--bg);border-color:var(--accent);font-weight:600}.result-column{display:grid;gap:18px;min-width:0}.quality-note{padding:18px 22px;background:var(--card);border:1px solid var(--border);border-radius:12px;display:grid;gap:12px}.quality-note summary{font-size:14px;cursor:pointer}.quality-note ul{padding-left:18px;margin:12px 0 0;font-size:12px;color:var(--hint);line-height:1.7}.quality-note li+li{margin-top:7px}.quality-note button{justify-self:start}.pair-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.pair-actions span{font-size:12px;color:var(--hint)}.pair-list{max-height:310px;overflow:auto;display:grid;gap:8px}.pair-head,.pair-row{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr) auto auto;gap:7px;align-items:center}.pair-head{font-size:11px;color:var(--hint)}.pair-row select{padding:8px 5px;font-size:11px}.pair-row button{padding:6px 8px;min-height:32px;font-size:12px}.feedback{color:var(--text);overflow-wrap:anywhere}.pair-preview{position:fixed;inset:0;z-index:2200;background:rgba(0,0,0,.8);display:grid;place-items:center;padding:20px}.pair-preview>div{width:min(100%,1000px);background:var(--card);border:1px solid var(--border);border-radius:16px;padding:20px}.pair-preview header{display:flex;align-items:center;justify-content:space-between}.pair-images{display:grid;grid-template-columns:1fr 1fr;gap:16px}.pair-images figure{margin:16px 0 0}.pair-images img{width:100%;max-height:65vh;object-fit:contain}.pair-images figcaption{font-size:13px;text-align:center;margin-top:10px}.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}input:focus-visible,textarea:focus-visible,select:focus-visible,button:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:3px}@media(max-width:1200px){.workspace-columns{grid-template-columns:1fr}.slider-workspace{max-width:960px}}@media(max-width:700px){.slider-workspace{padding:16px}.workspace-header{flex-wrap:wrap;gap:12px}.workspace-header h1{font-size:20px}.panel{padding:18px}.purpose,.training-options{grid-template-columns:1fr}.two-fields,.advanced-fields{grid-template-columns:1fr}.direction{flex-wrap:wrap}.launch{align-items:flex-start;flex-direction:column}.launch button{width:100%}.pair-images{grid-template-columns:1fr}.pair-images img{max-height:30vh}}
</style>
