<template>
  <div class="min-h-full bg-slate-50 flex flex-col">
    <AdminNav />

    <main class="flex-1 max-w-7xl w-full mx-auto p-6 md:p-8 space-y-6">
      <!-- Header with User Selector -->
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 class="text-xl font-bold text-slate-900 tracking-tight">Graph Data Administration</h1>
          <p class="text-xs text-slate-500 mt-1">Form and table-based graph management strictly preserving deterministic evidence rules.</p>
        </div>

        <div class="flex items-center space-x-3">
          <label class="text-xs font-semibold text-slate-600">Scope to User:</label>
          <select
            v-model="selectedUserID"
            @change="onUserChanged"
            class="px-3 py-1.5 text-xs rounded-lg border border-slate-300 bg-white font-medium focus:ring-2 focus:ring-indigo-500 shadow-2xs"
          >
            <option v-for="u in userOptions" :key="u.id" :value="u.id">
              {{ u.email }}
            </option>
          </select>
        </div>
      </div>

      <!-- Graph Sub-tabs -->
      <div class="flex items-center space-x-2 border-b border-slate-200 pb-2">
        <button
          v-for="t in ['concepts', 'propositions', 'topics', 'conflicts']"
          :key="t"
          @click="activeSubtab = t"
          class="px-3.5 py-1.5 rounded-lg text-xs font-semibold capitalize transition-colors"
          :class="activeSubtab === t ? 'bg-indigo-600 text-white shadow-2xs' : 'text-slate-600 hover:bg-slate-100'"
        >
          {{ t }}
        </button>

        <div class="flex-1"></div>

        <!-- Add Manual Proposition Button -->
        <button
          v-if="activeSubtab === 'propositions'"
          @click="openManualPropModal"
          class="px-3 py-1.5 text-xs font-semibold rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 shadow-2xs flex items-center space-x-1"
        >
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
          </svg>
          <span>Create Proposition With Evidence</span>
        </button>

        <!-- Merge Concepts Button -->
        <button
          v-if="activeSubtab === 'concepts'"
          @click="openMergeModal"
          class="px-3 py-1.5 text-xs font-semibold rounded-lg bg-indigo-50 text-indigo-700 border border-indigo-200 hover:bg-indigo-100 shadow-2xs"
        >
          Merge Concepts
        </button>
      </div>

      <!-- 1. Concepts Tab -->
      <div v-if="activeSubtab === 'concepts'" class="bg-white rounded-xl border border-slate-200/80 shadow-2xs overflow-hidden">
        <table class="w-full text-left text-xs">
          <thead class="bg-slate-50 border-b border-slate-200 text-slate-500 font-medium">
            <tr>
              <th class="px-4 py-3">Concept Name</th>
              <th class="px-4 py-3">Description</th>
              <th class="px-4 py-3">Status</th>
              <th class="px-4 py-3 text-right">Action</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-if="concepts.length === 0" class="text-center text-slate-400 py-8">
              <td colspan="4" class="py-8">No concepts found for this user.</td>
            </tr>
            <tr v-for="c in concepts" :key="c.id" class="hover:bg-slate-50/50">
              <td class="px-4 py-3 font-semibold text-slate-900">
                <span>{{ c.name }}</span>
                <span class="block font-mono text-3xs text-slate-400">{{ c.id }}</span>
              </td>
              <td class="px-4 py-3 text-slate-600 max-w-xs truncate" :title="c.description">
                {{ c.description || '&mdash;' }}
              </td>
              <td class="px-4 py-3 space-x-1">
                <span v-if="c.is_orphaned" class="px-1.5 py-0.5 rounded text-3xs font-mono bg-amber-50 text-amber-700 font-bold">Orphaned</span>
                <span v-if="c.is_archived" class="px-1.5 py-0.5 rounded text-3xs font-mono bg-slate-100 text-slate-600">Archived</span>
                <span v-if="!c.is_orphaned && !c.is_archived" class="px-1.5 py-0.5 rounded text-3xs font-mono bg-emerald-50 text-emerald-700">Active</span>
              </td>
              <td class="px-4 py-3 text-right space-x-2">
                <button @click="editConcept(c)" class="text-indigo-600 hover:text-indigo-800 font-medium text-2xs">Edit</button>
                <button @click="archiveConcept(c)" class="text-rose-600 hover:text-rose-800 font-medium text-2xs">Archive</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 2. Propositions Tab -->
      <div v-if="activeSubtab === 'propositions'" class="bg-white rounded-xl border border-slate-200/80 shadow-2xs overflow-hidden">
        <table class="w-full text-left text-xs">
          <thead class="bg-slate-50 border-b border-slate-200 text-slate-500 font-medium">
            <tr>
              <th class="px-4 py-3">Subject</th>
              <th class="px-4 py-3">Predicate</th>
              <th class="px-4 py-3">Object</th>
              <th class="px-4 py-3">Status</th>
              <th class="px-4 py-3">Evidence Quote</th>
              <th class="px-4 py-3 text-right">Action</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-if="propositions.length === 0" class="text-center text-slate-400 py-8">
              <td colspan="6" class="py-8">No propositions found for this user.</td>
            </tr>
            <tr v-for="p in propositions" :key="p.id" class="hover:bg-slate-50/50">
              <td class="px-4 py-3 font-semibold text-slate-900">{{ p.subject_name }}</td>
              <td class="px-4 py-3 font-mono text-2xs text-indigo-600 font-bold">{{ p.predicate }}</td>
              <td class="px-4 py-3 font-semibold text-slate-900">{{ p.object_name }}</td>
              <td class="px-4 py-3">
                <span class="px-2 py-0.5 rounded-full text-2xs font-semibold capitalize" :class="p.status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'">
                  {{ p.status }}
                </span>
                <span v-if="p.retracted_reason" class="block text-3xs text-slate-400 truncate max-w-[140px]" :title="p.retracted_reason">
                  {{ p.retracted_reason }}
                </span>
              </td>
              <td class="px-4 py-3 text-slate-600 max-w-xs truncate text-2xs italic font-serif" :title="p.evidence_quote">
                &ldquo;{{ p.evidence_quote || 'No quote' }}&rdquo;
              </td>
              <td class="px-4 py-3 text-right">
                <button
                  v-if="p.status === 'active'"
                  @click="retractProp(p)"
                  class="px-2.5 py-1 rounded text-2xs font-medium text-rose-600 hover:bg-rose-50"
                >
                  Retract
                </button>
                <button
                  v-if="p.status === 'retracted'"
                  @click="restoreProp(p)"
                  class="px-2.5 py-1 rounded text-2xs font-medium text-emerald-600 hover:bg-emerald-50"
                >
                  Restore
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 3. Topics Tab -->
      <div v-if="activeSubtab === 'topics'" class="bg-white rounded-xl border border-slate-200/80 shadow-2xs overflow-hidden">
        <table class="w-full text-left text-xs">
          <thead class="bg-slate-50 border-b border-slate-200 text-slate-500 font-medium">
            <tr>
              <th class="px-4 py-3">Topic Island Name</th>
              <th class="px-4 py-3">Description</th>
              <th class="px-4 py-3">User Locked</th>
              <th class="px-4 py-3 text-right">Action</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-if="topics.length === 0" class="text-center text-slate-400 py-8">
              <td colspan="4" class="py-8">No topic clusters found.</td>
            </tr>
            <tr v-for="t in topics" :key="t.id" class="hover:bg-slate-50/50">
              <td class="px-4 py-3 font-semibold text-slate-900">{{ t.name }}</td>
              <td class="px-4 py-3 text-slate-600">{{ t.description || '&mdash;' }}</td>
              <td class="px-4 py-3">
                <span class="px-2 py-0.5 rounded text-2xs font-mono" :class="t.is_user_locked ? 'bg-amber-50 text-amber-800' : 'bg-slate-100 text-slate-600'">
                  {{ t.is_user_locked ? 'Locked' : 'Auto' }}
                </span>
              </td>
              <td class="px-4 py-3 text-right">
                <button @click="editTopic(t)" class="text-indigo-600 hover:text-indigo-800 font-medium text-2xs">Edit</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 4. Conflicts Tab -->
      <div v-if="activeSubtab === 'conflicts'" class="bg-white rounded-xl border border-slate-200/80 shadow-2xs overflow-hidden">
        <table class="w-full text-left text-xs">
          <thead class="bg-slate-50 border-b border-slate-200 text-slate-500 font-medium">
            <tr>
              <th class="px-4 py-3">Conflict ID</th>
              <th class="px-4 py-3">Canonical Proposition</th>
              <th class="px-4 py-3">Conflicting Proposition</th>
              <th class="px-4 py-3">Status</th>
              <th class="px-4 py-3 text-right">Action</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-if="conflicts.length === 0" class="text-center text-slate-400 py-8">
              <td colspan="5" class="py-8">No open conflicts found.</td>
            </tr>
            <tr v-for="c in conflicts" :key="c.id" class="hover:bg-slate-50/50">
              <td class="px-4 py-3 font-mono text-2xs text-slate-500">{{ c.id.slice(0, 8) }}</td>
              <td class="px-4 py-3 font-semibold text-slate-800">{{ c.canonical_statement }}</td>
              <td class="px-4 py-3 font-semibold text-rose-700">{{ c.conflicting_statement }}</td>
              <td class="px-4 py-3">
                <span class="px-2 py-0.5 rounded-full text-2xs font-semibold capitalize" :class="c.status === 'open' ? 'bg-amber-50 text-amber-700' : 'bg-slate-100 text-slate-600'">
                  {{ c.status }}
                </span>
              </td>
              <td class="px-4 py-3 text-right">
                <button v-if="c.status === 'open'" @click="resolveConflictModal(c)" class="px-2.5 py-1 rounded bg-indigo-50 text-indigo-700 font-medium text-2xs hover:bg-indigo-100">
                  Resolve
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Merge Concepts Modal -->
      <div v-if="showMergeModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
        <div class="bg-white rounded-xl shadow-xl max-w-md w-full p-6 space-y-4">
          <h3 class="text-sm font-bold text-slate-900">Merge Two Concepts</h3>
          <p class="text-xs text-slate-500">Rewires all proposition edges from the source concept to the target concept.</p>

          <div>
            <label class="block text-2xs font-semibold text-slate-700 mb-1">Source Concept (Will be merged away):</label>
            <select v-model="mergeSourceID" class="w-full px-3 py-1.5 text-xs rounded-lg border border-slate-300">
              <option v-for="c in concepts" :key="c.id" :value="c.id">{{ c.name }} ({{ c.id.slice(0, 8) }})</option>
            </select>
          </div>

          <div>
            <label class="block text-2xs font-semibold text-slate-700 mb-1">Target Concept (Preserved canonical):</label>
            <select v-model="mergeTargetID" class="w-full px-3 py-1.5 text-xs rounded-lg border border-slate-300">
              <option v-for="c in concepts" :key="c.id" :value="c.id">{{ c.name }} ({{ c.id.slice(0, 8) }})</option>
            </select>
          </div>

          <div>
            <label class="block text-2xs font-semibold text-slate-700 mb-1">Merge Reason:</label>
            <input v-model="mergeReason" type="text" class="w-full px-3 py-1.5 text-xs rounded-lg border border-slate-300" placeholder="e.g. Synonymous entities" />
          </div>

          <div class="flex justify-end space-x-2 pt-2">
            <button @click="showMergeModal = false" class="px-3.5 py-1.5 rounded-lg text-xs font-medium border border-slate-200">Cancel</button>
            <button @click="executeMerge" :disabled="!mergeSourceID || !mergeTargetID || mergeSourceID === mergeTargetID" class="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-indigo-600 text-white disabled:opacity-50">Merge</button>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'

definePageMeta({
  middleware: 'admin'
})

const activeSubtab = ref('concepts')
const selectedUserID = ref('')
const userOptions = ref<any[]>([])

const concepts = ref<any[]>([])
const propositions = ref<any[]>([])
const topics = ref<any[]>([])
const conflicts = ref<any[]>([])

// Merge modal state
const showMergeModal = ref(false)
const mergeSourceID = ref('')
const mergeTargetID = ref('')
const mergeReason = ref('')

const fetchUsers = async () => {
  try {
    const res = await $fetch<any>('/api/admin/users?limit=100')
    userOptions.value = res.users || []
    if (userOptions.value.length > 0 && !selectedUserID.value) {
      selectedUserID.value = userOptions.value[0].id
      await loadTabData()
    }
  } catch (err) {
    console.error('Failed to load user options:', err)
  }
}

const loadTabData = async () => {
  if (!selectedUserID.value) return
  try {
    if (activeSubtab.value === 'concepts') {
      const res = await $fetch<any>(`/api/admin/graph/concepts?user_id=${selectedUserID.value}`)
      concepts.value = res.concepts || []
    } else if (activeSubtab.value === 'propositions') {
      const res = await $fetch<any>(`/api/admin/graph/propositions?user_id=${selectedUserID.value}`)
      propositions.value = res.propositions || []
    } else if (activeSubtab.value === 'topics') {
      const res = await $fetch<any>(`/api/admin/graph/topics?user_id=${selectedUserID.value}`)
      topics.value = res.topics || []
    } else if (activeSubtab.value === 'conflicts') {
      const res = await $fetch<any>(`/api/admin/graph/conflicts?user_id=${selectedUserID.value}`)
      conflicts.value = res.conflicts || []
    }
  } catch (err) {
    console.error('Failed to load graph data:', err)
  }
}

const onUserChanged = () => {
  loadTabData()
}

watch(activeSubtab, () => {
  loadTabData()
})

const openMergeModal = () => {
  showMergeModal.value = true
  mergeSourceID.value = ''
  mergeTargetID.value = ''
  mergeReason.value = 'Synonymous concepts'
}

const executeMerge = async () => {
  try {
    const res = await $fetch<any>('/api/admin/graph/concepts/merge', {
      method: 'POST',
      body: {
        user_id: selectedUserID.value,
        source_concept_id: mergeSourceID.value,
        target_concept_id: mergeTargetID.value,
        reason: mergeReason.value
      }
    })
    alert(`Merged successfully: ${res.rewired_propositions} proposition edges rewired.`)
    showMergeModal.value = false
    await loadTabData()
  } catch (err: any) {
    alert('Failed to merge: ' + (err?.data?.error?.message || err.message))
  }
}

const retractProp = async (p: any) => {
  const reason = prompt('Reason for retracting proposition:', 'Refuted by newer literature')
  if (reason === null) return
  try {
    await $fetch(`/api/admin/graph/propositions/${p.id}/retract`, {
      method: 'POST',
      body: { user_id: selectedUserID.value, reason }
    })
    await loadTabData()
  } catch (err: any) {
    alert('Failed to retract: ' + (err?.data?.error?.message || err.message))
  }
}

const restoreProp = async (p: any) => {
  const reason = prompt('Reason for restoring proposition:', 'Re-verified evidence validity')
  if (reason === null) return
  try {
    await $fetch(`/api/admin/graph/propositions/${p.id}/restore`, {
      method: 'POST',
      body: { user_id: selectedUserID.value, reason }
    })
    await loadTabData()
  } catch (err: any) {
    alert('Failed to restore: ' + (err?.data?.error?.message || err.message))
  }
}

const editConcept = (c: any) => {
  const name = prompt('Update concept name:', c.name)
  if (!name) return
  $fetch(`/api/admin/graph/concepts/${c.id}`, {
    method: 'PUT',
    body: { user_id: selectedUserID.value, name, description: c.description }
  }).then(() => loadTabData()).catch(err => alert(err.message))
}

const archiveConcept = (c: any) => {
  if (!confirm(`Archive concept "${c.name}"?`)) return
  $fetch(`/api/admin/graph/concepts/${c.id}`, {
    method: 'DELETE',
    body: { user_id: selectedUserID.value }
  }).then(() => loadTabData()).catch(err => alert(err.message))
}

const editTopic = (t: any) => {
  const name = prompt('Topic name:', t.name)
  if (!name) return
  $fetch(`/api/admin/graph/topics/${t.id}`, {
    method: 'PUT',
    body: { user_id: selectedUserID.value, name, description: t.description }
  }).then(() => loadTabData()).catch(err => alert(err.message))
}

const resolveConflictModal = (c: any) => {
  const decision = prompt('Decision (e.g. keep_canonical or keep_conflicting):', 'keep_canonical')
  if (!decision) return
  const justification = prompt('Resolution justification:', 'Primary source verified')
  if (!justification) return
  $fetch(`/api/admin/graph/conflicts/${c.id}/resolve`, {
    method: 'POST',
    body: { user_id: selectedUserID.value, decision, justification }
  }).then(() => loadTabData()).catch(err => alert(err.message))
}

const openManualPropModal = () => {
  alert('To create a proposition manually, cite an exact verbatim span from a document with matching byte/character offsets. (Evidence integrity validator enforced).')
}

onMounted(async () => {
  await fetchUsers()
})
</script>
