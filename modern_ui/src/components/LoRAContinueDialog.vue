<script setup lang="ts">
import { ref, watch } from 'vue'
const props = defineProps<{ open: boolean; projectName: string; runId?: string; sample?: string; refine?: boolean }>()
const emit = defineEmits<{ close: []; created: [name: string] }>()
const rows = ref<Array<{path: string; name: string}>>([])
const source = ref('')
const resolution = ref(512)
const oldResolution = ref(512)
const epochs = ref(2)
const steps = ref(200)
const learningRate = ref('1e-4')
const kind = ref('append')
const usesSteps = ref(false)
const busy = ref(false)
const loading = ref(false)
const error = ref('')
const warning = ref('')
let request = 0
watch(() => props.open, async (open) => {
  const token = ++request
  if (!open) return
  rows.value = []; source.value = ''; error.value = ''; warning.value = ''; loading.value = true
  kind.value = props.refine ? 'refine' : 'append'
  epochs.value = 2; steps.value = 200
  try {
    const api = window.pywebview?.api
    if (!api) throw new Error('此功能需要桌面版。')
    const result = await api.lora_continue_sources(props.projectName, props.runId || '', props.sample || '')
    if (token !== request) return
    if (!result.ok) throw new Error(result.error || '读取来源失败。')
    rows.value = result.checkpoints || []; source.value = result.matched || ''
    warning.value = result.warning || ''
    oldResolution.value = result.resolution || 512
    resolution.value = props.refine ? (oldResolution.value < 768 ? 768 : Math.max(1024, oldResolution.value + 64)) : oldResolution.value
    learningRate.value = String(result.learning_rate || '1e-4')
    usesSteps.value = !!result.uses_steps
  } catch (e) { if (token === request) error.value = e instanceof Error ? e.message : '读取失败。' }
  finally { if (token === request) loading.value = false }
})
async function browse() {
  const result = await window.pywebview?.api.choose_path('model', source.value, 'initial_lora')
  if (result?.ok && result.path) source.value = result.path
}
async function create() {
  if (busy.value || !source.value) return
  busy.value = true; error.value = ''
  try {
    const result = await window.pywebview!.api.create_lora_continue_project(props.projectName, {
      source_path: source.value, run_id: props.runId || '', sample: props.sample || '', kind: kind.value,
      resolution: resolution.value, epochs: epochs.value, steps: steps.value, learning_rate: learningRate.value,
    })
    if (!result.ok || !result.project_name) throw new Error(result.error || '创建失败。')
    emit('created', result.project_name)
  } catch (e) { error.value = e instanceof Error ? e.message : '创建失败。' }
  finally { busy.value = false }
}
</script>

<template>
  <div v-if="open" class="continue-backdrop">
    <section class="continue-dialog" role="dialog" aria-modal="true" aria-labelledby="continue-title" :aria-busy="busy || loading">
      <header><h2 id="continue-title">已有 LoRA · 追加训练 / 高清精修</h2><button :disabled="busy" aria-label="关闭" @click="emit('close')">×</button></header>
      <p>继承来源配置，新建独立项目；从选中权重开始，重新计算追加训练的轮数和优化器状态。</p>
      <p v-if="loading">正在查找来源检查点…</p>
      <p v-if="error" role="alert" class="continue-error">{{ error }}</p>
      <p v-if="warning" class="continue-warning">{{ warning }}</p>
      <fieldset :disabled="busy || loading">
        <label>来源检查点<select v-model="source"><option value="">请选择权重文件</option><option v-for="row in rows" :key="row.path" :value="row.path">{{ row.name }}</option><option v-if="source && !rows.some(row => row.path === source)" :value="source">{{ source }}</option></select></label>
        <div class="continue-source"><input v-model="source" placeholder=".safetensors 路径"><button @click="browse">选择文件</button></div>
        <label>训练方式<select v-model="kind"><option value="append">追加训练</option><option value="refine">高清精修</option></select></label>
        <div class="continue-grid"><label>目标分辨率（原 {{ oldResolution }}）<input v-model.number="resolution" type="number" min="256" max="2048" step="64"></label><label v-if="usesSteps">追加步数<input v-model.number="steps" type="number" min="100" max="6000" step="100"></label><label v-else>追加轮数<input v-model.number="epochs" type="number" min="1" max="100"></label></div>
        <details><summary>学习率</summary><label>训练学习率<input v-model="learningRate"><small>默认沿用来源设置；高清精修可酌情降低。</small></label></details>
      </fieldset>
      <p class="continue-note">使用原训练底模。继承当前磁盘上的原图、标签与触发词，重新生成目标分辨率的副本和缓存。高清阶段仍需要相应显存；结果不会覆盖原 LoRA。</p>
      <footer><button :disabled="busy" @click="emit('close')">取消</button><button :disabled="busy || loading || !source" @click="create">{{ busy ? '正在复制权重并创建…' : '创建并打开项目' }}</button></footer>
    </section>
  </div>
</template>

<style scoped>
.continue-backdrop { position:fixed; inset:0; z-index:2000; display:grid; place-items:center; padding:24px; background:#0009; }
.continue-dialog { width:min(620px,100%); max-height:90vh; overflow:auto; padding:24px; border:1px solid var(--border); border-radius:12px; background:var(--card, #22262d); color:var(--text, #ddd); box-shadow:0 20px 70px #0006; }
header,footer,.continue-source { display:flex; align-items:center; justify-content:space-between; gap:12px; } h2 { font-size:18px; margin:0; } p,small { color:var(--sub); font-size:12px; line-height:1.7; } fieldset { border:0; padding:0; margin:18px 0; display:grid; gap:14px; } label { display:grid; gap:7px; font-size:13px; } input,select,button { padding:9px 12px; border:1px solid var(--border); border-radius:6px; color:inherit; background:var(--input, #191d23); min-width:0; } button { cursor:pointer; } button:disabled { opacity:.45; cursor:default; } .continue-source input { flex:1; } .continue-grid { display:grid; grid-template-columns:1fr 1fr; gap:14px; } .continue-error { color:#efaaaa; } .continue-warning { color:#dac58d; } footer { justify-content:flex-end; margin-top:20px; } details label { margin-top:12px; } .continue-note { margin-bottom:0; }
</style>
