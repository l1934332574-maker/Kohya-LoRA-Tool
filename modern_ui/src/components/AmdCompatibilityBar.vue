<script setup lang="ts">
import { legacyTooltips } from '../legacyTooltips'

defineProps<{ enabled: boolean }>()

const emit = defineEmits<{
  toggle: []
  inspect: []
}>()
</script>

<template>
  <section class="amd-compat-bar" aria-label="AMD 兼容设置">
    <div class="amd-copy">
      <span class="amd-mark" aria-hidden="true">AMD</span>
      <div class="amd-description">
        <strong>AMD 兼容模式（实验性）</strong>
        <small>针对 AMD 显卡的兼容训练设置</small>
      </div>
    </div>
    <div class="amd-actions">
      <button
        class="amd-toggle"
        :class="{ enabled }"
        type="button"
        role="checkbox"
        :aria-checked="enabled"
        :title="legacyTooltips.amdMode"
        @click="emit('toggle')"
      >
        <i aria-hidden="true"></i>
        <span>{{ enabled ? '已开启' : '开启 AMD 兼容模式' }}</span>
      </button>
      <button class="amd-inspect" type="button" title="检查当前引擎的 AMD 训练环境并打开安装引导。" @click="emit('inspect')">
        环境检查 / 安装引导
      </button>
    </div>
  </section>
</template>

<style scoped>
.amd-compat-bar {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 50px;
  padding: 7px 24px;
  border-bottom: 1px solid var(--border);
  border-left: 3px solid #b65a55;
  background: linear-gradient(90deg, rgba(182, 90, 85, .10), var(--card) 42%);
}
.amd-copy,.amd-actions { display: flex; align-items: center; gap: 10px; }
.amd-mark {
  display: grid;
  width: 32px;
  height: 25px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid rgba(182, 90, 85, .55);
  border-radius: 4px;
  color: #b65a55;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .04em;
}
.amd-description { display: grid; gap: 3px; }
.amd-description strong { color: var(--text); font-size: 11px; font-weight: 450; }
.amd-description small { color: var(--hint); font-size: 9px; }
.amd-toggle,.amd-inspect {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 30px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: 5px;
  color: var(--sub);
  background: transparent;
  font-size: 10px;
  white-space: nowrap;
  cursor: pointer;
  transition: color 130ms ease, background-color 130ms ease, border-color 130ms ease;
}
.amd-toggle:hover,.amd-inspect:hover { border-color: var(--accent); color: var(--text); background: var(--card-hover); }
.amd-toggle > i {
  display: grid;
  width: 14px;
  height: 14px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid var(--hint);
  border-radius: 3px;
  background: var(--bg);
}
.amd-toggle.enabled > i { border-color: var(--accent); background: var(--accent); }
.amd-toggle.enabled > i::after {
  width: 6px;
  height: 3px;
  border-bottom: 1.4px solid var(--text);
  border-left: 1.4px solid var(--text);
  transform: translateY(-1px) rotate(-45deg);
  content: '';
}
.amd-toggle.enabled { color: var(--text); }
.amd-inspect { border-color: var(--accent); color: var(--text); background: var(--card-hover); }
@media(max-width:700px) {
  .amd-compat-bar { align-items: flex-start; flex-direction: column; padding: 9px 15px; }
  .amd-actions { width: 100%; flex-wrap: wrap; }
}
</style>
