<template>
  <div class="min-h-full bg-slate-50 flex flex-col">
    <AdminNav />

    <main class="flex-1 max-w-7xl w-full mx-auto p-6 md:p-8 space-y-6">
      <!-- Header with Active Probe Button -->
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 class="text-xl font-bold text-slate-900 tracking-tight">AI Health & Observability</h1>
          <p class="text-xs text-slate-500 mt-1">Deep telemetry, circuit breaker controls, real-time probe verification, and quality signals.</p>
        </div>
        <div class="flex items-center space-x-3">
          <button
            @click="runProbe"
            :disabled="probing"
            class="px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 shadow-2xs flex items-center space-x-1.5 disabled:opacity-60 transition-all"
          >
            <svg class="w-3.5 h-3.5" :class="{ 'animate-spin': probing }" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            <span>Run Active Probe</span>
          </button>
        </div>
      </div>

      <!-- Top Section: AI Gate & Circuit Breaker Control Card -->
      <div class="p-6 bg-white rounded-xl border border-slate-200/80 shadow-2xs space-y-5">
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div class="flex items-center space-x-3">
            <span class="w-3 h-3 rounded-full" :class="gateDotClass"></span>
            <div>
              <div class="flex items-center space-x-2">
                <span class="text-sm font-bold text-slate-900 capitalize">{{ health?.gate?.state || 'enabled' }}</span>
                <span class="text-2xs font-mono px-2 py-0.5 rounded" :class="gateBadgeClass">
                  {{ health?.gate?.consecutive_failures ?? 0 }} consecutive failures
                </span>
              </div>
              <p class="text-xs text-slate-500 mt-0.5">{{ health?.gate?.reason || 'Circuit breaker operating normally' }}</p>
            </div>
          </div>

          <!-- Gate Action Buttons -->
          <div class="flex items-center space-x-2">
            <button
              v-if="health?.gate?.state !== 'paused'"
              @click="pauseGate"
              class="px-3 py-1.5 rounded-lg text-xs font-medium border border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100 transition-colors"
            >
              Pause AI Gate
            </button>
            <button
              v-if="health?.gate?.state === 'paused'"
              @click="resumeGate"
              class="px-3 py-1.5 rounded-lg text-xs font-medium border border-emerald-300 bg-emerald-50 text-emerald-800 hover:bg-emerald-100 transition-colors"
            >
              Resume AI Gate
            </button>
            <button
              @click="resetBreaker"
              class="px-3 py-1.5 rounded-lg text-xs font-medium border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 transition-colors"
            >
              Reset Breaker
            </button>
          </div>
        </div>

        <!-- Last Active Probe Inline Result (if run) -->
        <div v-if="lastProbe" class="p-4 rounded-lg border text-xs" :class="lastProbe.status === 'success' ? 'bg-emerald-50/60 border-emerald-200 text-emerald-900' : 'bg-rose-50/60 border-rose-200 text-rose-900'">
          <div class="flex items-center justify-between">
            <span class="font-semibold flex items-center space-x-1.5">
              <span>Health Probe:</span>
              <span class="uppercase tracking-wider text-2xs px-1.5 py-0.2 rounded" :class="lastProbe.status === 'success' ? 'bg-emerald-200 text-emerald-800' : 'bg-rose-200 text-rose-800'">
                {{ lastProbe.status }}
              </span>
            </span>
            <span class="font-mono text-2xs text-slate-500">{{ lastProbe.probe_timestamp }}</span>
          </div>
          <div class="mt-2 flex items-center space-x-4 font-mono text-2xs">
            <span>Latency: <strong>{{ lastProbe.latency_ms }}ms</strong></span>
            <span>HTTP Status: <strong>{{ lastProbe.http_status }}</strong></span>
            <span>Tokens: <strong>{{ lastProbe.tokens_consumed }}</strong></span>
          </div>
          <p v-if="lastProbe.error" class="text-rose-700 mt-1 font-mono text-3xs">{{ lastProbe.error }}</p>
        </div>
      </div>

      <!-- 2-Col Grid: Telemetry & Provider Contract -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <!-- Provider Contract & Details (1 Col) -->
        <div class="bg-white rounded-xl border border-slate-200/80 p-6 shadow-2xs space-y-4">
          <h2 class="text-sm font-semibold text-slate-900">Provider Contract</h2>
          <div class="space-y-3 text-xs">
            <div class="flex justify-between py-1 border-b border-slate-100">
              <span class="text-slate-500">Provider Kind</span>
              <span class="font-mono font-medium text-slate-900 uppercase">{{ health?.provider?.kind }}</span>
            </div>
            <div class="flex justify-between py-1 border-b border-slate-100">
              <span class="text-slate-500">Model Name</span>
              <span class="font-mono font-medium text-slate-900 truncate max-w-[150px]" :title="health?.provider?.model">{{ health?.provider?.model }}</span>
            </div>
            <div class="flex justify-between py-1 border-b border-slate-100">
              <span class="text-slate-500">Configured Limits</span>
              <span class="font-mono text-slate-700">{{ health?.provider?.rpm_limit }} RPM / {{ health?.provider?.tpm_limit }} TPM</span>
            </div>
            <div class="flex justify-between py-1 border-b border-slate-100">
              <span class="text-slate-500">Capabilities</span>
              <span class="font-mono text-2xs text-slate-700">{{ health?.provider?.capabilities?.join(', ') }}</span>
            </div>
            <div class="flex justify-between py-1">
              <span class="text-slate-500">Health Latency</span>
              <span class="font-mono font-bold text-slate-900">{{ health?.latency_ms ?? 0 }}ms</span>
            </div>
          </div>
        </div>

        <!-- Observability Signals & Window Selector (2 Cols) -->
        <div class="lg:col-span-2 bg-white rounded-xl border border-slate-200/80 p-6 shadow-2xs space-y-5">
          <div class="flex items-center justify-between">
            <h2 class="text-sm font-semibold text-slate-900">Performance & Error Distribution</h2>
            <div class="flex items-center space-x-1 border border-slate-200 rounded-lg p-0.5 bg-slate-50 text-xs">
              <button
                v-for="w in ['1h', '24h', '7d']"
                :key="w"
                @click="setWindow(w)"
                class="px-2.5 py-1 rounded text-2xs font-medium transition-colors"
                :class="selectedWindow === w ? 'bg-white shadow-2xs font-semibold text-slate-900' : 'text-slate-500 hover:text-slate-800'"
              >
                {{ w }}
              </button>
            </div>
          </div>

          <!-- Signal Metrics 3-Col -->
          <div class="grid grid-cols-3 gap-4 text-center">
            <div class="p-3 bg-slate-50 rounded-lg">
              <span class="text-2xs text-slate-500 block">Total AI Calls</span>
              <span class="text-xl font-bold text-slate-900 mt-1 block">{{ metrics?.total_calls ?? 0 }}</span>
            </div>
            <div class="p-3 bg-slate-50 rounded-lg">
              <span class="text-2xs text-slate-500 block">Avg Latency</span>
              <span class="text-xl font-bold text-indigo-600 mt-1 block">{{ metrics?.avg_latency_ms ?? 0 }}ms</span>
            </div>
            <div class="p-3 bg-slate-50 rounded-lg">
              <span class="text-2xs text-slate-500 block">Total Tokens</span>
              <span class="text-xl font-bold text-slate-900 mt-1 block">{{ ((metrics?.total_tokens ?? 0) / 1000).toFixed(1) }}k</span>
            </div>
          </div>

          <!-- Inline SVG Sparkline for Latency Simulation -->
          <div class="p-4 rounded-lg bg-slate-50/70 border border-slate-100">
            <div class="flex justify-between text-2xs text-slate-400 mb-2">
              <span>Latency Distribution</span>
              <span class="font-mono">P95: {{ metrics?.p95_latency_ms ?? metrics?.avg_latency_ms ?? 0 }}ms</span>
            </div>
            <svg class="w-full h-16 overflow-visible" viewBox="0 0 300 50">
              <defs>
                <linearGradient id="latencyGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="#6366f1" stop-opacity="0.3" />
                  <stop offset="100%" stop-color="#6366f1" stop-opacity="0.0" />
                </linearGradient>
              </defs>
              <path
                d="M 0,35 Q 30,10 60,25 T 120,20 T 180,30 T 240,15 T 300,22 L 300,50 L 0,50 Z"
                fill="url(#latencyGrad)"
              />
              <path
                d="M 0,35 Q 30,10 60,25 T 120,20 T 180,30 T 240,15 T 300,22"
                fill="none"
                stroke="#6366f1"
                stroke-width="2"
              />
            </svg>
          </div>

          <!-- Error Class Breakdown -->
          <div class="text-xs">
            <span class="font-medium text-slate-700 block mb-2">Error Classes</span>
            <div v-if="!metrics?.error_breakdown || Object.keys(metrics.error_breakdown).length === 0" class="text-slate-400 text-2xs py-2">
              No errors recorded in the selected window.
            </div>
            <div v-else class="space-y-1.5">
              <div v-for="(count, errClass) in metrics.error_breakdown" :key="errClass" class="flex justify-between items-center text-2xs py-1 px-2 rounded bg-slate-50">
                <span class="font-mono text-slate-700">{{ errClass }}</span>
                <span class="font-bold text-rose-600">{{ count }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Evaluation Runs Benchmark Section -->
      <div class="bg-white rounded-xl border border-slate-200/80 p-6 shadow-2xs space-y-4">
        <div class="flex items-center justify-between">
          <div>
            <h2 class="text-sm font-semibold text-slate-900">Benchmark Gold Evaluation Runs</h2>
            <p class="text-2xs text-slate-500">Historical precision, recall, and hallucination scores against curated benchmark datasets.</p>
          </div>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-left text-xs">
            <thead class="bg-slate-50 border-b border-slate-100 text-slate-500 font-medium">
              <tr>
                <th class="px-4 py-2.5">Dataset Version</th>
                <th class="px-4 py-2.5">Model</th>
                <th class="px-4 py-2.5">Precision</th>
                <th class="px-4 py-2.5">Recall</th>
                <th class="px-4 py-2.5">Evidence Validity</th>
                <th class="px-4 py-2.5">Date</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 font-mono text-2xs">
              <tr v-if="evalRuns.length === 0" class="text-center text-slate-400 py-6">
                <td colspan="6" class="py-6">No evaluation benchmark runs logged yet.</td>
              </tr>
              <tr v-for="run in evalRuns" :key="run.id" class="hover:bg-slate-50">
                <td class="px-4 py-2.5 text-slate-900 font-semibold">{{ run.dataset_version }}</td>
                <td class="px-4 py-2.5 text-slate-600">{{ run.model }}</td>
                <td class="px-4 py-2.5 text-emerald-600 font-bold">{{ (run.precision_score * 100).toFixed(1) }}%</td>
                <td class="px-4 py-2.5 text-indigo-600 font-bold">{{ (run.recall_score * 100).toFixed(1) }}%</td>
                <td class="px-4 py-2.5 text-slate-700">{{ (run.evidence_validity_rate * 100).toFixed(1) }}%</td>
                <td class="px-4 py-2.5 text-slate-400">{{ run.created_at?.slice(0, 10) }}</td>
              </tr>
            </tbody>
          </table>
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

const probing = ref(false)
const selectedWindow = ref('24h')
const health = ref<any>({})
const metrics = ref<any>({})
const evalRuns = ref<any[]>([])
const lastProbe = ref<any>(null)

const gateDotClass = computed(() => {
  const st = health.value?.gate?.state
  if (st === 'enabled' || st === 'healthy') return 'bg-emerald-500'
  if (st === 'paused') return 'bg-amber-500'
  return 'bg-rose-500 animate-pulse'
})

const gateBadgeClass = computed(() => {
  const st = health.value?.gate?.state
  if (st === 'enabled' || st === 'healthy') return 'bg-emerald-50 text-emerald-700 border border-emerald-200'
  if (st === 'paused') return 'bg-amber-50 text-amber-700 border border-amber-200'
  return 'bg-rose-50 text-rose-700 border border-rose-200'
})

const setWindow = (w: string) => {
  selectedWindow.value = w
  fetchMetrics()
}

const fetchHealth = async () => {
  try {
    const res = await $fetch<any>('/api/admin/ai/health')
    health.value = res || {}
  } catch (err) {
    console.error('Failed to fetch AI health:', err)
  }
}

const fetchMetrics = async () => {
  try {
    const res = await $fetch<any>(`/api/admin/ai/metrics?window=${selectedWindow.value}`)
    metrics.value = res || {}
  } catch (err) {
    console.error('Failed to fetch AI metrics:', err)
  }
}

const fetchEvalRuns = async () => {
  try {
    const res = await $fetch<any>('/api/admin/ai/eval-runs')
    evalRuns.value = res.eval_runs || []
  } catch (err) {
    console.error('Failed to fetch eval runs:', err)
  }
}

const runProbe = async () => {
  probing.value = true
  try {
    const res = await $fetch<any>('/api/admin/ai/probe', { method: 'POST' })
    lastProbe.value = res
    await fetchHealth()
  } catch (err: any) {
    alert('AI Probe failed: ' + (err?.data?.error?.message || err.message))
  } finally {
    probing.value = false
  }
}

const pauseGate = async () => {
  const reason = prompt('Enter reason for pausing AI processing gate:', 'Maintenance window')
  if (reason === null) return
  try {
    await $fetch('/api/admin/ai/gate/pause', {
      method: 'POST',
      body: { reason }
    })
    await fetchHealth()
  } catch (err: any) {
    alert('Failed to pause gate: ' + (err?.data?.error?.message || err.message))
  }
}

const resumeGate = async () => {
  try {
    await $fetch('/api/admin/ai/gate/resume', { method: 'POST' })
    await fetchHealth()
  } catch (err: any) {
    alert('Failed to resume gate: ' + (err?.data?.error?.message || err.message))
  }
}

const resetBreaker = async () => {
  try {
    await $fetch('/api/admin/ai/gate/reset-breaker', { method: 'POST' })
    await fetchHealth()
  } catch (err: any) {
    alert('Failed to reset breaker: ' + (err?.data?.error?.message || err.message))
  }
}

onMounted(() => {
  fetchHealth()
  fetchMetrics()
  fetchEvalRuns()
})
</script>
