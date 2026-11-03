<template>
  <div class="min-h-full bg-slate-50 flex flex-col">
    <AdminNav />

    <main class="flex-1 max-w-7xl w-full mx-auto p-6 md:p-8 space-y-6">
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 class="text-xl font-bold text-slate-900 tracking-tight">Audit Log</h1>
          <p class="text-xs text-slate-500 mt-1">Immutable audit trail of all administrative actions, destructive operations, and AI gate mutations.</p>
        </div>

        <div class="flex items-center space-x-3">
          <select
            v-model="actionFilter"
            @change="fetchAuditLogs"
            class="px-3 py-1.5 text-xs rounded-lg border border-slate-200 bg-white focus:outline-hidden focus:ring-2 focus:ring-indigo-500 shadow-2xs"
          >
            <option value="">All Action Types</option>
            <option value="user_suspend">User Suspend</option>
            <option value="user_unsuspend">User Unsuspend</option>
            <option value="user_delete">User Delete (Purge)</option>
            <option value="document_delete">Document Delete (Cascade)</option>
            <option value="concept_merge">Concept Merge</option>
            <option value="proposition_retract">Proposition Retract</option>
            <option value="ai_gate_pause">AI Gate Pause</option>
            <option value="ai_gate_resume">AI Gate Resume</option>
            <option value="ai_circuit_reset">AI Circuit Reset</option>
            <option value="pipeline_retry">Pipeline Retry</option>
          </select>
          <button
            @click="fetchAuditLogs"
            class="px-3 py-1.5 text-xs font-medium rounded-md bg-white border border-slate-200 text-slate-700 hover:bg-slate-50 shadow-2xs"
          >
            Refresh
          </button>
        </div>
      </div>

      <!-- Audit Logs Table -->
      <div class="bg-white rounded-xl border border-slate-200/80 shadow-2xs overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full text-left text-xs">
            <thead class="bg-slate-50/80 border-b border-slate-200/60 text-slate-500 font-medium">
              <tr>
                <th class="px-4 py-3">Timestamp</th>
                <th class="px-4 py-3">Action Type</th>
                <th class="px-4 py-3">Target</th>
                <th class="px-4 py-3">Target User</th>
                <th class="px-4 py-3">Reason / Details</th>
                <th class="px-4 py-3 text-right">State</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 font-mono text-2xs">
              <tr v-if="logs.length === 0" class="text-center text-slate-400 py-8">
                <td colspan="6" class="py-8 font-sans">No audit logs recorded matching filter.</td>
              </tr>
              <tr v-for="l in logs" :key="l.id" class="hover:bg-slate-50/50 transition-colors">
                <td class="px-4 py-3 text-slate-500 whitespace-nowrap">
                  {{ formatDate(l.created_at) }}
                </td>
                <td class="px-4 py-3">
                  <span class="px-2 py-0.5 rounded text-3xs font-bold uppercase tracking-wider" :class="actionBadgeClass(l.action_type)">
                    {{ l.action_type }}
                  </span>
                </td>
                <td class="px-4 py-3 text-slate-800">
                  <span class="capitalize text-slate-500">{{ l.target_type }}: </span>
                  <span v-if="l.target_id" class="text-slate-900 font-semibold">{{ l.target_id.slice(0, 8) }}</span>
                  <span v-else class="text-slate-400">&mdash;</span>
                </td>
                <td class="px-4 py-3 text-slate-600 truncate max-w-[140px]" :title="l.target_email || l.target_user_id">
                  {{ l.target_email || (l.target_user_id ? l.target_user_id.slice(0, 8) : '&mdash;') }}
                </td>
                <td class="px-4 py-3 font-sans text-xs text-slate-700 max-w-xs truncate" :title="l.reason">
                  {{ l.reason || '&mdash;' }}
                </td>
                <td class="px-4 py-3 text-right">
                  <button
                    v-if="l.before_state || l.after_state"
                    @click="inspectState(l)"
                    class="px-2 py-1 rounded bg-slate-100 text-slate-700 hover:bg-slate-200 text-3xs font-semibold"
                  >
                    View Diff
                  </button>
                  <span v-else class="text-slate-300">&mdash;</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- State Inspector Modal -->
      <div v-if="inspectTarget" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
        <div class="bg-white rounded-xl shadow-xl max-w-xl w-full p-6 space-y-4">
          <div class="flex items-center justify-between pb-2 border-b border-slate-100">
            <div>
              <h3 class="text-sm font-bold text-slate-900 uppercase tracking-wider font-mono">{{ inspectTarget.action_type }}</h3>
              <p class="text-2xs text-slate-400 font-mono mt-0.5">{{ inspectTarget.id }}</p>
            </div>
            <button @click="inspectTarget = null" class="text-slate-400 hover:text-slate-600 text-lg leading-none">&times;</button>
          </div>

          <div class="space-y-3 text-xs">
            <div v-if="inspectTarget.before_state">
              <span class="font-semibold text-slate-600 text-2xs uppercase block mb-1">Before State</span>
              <pre class="p-3 bg-slate-50 border border-slate-200 rounded-lg text-2xs font-mono text-slate-800 overflow-x-auto">{{ JSON.stringify(inspectTarget.before_state, null, 2) }}</pre>
            </div>

            <div v-if="inspectTarget.after_state">
              <span class="font-semibold text-slate-600 text-2xs uppercase block mb-1">After State</span>
              <pre class="p-3 bg-slate-50 border border-slate-200 rounded-lg text-2xs font-mono text-slate-800 overflow-x-auto">{{ JSON.stringify(inspectTarget.after_state, null, 2) }}</pre>
            </div>
          </div>

          <div class="pt-2 flex justify-end">
            <button @click="inspectTarget = null" class="px-4 py-1.5 text-xs rounded-lg bg-slate-100 text-slate-700 hover:bg-slate-200 font-medium">
              Close
            </button>
          </div>
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

const actionFilter = ref('')
const logs = ref<any[]>([])
const inspectTarget = ref<any>(null)

const formatDate = (isoStr: string) => {
  if (!isoStr) return ''
  const d = new Date(isoStr)
  return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

const actionBadgeClass = (action: string) => {
  if (action.includes('delete') || action.includes('retract')) {
    return 'bg-rose-50 text-rose-700'
  }
  if (action.includes('suspend') || action.includes('pause')) {
    return 'bg-amber-50 text-amber-700'
  }
  if (action.includes('resume') || action.includes('restore') || action.includes('reset')) {
    return 'bg-emerald-50 text-emerald-700'
  }
  return 'bg-indigo-50 text-indigo-700'
}

const fetchAuditLogs = async () => {
  try {
    const params = new URLSearchParams()
    if (actionFilter.value) params.set('action_type', actionFilter.value)
    const res = await $fetch<any>(`/api/admin/audit?${params.toString()}`)
    logs.value = res.audit_logs || []
  } catch (err) {
    console.error('Failed to load audit logs:', err)
  }
}

const inspectState = (l: any) => {
  inspectTarget.value = l
}

onMounted(() => {
  fetchAuditLogs()
})
</script>
