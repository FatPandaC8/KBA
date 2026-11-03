<template>
  <header class="border-b border-hairline bg-white/80 backdrop-blur-md sticky top-0 z-20">
    <!-- Top Bar -->
    <div class="max-w-7xl mx-auto px-6 h-14 flex items-center justify-between">
      <div class="flex items-center space-x-3">
        <div class="w-8 h-8 rounded-lg bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/>
          </svg>
        </div>
        <div>
          <span class="text-sm font-semibold tracking-tight text-ink-900">Admin Console</span>
          <span class="ml-2 text-2xs px-1.5 py-0.5 rounded bg-ink-100 text-ink-600 font-mono">v1.1</span>
        </div>
      </div>

      <!-- Quick Status Badges -->
      <div class="flex items-center space-x-3 text-xs">
        <NuxtLink
          to="/admin/ai"
          class="flex items-center space-x-1.5 px-2.5 py-1 rounded-full border transition-colors"
          :class="gateBadgeClass"
        >
          <span class="w-1.5 h-1.5 rounded-full" :class="gateDotClass"></span>
          <span class="font-medium capitalize">{{ gateState }}</span>
        </NuxtLink>

        <NuxtLink
          to="/"
          class="text-xs text-ink-500 hover:text-ink-900 transition-colors flex items-center space-x-1 pl-2 border-l border-hairline"
        >
          <span>Knowledge Space</span>
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
          </svg>
        </NuxtLink>
      </div>
    </div>

    <!-- Navigation Tabs -->
    <div class="max-w-7xl mx-auto px-6 flex space-x-1 overflow-x-auto scrollbar-none">
      <NuxtLink
        v-for="tab in tabs"
        :key="tab.path"
        :to="tab.path"
        class="px-3.5 py-2.5 text-xs font-medium border-b-2 transition-colors whitespace-nowrap flex items-center space-x-1.5"
        :class="isActive(tab.path)
          ? 'border-indigo-600 text-indigo-600 font-semibold'
          : 'border-transparent text-ink-500 hover:text-ink-900 hover:border-ink-200'"
      >
        <span>{{ tab.label }}</span>
        <span v-if="tab.badge" class="px-1.5 py-0.2 rounded-full text-3xs font-mono bg-ink-100 text-ink-600">
          {{ tab.badge }}
        </span>
      </NuxtLink>
    </div>
  </header>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const gateState = ref('Checking...')

const tabs = [
  { label: 'Overview', path: '/admin' },
  { label: 'Pipeline & Queue', path: '/admin/pipeline' },
  { label: 'AI Observability', path: '/admin/ai' },
  { label: 'Users', path: '/admin/users' },
  { label: 'Documents', path: '/admin/documents' },
  { label: 'Graph Data', path: '/admin/graph' },
  { label: 'Audit Log', path: '/admin/audit' }
]

const isActive = (path: string) => {
  if (path === '/admin') {
    return route.path === '/admin'
  }
  return route.path.startsWith(path)
}

const gateBadgeClass = computed(() => {
  if (gateState.value === 'enabled' || gateState.value === 'healthy') {
    return 'bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100/60'
  }
  if (gateState.value === 'paused') {
    return 'bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100/60'
  }
  if (gateState.value === 'circuit_open' || gateState.value === 'down') {
    return 'bg-rose-50 text-rose-700 border-rose-200 hover:bg-rose-100/60'
  }
  return 'bg-slate-50 text-slate-600 border-slate-200'
})

const gateDotClass = computed(() => {
  if (gateState.value === 'enabled' || gateState.value === 'healthy') return 'bg-emerald-500'
  if (gateState.value === 'paused') return 'bg-amber-500'
  if (gateState.value === 'circuit_open' || gateState.value === 'down') return 'bg-rose-500 animate-pulse'
  return 'bg-slate-400'
})

onMounted(async () => {
  try {
    const res = await $fetch<{ state: string }>('/api/admin/ai/gate')
    gateState.value = res.state || 'enabled'
  } catch (err) {
    gateState.value = 'unknown'
  }
})
</script>
