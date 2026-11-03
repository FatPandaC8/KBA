<template>
  <div class="min-h-full bg-slate-50 flex flex-col">
    <AdminNav />

    <main class="flex-1 max-w-7xl w-full mx-auto p-6 md:p-8 space-y-6">
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 class="text-xl font-bold text-slate-900 tracking-tight">Pipeline & Queue Management</h1>
          <p class="text-xs text-slate-500 mt-1">Monitor background processing stages, backpressure, and retry failed ingestion jobs.</p>
        </div>
        <div class="flex items-center space-x-3">
          <button
            @click="fetchPipeline"
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

      <!-- Stage Filters -->
      <div class="flex items-center space-x-2 overflow-x-auto pb-1 scrollbar-none">
        <button
          v-for="st in stages"
          :key="st.key"
          @click="selectStage(st.key)"
          class="px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors flex items-center space-x-1.5"
          :class="selectedStage === st.key
            ? 'bg-indigo-600 text-white border-indigo-600 shadow-2xs'
            : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'"
        >
          <span>{{ st.label }}</span>
          <span v-if="getStageCount(st.key) !== null" class="px-1.5 py-0.2 rounded-full text-3xs font-mono" :class="selectedStage === st.key ? 'bg-indigo-700 text-indigo-100' : 'bg-slate-100 text-slate-600'">
            {{ getStageCount(st.key) }}
          </span>
        </button>
      </div>

      <!-- Jobs Table -->
      <div class="bg-white rounded-xl border border-slate-200/80 shadow-2xs overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full text-left text-xs">
            <thead class="bg-slate-50/80 border-b border-slate-200/60 text-slate-500 font-medium">
              <tr>
                <th class="px-4 py-3">Job ID</th>
                <th class="px-4 py-3">Document</th>
                <th class="px-4 py-3">User</th>
                <th class="px-4 py-3">Stage</th>
                <th class="px-4 py-3">Attempts</th>
                <th class="px-4 py-3">Created / Updated</th>
                <th class="px-4 py-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100">
              <tr v-if="jobs.length === 0" class="text-center text-slate-400 py-8">
                <td colspan="7" class="py-8">No jobs found matching the selected stage filter.</td>
              </tr>
              <tr v-for="job in jobs" :key="job.id" class="hover:bg-slate-50/50 transition-colors">
                <td class="px-4 py-3 font-mono text-slate-500 truncate max-w-[120px]" :title="job.id">
                  {{ job.id.slice(0, 8) }}...
                </td>
                <td class="px-4 py-3">
                  <span class="font-medium text-slate-900 block truncate max-w-[200px]" :title="job.document_title || 'Untitled'">
                    {{ job.document_title || 'Untitled' }}
                  </span>
                  <span class="text-2xs text-slate-400 font-mono">{{ job.document_id.slice(0, 8) }}</span>
                </td>
                <td class="px-4 py-3 text-slate-600 truncate max-w-[160px]" :title="job.user_email">
                  {{ job.user_email }}
                </td>
                <td class="px-4 py-3">
                  <span class="px-2 py-0.5 rounded-full text-2xs font-semibold capitalize inline-flex items-center space-x-1" :class="stageBadgeClass(job.stage)">
                    <span class="w-1.5 h-1.5 rounded-full" :class="stageDotClass(job.stage)"></span>
                    <span>{{ job.stage }}</span>
                  </span>
                  <span v-if="job.last_error" class="block text-3xs text-rose-600 mt-0.5 truncate max-w-[220px]" :title="job.last_error">
                    {{ job.last_error }}
                  </span>
                </td>
                <td class="px-4 py-3 font-mono text-slate-600">
                  {{ job.attempts }} / {{ job.max_attempts }}
                </td>
                <td class="px-4 py-3 text-2xs text-slate-500">
                  <span>{{ formatDate(job.created_at) }}</span>
                </td>
                <td class="px-4 py-3 text-right">
                  <button
                    v-if="job.stage === 'failed'"
                    @click="retryJob(job.id)"
                    class="px-2.5 py-1 rounded text-2xs font-medium bg-indigo-50 text-indigo-700 hover:bg-indigo-100 transition-colors"
                  >
                    Retry
                  </button>
                  <span v-else class="text-2xs text-slate-300">&mdash;</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

definePageMeta({
  middleware: 'admin'
})

const loading = ref(false)
const selectedStage = ref('')
const metrics = ref<any>({})
const jobs = ref<any[]>([])
const total = ref(0)

const stages = [
  { key: '', label: 'All Jobs' },
  { key: 'queued', label: 'Queued' },
  { key: 'chunking', label: 'Chunking' },
  { key: 'extracting', label: 'Extracting' },
  { key: 'integrating', label: 'Integrating' },
  { key: 'waiting_for_ai', label: 'Waiting for AI' },
  { key: 'failed', label: 'Failed' },
  { key: 'completed', label: 'Completed' }
]

const getStageCount = (key: string) => {
  if (!key) return null
  return metrics.value?.stages?.[key] ?? 0
}

const selectStage = (key: string) => {
  selectedStage.value = key
  fetchPipeline()
}

const stageBadgeClass = (stage: string) => {
  switch (stage) {
    case 'completed': return 'bg-emerald-50 text-emerald-700'
    case 'failed': return 'bg-rose-50 text-rose-700'
    case 'waiting_for_ai': return 'bg-amber-50 text-amber-700'
    case 'extracting':
    case 'integrating': return 'bg-indigo-50 text-indigo-700'
    default: return 'bg-slate-100 text-slate-700'
  }
}

const stageDotClass = (stage: string) => {
  switch (stage) {
    case 'completed': return 'bg-emerald-500'
    case 'failed': return 'bg-rose-500'
    case 'waiting_for_ai': return 'bg-amber-500'
    case 'extracting':
    case 'integrating': return 'bg-indigo-500 animate-pulse'
    default: return 'bg-slate-400'
  }
}

const formatDate = (isoStr: string) => {
  if (!isoStr) return ''
  const d = new Date(isoStr)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

const fetchPipeline = async () => {
  loading.value = true
  try {
    const url = selectedStage.value
      ? `/api/admin/pipeline?stage=${selectedStage.value}`
      : '/api/admin/pipeline'
    const res = await $fetch<any>(url)
    metrics.value = res.metrics || {}
    jobs.value = res.jobs || []
    total.value = res.total || 0
  } catch (err) {
    console.error('Failed to load pipeline jobs:', err)
  } finally {
    loading.value = false
  }
}

const retryJob = async (jobID: string) => {
  try {
    await $fetch(`/api/admin/pipeline/jobs/${jobID}/retry`, { method: 'POST' })
    await fetchPipeline()
  } catch (err: any) {
    alert('Failed to retry job: ' + (err?.data?.error?.message || err.message))
  }
}

onMounted(() => {
  fetchPipeline()
})
</script>
