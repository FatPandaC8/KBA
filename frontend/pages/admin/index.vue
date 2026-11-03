<template>
  <div class="min-h-full bg-slate-50 flex flex-col">
    <AdminNav />

    <main class="flex-1 max-w-7xl w-full mx-auto p-6 md:p-8 space-y-8">
      <!-- Welcome & System Header -->
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 class="text-xl font-bold text-slate-900 tracking-tight">System Overview</h1>
          <p class="text-xs text-slate-500 mt-1">Real-time telemetry, pipeline throughput, and knowledge graph health metrics.</p>
        </div>
        <div class="flex items-center space-x-3">
          <button
            @click="fetchOverview"
            :disabled="loading"
            class="px-3 py-1.5 text-xs font-medium rounded-md bg-white border border-slate-200 text-slate-700 hover:bg-slate-50 shadow-2xs flex items-center space-x-1.5 disabled:opacity-60 transition-all"
          >
            <svg class="w-3.5 h-3.5" :class="{ 'animate-spin': loading }" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            <span>Refresh</span>
          </button>
        </div>
      </div>

      <!-- Key Metrics 4-Col Grid -->
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <!-- Users Card -->
        <div class="p-5 bg-white rounded-xl border border-slate-200/80 shadow-2xs">
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium text-slate-500">Total Users</span>
            <span class="p-2 rounded-lg bg-indigo-50 text-indigo-600">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"/>
              </svg>
            </span>
          </div>
          <div class="mt-4 flex items-baseline space-x-2">
            <span class="text-2xl font-bold tracking-tight text-slate-900">{{ metrics.users?.total ?? 0 }}</span>
            <span class="text-xs text-emerald-600 font-medium">{{ metrics.users?.active ?? 0 }} active</span>
          </div>
          <p class="text-2xs text-slate-400 mt-1">{{ metrics.users?.suspended ?? 0 }} suspended accounts</p>
        </div>

        <!-- Documents Card -->
        <div class="p-5 bg-white rounded-xl border border-slate-200/80 shadow-2xs">
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium text-slate-500">Ingested Documents</span>
            <span class="p-2 rounded-lg bg-blue-50 text-blue-600">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
              </svg>
            </span>
          </div>
          <div class="mt-4 flex items-baseline space-x-2">
            <span class="text-2xl font-bold tracking-tight text-slate-900">{{ metrics.documents?.total ?? 0 }}</span>
            <span class="text-xs text-slate-500 font-medium">{{ metrics.documents?.completed ?? 0 }} completed</span>
          </div>
          <p class="text-2xs text-slate-400 mt-1">{{ metrics.documents?.failed ?? 0 }} ingestion failures</p>
        </div>

        <!-- Processing Queue Card -->
        <div class="p-5 bg-white rounded-xl border border-slate-200/80 shadow-2xs">
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium text-slate-500">Queue Depth</span>
            <span class="p-2 rounded-lg bg-amber-50 text-amber-600">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/>
              </svg>
            </span>
          </div>
          <div class="mt-4 flex items-baseline space-x-2">
            <span class="text-2xl font-bold tracking-tight text-slate-900">{{ metrics.queue?.queued ?? 0 }}</span>
            <span class="text-xs text-amber-600 font-medium">{{ metrics.queue?.processing ?? 0 }} active</span>
          </div>
          <p class="text-2xs text-slate-400 mt-1">{{ metrics.queue?.waiting_for_ai ?? 0 }} paused / waiting for AI</p>
        </div>

        <!-- Knowledge Graph Card -->
        <div class="p-5 bg-white rounded-xl border border-slate-200/80 shadow-2xs">
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium text-slate-500">Knowledge Graph</span>
            <span class="p-2 rounded-lg bg-emerald-50 text-emerald-600">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="3" stroke-width="1.8"/>
                <circle cx="6" cy="6" r="2" stroke-width="1.8"/>
                <circle cx="18" cy="7" r="2" stroke-width="1.8"/>
                <circle cx="16" cy="18" r="2" stroke-width="1.8"/>
                <circle cx="6" cy="16" r="2" stroke-width="1.8"/>
              </svg>
            </span>
          </div>
          <div class="mt-4 flex items-baseline space-x-2">
            <span class="text-2xl font-bold tracking-tight text-slate-900">{{ metrics.graph?.propositions ?? 0 }}</span>
            <span class="text-xs text-slate-500 font-medium">props</span>
          </div>
          <p class="text-2xs text-slate-400 mt-1">{{ metrics.graph?.concepts ?? 0 }} concepts &middot; {{ metrics.graph?.conflicts ?? 0 }} conflicts</p>
        </div>
      </div>

      <!-- Middle 2-Column Section: Component Health & Gate Telemetry -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- AI Health Card -->
        <div class="bg-white rounded-xl border border-slate-200/80 p-6 shadow-2xs space-y-4">
          <div class="flex items-center justify-between">
            <h2 class="text-sm font-semibold text-slate-900">AI Component Status</h2>
            <NuxtLink to="/admin/ai" class="text-xs text-indigo-600 hover:text-indigo-800 font-medium">Manage AI &rarr;</NuxtLink>
          </div>

          <div class="p-4 rounded-lg bg-slate-50 border border-slate-200/60 flex items-center justify-between">
            <div class="flex items-center space-x-3">
              <div class="w-3 h-3 rounded-full" :class="aiGate?.state === 'enabled' ? 'bg-emerald-500' : (aiGate?.state === 'paused' ? 'bg-amber-500' : 'bg-rose-500 animate-pulse')"></div>
              <div>
                <span class="text-xs font-semibold text-slate-900 capitalize">{{ aiGate?.state || 'enabled' }} Gate</span>
                <p class="text-2xs text-slate-500 mt-0.5">{{ aiGate?.reason || 'Operating normally' }}</p>
              </div>
            </div>
            <span class="text-2xs px-2 py-0.5 rounded font-mono bg-white border border-slate-200 text-slate-600">
              {{ aiGate?.consecutive_failures ?? 0 }} failures
            </span>
          </div>

          <div class="grid grid-cols-2 gap-4 text-xs">
            <div class="p-3 rounded-lg border border-slate-100 bg-white">
              <span class="text-slate-400 text-2xs block">Provider & Model</span>
              <span class="font-medium text-slate-800 mt-0.5 block truncate">{{ aiProvider?.kind }} / {{ aiProvider?.model }}</span>
            </div>
            <div class="p-3 rounded-lg border border-slate-100 bg-white">
              <span class="text-slate-400 text-2xs block">Configured</span>
              <span class="font-medium text-slate-800 mt-0.5 block">{{ aiProvider?.is_configured ? 'Active Key' : 'Unconfigured' }}</span>
            </div>
          </div>
        </div>

        <!-- Pipeline Health Card -->
        <div class="bg-white rounded-xl border border-slate-200/80 p-6 shadow-2xs space-y-4">
          <div class="flex items-center justify-between">
            <h2 class="text-sm font-semibold text-slate-900">Pipeline Stages</h2>
            <NuxtLink to="/admin/pipeline" class="text-xs text-indigo-600 hover:text-indigo-800 font-medium">View Queue &rarr;</NuxtLink>
          </div>

          <div class="space-y-2.5">
            <div v-for="st in stageList" :key="st.key" class="flex items-center justify-between text-xs">
              <span class="text-slate-600 font-medium capitalize">{{ st.label }}</span>
              <span class="font-mono px-2 py-0.5 rounded text-2xs bg-slate-100 text-slate-700 font-semibold">
                {{ st.count }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

definePageMeta({
  middleware: 'admin'
})

const loading = ref(false)
const metrics = ref<any>({})
const aiProvider = ref<any>({})
const aiGate = ref<any>({})

const stageList = computed(() => [
  { key: 'queued', label: 'Queued (Ready)', count: metrics.value.queue?.queued ?? 0 },
  { key: 'chunking', label: 'Chunking Text', count: metrics.value.queue?.chunking ?? 0 },
  { key: 'extracting', label: 'Extracting (AI)', count: metrics.value.queue?.extracting ?? 0 },
  { key: 'integrating', label: 'Graph Integration', count: metrics.value.queue?.integrating ?? 0 },
  { key: 'waiting_for_ai', label: 'Waiting for AI Gate', count: metrics.value.queue?.waiting_for_ai ?? 0 },
  { key: 'failed', label: 'Failed Jobs', count: metrics.value.queue?.failed ?? 0 }
])

const fetchOverview = async () => {
  loading.value = true
  try {
    const res = await $fetch<any>('/api/admin/overview')
    metrics.value = res.metrics || {}
    aiProvider.value = res.ai_provider || {}
    aiGate.value = res.ai_gate || {}
  } catch (err) {
    console.error('Failed to load admin overview:', err)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchOverview()
})
</script>
