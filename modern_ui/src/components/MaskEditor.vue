<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import type { DatasetSummary, DatasetPreview, ModernTaskStatus } from '../bridge'
const props = defineProps<{ projectName: string; hideLauncher?: boolean }>()
const emit=defineEmits<{updated: []}>()
const maskSource=ref('photo'),maskKind=ref('person')
const open = ref(false), busy = ref(false), saving = ref(false), dirty = ref(false)
const error = ref(''), notice = ref(''), selected = ref(''), issuesOnly = ref(false)
const catalog = ref<DatasetSummary | null>(null), image = ref<DatasetPreview | null>(null)
const names = ref<string[]>([]), thumbnails = ref<Record<string,string>>({})
const canvas = ref<HTMLCanvasElement | null>(null), overlay = ref<HTMLCanvasElement | null>(null)
const viewport = ref<HTMLElement | null>(null), panel = ref<HTMLElement | null>(null)
const viewportSize=ref({width:700,height:600})
let resizeObserver:ResizeObserver | null=null, previousFocus:HTMLElement | null=null, catalogEpoch=0
const tool = ref<'add'|'erase'|'pan'>('add'), brushSize = ref(32), opacity = ref(.5), zoom = ref(1)
const view = ref<'overlay'|'original'|'mask'>('overlay')
const history: ImageData[] = []
const undoCount = ref(0), drawing = ref(false)
let last: [number,number] | null = null
let drag: {x:number;y:number;left:number;top:number} | null = null
let request = 0, timer = 0, polling = false
const pending = ref<null | {name?:string;close?:boolean;reload?:boolean;generate?:boolean}>(null)
const taskId = ref(''), task = ref<ModernTaskStatus | null>(null), logs = ref<string[]>([])
const running = computed(() => task.value?.status === 'running')
const rows = computed(() => catalog.value?.mask_report?.rows || [])
const visibleNames = computed(() => issuesOnly.value ? names.value.filter(n => { const r=rows.value.find(r=>r.name===n); return r && r.status!=='valid' && !['exclude','unmasked'].includes(r.decision) }) : names.value)
const index = computed(() => visibleNames.value.indexOf(selected.value))
const editable = computed(() => image.value?.mask_editable && !busy.value && !saving.value && !running.value)
const stageStyle = computed(() => {
  const w=image.value?.width || 1, h=image.value?.height || 1
  const fit=Math.min(1, (viewportSize.value.width-48)/w, (viewportSize.value.height-48)/h)
  return {width:`${Math.max(1,w*fit*zoom.value)}px`,height:`${Math.max(1,h*fit*zoom.value)}px`}
})
function readImage(url:string):Promise<HTMLImageElement> { return new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=()=>reject(new Error('无法读取图片或遮罩。'));im.src=url}) }
function refreshOverlay(region?: {x:number;y:number;width:number;height:number}) {
  if (!canvas.value || !overlay.value) return
  const src=canvas.value, dst=overlay.value;if(dst.width!==src.width || dst.height!==src.height){dst.width=src.width;dst.height=src.height}
  const ctx=dst.getContext('2d'), source=src.getContext('2d');if(!ctx || !source)return
  const rect=region || {x:0,y:0,width:src.width,height:src.height}
  if(rect.width<=0 || rect.height<=0)return
  const pixels=source.getImageData(rect.x,rect.y,rect.width,rect.height)
  for(let i=0;i<pixels.data.length;i+=4){const value=pixels.data[i] || 0;pixels.data[i]=52;pixels.data[i+1]=211;pixels.data[i+2]=153;pixels.data[i+3]=value}
  ctx.putImageData(pixels,rect.x,rect.y)
}
async function load(name:string) {
  if(!catalog.value?.preview_token || !name)return
  const token=++request;busy.value=true;error.value='';image.value=null
  try {
    const result=await window.pywebview!.api.get_dataset_preview(catalog.value.preview_token,name)
    if(token!==request)return
    if(!result.ok)throw new Error(result.error || '无法读取图片。')
    selected.value=name;image.value=result;notice.value='';zoom.value=1;history.length=0;undoCount.value=0;dirty.value=false
    await nextTick()
    const el=canvas.value;if(!el || !result.width || !result.height)return
    el.width=result.width;el.height=result.height
    const ctx=el.getContext('2d');if(!ctx)return
    ctx.fillStyle='black';ctx.fillRect(0,0,el.width,el.height)
    const url=result.mask_edit_data_url || result.mask_data_url
    if(url) { const mask=await readImage(url); if(token!==request)return;ctx.drawImage(mask,0,0,el.width,el.height) }
    refreshOverlay()
  } catch(e){if(token===request)error.value=String(e)}
  finally {if(token===request)busy.value=false}
}
async function inspect() {
  const preferred=selected.value;const token=++request;const epoch=++catalogEpoch;busy.value=true;error.value=''
  try {
    const result=await window.pywebview!.api.inspect_mask_dataset(props.projectName)
    if(token!==request)return
    if(!result.ok)throw new Error(result.error || '请先准备项目训练图片。')
    maskSource.value=result.mask_source || maskSource.value;maskKind.value=result.mask_kind || maskKind.value
    catalog.value=result;thumbnails.value={};names.value=[...(result.preview_images || [])]
    while(catalog.value.next_offset!=null){const part=await window.pywebview!.api.list_dataset_preview(result.preview_token!,catalog.value.next_offset);if(token!==request)return;if(!part.ok)throw new Error(part.error || '读取图片列表失败。');names.value.push(...(part.images || []));catalog.value.next_offset=part.next_offset ?? null}
    void loadThumbnails(epoch)
    const next=visibleNames.value.includes(preferred)?preferred:visibleNames.value[0]
    if(next)await load(next);else {image.value=null;selected.value=''}
  }catch(e){error.value=String(e)}finally{if(token===request)busy.value=false}
}
async function loadThumbnails(epoch:number) {
  let cursor=0
  const token=catalog.value?.preview_token, list=[...names.value]
  if(!token)return
  async function worker(){while(open.value && epoch===catalogEpoch && cursor<list.length){const name=list[cursor++]!;if(thumbnails.value[name])continue;try{const result=await window.pywebview!.api.get_dataset_thumbnail(token!,name);if(epoch!==catalogEpoch || !open.value)return;if(result.ok && result.data_url)thumbnails.value[name]=result.data_url}catch{/* A broken photo keeps its status and can still be selected. */}}}
  await Promise.all([worker(),worker()])
}
async function show() {
  previousFocus=document.activeElement as HTMLElement
  open.value=true;await nextTick();panel.value?.focus()
  resizeObserver?.disconnect()
  if(viewport.value){resizeObserver=new ResizeObserver(entries=>{const size=entries[0]?.contentRect;if(size)viewportSize.value={width:size.width+48,height:size.height+48}});resizeObserver.observe(viewport.value)}
  await inspect()
}
function route(action:NonNullable<typeof pending.value>) {
  if(busy.value || saving.value)return
  if(dirty.value){pending.value=action;return}
  void perform(action)
}
async function perform(action:NonNullable<typeof pending.value>) {
  pending.value=null
  if(action.close){open.value=false;request++;catalogEpoch++;resizeObserver?.disconnect();previousFocus?.focus();return}
  if(action.reload){await inspect();return}
  if(action.generate){await generate();return}
  if(action.name)await load(action.name)
}
async function discard() { const action=pending.value;pending.value=null;dirty.value=false;if(action)await perform(action) }
function snapshot() {
  if(!canvas.value)return
  const ctx=canvas.value.getContext('2d');if(!ctx)return
  // Bound undo by pixel memory as well as stroke count.
  const limit=Math.max(1,Math.min(12,Math.floor(64*1024*1024/(canvas.value.width*canvas.value.height*4))))
  history.push(ctx.getImageData(0,0,canvas.value.width,canvas.value.height));while(history.length>limit)history.shift();undoCount.value=history.length
}
function point(e:PointerEvent):[number,number] {const el=canvas.value!,r=el.getBoundingClientRect();return [(e.clientX-r.left)*el.width/r.width,(e.clientY-r.top)*el.height/r.height]}
function stroke(e:PointerEvent){
  if(drag && viewport.value){viewport.value.scrollLeft=drag.left-(e.clientX-drag.x);viewport.value.scrollTop=drag.top-(e.clientY-drag.y);return}
  if(!drawing.value || !canvas.value)return
  const ctx=canvas.value.getContext('2d');if(!ctx)return
  const p=point(e);ctx.strokeStyle=ctx.fillStyle=tool.value==='erase'?'black':'white';ctx.lineWidth=brushSize.value;ctx.lineCap='round';ctx.lineJoin='round'
  if(last){ctx.beginPath();ctx.moveTo(...last);ctx.lineTo(...p);ctx.stroke()}else{ctx.beginPath();ctx.arc(...p,brushSize.value/2,0,Math.PI*2);ctx.fill()}
  const previous=last || p, radius=brushSize.value/2+2
  const x=Math.max(0,Math.floor(Math.min(previous[0],p[0])-radius)),y=Math.max(0,Math.floor(Math.min(previous[1],p[1])-radius))
  const right=Math.min(canvas.value.width,Math.ceil(Math.max(previous[0],p[0])+radius)),bottom=Math.min(canvas.value.height,Math.ceil(Math.max(previous[1],p[1])+radius))
  last=p;dirty.value=true;refreshOverlay({x,y,width:right-x,height:bottom-y})
}
function startStroke(e:PointerEvent){
  if(!canvas.value || (e.button!==0 && e.button!==1))return
  if(tool.value==='pan' || e.button===1){if(!viewport.value)return;canvas.value.setPointerCapture(e.pointerId);drag={x:e.clientX,y:e.clientY,left:viewport.value.scrollLeft,top:viewport.value.scrollTop};return}
  if(!editable.value || view.value==='original')return
  snapshot();canvas.value.setPointerCapture(e.pointerId);drawing.value=true;last=null;stroke(e)
}
function endStroke(){drawing.value=false;last=null;drag=null}
function undo(){if(!editable.value || !canvas.value)return;const old=history.pop();if(!old)return;canvas.value.getContext('2d')?.putImageData(old,0,0);undoCount.value=history.length;dirty.value=true;refreshOverlay()}
function fill(white:boolean){if(!editable.value || !canvas.value)return;snapshot();const ctx=canvas.value.getContext('2d');if(!ctx)return;ctx.fillStyle=white?'white':'black';ctx.fillRect(0,0,canvas.value.width,canvas.value.height);dirty.value=true;refreshOverlay()}
async function save(next=false):Promise<boolean>{
  if(!editable.value || !canvas.value || !catalog.value?.preview_token)return false
  saving.value=true;error.value=''
  const following=next?visibleNames.value[index.value+1]:undefined
  try {
    const result=await window.pywebview!.api.save_dataset_mask(catalog.value.preview_token,selected.value,canvas.value.toDataURL('image/png'))
    if(!result.ok)throw new Error(result.error || '保存失败。')
    image.value=result;if(result.mask_report)catalog.value.mask_report=result.mask_report
    dirty.value=false;notice.value='已保存，原遮罩已备份。'
    if(following)await load(following)
    return true
  }catch(e){error.value=String(e);return false}finally{saving.value=false}
}
async function savePending(){const action=pending.value;if(await save()){pending.value=null;if(action)await perform(action)}}
async function decide(decision:string){
  if(!editable.value || !catalog.value?.preview_token)return
  if(dirty.value){error.value='请先保存或撤销当前修改，再更改此图的处理方式。';return}
  saving.value=true
  try{const result=await window.pywebview!.api.set_dataset_mask_decision(catalog.value.preview_token,selected.value,decision);if(!result.ok)throw new Error(result.error || '保存失败。');image.value=result;if(result.mask_report)catalog.value.mask_report=result.mask_report;notice.value='已更新此图片的处理方式。'}catch(e){error.value=String(e)}finally{saving.value=false}
}
async function changeOptions(source:string, kind:string){
  if(busy.value || saving.value || running.value || dirty.value)return
  const adjusted=source==='anime' && !['person','existing'].includes(kind)
  if(adjusted)kind='person'
  busy.value=true;error.value=''
  try{
    const result=await window.pywebview!.api.set_mask_options(props.projectName,source,kind)
    if(!result.ok)throw new Error(result.error || '设置保存失败。')
    maskSource.value=result.mask_source || source;maskKind.value=result.mask_kind || kind
    if(catalog.value?.preview_token)await inspect()
    notice.value=adjusted?'二次元自动模型只支持人物整体，已切换；手绘区域保留。':'识别设置已保存。点击自动识别更新旧的自动遮罩，手绘区域保留。'
    emit('updated')
  }catch(e){error.value=String(e)}finally{busy.value=false}
}
async function importModel(){
  if(running.value || busy.value || saving.value)return
  busy.value=true;error.value=''
  try{const result=await window.pywebview!.api.import_mask_model(props.projectName);if(!result.ok)throw new Error(result.error || '模型导入失败。');if(!result.cancelled)notice.value='分割模型已校验并准备好，可以自动识别。'}catch(e){error.value=String(e)}finally{busy.value=false}
}
async function generate(){
  busy.value=true;error.value='';logs.value=[];offset=0
  try{const result=await window.pywebview!.api.start_mask_task(props.projectName);if(!result.ok || !result.task_id)throw new Error(result.error || '无法启动自动识别。');taskId.value=result.task_id;task.value={ok:true,status:'running',message:'正在准备自动识别…'};timer=window.setInterval(()=>void poll(),900);await poll()}catch(e){error.value=String(e)}finally{busy.value=false}
}
let offset=0
async function poll(){
  if(polling || !taskId.value)return;polling=true
  try{const result=await window.pywebview!.api.get_task_status(taskId.value,offset);if(!result.ok){window.clearInterval(timer);timer=0;task.value={ok:false,status:'failed',message:result.error || '任务已结束或不存在。'};throw new Error(task.value.message)}task.value=result;logs.value=[...logs.value,...(result.logs || [])].slice(-1500);offset=result.next_offset ?? offset
    if(result.status!=='running'){window.clearInterval(timer);timer=0;await inspect();if(result.status==='failed')error.value=(result.message || '自动识别失败。')+' 仍可用画笔手动添加学习区域。'}
  }catch(e){error.value=String(e)}finally{polling=false}
}
async function cancelTask(){if(!taskId.value)return;const result=await window.pywebview!.api.cancel_task(taskId.value);if(!result.ok)error.value=result.error || '无法停止任务。'}
function keydown(e:KeyboardEvent){
  if(e.key==='Tab'){
    const root=panel.value?.querySelector<HTMLElement>('.unsaved-backdrop') || panel.value
    const nodes=Array.from(root?.querySelectorAll<HTMLElement>('button:not(:disabled),select:not(:disabled),input:not(:disabled),summary,[tabindex="0"]') || []).filter(el=>el.getClientRects().length)
    const first=nodes[0],end=nodes[nodes.length-1]
    if(e.shiftKey && (document.activeElement===first || document.activeElement===root)){e.preventDefault();end?.focus()}
    else if(!e.shiftKey && (document.activeElement===end || document.activeElement===root)){e.preventDefault();first?.focus()}
    return
  }
  if(pending.value)return
  const target=e.target as HTMLElement
  if(['INPUT','SELECT','TEXTAREA'].includes(target.tagName))return
  if((e.ctrlKey || e.metaKey) && e.key==='s'){e.preventDefault();void save()}
  else if((e.ctrlKey || e.metaKey) && e.key==='z'){e.preventDefault();undo()}
  else if(e.key==='Escape'){e.preventDefault();if(!running.value)route({close:true})}
  else if(e.key.toLowerCase()==='b')tool.value='add'
  else if(e.key.toLowerCase()==='e')tool.value='erase'
  else if(e.key.toLowerCase()==='h')tool.value='pan'
}
watch(pending,async value=>{if(value){await nextTick();panel.value?.querySelector<HTMLElement>('.unsaved-backdrop button')?.focus()}else{panel.value?.focus()}})
watch(issuesOnly,()=>{if(!dirty.value && !visibleNames.value.includes(selected.value)){const next=visibleNames.value[0];if(next)void load(next)}})
defineExpose({show})
onUnmounted(()=>{request++;catalogEpoch++;resizeObserver?.disconnect();if(timer)window.clearInterval(timer)})
</script>

<template>
  <button v-if="!hideLauncher" type="button" class="editor-launch" @click="show">打开遮罩编辑器</button>
  <Teleport to="body">
    <div v-if="open" class="mask-editor-backdrop" @keydown.stop="keydown">
      <section ref="panel" class="mask-editor" role="dialog" aria-modal="true" aria-label="遮罩编辑器" tabindex="-1">
        <header><div><h2>遮罩编辑器 <span>{{ projectName }}</span></h2><p>绿色区域重点学习 · 原图保留</p></div><button :disabled="running || saving || busy" aria-label="关闭遮罩编辑器" @click="route({close:true})">关闭 ×</button></header>
        <div class="editor-toolbar">
          <div class="toolset"><button :class="{active:tool==='add'}" :disabled="!editable" @click="tool='add';view='overlay'">画笔 B</button><button :class="{active:tool==='erase'}" :disabled="!editable" @click="tool='erase';view='overlay'">擦除 E</button><button :class="{active:tool==='pan'}" @click="tool='pan'">移动 H</button></div>
          <label>画笔 <input v-model.number="brushSize" type="range" min="2" max="200"><span>{{ brushSize }} px</span></label>
          <button :disabled="!undoCount || !editable" @click="undo">撤销</button>
          <label>显示<select v-model="view"><option value="overlay">学习区域预览</option><option value="original">原图</option><option value="mask">遮罩灰度图</option></select></label>
          <label>透明度<input v-model.number="opacity" type="range" min="0.1" max="0.9" step="0.05"></label>
          <button @click="zoom=Math.max(.25,zoom/1.25)">−</button><button @click="zoom=1">适应画布</button><button @click="zoom=Math.min(8,zoom*1.25)">＋</button>
        </div>
        <div class="editor-body">
          <aside class="image-list"><label><input v-model="issuesOnly" type="checkbox" :disabled="dirty || busy">仅待处理</label><p>{{ catalog?.mask_report?.valid || 0 }} / {{ catalog?.mask_report?.total || 0 }} 张格式检查通过</p>
            <button v-for="(name,i) in visibleNames" :key="name" :title="name" :class="{active:name===selected}" :disabled="busy || saving || running" @click="route({name})"><img v-if="thumbnails[name]" :src="thumbnails[name]" alt="" loading="lazy"><span>{{ i+1 }}. {{ name }}</span><small>{{ rows.find(r=>r.name===name)?.decision==='exclude'?'已排除':rows.find(r=>r.name===name)?.decision==='unmasked'?'整图学习':rows.find(r=>r.name===name)?.status==='valid'?'格式通过':'待处理' }}</small></button>
          </aside>
          <main ref="viewport" class="editor-viewport">
            <div v-if="image?.data_url" class="editor-stage" :class="{'is-pan':tool==='pan','is-original':view==='original'}" :style="stageStyle">
              <img :src="image.data_url" alt="项目训练图片" draggable="false">
              <canvas ref="overlay" class="tinted-mask" :style="{opacity:view==='overlay'?opacity:0}" aria-hidden="true" />
              <canvas ref="canvas" class="paint-mask" :style="{opacity:view==='mask'?1:0}" aria-label="涂抹学习区域" @pointerdown.prevent="startStroke" @pointermove.prevent="stroke" @pointerup="endStroke" @pointercancel="endStroke" @lostpointercapture="endStroke" />
            </div>
            <div v-else class="editor-empty">{{ busy ? '正在读取项目图片…' : '尚无训练副本。请先准备图片，或点击自动识别完成预处理。' }}</div>
          </main>
          <aside class="editor-options">
            <h3>自动识别</h3>
            <label>图片类型<select :value="maskSource" :disabled="busy || saving || running || dirty" @change="changeOptions(($event.target as HTMLSelectElement).value,maskKind)"><option value="anime">二次元 · 专用人物分割</option><option value="photo">真人 · 多类别分割</option></select></label>
            <label>识别范围<select :value="maskKind" :disabled="busy || saving || running || dirty" @change="changeOptions(maskSource,($event.target as HTMLSelectElement).value)"><option value="person">人物整体</option><option v-if="maskSource==='photo'" value="head">脸部与头发</option><option v-if="maskSource==='photo'" value="body_clothes">身体与服装</option><option v-if="maskSource==='photo'" value="not_faces">排除脸部与头发</option><option value="existing">使用已有遮罩 / 手绘</option></select></label>
            <p>{{ maskSource==='anime'?'二次元模型识别人物整体，不区分脸部与头发；局部区域可手绘修正。':'真人模型可识别人物、脸部与头发等区域。' }} 自动结果请逐张检查；手绘区域保留。</p>
            <p>遮罩指定学习范围，标签描述人物与内容；仍然需要打标。</p><button :disabled="busy || saving || running" @click="route({generate:true})">{{ running?'正在识别…':'自动识别本项目' }}</button><button :disabled="busy || saving || running" @click="importModel">选择本地分割模型</button>
            <p class="subtle">自动模型不可用时，可以直接用画笔涂抹。</p>
            <template v-if="task"><p role="status">{{ task.message }}</p><progress v-if="task.progress!=null" :value="task.progress" max="1" /><button v-if="running" @click="cancelTask">停止识别</button><details><summary>详细日志</summary><pre>{{ logs.join('\n') }}</pre></details></template>
            <hr><h3>当前图片</h3><p>{{ image?.width || '—' }} × {{ image?.height || '—' }}</p><p v-if="image?.problem" class="warning">{{ image.problem }}</p><p v-if="image?.warning" class="warning">{{ image.warning }}</p><p v-if="image?.mask_balanced">均衡副本会同步修改。</p>
            <label>参与训练<select :value="image?.decision || 'default'" :disabled="!editable || dirty" @change="decide(($event.target as HTMLSelectElement).value)"><option value="default">使用遮罩</option><option value="exclude">排除此图</option><option value="unmasked">整张图片学习</option></select></label>
            <div class="fill-actions"><button :disabled="!editable" @click="fill(false)">清空遮罩</button><button :disabled="!editable" @click="fill(true)">全部选中</button></div><button :disabled="busy || saving || running" @click="route({reload:true})">重新读取</button>
          </aside>
        </div>
        <div v-if="error" class="editor-message warning" role="alert">{{ error }}</div><div v-else-if="notice" class="editor-message" role="status">{{ notice }}</div>
        <footer><span>{{ dirty?'有未保存修改':selected || '选择图片开始编辑' }}</span><div><button :disabled="index<=0 || busy || saving || running" @click="route({name:visibleNames[index-1]})">上一张</button><button :disabled="index<0 || index>=visibleNames.length-1 || busy || saving || running" @click="route({name:visibleNames[index+1]})">下一张</button><button :disabled="!editable || !dirty" @click="save()">{{ saving?'保存中…':'保存' }}</button><button class="primary" :disabled="!editable || !dirty" @click="save(true)">保存并下一张</button></div></footer>
        <div v-if="pending" class="unsaved-backdrop"><section role="alertdialog" aria-modal="true" aria-label="保存修改"><h3>当前遮罩尚未保存</h3><p>保存后继续，或放弃这次修改。</p><div><button @click="pending=null">返回编辑</button><button :disabled="saving" @click="discard">放弃修改</button><button class="primary" :disabled="saving" @click="savePending">保存并继续</button></div></section></div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.editor-launch{padding:9px 14px;border-radius:7px;border:1px solid var(--border);color:var(--text);background:var(--bg);cursor:pointer;font:inherit}
.mask-editor-backdrop{position:fixed;inset:0;z-index:10000;background:#0009;display:grid;place-items:center;padding:18px;color:var(--text,#ddd);font-size:13px}
.mask-editor{position:relative;width:min(1600px,100%);height:calc(100dvh - 36px);display:flex;flex-direction:column;background:var(--panel,var(--bg,#24272f));border:1px solid var(--border,#424650);border-radius:12px;overflow:hidden;box-shadow:0 24px 80px #0006}
header{display:flex;justify-content:space-between;align-items:center;padding:15px 20px;border-bottom:1px solid var(--border)}h2{font-size:18px;margin:0 0 4px}h2 span{font-size:12px;font-weight:400;color:var(--hint);margin-left:12px}h3{font-size:13px;margin:0}p{font-size:12px;line-height:1.6;color:var(--hint,#aaa);margin:0;overflow-wrap:anywhere}
button,select{font:inherit;color:var(--text,#ddd);background:var(--bg,#24272f);border:1px solid var(--border,#424650);border-radius:6px;min-height:34px;padding:6px 10px}button{cursor:pointer}button:disabled{opacity:.45;cursor:default}button:not(:disabled):hover{border-color:var(--tone-8fb0c9,#8fb0c9)}button:not(:disabled):active{transform:translateY(1px)}button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid #8fb0c9;outline-offset:2px}.active{border-color:#60beaa;background:#60beaa1a}.primary{background:#9ab5ce;color:#15202a;border-color:#9ab5ce}
.editor-toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:10px 16px;border-bottom:1px solid var(--border)}.toolset{display:flex;gap:4px}.editor-toolbar label{display:flex;align-items:center;gap:6px;font-size:12px}.editor-toolbar input{width:85px;accent-color:#60beaa}.editor-toolbar label span{min-width:42px;font-variant-numeric:tabular-nums}
.editor-body{flex:1;min-height:0;display:grid;grid-template-columns:174px minmax(0,1fr) 230px}.image-list{padding:12px;overflow:auto;border-right:1px solid var(--border);display:flex;flex-direction:column;gap:8px}.image-list label{display:flex;align-items:center;gap:5px;font-size:12px}.image-list button{flex-shrink:0;display:grid;grid-template-columns:38px minmax(0,1fr);gap:5px;text-align:left;font-size:11px;padding:7px}.image-list button img{grid-row:span 2;width:38px;height:44px;object-fit:cover;border-radius:3px}.image-list button span{grid-column:2;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.image-list small{grid-column:2;color:var(--hint)}
.editor-viewport{min-width:0;min-height:0;overflow:auto;background:#171a20;overscroll-behavior:contain;padding:24px;position:relative;display:flex;align-items:safe center;justify-content:safe center}.editor-stage{position:relative;flex-shrink:0;background:#333;box-shadow:0 4px 22px #0005}.editor-stage img,.editor-stage canvas{position:absolute;inset:0;width:100%;height:100%}.editor-stage img{user-select:none}.tinted-mask{pointer-events:none}.paint-mask{touch-action:none;cursor:crosshair}.is-pan .paint-mask{cursor:grab}.is-original .paint-mask{cursor:default}.editor-empty{margin:auto;max-width:320px;color:#aeb5bf;line-height:1.8;text-align:center}
.editor-options{padding:16px;display:flex;flex-direction:column;gap:12px;overflow:auto;border-left:1px solid var(--border)}.editor-options label{display:grid;gap:6px}.editor-options select{width:100%}.subtle{font-size:11px}.fill-actions{display:flex;flex-wrap:wrap;gap:5px}hr{border:0;border-top:1px solid var(--border);width:100%;margin:3px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:10px;max-height:180px;overflow:auto}summary{cursor:pointer;color:var(--hint);font-size:12px}progress{width:100%}
footer{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px;border-top:1px solid var(--border)}footer>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;color:var(--hint)}footer>div{display:flex;gap:7px;flex-shrink:0}.editor-message{padding:9px 16px;background:#60beaa12;border-top:1px solid var(--border);font-size:12px;max-height:78px;overflow:auto}.warning{color:#d9b075}.unsaved-backdrop{position:absolute;inset:0;z-index:2;display:grid;place-items:center;background:#0009}.unsaved-backdrop section{padding:24px;border:1px solid var(--border);border-radius:10px;background:var(--bg,#24272f);display:grid;gap:15px}.unsaved-backdrop section>div{display:flex;gap:8px}
@media(max-width:1000px){.editor-body{grid-template-columns:130px minmax(0,1fr) 190px}.mask-editor-backdrop{padding:6px}.mask-editor{height:calc(100dvh - 12px)}.editor-options{padding:10px}.editor-toolbar{padding:8px}.editor-toolbar label{gap:4px}}
</style>
