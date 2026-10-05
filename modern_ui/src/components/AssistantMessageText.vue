<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ text: string }>()
type Block = { kind:'paragraph'|'heading'|'list'|'ordered'|'code'|'quote'; lines:string[] }
const blocks = computed(() => {
  const output:Block[] = []
  let fenced = false
  for (const line of props.text.split('\n')) {
    if (/^\s*```/.test(line)) { fenced=!fenced; if(fenced) output.push({kind:'code',lines:[]}); continue }
    if (fenced) { output[output.length-1]!.lines.push(line); continue }
    if (!line.trim()) { if(output[output.length-1]?.kind==='paragraph') output.push({kind:'paragraph',lines:[]}); continue }
    let kind:Block['kind']='paragraph', text=line
    if (/^#{1,6}\s/.test(line)) { kind='heading'; text=line.replace(/^#{1,6}\s+/,'') }
    else if (/^\s*[-*+]\s+/.test(line)) { kind='list'; text=line.replace(/^\s*[-*+]\s+/,'') }
    else if (/^\s*\d+[.)]\s+/.test(line)) { kind='ordered'; text=line.replace(/^\s*\d+[.)]\s+/,'') }
    else if (/^>\s?/.test(line)) { kind='quote'; text=line.replace(/^>\s?/,'') }
    const previous=output[output.length-1]
    if (previous?.kind===kind && kind!=='heading') previous.lines.push(text)
    else output.push({kind,lines:[text]})
  }
  return output.filter(block=>block.lines.length)
})
function inline(text:string) {
  const parts:Array<{kind:'text'|'strong'|'code';text:string}>=[]
  const pattern=/\*\*([^*\n]+)\*\*|`([^`\n]+)`/g
  let offset=0
  for(const match of text.matchAll(pattern)) {
    const start=match.index||0
    if(start>offset) parts.push({kind:'text',text:text.slice(offset,start)})
    parts.push({kind:match[1]?'strong':'code',text:match[1]||match[2]||''})
    offset=start+match[0].length
  }
  if(offset<text.length) parts.push({kind:'text',text:text.slice(offset)})
  return parts
}
</script>
<template>
  <div class="assistant-markdown">
    <template v-for="(block,index) in blocks" :key="index">
      <pre v-if="block.kind==='code'"><code>{{ block.lines.join('\n') }}</code></pre>
      <component :is="block.kind==='list'?'ul':'ol'" v-else-if="['list','ordered'].includes(block.kind)"><li v-for="(line,lineIndex) in block.lines" :key="lineIndex"><template v-for="(part,partIndex) in inline(line)" :key="partIndex"><strong v-if="part.kind==='strong'">{{ part.text }}</strong><code v-else-if="part.kind==='code'">{{ part.text }}</code><template v-else>{{ part.text }}</template></template></li></component>
      <component :is="block.kind==='heading'?'h4':block.kind==='quote'?'blockquote':'p'" v-else><template v-for="(part,partIndex) in inline(block.lines.join('\n'))" :key="partIndex"><strong v-if="part.kind==='strong'">{{ part.text }}</strong><code v-else-if="part.kind==='code'">{{ part.text }}</code><template v-else>{{ part.text }}</template></template></component>
    </template>
  </div>
</template>
<style scoped>
.assistant-markdown{min-width:0;max-width:100%;color:inherit;overflow-wrap:anywhere;font-size:13px;line-height:1.8}.assistant-markdown p{margin:0 0 12px;white-space:pre-wrap}.assistant-markdown>:last-child{margin-bottom:0}.assistant-markdown h4{margin:18px 0 9px;font-size:14px;line-height:1.6;font-weight:600}.assistant-markdown h4:first-child{margin-top:0}.assistant-markdown ul,.assistant-markdown ol{padding-left:21px;margin:10px 0 16px}.assistant-markdown li{margin:6px 0}.assistant-markdown strong{font-weight:600;color:var(--text)}.assistant-markdown code{font-size:.92em;border-radius:4px;background:var(--assistant-subtle);padding:2px 5px;font-family:Consolas,monospace;overflow-wrap:anywhere}.assistant-markdown pre{margin:12px 0;padding:12px;border:1px solid var(--border);border-radius:8px;background:var(--bg);overflow:auto;max-height:260px;white-space:pre-wrap;font:11px/1.65 Consolas,monospace}.assistant-markdown pre code{padding:0;background:none}.assistant-markdown blockquote{margin:12px 0;border-left:3px solid var(--border);padding:4px 12px;color:var(--hint);white-space:pre-wrap}
</style>
