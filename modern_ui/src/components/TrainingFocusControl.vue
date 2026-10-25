<script setup lang="ts">
import { ref } from 'vue'
const props = defineProps<{ projectName: string; desktop: boolean; multi: boolean; mode: string; source: string; floor: string; overwriteAuto: boolean; disabled: boolean }>()
const emit = defineEmits<{ change: [key: string, value: string | boolean]; generate: []; edit: [] }>()
const more = ref(false)
function changeSource(value:string) {
  emit('change','mask_source',value)
  if(value==='anime' && !['off','person','existing'].includes(props.mode)) emit('change','mask_mode','person')
}
const advancedLabels: Record<string, string> = { existing: '使用已有遮罩', body_clothes: '身体与服装', not_faces: '排除脸部与头发' }
</script>
<template>
  <section class="training-focus" aria-label="学习重点">
    <label>图片类型<select :value="source" :disabled="disabled" @change="changeSource(($event.target as HTMLSelectElement).value)"><option value="anime">二次元 · 专用人物分割</option><option value="photo">真人 · 多类别分割</option></select></label>
    <label>学习重点
      <select :value="mode" :disabled="disabled" @change="emit('change', 'mask_mode', ($event.target as HTMLSelectElement).value)">
        <option value="off">整张图片（默认）</option>
        <option value="person">{{ multi ? '所有角色' : '人物整体' }}</option>
        <option value="head" :disabled="source === 'anime'">脸部与头发</option>
        <option v-if="advancedLabels[mode]" :value="mode">{{ advancedLabels[mode] }}</option>
      </select>
    </label>
    <template v-if="mode !== 'off'">
      <p>{{ multi ? '每张图中的所有人物都参与学习；学习区域不会自动分离角色身份。' : '白色区域重点学习，背景按下方设置参与。' }}</p>
      <p>{{ source === 'anime' ? '二次元自动识别人物整体；局部区域请用画笔修正。' : '真人模型可识别脸部与头发等区域；远景和遮挡请检查覆盖范围。' }}</p>
      <p>遮罩不替代打标：标签描述人物和内容，遮罩指定重点学习范围。</p>
      <button type="button" :disabled="disabled || !desktop" @click="emit('edit')">打开遮罩编辑器</button>
    </template>
    <button type="button" class="more" :aria-expanded="more" @click="more = !more">{{ more ? '收起设置' : '更多设置' }}</button>
    <div v-if="more" class="options">
      <label>其他学习区域<select :value="advancedLabels[mode] ? mode : ''" :disabled="disabled" @change="emit('change', 'mask_mode', ($event.target as HTMLSelectElement).value)"><option value="" disabled>选择其他区域…</option><option value="existing">使用已有遮罩</option><option value="body_clothes" :disabled="source === 'anime'">身体与服装</option><option value="not_faces" :disabled="source === 'anime'">排除脸部与头发</option></select></label>
        <label>背景参与程度<select :value="floor" :disabled="disabled" @change="emit('change', 'mask_floor', ($event.target as HTMLSelectElement).value)"><option value="0">忽略背景</option><option value="0.1">少量学习 · 10%（推荐）</option><option value="0.3">较多学习 · 30%</option><option v-if="!['0','0.1','0.3'].includes(floor)" :value="floor">自定义 · {{ Number(floor) * 100 }}%</option></select></label>
        <label class="check"><input type="checkbox" :checked="overwriteAuto" :disabled="disabled" @change="emit('change', 'mask_overwrite_auto', ($event.target as HTMLInputElement).checked)">重新生成自动遮罩（保留手绘与导入区域）</label>
        <p v-if="mode === 'existing'">原图旁放置同名的 photo-masklabel.png，尺寸与原图一致。软件会同步裁剪到训练副本。</p>
    </div>
  </section>
</template>
<style scoped>
.training-focus{display:grid;gap:9px;padding:14px 0;margin:8px 0;border-top:1px solid var(--border);font-size:12px;color:var(--text)}label{display:grid;gap:6px}select,button{font:inherit;border:1px solid var(--border);border-radius:5px;padding:8px 10px;background:var(--bg);color:var(--text);min-height:34px}button{width:fit-content;cursor:pointer}button:disabled,select:disabled{opacity:.5;cursor:default}p{margin:0;line-height:1.6;color:var(--hint)}.more{border:0;padding:0;min-height:24px;color:var(--hint)}.options{display:grid;gap:10px}.check{display:flex;align-items:center;gap:7px}button:focus-visible,select:focus-visible{outline:2px solid var(--tone-8fb0c9);outline-offset:2px}
</style>
