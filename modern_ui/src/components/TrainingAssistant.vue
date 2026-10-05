<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import AssistantPreferences from './AssistantPreferences.vue'
import AssistantMessageText from './AssistantMessageText.vue'
import UiIcon from './UiIcon.vue'
import type { AgentMessage, AgentRun, AssistantResult, CaptionServiceSettings, ModernTaskStatus } from '../bridge'

const props = defineProps<{ desktop: boolean; projectName: string; canUseProject: () => boolean }>()
const emit = defineEmits<{ changed: [project: string]; close: []; active: [value: boolean]; 'created-project': [project: string]; 'open-project': [project: string]; 'open-task': [id: string] }>()
const settings = reactive<CaptionServiceSettings>({ provider: 'compatible', base_url: 'http://127.0.0.1:1234/v1', model: '', unload_after: true, has_key: false })
const key = ref(''), clearKey = ref(false), dirty = ref(false), question = ref(''), draft = ref(''), message = ref('')
const includeLogs = ref(false), allowRemote = ref(false), busy = ref(false), saving = ref(false), applying = ref(false)
const result = ref<AssistantResult | null>(null), requestId = ref(''), mode = ref<'advice' | 'agent'>('agent')
const agent = ref<AgentRun | null>(null), startingAgent = ref(false), sendingMessage = ref(false)
const allowInstall = ref(false), allowDownload = ref(false), allowRemoteImages = ref(false), autoReview = ref(true), allowAutoTrain = ref(false)
const activeProject = ref(''), activeRunId = ref(''), pathDraft = ref(''), taskStatus = ref('')
const taskState = ref<ModernTaskStatus | null>(null), taskOffset = ref(0), settingsOpen = ref(false)
const settingsTab = ref<'connection' | 'permissions'>('connection'), expanded = ref(false), conversationTab = ref<'chat' | 'activity'>('chat')
const serviceName = computed(() => settings.model.trim() || '尚未配置 AI 模型')
const taskLogs = ref<string[]>([]), taskSamples = ref<Array<{name:string;version:string;modified:number;bytes:number}>>([])
const samplePreview = ref(''), sampleName = ref(''), taskDetailsOpen = ref(false), taskDetailsLoading = ref(false), taskDetailsError = ref('')
const conversation = ref<HTMLElement | null>(null), composer = ref<HTMLTextAreaElement | null>(null), stickToBottom = ref(true), forceBottom = ref(false)
const serviceLocked = computed(() => busy.value || saving.value || startingAgent.value || agentActive.value)
const isRemoteService = computed(() => { try { return !['localhost','127.0.0.1','[::1]','::1'].includes(new URL(settings.base_url).hostname) } catch { return true } })
const agentOwnsCurrentRun = computed(() => Boolean(agent.value?.id && activeRunId.value && agent.value.id === activeRunId.value))
const agentActive = computed(() => agentOwnsCurrentRun.value && ['running','waiting_user','waiting_task'].includes(agent.value?.status || ''))
const pausedOrInterrupted = computed(() => ['paused','interrupted'].includes(agent.value?.status || ''))
const ownerElsewhere = computed(() => Boolean(activeRunId.value && activeProject.value !== props.projectName && agent.value?.id !== activeRunId.value))
const globalAgentActive = computed(() => Boolean(activeProject.value || activeRunId.value))
const canStartGoal = computed(() => !globalAgentActive.value && !pausedOrInterrupted.value && !startingAgent.value && !sendingMessage.value)
const canSendWhilePaused = computed(() => agent.value?.status === 'paused' && !ownerElsewhere.value && (!globalAgentActive.value || agentOwnsCurrentRun.value))
const canSubmitAgent = computed(() => !!draft.value.trim() && !startingAgent.value && !sendingMessage.value && !ownerElsewhere.value && (agentActive.value || canSendWhilePaused.value || canStartGoal.value))
const actionable = computed(() => result.value?.status === 'completed' && result.value.project === props.projectName && !!result.value.changes?.length && !result.value.undone)
const displayedMessages = computed(() => (agent.value?.messages || []).filter(item =>
  ['user', 'assistant'].includes(item.role) && item.content.trim() &&
  !(agent.value?.status === 'waiting_user' && item.question_id && item.question_id === agent.value.question_id)
))
const toolMessages = computed(() => (agent.value?.messages || []).filter(item => item.role === 'tool'))
const taskLabel = computed(() => taskState.value?.kind === 'training' ? '训练' : '任务')
const taskProgress = computed(() => {
  const progress = taskState.value?.progress
  return typeof progress === 'number' && Number.isFinite(progress) ? Math.max(0, Math.min(1, progress)) : null
})
const taskEta = computed(() => {
  const seconds = taskState.value?.eta_seconds
  if (taskStatus.value !== 'running' || seconds == null || !Number.isFinite(seconds) || seconds < 0) return ''
  return seconds < 60 ? `预计剩余 ${Math.ceil(seconds)} 秒` : `预计剩余 ${Math.ceil(seconds / 60)} 分钟`
})
const failureText = computed(() => agent.value?.status === 'failed' && agent.value.phase !== 'result' && agent.value.detail !== agent.value.result?.message && agent.value.detail !== agent.value.result?.error ? agent.value.detail : '')
const phaseText = computed(() => {
  const status = agent.value?.status || ''
  const labels: Record<string, string> = { waiting_user:'等你回复', waiting_task:'任务执行中', paused:'助手已暂停', completed:'对话已完成', failed:'本次执行失败', cancelled:'助手已停止', takeover:'已交还控制权', interrupted:'上次执行已中断' }
  if (status in labels) return labels[status]
  const phase = agent.value?.phase || status
  return ({starting:'正在准备',environment:'检查环境',planning:'整理方案',conversation:'正在回复',tool:'正在处理',plan:'核对方案',training:'训练中',result:'整理结果',running:'正在处理'} as Record<string,string>)[phase] || '等待目标'
})
const resultLabel = computed(() => {
  const state = agent.value?.result
  if (!state) return ''
  if (['stopped','cancelled'].includes(state.status)) return '已停止'
  if (['failed','error'].includes(state.status)) return '执行失败'
  return state.ok ? '执行完成' : '执行失败'
})
const resultClass = computed(() => {
  const state = agent.value?.result
  if (!state) return ''
  if (['stopped','cancelled'].includes(state.status)) return 'stopped'
  return state.ok && !['failed','error'].includes(state.status) ? 'success' : 'failure'
})
const canContinueTask = computed(() => taskStatus.value === 'awaiting_review' && !!agent.value?.task_id && !globalAgentActive.value)
const statusLabels: Record<string,string> = {running:'正在执行',waiting_user:'等待你的回答',waiting_task:'等待训练任务',completed:'已完成',failed:'执行失败',cancelled:'已停止',stopped:'已停止',paused:'已暂停',interrupted:'上次执行已中断',takeover:'已交还控制权'}
let agentTimer: ReturnType<typeof setTimeout> | undefined, timer: ReturnType<typeof setTimeout> | undefined, changedTimer: ReturnType<typeof setTimeout> | undefined
let disposed = false, pollingAgent = false, seenRun = '', seenRevision = -1, seenTaskId = '', homeGoalStarted = false, createdProjectEmitted = '', pendingChangedProject = ''
let taskTimer: ReturnType<typeof setTimeout> | undefined
let pollingTask = ''
let chatScrollTop = 0
const showCurrentControls = computed(() => agentOwnsCurrentRun.value || (pausedOrInterrupted.value && !globalAgentActive.value))

function scheduleAgentPoll(delay = 900) { if (agentTimer) clearTimeout(agentTimer); agentTimer = setTimeout(() => void pollAgent(), delay) }
function scheduleProjectRefresh(project: string) {
  if (!project || project !== props.projectName) return
  pendingChangedProject = project
  if (changedTimer) clearTimeout(changedTimer)
  changedTimer = setTimeout(() => { const name = pendingChangedProject; pendingChangedProject = ''; if (name === props.projectName) emit('changed', name) }, 1200)
}
async function pollAgent() {
  if (disposed || pollingAgent || !window.pywebview?.api) return
  pollingAgent = true
  const requestedProject = props.projectName
  try {
    const value = await window.pywebview.api.get_agent_state(requestedProject)
    if (disposed || requestedProject !== props.projectName) return
    if (!value.ok) { message.value = value.error || '无法读取 Agent 状态。'; return }
    activeProject.value = value.active_project || ''
    activeRunId.value = value.active_run_id || ''
    agent.value = value.run || null
    emit('active', globalAgentActive.value)
    const current = agent.value
    if (current) {
      if (seenRun !== current.id) { seenRun = current.id; seenRevision = current.revision; seenTaskId = ''; taskState.value = null; taskOffset.value = 0; taskStatus.value = ''; taskLogs.value = []; taskSamples.value = []; taskDetailsOpen.value = false; samplePreview.value = ''; if (taskTimer) { clearTimeout(taskTimer); taskTimer = undefined } }
      else if (seenRevision !== current.revision) { seenRevision = current.revision; scheduleProjectRefresh(current.project) }
      if ((current.task_id || '') !== seenTaskId) { seenTaskId = current.task_id || ''; taskStatus.value = ''; taskState.value = null; taskOffset.value = 0; taskDetailsOpen.value = false; taskDetailsError.value = ''; samplePreview.value = ''; taskLogs.value = []; taskSamples.value = []; if (taskTimer) clearTimeout(taskTimer) }
      if (current.policy) {
        allowInstall.value = !!current.policy.allow_install; allowDownload.value = !!current.policy.allow_download
        allowRemoteImages.value = !!current.policy.allow_remote_images; autoReview.value = current.policy.auto_review !== false
        allowAutoTrain.value = !!current.policy.allow_auto_train
      }
      if (homeGoalStarted && !props.projectName && current.project && createdProjectEmitted !== current.project && (current.created_project || activeRunId.value === current.id)) {
        createdProjectEmitted = current.project; emit('created-project', current.project)
      }
      if (current.task_id && !taskTimer) void refreshTaskStatus(current.task_id)
    }
    await followConversationIfNeeded()
    if (globalAgentActive.value || current?.task_active) scheduleAgentPoll()
  } catch {
    if (requestedProject === props.projectName) {
      message.value = 'Agent 状态连接中断；重新打开侧栏后可以继续查看。'
      if (globalAgentActive.value) scheduleAgentPoll(2000)
    }
  } finally {
    pollingAgent = false
    if (!disposed && requestedProject !== props.projectName) void pollAgent()
  }
}
async function startAgent(goal = draft.value) {
  const text = goal.trim()
  if (!props.desktop || !window.pywebview?.api || !text || startingAgent.value || saving.value) return
  if (dirty.value) { openSettings('connection'); message.value = '请先保存服务设置。'; return }
  if (props.projectName && !props.canUseProject()) { message.value = '训练页有未保存的修改，请先保存再交给 Agent。'; return }
  if (!settings.model.trim() || !settings.base_url.trim()) { openSettings('connection'); message.value = '先填写模型名称和服务地址，保存后即可开始对话。'; return }
  if (isRemoteService.value && !allowRemote.value) { openSettings('permissions'); message.value = '请在执行权限中允许本次对话使用在线文字服务。'; return }
  startingAgent.value = true; message.value = ''; homeGoalStarted = !props.projectName; createdProjectEmitted = ''; forceBottom.value = true; draft.value = ''
  try {
    const value = await window.pywebview.api.start_agent(props.projectName, { goal:text, execute:true, allow_remote:allowRemote.value, allow_install:allowInstall.value, allow_download:allowDownload.value, allow_remote_images:allowRemoteImages.value, auto_review:autoReview.value, allow_auto_train:allowAutoTrain.value })
    if (!value.ok) { draft.value = text; message.value = value.error || '无法开始 Agent。'; homeGoalStarted = false; return }
    seenRun = value.id || ''; seenRevision = -1
    if (agentTimer) clearTimeout(agentTimer)
    await pollAgent()
  } catch {
    draft.value = text
    message.value = '启动结果未能返回，正在重新读取状态；如果 Agent 已启动，目标会保留在输入框中。'
    await pollAgent()
  }
  finally { startingAgent.value = false }
}
async function sendAgentMessage(text = draft.value) {
  const content = text.trim()
  if (!agent.value || !window.pywebview?.api || !content || sendingMessage.value) return
  sendingMessage.value = true; forceBottom.value = true; draft.value = ''; message.value = ''
  try {
    const value = agent.value.status === 'waiting_user' && agent.value.question_id
      ? await window.pywebview.api.reply_agent(agent.value.id, content, agent.value.question_id)
      : await window.pywebview.api.send_agent_message(agent.value.id, content)
    if (!value.ok) { draft.value = content; message.value = value.error || '消息没有送达。' }
    else await pollAgent()
  } catch { draft.value = content; message.value = '消息没有送达，请检查本机连接。' }
  finally { sendingMessage.value = false }
}
async function submitAgentComposer() {
  if (!props.desktop || !window.pywebview?.api) return
  if (ownerElsewhere.value) { message.value = `Agent 正在处理「${activeProject.value}」。打开该项目可查看对话或接管。`; return }
  conversationTab.value = 'chat'
  if (agentActive.value) return sendAgentMessage()
  if (canSendWhilePaused.value) return sendAgentMessage()
  if (pausedOrInterrupted.value) { message.value = '此对话已中断。请接管后再开始新目标。'; return }
  if (canStartGoal.value) await startAgent()
}
async function replyAgent(answer: string, questionId = agent.value?.question_id) {
  if (!agent.value || !window.pywebview?.api || sendingMessage.value || !answer.trim()) return
  sendingMessage.value = true; forceBottom.value = true
  try {
    const value = await window.pywebview.api.reply_agent(agent.value.id, answer, questionId)
    if (!value.ok) { message.value = value.error || '回答失败。'; return }
    pathDraft.value = ''; await pollAgent()
  } catch { message.value = '回答未能送达，请检查连接。' }
  finally { sendingMessage.value = false }
}
async function chooseAgentPath(path?: string) {
  if (!agent.value?.path_kind || !window.pywebview?.api || sendingMessage.value) return
  sendingMessage.value = true; message.value = ''
  try {
    const value = await window.pywebview.api.pick_agent_path(agent.value.id, agent.value.path_kind, path)
    if (value.cancelled) return
    if (!value.ok || !value.path) { message.value = value.error || '无法使用这个路径。'; return }
    pathDraft.value = ''; await pollAgent()
  } catch { message.value = '无法选择或检查此路径。' }
  finally { sendingMessage.value = false }
}
async function controlAgent(action: 'pause'|'resume'|'takeover') {
  if (!agent.value || !window.pywebview?.api) return
  if (action !== 'takeover' && action !== 'resume' && !agentOwnsCurrentRun.value) return
  try {
    const value = await window.pywebview.api.control_agent(agent.value.id, action)
    message.value = value.ok ? ({pause:'已请求暂停 Agent；当前软件任务状态会单独显示。',resume:'已请求恢复 Agent。',takeover:'已请求停止 Agent 并释放训练页控制权；已启动的软件任务状态会单独显示。'} as Record<string,string>)[action] : value.error || '操作未完成。'
    await pollAgent()
  } catch { message.value = '操作未能送达，请重新查看实际状态。' }
}
async function stopAgent(stopTask: boolean) {
  if (!agent.value || !window.pywebview?.api) return
  try {
    const value = await window.pywebview.api.stop_agent(agent.value.id, stopTask)
    message.value = value.ok ? (stopTask ? '已请求停止 Agent 和软件任务。' : '已请求停止 Agent；已启动的软件任务继续运行。') : value.error || '停止请求失败。'
    await pollAgent()
  } catch { message.value = '停止请求未能送达，请检查任务实际状态。' }
}
async function openOutput() {
  if (!agent.value?.project || !window.pywebview?.api) return
  try { const value = await window.pywebview.api.run_action('output_dir', agent.value.project); if (!value.ok) message.value = value.error || '无法打开输出目录。' }
  catch { message.value = '无法打开输出目录，请检查本地界面连接。' }
}
async function refreshTaskStatus(taskId: string) {
  if (!window.pywebview?.api || !taskId || pollingTask === taskId) return
  pollingTask = taskId
  const readOffset = taskOffset.value
  if (taskTimer) { clearTimeout(taskTimer); taskTimer = undefined }
  try {
    const value = await window.pywebview.api.get_task_status(taskId, readOffset)
    if (value.ok && value.status && agent.value?.task_id === taskId) {
      taskStatus.value = value.status
      taskState.value = value
      if (taskDetailsOpen.value && taskOffset.value === readOffset) taskLogs.value = [...taskLogs.value, ...(value.logs || [])].slice(-1000)
      taskOffset.value = Math.max(taskOffset.value, value.next_offset || 0)
      if (['running','awaiting_review'].includes(value.status)) taskTimer = setTimeout(() => { taskTimer = undefined; void refreshTaskStatus(taskId) }, 2000)
      else taskTimer = undefined
    } else if (!value.ok && agent.value?.task_id === taskId) {
      taskState.value = { ok:false, message:'这个任务窗口已不可用，可查看对话中保留的执行结果；需要完整训练记录时，请打开项目训练历史。' }
      taskStatus.value = ''
    }
  } catch {
    if (agent.value?.task_id === taskId) taskTimer = setTimeout(() => { taskTimer = undefined; void refreshTaskStatus(taskId) }, 2500)
  } finally { if (pollingTask === taskId) pollingTask = '' }
}
async function loadTaskDetails() {
  if (!agent.value?.task_id || !window.pywebview?.api || taskDetailsLoading.value) return
  const current = agent.value.task_id
  conversationTab.value = 'activity'
  taskDetailsLoading.value = true; taskDetailsError.value = ''; taskDetailsOpen.value = true
  try {
    const [status, samples] = await Promise.all([window.pywebview.api.get_task_status(current, 0), window.pywebview.api.list_task_samples(current, 0)])
    if (current !== agent.value?.task_id) return
    if (status.ok) { taskState.value = status; taskOffset.value = status.next_offset || 0; taskStatus.value = status.status || taskStatus.value; taskLogs.value = (status.logs || []).slice(-1000) } else taskDetailsError.value = status.error || '无法读取任务记录。'
    if (samples.ok) taskSamples.value = samples.samples || []; else if (status.kind === 'training' && !taskDetailsError.value) taskDetailsError.value = samples.error || '无法读取训练采样。'
  } catch { if (current === agent.value?.task_id) taskDetailsError.value = '无法读取任务记录。' }
  finally { taskDetailsLoading.value = false }
}
async function showSample(name: string) {
  if (!agent.value?.task_id || !window.pywebview?.api) return
  const current = agent.value.task_id
  try { const value = await window.pywebview.api.get_task_sample(current, undefined, false, name); if (current !== agent.value?.task_id) return; if (!value.ok || !value.data_url) { message.value = value.error || value.warning || '当前没有可显示的采样图。'; return }; samplePreview.value = value.data_url; sampleName.value = value.name || name }
  catch { message.value = '无法读取采样图。' }
}
async function continueTask() {
  if (!canContinueTask.value || !agent.value?.task_id || !window.pywebview?.api) return
  try { const value = await window.pywebview.api.continue_training(agent.value.task_id); message.value = value.ok ? '已请求继续训练。' : value.error || '无法继续训练。'; if (value.ok) { taskStatus.value = 'running'; taskLogs.value = []; await refreshTaskStatus(agent.value.task_id) } }
  catch { message.value = '继续训练请求未能送达。' }
}
function changed() { dirty.value = true; allowRemote.value = false }
async function save() {
  if (!props.desktop || !window.pywebview?.api || serviceLocked.value) return
  saving.value = true; message.value = ''
  try {
    const value = await window.pywebview.api.save_assistant_service({ ...settings, api_key:key.value, clear_key:clearKey.value })
    if (!value.ok) { message.value = value.error || '设置保存失败。'; return }
    Object.assign(settings, value.settings); key.value = ''; clearKey.value = false; dirty.value = false
    message.value = '连接设置已保存。密钥只用于文字服务，不会进入 Agent 对话。'
  } catch { message.value = '无法保存设置，请检查本地界面连接。' }
  finally { saving.value = false }
}
async function pollAdvice() {
  if (disposed || !requestId.value || !window.pywebview?.api) return
  try { const value = await window.pywebview.api.get_assistant_result(requestId.value); result.value = value; busy.value = value.ok && value.status === 'running'; if (value.error) message.value = value.error; if (busy.value) timer = setTimeout(pollAdvice, 700) }
  catch { busy.value = false; message.value = '无法获取助手结果；可重新打开侧栏查看。' }
}
async function sendAdvice() {
  if (!props.desktop || !window.pywebview?.api || busy.value || saving.value) return
  if (dirty.value) { message.value = '请先保存服务设置。'; return }
  if (props.projectName && !props.canUseProject()) { message.value = '训练页有未保存修改，请先保存再提问。'; return }
  if (isRemoteService.value && !allowRemote.value) { message.value = '请确认允许发送到在线文字服务。'; return }
  busy.value = true; result.value = null; message.value = ''
  try {
    const value = await window.pywebview.api.start_assistant_request(props.projectName, { question:question.value, include_logs:includeLogs.value, allow_remote:allowRemote.value })
    if (!value.ok || !value.id) { busy.value = false; message.value = value.error || '无法开始请求。'; return }
    requestId.value = value.id; void pollAdvice()
  } catch { busy.value = false; message.value = '请求失败，请检查本地界面连接。' }
}
async function stopAdvice() {
  if (!window.pywebview?.api || !requestId.value) return
  try { const value = await window.pywebview.api.stop_assistant_request(requestId.value); message.value = value.ok ? '已请求停止；服务端可能仍在处理。' : value.error || '停止失败。' }
  catch { message.value = '停止请求未送达，请检查连接。' }
}
async function apply(undo = false) {
  if (!window.pywebview?.api || !actionable.value || applying.value) return
  if (props.projectName && !props.canUseProject()) { message.value = '请先保存页面上的手动修改，再重新生成方案。'; return }
  applying.value = true
  try {
    const value = await window.pywebview.api.apply_assistant_proposal(requestId.value, undo)
    message.value = value.ok ? (undo ? '已撤销本次参数修改。' : '参数已应用并保存，请检查页面。') : value.error || '操作失败。'
    if (value.ok) { emit('changed', props.projectName); await pollAdvice() }
  } catch { message.value = '操作结果未返回，请检查项目实际保存的参数。' }
  finally { applying.value = false }
}
function onComposerKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return
  event.preventDefault(); if (canSubmitAgent.value) void submitAgentComposer()
}
function onConversationScroll() {
  const el = conversation.value
  if (el) { chatScrollTop = el.scrollTop; stickToBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 44 }
}
async function followConversationIfNeeded() {
  if (settingsOpen.value || conversationTab.value !== 'chat' || mode.value !== 'agent') return
  await nextTick()
  const el = conversation.value
  if (!el) return
  if (forceBottom.value || stickToBottom.value) { el.scrollTop = el.scrollHeight; stickToBottom.value = true }
  chatScrollTop = el.scrollTop
  forceBottom.value = false
}
function formatValue(value: unknown) {
  if (value == null || value === '') return '未设置'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}
function toolTitle(item: AgentMessage) {
  return agent.value?.catalog?.find(tool => tool.name === item.tool)?.title || '工具执行记录'
}
function toolSummary(item: AgentMessage) {
  try {
    const value = JSON.parse(item.content)
    const text = value.error || value.message || (value.ok === false ? '未完成' : '结果已记录')
    return String(text).slice(0, 120)
  } catch { return item.content.split('\n').find(line => line.trim())?.slice(0, 120) || '结果已记录' }
}
function startSuggestion(text: string) { conversationTab.value = 'chat'; draft.value = text; void nextTick(() => composer.value?.focus()) }
function openSettings(tab: 'connection' | 'permissions' = 'connection') { settingsTab.value = tab; settingsOpen.value = true }
function patchSettings(value: Partial<CaptionServiceSettings>) { Object.assign(settings, value); changed() }
function closeSettings() { settingsOpen.value = false; void nextTick(() => composer.value?.focus()) }
function handleEscape() { if (samplePreview.value) samplePreview.value = ''; else if (settingsOpen.value) closeSettings(); else emit('close') }

watch([settingsOpen, conversationTab, mode], async () => {
  if (conversation.value) chatScrollTop = conversation.value.scrollTop
  await nextTick()
  if (!settingsOpen.value && conversationTab.value === 'chat' && mode.value === 'agent' && conversation.value) {
    conversation.value.scrollTop = stickToBottom.value || forceBottom.value ? conversation.value.scrollHeight : chatScrollTop
  }
})
watch(() => props.projectName, async () => {
  agent.value = null; seenRun = ''; seenRevision = -1; seenTaskId = ''; taskStatus.value = ''; taskState.value = null; taskOffset.value = 0; taskDetailsOpen.value = false; taskDetailsError.value = ''; samplePreview.value = ''; taskLogs.value = []; taskSamples.value = []; forceBottom.value = true
  if (taskTimer) { clearTimeout(taskTimer); taskTimer = undefined }
  if (agentTimer) clearTimeout(agentTimer)
  await pollAgent()
})
watch(() => agent.value?.messages, () => void followConversationIfNeeded(), { deep:true })
watch(() => agent.value?.result?.status, status => { if (status && agent.value?.task_id) void refreshTaskStatus(agent.value.task_id) })
onMounted(async () => {
  if (!props.desktop || !window.pywebview?.api) return
  try {
    const value = await window.pywebview.api.get_assistant_service()
    if (value.settings) Object.assign(settings, value.settings)
    if (value.request) { requestId.value = value.request.id; busy.value = value.request.status === 'running'; if (busy.value) void pollAdvice() }
    if (value.error) message.value = value.error
    forceBottom.value = true; await pollAgent()
  } catch { message.value = '助手接口尚未就绪，请重新打开本地界面。' }
})
onUnmounted(() => { disposed = true; if (timer) clearTimeout(timer); if (agentTimer) clearTimeout(agentTimer); if (changedTimer) clearTimeout(changedTimer); if (taskTimer) clearTimeout(taskTimer) })
</script>

<template>
  <aside id="training-assistant-panel" class="assistant-panel" :class="{ 'is-expanded': expanded }" aria-label="训练助手" @keydown.esc.stop="handleEscape">
    <header class="assistant-header">
      <div class="assistant-title"><span class="assistant-symbol"><UiIcon :name="settingsOpen?'settings':'feedback'" /></span><div><h2>{{ settingsOpen?'助手设置':'训练助手' }}</h2><span class="project-label" :title="projectName || '新项目对话'">{{ projectName || '新项目对话' }}</span></div></div>
      <div class="header-actions">
        <button v-if="settingsOpen" class="quiet-button" type="button" @click="closeSettings"><UiIcon name="back" />返回对话</button>
        <button v-else class="icon-button" type="button" title="设置连接与权限" aria-label="设置连接与权限" @click="openSettings()"><UiIcon name="settings" /></button>
        <button class="icon-button expand-button" type="button" :title="expanded?'恢复侧栏宽度':'展开聊天窗口'" :aria-label="expanded?'恢复侧栏宽度':'展开聊天窗口'" :aria-pressed="expanded" @click="expanded=!expanded"><svg viewBox="0 0 24 24" aria-hidden="true"><path v-if="!expanded" d="M8 3H3v5M16 3h5v5M21 16v5h-5M8 21H3v-5"/><path v-else d="M3 8h5V3M21 8h-5V3M16 21v-5h5M3 16h5v5"/></svg></button>
        <button class="icon-button" type="button" title="收起助手，任务继续运行" aria-label="收起助手" @click="emit('close')"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg></button>
      </div>
    </header>
    <AssistantPreferences v-if="settingsOpen" :settings="settings" :locked="serviceLocked" :desktop="desktop" :dirty="dirty" :saving="saving" :remote="isRemoteService" :notice="message"
      v-model:tab="settingsTab" v-model:api-key="key" v-model:clear-key="clearKey" v-model:allow-remote="allowRemote" v-model:allow-install="allowInstall" v-model:allow-download="allowDownload" v-model:allow-remote-images="allowRemoteImages" v-model:auto-review="autoReview" v-model:allow-auto-train="allowAutoTrain"
      @patch="patchSettings" @changed="changed" @save="save" @back="closeSettings" @advice="mode='advice';settingsOpen=false" />
    <template v-else-if="mode==='agent'">
    <div v-if="ownerElsewhere" class="owner-banner" role="status">
      <div><strong>另一个项目正在使用 Agent</strong><p>当前运行属于「{{ activeProject || '新项目对话' }}」，此处显示「{{ projectName || '新项目对话' }}」的独立记录。</p></div>
      <button type="button" @click="emit('open-project', activeProject)">{{ activeProject ? '查看运行项目' : '回到新项目对话' }}</button>
    </div>

      <div class="status-strip" aria-live="polite"><div class="status-label"><span class="status-dot" :class="{active:agentActive}"></span><span>{{ phaseText }}</span></div>
        <div v-if="showCurrentControls" class="session-actions"><button v-if="agentActive" class="quiet-button" type="button" @click="controlAgent('pause')">暂停</button><button v-if="pausedOrInterrupted" class="quiet-button" type="button" @click="controlAgent('resume')">继续助手</button><details class="control-menu"><summary>更多</summary><div><button type="button" @click="controlAgent('takeover')">我来操作 · 交还控制权</button><button v-if="agentActive" type="button" @click="stopAgent(false)">结束助手，保留任务</button><button v-if="agent?.task_active" class="danger-text" type="button" @click="stopAgent(true)">停止助手和当前任务</button><p>暂停助手不会停止已启动的任务。</p></div></details></div>
      </div>
      <nav class="conversation-tabs" aria-label="助手内容"><button type="button" :class="{selected:conversationTab==='chat'}" :aria-pressed="conversationTab==='chat'" @click="conversationTab='chat'">对话<span v-if="agent?.status==='waiting_user'" class="tab-dot" title="等待回答"></span></button><button type="button" :class="{selected:conversationTab==='activity'}" :aria-pressed="conversationTab==='activity'" @click="conversationTab='activity'">执行记录<span v-if="toolMessages.length" class="tab-count">{{ toolMessages.length }}</span></button></nav>
    <section v-if="!settingsOpen && mode==='agent' && agent?.task_id" class="live-task-card" aria-label="当前任务进度" aria-live="polite">
      <div class="card-heading"><h3>{{ taskState?.title || '正在读取任务' }}</h3><span>{{ statusLabels[taskStatus] || (taskState?.ok===false?'窗口已失效':taskStatus==='awaiting_review'?'等待标签检查':'读取中') }}</span></div>
      <p>{{ taskState?.message || '正在读取软件的实际进度…' }}</p>
      <div class="task-metrics"><span v-if="taskState?.metrics?.total">{{ taskState.metrics.step }} / {{ taskState.metrics.total }} 步</span><span v-if="taskState?.metrics?.loss!=null">loss {{ taskState.metrics.loss.toFixed(4) }}</span><span>{{ taskEta }}</span></div>
      <progress v-if="taskProgress!=null" :value="taskProgress" max="1" aria-label="软件任务进度"></progress>
      <div class="result-actions"><button type="button" :disabled="taskState?.ok===false" @click="emit('open-task', agent.task_id)">查看{{ taskLabel }}进度</button><button class="secondary-button" type="button" @click="loadTaskDetails">查看日志{{ taskState?.kind==='training'?'与采样':'' }}</button><button v-if="canContinueTask" type="button" @click="continueTask">继续训练</button></div>
    </section>

      <section v-if="conversationTab==='chat'" ref="conversation" class="conversation" aria-label="项目对话" @scroll="onConversationScroll">
        <div v-if="!agent" class="welcome-card"><span class="welcome-kicker">你的本地训练助手</span><h3>想训练什么？<br>从一句话开始。</h3><p>告诉我目标，我会检查环境、询问缺少的信息，再帮你准备训练。你可以随时补充要求。</p><div class="starter-list"><button type="button" @click="startSuggestion('我要训练一个 LoRA，请一步步问我需要的信息')"><UiIcon name="plus" /><span><strong>训练一个 LoRA</strong><small>从目标、模型和图片开始</small></span><span aria-hidden="true">→</span></button><button type="button" @click="startSuggestion(projectName?'检查当前项目和训练环境，告诉我还缺少什么':'检查我的训练环境和已安装的模型，告诉我还缺少什么')"><UiIcon name="model" /><span><strong>检查环境与模型</strong><small>看看准备得是否完整</small></span><span aria-hidden="true">→</span></button><button type="button" @click="startSuggestion('帮我分析训练报错，先告诉我需要提供哪些日志或信息')"><UiIcon name="feedback" /><span><strong>分析训练报错</strong><small>根据实际日志找下一步</small></span><span aria-hidden="true">→</span></button></div></div>
        <div v-if="!settings.model.trim()" class="connection-prompt"><p>先连接一个 AI 模型，助手才能与你对话。</p><button type="button" @click="openSettings('connection')">配置 AI 模型</button></div>
        <article v-for="item in displayedMessages" :key="item.id" class="chat-message" :class="`role-${item.role}`"><span class="message-author">{{ item.role==='user'?'你':'训练助手' }}</span><AssistantMessageText v-if="item.role==='assistant'" :text="item.content" /><p v-else class="message-content">{{ item.content }}</p><span v-if="item.status==='streaming'" class="typing-caret" aria-label="正在生成">▍</span></article>
        <p v-if="agentActive && agent?.phase==='conversation' && !displayedMessages.some(item=>item.status==='streaming')" class="thinking-note" role="status"><span class="status-dot active"></span>正在整理回复…</p>
        <section v-if="failureText" class="failure-notice" role="alert"><strong>本次执行未完成</strong><p>{{ failureText }}</p><span>已完成的操作保留。可以补充要求继续处理。</span></section>
      <details v-if="agent?.plan" class="plan-card" :open="agent.status==='waiting_user' && agent.question_kind==='plan'"><summary>训练方案 · 查看设置与改动</summary>
        <div class="card-heading"><h3>执行方案</h3><span>可逐项检查</span></div>
        <dl v-if="agent.plan.fields?.length" class="plan-fields"><div v-for="field in agent.plan.fields" :key="field.key"><dt>{{ field.label }}</dt><dd>{{ formatValue(field.value) }}</dd></div></dl>
        <ul v-if="agent.plan.changes?.length" class="plan-changes"><li v-for="(change,index) in agent.plan.changes" :key="String(change.key||change.label||index)"><strong>{{ change.label||change.key||'修改项' }}</strong><span>{{ formatValue(change.before) }} → {{ formatValue(change.after??change.value) }}</span></li></ul>
        <ul v-if="agent.plan.warnings?.length" class="plan-warnings"><li v-for="warning in agent.plan.warnings" :key="warning">{{ warning }}</li></ul>
        <button v-if="agent.status==='waiting_user' && agent.question_kind==='plan'" type="button" class="secondary-button" @click="startSuggestion('我想调整这份方案：')">在对话中修改</button>
      </details>

      <section v-if="agent?.status==='waiting_user' && agent.question" class="question-card"><div class="question-label"><span></span>{{ agent.question_kind==='plan'?'确认训练方案':'等你选择' }}</div><AssistantMessageText :text="agent.question" />
        <div v-if="agent.choices?.length" class="choice-list"><button v-for="choice in agent.choices" :key="choice" type="button" :disabled="sendingMessage" @click="replyAgent(choice,agent.question_id)">{{ choice }}</button></div>
        <div v-if="agent.path_kind" class="path-picker"><p>请选择{{ agent.path_kind==='model'?'模型文件':'文件夹' }}，也可以粘贴路径后检查。</p><div class="path-row"><input v-model="pathDraft" type="text" :placeholder="agent.path_kind==='model'?'粘贴模型文件路径':'粘贴文件夹路径'"><button type="button" :disabled="sendingMessage" @click="chooseAgentPath()">从电脑选择</button></div><button v-if="pathDraft.trim()" type="button" :disabled="sendingMessage" @click="chooseAgentPath(pathDraft.trim())">检查路径并交给 Agent</button></div>
      </section>

      <section v-if="agent?.result" class="result-card" :class="resultClass"><div class="card-heading"><h3>{{ resultLabel }}</h3><span>{{ statusLabels[agent.result.status]||agent.result.status }}</span></div>
        <p>{{ agent.result.message||agent.result.error }}</p><p v-if="agent.result.error && agent.result.error!==agent.result.message" class="result-error">{{ agent.result.error }}</p>
        <div class="result-actions"><button v-if="agent.result.ok && agent.result.status==='completed' && agent.project" type="button" @click="openOutput">打开项目输出目录</button></div>
        <p v-if="agent.task_id && taskStatus==='awaiting_review'" class="hint">训练预处理已完成，等待你确认后继续。</p>

      </section>


      </section>
      <section v-else class="conversation activity-view" aria-label="执行记录"><div class="activity-heading"><h3>助手做过什么</h3><p>查看工具返回的实际结果，以及当前任务的日志。</p></div><p v-if="!toolMessages.length && !agent?.environment" class="empty-records">还没有执行记录。开始对话后，实际操作会记录在这里。</p>
      <details v-if="toolMessages.length" class="tool-history" open><summary>已调用工具 {{ toolMessages.length }} 次 · 查看执行记录</summary><details v-for="item in toolMessages" :key="item.id" class="tool-card"><summary><strong>{{ toolTitle(item) }}</strong><span>{{ toolSummary(item) }}</span></summary><pre>{{ item.content }}</pre></details></details>

        <details v-if="taskDetailsOpen || taskLogs.length || taskSamples.length" class="task-details" :open="taskDetailsOpen"><summary @click.prevent="taskDetailsOpen=!taskDetailsOpen">任务日志与采样 {{ taskDetailsLoading?'· 读取中':'' }}</summary><p v-if="taskDetailsError" class="hint">{{ taskDetailsError }}</p><pre v-if="taskLogs.length" class="task-log">{{ taskLogs.join('\n') }}</pre><p v-else-if="!taskDetailsLoading" class="hint">当前任务没有可显示的日志。</p><div v-if="taskSamples.length" class="sample-list"><button v-for="sample in taskSamples" :key="sample.name" type="button" @click="showSample(sample.name)">{{ sample.name }}</button></div><figure v-if="samplePreview" class="sample-preview"><img :src="samplePreview" :alt="sampleName"><figcaption>{{ sampleName }}</figcaption></figure></details>

      <details v-if="agent?.catalog?.length || agent?.environment" class="capabilities-card"><summary>本次检查到的环境与可用工具</summary><p v-if="agent.environment" class="hint">{{ agent.environment.gpu?.name||'未检测到显卡' }}<span v-if="agent.environment.gpu?.vram_gb!=null"> · {{ agent.environment.gpu.vram_gb }} GB 显存</span> · {{ agent.catalog?.length||0 }} 项工具</p><ul v-if="agent.catalog?.length"><li v-for="tool in agent.catalog" :key="tool.name"><strong>{{ tool.title }}</strong><span>{{ tool.description }}</span></li></ul></details>

      </section>
      <p v-if="message" class="system-notice" role="status">{{ message }}</p>
      <form class="composer" @submit.prevent="submitAgentComposer"><div class="composer-field"><textarea ref="composer" v-model="draft" rows="2" maxlength="6000" :placeholder="agent?.status==='waiting_user'?'点击上方选项，或在这里回答…':'告诉我目标，或补充新的要求…'" aria-label="给训练助手的消息" @keydown="onComposerKeydown"></textarea><button class="send-button" type="submit" :disabled="!canSubmitAgent || !desktop">{{ sendingMessage?'发送中':startingAgent?'开始中':agent?.status==='waiting_user'?'回答':agent?.status==='paused' && agent.pause_explicit?'记录':'发送' }}<span aria-hidden="true">↑</span></button></div><div class="composer-footer"><button class="service-chip" type="button" :title="serviceName" @click="openSettings('connection')"><span class="service-indicator" :class="{configured:settings.model.trim()}"></span><span class="service-model-name">{{ serviceName }}</span><span aria-hidden="true">⌄</span></button><span>Enter 发送 · Shift+Enter 换行</span></div><p class="composer-context">{{ agent?.status==='paused' && agent.pause_explicit?'助手已暂停：消息会保留，继续后再处理。':allowAutoTrain?'已允许准备完成后自动训练':'开始训练前会先确认方案' }}</p></form>
    </template>
    <div v-if="!settingsOpen && mode==='advice'" class="advice-mode"><header><h3>参数建议模式 <small>{{ result?.project||projectName||'通用咨询' }}</small></h3><button type="button" class="secondary-button" @click="mode='agent'">返回 Agent 对话</button></header><label>你希望调整什么<textarea v-model="question" maxlength="6000" rows="4" placeholder="例如：降低显存占用，分辨率不要变。"></textarea></label><label v-if="projectName" class="check"><input v-model="includeLogs" type="checkbox">附加同项目最近任务的最多 100 行日志</label><button v-if="isRemoteService && !allowRemote" type="button" @click="openSettings('permissions')">设置在线文字服务权限</button><p class="hint">参数建议读取已保存参数，先展示差异，应用后才会保存。密钥不会进入上下文。</p><div class="buttons"><button type="button" :disabled="busy||saving||!desktop||!question.trim()" @click="sendAdvice">{{ busy?'正在生成方案…':'生成参数建议' }}</button><button v-if="busy" type="button" @click="stopAdvice">停止</button></div><p v-if="result?.answer" class="answer">{{ result.answer }}</p><table v-if="result?.changes?.length"><thead><tr><th>参数</th><th>原值 → 新值</th></tr></thead><tbody><tr v-for="item in result.changes" :key="item.key"><td>{{ item.label }}</td><td>{{ item.before??'自动' }} → {{ item.after }}</td></tr></tbody></table><div v-if="actionable" class="buttons"><button v-if="!result?.applied" type="button" :disabled="applying" @click="apply()">应用并保存这些修改</button><button v-else type="button" :disabled="applying" @click="apply(true)">撤销本次修改</button></div><p v-if="message" class="system-notice" role="status">{{ message }}</p></div>

    <div v-if="samplePreview" class="sample-lightbox" role="dialog" aria-modal="true" :aria-label="sampleName" @click.self="samplePreview=''" @keydown.esc.stop="samplePreview=''"><button type="button" aria-label="关闭采样图" @click="samplePreview=''">×</button><img :src="samplePreview" :alt="sampleName"></div>
    <p v-if="!desktop" class="preview-note">浏览器预览不会调用本机助手，请从桌面版打开。</p>
  </aside>
</template>
<style scoped>
.assistant-panel {
  --card:#232831; --bg:#1c2129; --text:#e6eaf0; --hint:#a0aab8; --border:#39424f;
  --assistant-subtle:#2c333f; --assistant-accent:#93b4de; --assistant-accent-soft:#93b4de22; --assistant-on-accent:#17212e;
  position:fixed; right:14px; top:56px; bottom:16px; width:min(540px,calc(100vw - 28px)); z-index:60;
  display:flex; flex-direction:column; overflow:hidden; min-width:0; background:var(--card); color:var(--text);
  border:1px solid var(--border); border-radius:16px; box-shadow:0 22px 70px #0005; font-size:13px;
}
.assistant-panel.is-expanded { width:min(860px,calc(100vw - 28px)); }
.assistant-panel * { box-sizing:border-box; }
button,input,select,textarea { font:inherit; color:inherit; }
button { border:1px solid var(--border); border-radius:8px; padding:8px 11px; background:var(--bg); cursor:pointer; transition:background-color 120ms ease,border-color 120ms ease,transform 120ms var(--ease-out); }
button:hover:not(:disabled) { background:var(--assistant-subtle); border-color:var(--hint); }
button:active:not(:disabled) { transform:translateY(1px); }
button:disabled { opacity:.45; cursor:default; }
button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,summary:focus-visible { outline:2px solid var(--assistant-accent); outline-offset:3px; }
input:not([type='checkbox']),select,textarea { min-width:0; max-width:100%; padding:9px 11px; border:1px solid var(--border); border-radius:8px; background:var(--bg); }
input[type='checkbox'] { appearance:auto; width:16px; height:16px; min-width:16px; max-width:16px; padding:0; margin:3px 0 0; flex:none; accent-color:var(--assistant-accent); }
.quiet-button,.secondary-button { background:transparent; }
.assistant-header { display:flex; align-items:center; justify-content:space-between; flex:none; gap:12px; padding:18px 20px; border-bottom:1px solid var(--border); }
.assistant-title { display:flex; gap:11px; align-items:center; min-width:0; flex:1; }
.assistant-title>div { min-width:0; }
.assistant-title h2 { margin:0 0 4px; font-size:17px; line-height:1.3; font-weight:650; letter-spacing:-.2px; }
.assistant-symbol { width:34px; height:34px; border:1px solid var(--border); border-radius:10px; background:var(--assistant-subtle); display:grid; place-items:center; color:var(--assistant-accent); flex:none; }
:deep(.ui-icon) { display:block; width:18px; height:18px; fill:none; stroke:currentColor; stroke-width:1.5; stroke-linecap:round; stroke-linejoin:round; flex:none; }
.project-label { display:block; max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:11px; color:var(--hint); }
.header-actions { display:flex; align-items:center; gap:4px; flex:none; }
.header-actions .quiet-button { display:flex; align-items:center; gap:5px; padding:7px 8px; font-size:11px; border:0; }
.icon-button { width:32px; height:32px; border:0; padding:7px; background:transparent; display:grid; place-items:center; }
.icon-button svg { display:block; width:18px; height:18px; fill:none; stroke:currentColor; stroke-width:1.6; stroke-linecap:round; stroke-linejoin:round; }
.status-strip { display:flex; justify-content:space-between; gap:10px; align-items:center; min-height:43px; padding:5px 22px; font-size:11px; color:var(--hint); flex:none; }
.status-label { display:flex; align-items:center; gap:8px; min-width:0; }
.status-dot { display:inline-block; width:6px; height:6px; border-radius:50%; background:var(--hint); flex:none; }
.status-dot.active { background:#82c5a3; box-shadow:0 0 0 3px #82c5a316; }
.session-actions { display:flex; gap:6px; align-items:center; flex:none; }
.session-actions>button { padding:5px 8px; font-size:11px; border:0; }
.control-menu { position:relative; }
.control-menu summary { cursor:pointer; list-style:none; padding:5px 8px; font-size:11px; }
.control-menu summary::-webkit-details-marker { display:none; }
.control-menu>div { position:absolute; right:0; top:100%; z-index:5; width:240px; padding:7px; border:1px solid var(--border); border-radius:10px; background:var(--bg); box-shadow:0 10px 24px #0004; }
.control-menu button { display:block; width:100%; border:0; background:transparent; font-size:11px; text-align:left; }
.control-menu p { margin:7px 8px 5px; color:var(--hint); font-size:10px; line-height:1.5; }
.danger-text { color:#e69d9d; }
.conversation-tabs { display:flex; flex:none; gap:24px; margin:0 22px 10px; border-bottom:1px solid var(--border); }
.conversation-tabs>button { display:flex; align-items:center; gap:7px; border:0; border-bottom:2px solid transparent; border-radius:0; padding:9px 0 12px; background:transparent; font-size:12px; color:var(--hint); }
.conversation-tabs>button.selected { color:var(--text); border-bottom-color:var(--assistant-accent); }
.tab-count { color:var(--hint); font-size:10px; background:var(--assistant-subtle); padding:1px 5px; border-radius:5px; }
.tab-dot { width:5px; height:5px; border-radius:50%; background:var(--assistant-accent); }
.owner-banner { display:flex; align-items:center; flex-wrap:wrap; justify-content:space-between; gap:10px; margin:12px 20px 2px; padding:12px; border:1px solid #bc934b66; border-radius:10px; font-size:11px; line-height:1.55; }
.owner-banner>div { flex:1; min-width:160px; }
.owner-banner p { margin:5px 0 0; color:var(--hint); overflow-wrap:anywhere; }
.owner-banner button { font-size:11px; }
.live-task-card { flex:none; margin:2px 20px 12px; padding:12px 14px; border:1px solid #93b4de44; border-radius:10px; background:var(--bg); max-height:24vh; overflow-y:auto; overflow-x:hidden; }
.card-heading { display:flex; justify-content:space-between; gap:10px; align-items:baseline; min-width:0; }
.card-heading h3 { font-size:12px; font-weight:600; margin:0; min-width:0; overflow-wrap:anywhere; }
.card-heading>span { font-size:10px; color:var(--hint); flex:none; }
.live-task-card p { font-size:11px; line-height:1.6; margin:6px 0; color:var(--hint); overflow-wrap:anywhere; }
.task-metrics { display:flex; flex-wrap:wrap; gap:12px; margin-top:7px; color:var(--hint); font-size:11px; font-variant-numeric:tabular-nums; }
.live-task-card progress { display:block; width:100%; height:4px; margin-top:10px; accent-color:var(--assistant-accent); }
.live-task-card .result-actions { margin-top:9px; }
.live-task-card .result-actions button { font-size:11px; padding:5px 8px; }
.conversation { flex:1; min-height:0; min-width:0; padding:10px 24px 24px; overflow-y:auto; overflow-x:hidden; overscroll-behavior:contain; scrollbar-gutter:stable; }
.is-expanded .conversation { padding-inline:40px; }
.welcome-card { padding:20px 0 8px; margin:auto; max-width:480px; }
.welcome-kicker { font-size:10px; letter-spacing:1px; color:var(--hint); }
.welcome-card h3 { margin:15px 0 12px; font-size:27px; line-height:1.4; font-weight:550; letter-spacing:-.6px; }
.welcome-card>p { font-size:12px; line-height:1.85; color:var(--hint); max-width:390px; margin:0 0 24px; }
.starter-list { display:grid; gap:8px; margin-top:24px; }
.starter-list button { display:flex; align-items:center; gap:12px; padding:13px 14px; text-align:left; background:transparent; border-radius:10px; }
.starter-list button>span:nth-child(2) { display:grid; gap:4px; flex:1; min-width:0; }
.starter-list strong { font-size:12px; font-weight:500; }
.starter-list small { font-size:11px; color:var(--hint); line-height:1.5; }
.starter-list button>span:last-child { color:var(--hint); }
.connection-prompt { display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap; margin:16px 0; padding:12px; border:1px dashed var(--border); border-radius:10px; }
.connection-prompt p { flex:1; margin:0; color:var(--hint); font-size:11px; line-height:1.5; min-width:160px; }
.connection-prompt button { font-size:11px; flex:none; }
.chat-message { min-width:0; max-width:100%; margin:24px 0; }
.chat-message.role-user { width:fit-content; max-width:90%; margin-left:auto; padding:12px 15px; background:var(--assistant-subtle); border-radius:14px 14px 4px 14px; }
.chat-message.role-assistant { margin-right:auto; }
.message-author { display:block; font-size:10px; line-height:1.4; color:var(--hint); margin:0 0 9px; }
.role-user .message-author { margin-bottom:6px; }
.message-content { font-size:13px; line-height:1.75; white-space:pre-wrap; overflow-wrap:anywhere; margin:0; }
.typing-caret { display:inline-block; color:var(--assistant-accent); animation:blink 1s steps(2,start) infinite; margin-left:2px; }
.thinking-note { display:flex; align-items:center; gap:9px; font-size:12px; color:var(--hint); margin:20px 0; }
.plan-card,.question-card,.result-card,.failure-notice { min-width:0; margin:20px 0; padding:16px; border:1px solid var(--border); border-radius:12px; background:var(--bg); }
.plan-card>summary { cursor:pointer; font-size:12px; color:var(--hint); line-height:1.5; }
.plan-card .card-heading { margin-top:14px; }
.plan-fields { margin:16px 0; display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:13px; }
.plan-fields>div { min-width:0; }
.plan-fields dt { font-size:10px; color:var(--hint); }
.plan-fields dd { margin:4px 0 0; font-size:12px; line-height:1.65; overflow-wrap:anywhere; }
.plan-changes,.plan-warnings { padding-left:18px; font-size:11px; line-height:1.65; margin:14px 0; }
.plan-changes li { margin:8px 0; }
.plan-changes strong { display:block; font-weight:500; }
.plan-changes span { color:var(--hint); overflow-wrap:anywhere; }
.plan-warnings { color:#d4b583; }
.question-card { border-color:#93b4de66; background:var(--assistant-accent-soft); }
.question-label { display:flex; align-items:center; gap:7px; font-size:10px; letter-spacing:.5px; color:var(--assistant-accent); margin:0 0 12px; }
.question-label>span { width:5px; height:5px; border-radius:50%; background:currentColor; }
.choice-list { display:grid; grid-template-columns:minmax(0,1fr); gap:8px; margin-top:16px; }
.choice-list button { text-align:left; padding:10px 12px; font-size:12px; line-height:1.55; background:var(--card); overflow-wrap:anywhere; white-space:normal; }
.choice-list button:hover:not(:disabled) { border-color:var(--assistant-accent); }
.path-picker { padding-top:12px; margin-top:14px; border-top:1px solid var(--border); }
.path-picker p { margin:0; font-size:11px; line-height:1.6; color:var(--hint); }
.path-row { display:flex; gap:7px; margin:10px 0; flex-wrap:wrap; }
.path-row input { min-width:120px; width:0; flex:1; font-size:11px; }
.path-row button,.path-picker>button { font-size:11px; }
.result-card.success { border-color:#82c5a366; }.result-card.failure,.failure-notice { border-color:#e69d9d55; }.result-card.stopped { border-color:var(--border); }
.result-card>p,.failure-notice p { margin:10px 0 0; white-space:pre-wrap; overflow-wrap:anywhere; font-size:12px; line-height:1.8; }
.failure-notice>strong { font-size:12px; font-weight:600; }.failure-notice>span { display:block; color:var(--hint); font-size:11px; line-height:1.65; margin-top:8px; }
.result-error { color:#e69d9d; }.result-actions,.buttons { display:flex; gap:8px; flex-wrap:wrap; margin-top:14px; }.result-actions button { font-size:11px; }
.hint { font-size:11px; line-height:1.7; color:var(--hint); overflow-wrap:anywhere; }
.activity-heading { margin:5px 0 24px; }.activity-heading h3 { font-size:17px; margin:0 0 7px; font-weight:550; }.activity-heading p,.empty-records { color:var(--hint); font-size:12px; line-height:1.8; margin:0; }
.tool-history,.capabilities-card,.task-details { min-width:0; margin:18px 0; border:1px solid var(--border); padding:12px 14px; border-radius:10px; }
.tool-history>summary,.capabilities-card>summary,.task-details>summary { cursor:pointer; font-size:12px; line-height:1.6; color:var(--hint); }
.tool-card { margin-top:12px; padding-top:10px; border-top:1px solid var(--border); min-width:0; }
.tool-card summary { cursor:pointer; font-size:11px; line-height:1.7; }
.tool-card summary strong { display:block; color:var(--text); font-weight:500; }.tool-card summary span { display:block; color:var(--hint); overflow-wrap:anywhere; margin-top:3px; }
.tool-card pre,.task-log { margin:10px 0 0; padding:10px; border-radius:7px; max-width:100%; max-height:240px; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; background:var(--bg); color:var(--hint); font:11px/1.6 Consolas,monospace; }
.capabilities-card ul { list-style:none; padding:0; margin:14px 0 0; }.capabilities-card li { display:grid; grid-template-columns:90px minmax(0,1fr); gap:10px; margin:10px 0; font-size:11px; line-height:1.7; }.capabilities-card li strong { font-weight:500; overflow-wrap:anywhere; }.capabilities-card li span { color:var(--hint); overflow-wrap:anywhere; }
.sample-list { display:flex; flex-wrap:wrap; gap:6px; margin-top:10px; }.sample-list button { font-size:10px; overflow-wrap:anywhere; max-width:100%; }.sample-preview { margin:10px 0; text-align:center; }.sample-preview img { max-width:100%; max-height:230px; object-fit:contain; border-radius:7px; }.sample-preview figcaption { color:var(--hint); font-size:10px; overflow-wrap:anywhere; }
.system-notice { flex:none; max-height:90px; overflow-y:auto; overflow-x:hidden; margin:0 20px 10px; padding:10px 12px; border-radius:8px; background:var(--assistant-subtle); color:var(--hint); font-size:11px; line-height:1.65; overflow-wrap:anywhere; }
.composer { flex:none; padding:14px 18px 13px; border-top:1px solid var(--border); background:var(--card); min-width:0; }
.composer-field { display:flex; align-items:flex-end; gap:9px; border:1px solid var(--border); border-radius:12px; padding:10px; background:var(--bg); min-width:0; }
.composer-field:focus-within { border-color:var(--assistant-accent); box-shadow:0 0 0 3px var(--assistant-accent-soft); }
.composer-field textarea { width:0; min-width:0; flex:1; height:70px; min-height:70px; max-height:160px; resize:vertical; background:transparent; border:0; padding:3px 4px; font-size:13px; line-height:1.75; outline:none; }
.composer-field textarea:focus-visible { outline:none; }
.composer-field textarea::placeholder { color:var(--hint); }
.send-button { display:flex; align-items:center; justify-content:center; gap:5px; flex:none; padding:8px 11px; border:0; background:var(--assistant-accent); color:var(--assistant-on-accent); border-radius:8px; font-size:12px; min-height:34px; }
.send-button:hover:not(:disabled) { background:var(--assistant-accent); filter:brightness(1.1); }.send-button span { font-size:16px; line-height:1; }
.composer-footer { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px; margin-top:9px; }
.composer-footer>span { font-size:10px; color:var(--hint); white-space:nowrap; }
.service-chip { display:flex; gap:6px; align-items:center; min-width:0; max-width:55%; padding:3px 4px; border:0; background:transparent; font-size:10px; color:var(--hint); overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
.service-model-name { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.service-chip>span:last-child { margin-left:2px; }.service-indicator { width:5px; height:5px; border-radius:50%; background:var(--hint); flex:none; }.service-indicator.configured { background:var(--assistant-accent); }
.composer-context { margin:6px 3px 0; color:var(--hint); font-size:10px; line-height:1.5; }
.advice-mode { flex:1; min-width:0; min-height:0; padding:24px; overflow-y:auto; overflow-x:hidden; }.advice-mode header { display:flex; justify-content:space-between; flex-wrap:wrap; align-items:center; gap:10px; margin-bottom:24px; }.advice-mode h3 { font-size:15px; margin:0; }.advice-mode small { display:block; margin-top:4px; color:var(--hint); font-size:11px; font-weight:400; }.advice-mode label { display:grid; gap:8px; font-size:12px; margin:16px 0; }.advice-mode textarea { width:100%; resize:vertical; line-height:1.75; }.advice-mode .check { display:flex; align-items:flex-start; gap:10px; line-height:1.65; }.advice-mode .answer { white-space:pre-wrap; line-height:1.8; font-size:13px; overflow-wrap:anywhere; }.advice-mode table { width:100%; border-collapse:collapse; font-size:11px; overflow-wrap:anywhere; }.advice-mode th,.advice-mode td { text-align:left; padding:9px 4px; border-bottom:1px solid var(--border); }.advice-mode .system-notice { margin:14px 0; }
.sample-lightbox { position:fixed; inset:0; z-index:90; background:#000d; display:grid; place-items:center; padding:24px; }.sample-lightbox img { max-width:96%; max-height:90%; object-fit:contain; }.sample-lightbox button { position:absolute; right:18px; top:18px; font-size:24px; background:var(--card); }
.preview-note { flex:none; margin:0; padding:7px 18px; background:var(--bg); color:var(--hint); font-size:10px; line-height:1.5; }
:global(.app-shell[data-theme='light']) .assistant-panel { --card:#fafbfc; --bg:#f0f3f7; --text:#252c38; --hint:#667383; --border:#dce2ea; --assistant-subtle:#e9edf4; --assistant-accent:#486e9d; --assistant-accent-soft:#486e9d12; --assistant-on-accent:#ffffff; }
@keyframes blink { to { visibility:hidden; } }
@media(max-width:600px) { .assistant-panel,.assistant-panel.is-expanded { top:0; right:0; bottom:0; width:100%; border:0; border-radius:0; }.assistant-header { padding:14px 16px; }.conversation,.is-expanded .conversation { padding:12px 18px 24px; }.expand-button { display:none; }.status-strip { padding-inline:18px; }.conversation-tabs { margin-inline:18px; }.live-task-card { margin-inline:16px; }.composer { padding:12px 14px; }.plan-fields { grid-template-columns:minmax(0,1fr); } }
@media(max-width:380px) { .composer-footer>span { font-size:9px; }.welcome-card h3 { font-size:24px; }.capabilities-card li { grid-template-columns:minmax(0,1fr); gap:3px; }.card-heading { flex-wrap:wrap; }.service-chip { max-width:100%; } }
@media(prefers-reduced-motion:reduce) { .typing-caret { animation:none; } button { transition:none; } }
</style>
