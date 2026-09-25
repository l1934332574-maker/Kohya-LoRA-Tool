<script setup lang="ts">
export type IconName = 'home' | 'toolbox' | 'refresh' | 'folder' | 'database' | 'queue' | 'plus' | 'settings' | 'play' | 'export' | 'back' | 'model'

defineProps<{ name: IconName }>()
</script>

<template>
  <svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <template v-if="name === 'home'"><path d="m3 10 9-7 9 7" /><path d="M5 9v11h14V9M9 20v-6h6v6" /></template>
    <template v-else-if="name === 'toolbox'"><rect x="3" y="7" width="18" height="14" rx="2" /><path d="M8 7V4h8v3M3 12h18M10 12v2h4v-2" /></template>
    <template v-else-if="name === 'refresh'"><path d="M20 7v5h-5M4 17v-5h5" /><path d="M5.5 9a7 7 0 0 1 11.7-2L20 12M4 12l2.8 5a7 7 0 0 0 11.7-2" /></template>
    <template v-else-if="name === 'folder'"><path d="M3 6.5A1.5 1.5 0 0 1 4.5 5H10l2 2h7.5A1.5 1.5 0 0 1 21 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z" /><path d="M3.5 9h17" /></template>
    <template v-else-if="name === 'database'"><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" /></template>
    <template v-else-if="name === 'queue'"><path d="M8 3h8M8 21h8M9 3v5l3 4-3 4v5M15 3v5l-3 4 3 4v5" /></template>
    <template v-else-if="name === 'plus'"><path d="M12 5v14M5 12h14" /></template>
    <template v-else-if="name === 'settings'"><path d="M4 7h5m6 0h5M4 17h2m6 0h8" /><circle cx="12" cy="7" r="2" /><circle cx="9" cy="17" r="2" /></template>
    <template v-else-if="name === 'play'"><path d="m8 5 11 7-11 7z" /></template>
    <template v-else-if="name === 'export'"><path d="M12 15V3m0 0L8 7m4-4 4 4" /><path d="M5 12v8h14v-8" /></template>
    <template v-else-if="name === 'back'"><path d="m14.5 5-7 7 7 7" /><path d="M8 12h12" /></template>
    <template v-else-if="name === 'model'"><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9z" /><path d="m4.5 7.7 7.5 4.2 7.5-4.2M12 12v8.5" /></template>
  </svg>
</template>
