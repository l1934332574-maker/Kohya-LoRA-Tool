<script setup lang="ts">
import type { CaptionServiceSettings } from '../bridge'

const props = defineProps<{
  settings: CaptionServiceSettings
  locked: boolean
  desktop: boolean
  dirty: boolean
  saving: boolean
  remote: boolean
  notice: string
}>()
const emit = defineEmits<{ patch: [value: Partial<CaptionServiceSettings>]; changed: []; save: []; back: []; advice: [] }>()
const tab = defineModel<'connection' | 'permissions'>('tab', { required: true })
const apiKey = defineModel<string>('apiKey', { required: true })
const clearKey = defineModel<boolean>('clearKey', { required: true })
const allowRemote = defineModel<boolean>('allowRemote', { required: true })
const allowInstall = defineModel<boolean>('allowInstall', { required: true })
const allowDownload = defineModel<boolean>('allowDownload', { required: true })
const allowRemoteImages = defineModel<boolean>('allowRemoteImages', { required: true })
const autoReview = defineModel<boolean>('autoReview', { required: true })
const allowAutoTrain = defineModel<boolean>('allowAutoTrain', { required: true })
function patch(field: 'provider' | 'base_url' | 'model', event: Event) {
  const value = (event.target as HTMLInputElement).value
  emit('patch', { [field]: value } as Partial<CaptionServiceSettings>)
}
</script>

<template>
  <section class="preferences" aria-label="助手设置">
    <nav class="preferences-tabs" aria-label="设置分类">
      <button type="button" :class="{ selected: tab==='connection' }" :aria-pressed="tab==='connection'" @click="tab='connection'">连接服务</button>
      <button type="button" :class="{ selected: tab==='permissions' }" :aria-pressed="tab==='permissions'" @click="tab='permissions'">执行权限</button>
    </nav>
    <div class="preferences-body">
      <section v-if="tab==='connection'" class="settings-section">
        <div class="section-heading"><h3>让助手使用你的 AI 模型</h3><p>填写一次即可保存。支持本地服务，也支持兼容接口的在线服务。</p></div>
        <p v-if="locked" class="settings-note">助手执行期间连接设置已锁定。结束当前对话后可以修改。</p>
        <label class="setting-field"><span>服务类型</span><select :value="settings.provider" :disabled="locked" @change="patch('provider',$event)"><option value="compatible">兼容接口 · 本地或在线</option><option value="ollama">Ollama · 本地模型</option></select></label>
        <label class="setting-field"><span>服务地址</span><input type="url" :value="settings.base_url" :disabled="locked" placeholder="http://127.0.0.1:1234/v1" spellcheck="false" @input="patch('base_url',$event)"><small>填写服务提供的接口地址。</small></label>
        <label class="setting-field"><span>模型名称</span><input :value="settings.model" :disabled="locked" placeholder="填写服务中实际可用的模型名" spellcheck="false" @input="patch('model',$event)"></label>
        <label class="setting-field"><span>API 密钥 <em>{{ settings.has_key?'已保存':'按需填写' }}</em></span><input v-model="apiKey" :disabled="locked" type="password" autocomplete="new-password" placeholder="留空即可保留已保存的密钥" @input="emit('changed')"><small>密钥不进入助手的对话上下文。</small></label>
        <label class="setting-check compact"><input v-model="clearKey" type="checkbox" :disabled="locked" @change="emit('changed')"><span>清除已保存的密钥</span></label>
        <label v-if="settings.provider==='ollama'" class="setting-check compact"><input type="checkbox" :checked="settings.unload_after" :disabled="locked" @change="emit('patch',{unload_after:($event.target as HTMLInputElement).checked})"><span><strong>参数建议结束后请求释放本地模型</strong><small>仅用于参数建议模式；训练助手的连续对话仍保持模型驻留。</small></span></label>
        <div class="settings-note"><strong>{{ settings.provider==='ollama'?'本地模型与训练显存':'使用在线或本地兼容服务' }}</strong><p>{{ settings.provider==='ollama'?'聊天时模型保持驻留，GPU 训练前请求卸载。':'在线文字服务需要在执行权限中允许发送对话；本地兼容服务没有统一卸载接口，训练前需释放文字模型显存。' }}</p></div>
        <div class="advice-link"><span>只想咨询参数，不执行操作？</span><button type="button" @click="emit('advice')">进入参数建议</button></div>
      </section>
      <section v-else class="settings-section">
        <div class="section-heading"><h3>决定助手可以帮到哪一步</h3><p>这些选项用于下一次目标。没有授予的操作，助手会在需要时询问你。</p></div>
        <p v-if="locked" class="settings-note">当前目标已开始，权限暂时锁定。额外操作仍会通过对话询问。</p>
        <fieldset :disabled="locked">
          <legend>准备环境与文件</legend>
          <label class="setting-check"><input v-model="allowInstall" type="checkbox"><span><strong>安装或修复训练组件</strong><small>检查缺少的组件，调用工具已有的安装与修复流程。</small></span></label>
          <label class="setting-check"><input v-model="allowDownload" type="checkbox"><span><strong>查找并下载模型</strong><small>下载前说明来源、文件和保存目录。</small></span></label>
        </fieldset>
        <fieldset :disabled="locked">
          <legend>开始训练的方式</legend>
          <label class="setting-check"><input v-model="autoReview" type="checkbox"><span><strong>标签文件完整时自动继续</strong><small>只检查文件是否缺失或为空；图片与文字是否匹配仍需要你判断。</small></span></label>
          <label class="setting-check"><input v-model="allowAutoTrain" type="checkbox"><span><strong>准备好后自动开始训练</strong><small>关闭时，先展示方案并等你确认。</small></span></label>
        </fieldset>
        <fieldset :disabled="locked">
          <legend>在线服务与图片</legend>
          <label v-if="remote" class="setting-check"><input v-model="allowRemote" type="checkbox"><span><strong>允许本次对话使用在线文字服务</strong><small>发送目标、对话、训练设置、工具结果及按需读取的日志，可能收费；不包含图集图片。</small></span></label>
          <p v-else class="local-service-note">当前文字服务地址在本机，对话使用本地服务。</p>
          <label class="setting-check"><input v-model="allowRemoteImages" type="checkbox"><span><strong>允许在线视觉服务读取图集图片</strong><small>只有需要视觉处理时才发送，可能收费。这项权限与文字对话分开。</small></span></label>
        </fieldset>
        <p class="settings-note">电脑命令仍会展示用途和完整命令，每条单独确认。</p>
      </section>
      <p v-if="notice" class="settings-notice" role="status">{{ notice }}</p>
    </div>
    <footer class="preferences-footer">
      <span>{{ tab==='connection'?(dirty?'连接设置尚未保存':'连接设置保存在本机'):'权限选择会用于下一次目标' }}</span>
      <div><button type="button" @click="emit('back')">返回对话</button><button v-if="tab==='connection'" class="primary" type="button" :disabled="locked || !desktop || !dirty" @click="emit('save')">{{ saving?'保存中…':'保存连接' }}</button></div>
    </footer>
  </section>
</template>

<style scoped>
.preferences{display:flex;flex:1;flex-direction:column;min-height:0;min-width:0;overflow:hidden}.preferences *{box-sizing:border-box;min-width:0}.preferences-tabs{display:flex;gap:24px;padding:0 24px;border-bottom:1px solid var(--border);flex:none}.preferences-tabs button{padding:14px 0;border:0;border-bottom:2px solid transparent;border-radius:0;background:transparent;color:var(--hint);font:inherit;font-size:13px;cursor:pointer}.preferences-tabs button.selected{color:var(--text);border-bottom-color:var(--assistant-accent)}.preferences-body{flex:1;overflow-y:auto;overflow-x:hidden;min-height:0;padding:24px;overscroll-behavior:contain;scrollbar-gutter:stable}.section-heading{margin-bottom:22px}.section-heading h3{font-size:17px;font-weight:600;margin:0 0 8px;color:var(--text)}.section-heading p{margin:0;color:var(--hint);font-size:12px;line-height:1.65}.setting-field{display:grid;gap:8px;margin:0 0 18px;font-size:13px;line-height:1.5}.setting-field>span{display:flex;gap:8px;align-items:baseline;color:var(--text)}.setting-field em{font-style:normal;color:var(--hint);font-size:11px}.setting-field input,.setting-field select{display:block;width:100%;min-width:0;max-width:100%;height:42px;padding:0 12px;border:1px solid var(--border);border-radius:9px;background:var(--bg);font:inherit;color:var(--text);outline:none}.setting-field input:focus-visible,.setting-field select:focus-visible{border-color:var(--assistant-accent);box-shadow:0 0 0 3px var(--assistant-accent-soft)}.setting-field small,.setting-check small{font-size:11px;color:var(--hint);line-height:1.65}.setting-check{display:grid;grid-template-columns:18px minmax(0,1fr);align-items:start;column-gap:12px;max-width:100%;margin:0;padding:12px 0;cursor:pointer}.setting-check input[type='checkbox']{appearance:auto;width:16px;height:16px;min-width:16px;max-width:16px;padding:0;margin:3px 0 0;accent-color:var(--assistant-accent);flex:none}.setting-check>span{display:grid;gap:5px;line-height:1.5;overflow-wrap:anywhere;font-size:12px}.setting-check strong{font-weight:500;font-size:13px;color:var(--text)}.setting-check.compact{padding:0 0 16px}.settings-section fieldset{min-inline-size:0;min-width:0;padding:8px 15px;margin:0 0 20px;border:1px solid var(--border);border-radius:12px}.settings-section legend{padding:0 7px;color:var(--hint);font-size:11px}.settings-section fieldset .setting-check+.setting-check{border-top:1px solid var(--border)}.settings-note,.settings-notice{padding:12px 14px;border-radius:10px;background:var(--assistant-subtle);font-size:11px;line-height:1.65;color:var(--hint);margin:10px 0 20px;overflow-wrap:anywhere}.settings-note strong{color:var(--text);font-weight:500}.settings-note p{margin:5px 0 0}.local-service-note{color:var(--hint);font-size:11px;line-height:1.6;margin:8px 0 12px}.advice-link{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-top:20px;border-top:1px solid var(--border);padding-top:18px;font-size:11px;color:var(--hint)}.advice-link button{border:0;background:transparent;color:var(--text);font:inherit;cursor:pointer;padding:6px 0}.preferences-footer{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:16px 24px;border-top:1px solid var(--border);flex:none}.preferences-footer>span{color:var(--hint);font-size:11px;line-height:1.5;overflow-wrap:anywhere}.preferences-footer>div{display:flex;gap:8px;flex:none}.preferences-footer button{font:inherit;font-size:12px;border:1px solid var(--border);border-radius:8px;padding:9px 12px;background:transparent;color:var(--text);cursor:pointer}.preferences-footer button.primary{background:var(--assistant-accent);color:var(--assistant-on-accent);border-color:transparent}button:disabled,input:disabled,select:disabled,fieldset:disabled{opacity:.55;cursor:default}fieldset:disabled input{opacity:1}button:focus-visible{outline:2px solid var(--assistant-accent);outline-offset:3px}button:hover:not(:disabled){filter:brightness(1.12)}@media(max-width:420px){.preferences-tabs{padding-inline:16px}.preferences-body{padding:20px 16px}.preferences-footer{padding:12px 16px;flex-wrap:wrap}.preferences-footer>div{margin-left:auto}}
</style>
