<template>
  <div class="min-h-full bg-slate-50 flex flex-col">
    <AdminNav />

    <main class="flex-1 max-w-7xl w-full mx-auto p-6 md:p-8 space-y-6">
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 class="text-xl font-bold text-slate-900 tracking-tight">Document Operations</h1>
          <p class="text-xs text-slate-500 mt-1">Audit ingested documents, inspect text spans and extraction runs, or trigger cascade deletions.</p>
        </div>
        <div class="flex items-center space-x-3">
          <select
            v-model="statusFilter"
            @change="fetchDocuments"
            class="px-3 py-1.5 text-xs rounded-lg border border-slate-200 bg-white focus:outline-hidden focus:ring-2 focus:ring-indigo-500 shadow-2xs"
          >
            <option value="">All Statuses</option>
            <option value="completed">Completed</option>
            <option value="queued">Queued</option>
            <option value="processing">Processing</option>
            <option value="failed">Failed</option>
          </select>
          <button
            @click="fetchDocuments"
            class="px-3 py-1.5 text-xs font-medium rounded-md bg-white border border-slate-200 text-slate-700 hover:bg-slate-50 shadow-2xs"
          >
            Refresh
          </button>
        </div>
      </div>

      <!-- Documents Table -->
      <div class="bg-white rounded-xl border border-slate-200/80 shadow-2xs overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full text-left text-xs">
            <thead class="bg-slate-50/80 border-b border-slate-200/60 text-slate-500 font-medium">
              <tr>
                <th class="px-4 py-3">Document Title</th>
                <th class="px-4 py-3">User</th>
                <th class="px-4 py-3">Type</th>
                <th class="px-4 py-3">Status</th>
                <th class="px-4 py-3">Size / Chunks</th>
                <th class="px-4 py-3">Created</th>
                <th class="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100">
              <tr v-if="documents.length === 0" class="text-center text-slate-400 py-8">
                <td colspan="7" class="py-8">No documents found.</td>
              </tr>
              <tr v-for="d in documents" :key="d.id" class="hover:bg-slate-50/50 transition-colors">
                <td class="px-4 py-3">
                  <span class="font-medium text-slate-900 block truncate max-w-[240px]" :title="d.title">
                    {{ d.title }}
                  </span>
                  <span class="text-2xs text-slate-400 font-mono">{{ d.id }}</span>
                </td>
                <td class="px-4 py-3 text-slate-600 truncate max-w-[160px]" :title="d.user_email">
                  {{ d.user_email }}
                </td>
                <td class="px-4 py-3 uppercase font-mono text-2xs text-slate-500">
                  {{ d.source_type }}
                </td>
                <td class="px-4 py-3">
                  <span class="px-2 py-0.5 rounded-full text-2xs font-semibold capitalize" :class="d.status === 'completed' ? 'bg-emerald-50 text-emerald-700' : (d.status === 'failed' ? 'bg-rose-50 text-rose-700' : 'bg-amber-50 text-amber-700')">
                    {{ d.status }}
                  </span>
                </td>
                <td class="px-4 py-3 text-slate-600 font-mono text-2xs">
                  {{ d.char_count }} chars &middot; {{ d.chunk_count }} chunks
                </td>
                <td class="px-4 py-3 text-2xs text-slate-500">
                  {{ formatDate(d.created_at) }}
                </td>
                <td class="px-4 py-3 text-right space-x-2">
                  <button
                    @click="inspectDocument(d.id)"
                    class="px-2.5 py-1 rounded text-2xs font-medium text-indigo-600 hover:bg-indigo-50 transition-colors"
                  >
                    Inspect
                  </button>
                  <button
                    @click="reprocessDocument(d.id)"
                    class="px-2.5 py-1 rounded text-2xs font-medium text-slate-700 hover:bg-slate-100 transition-colors"
                  >
                    Reprocess
                  </button>
                  <button
                    @click="openDeleteModal(d)"
                    class="px-2.5 py-1 rounded text-2xs font-medium text-rose-600 hover:bg-rose-50 transition-colors"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Document Inspector Drawer / Modal -->
      <div v-if="activeDoc" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
        <div class="bg-white rounded-xl shadow-xl max-w-2xl w-full p-6 space-y-4 max-h-[85vh] flex flex-col">
          <div class="flex items-center justify-between pb-3 border-b border-slate-100">
            <div>
              <h3 class="text-sm font-bold text-slate-900">{{ activeDoc.title }}</h3>
              <p class="text-2xs text-slate-400 font-mono mt-0.5">{{ activeDoc.id }}</p>
            </div>
            <button @click="activeDoc = null" class="text-slate-400 hover:text-slate-600 text-lg leading-none">&times;</button>
          </div>

          <div class="overflow-y-auto space-y-4 flex-1 text-xs">
            <!-- Source Text -->
            <div>
              <span class="font-semibold text-slate-700 block mb-1">Source Text Preview</span>
              <div class="p-3 rounded-lg bg-slate-50 font-mono text-2xs text-slate-800 leading-relaxed border border-slate-200 max-h-40 overflow-y-auto whitespace-pre-wrap">
                {{ activeDoc.source_text }}
              </div>
            </div>

            <!-- Chunks List -->
            <div>
              <span class="font-semibold text-slate-700 block mb-1">Document Chunks ({{ activeDoc.chunks?.length ?? 0 }})</span>
              <div class="space-y-2">
                <div v-for="c in activeDoc.chunks" :key="c.id" class="p-2.5 rounded bg-slate-50 border border-slate-200 text-2xs">
                  <div class="flex justify-between text-3xs font-mono text-slate-500 mb-1">
                    <span>Chunk #{{ c.chunk_index }} ({{ c.id.slice(0, 8) }})</span>
                    <span>Bytes: [{{ c.byte_start }} - {{ c.byte_end }}]</span>
                  </div>
                  <p class="text-slate-700 line-clamp-2">{{ c.chunk_text }}</p>
                </div>
              </div>
            </div>
          </div>

          <div class="pt-3 border-t border-slate-100 flex justify-end">
            <button @click="activeDoc = null" class="px-4 py-1.5 rounded-lg text-xs font-medium bg-slate-100 text-slate-700 hover:bg-slate-200">
              Close
            </button>
          </div>
        </div>
      </div>

      <!-- Typed Confirmation Modal for Document Delete -->
      <div v-if="deleteTarget" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
        <div class="bg-white rounded-xl shadow-xl max-w-md w-full p-6 space-y-4 border border-rose-200">
          <div class="flex items-center space-x-3 text-rose-600">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
            </svg>
            <h3 class="text-base font-bold text-slate-900">Delete Document</h3>
          </div>

          <div class="p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-900 text-2xs space-y-1">
            <span class="font-bold block">Cascade Retraction Warning</span>
            <p>
              Deleting this document will soft-retract any canonical propositions that have no remaining valid evidence in other documents. Concepts that lose all citations will be marked as orphaned.
            </p>
          </div>

          <div>
            <label class="block text-2xs font-semibold text-slate-700 mb-1">
              Type <span class="font-mono text-rose-600 select-all">{{ deleteTarget.title }}</span> to confirm:
            </label>
            <input
              v-model="deleteConfirmInput"
              type="text"
              class="w-full px-3 py-2 text-xs rounded-lg border border-slate-300 font-medium focus:ring-2 focus:ring-rose-500 focus:outline-hidden"
              placeholder="Enter exact document title"
            />
          </div>

          <div class="flex justify-end space-x-3 pt-2">
            <button
              @click="closeDeleteModal"
              class="px-3.5 py-1.5 rounded-lg text-xs font-medium border border-slate-200 text-slate-600 hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              @click="confirmDeleteDocument"
              :disabled="deleteConfirmInput !== deleteTarget.title || deleting"
              class="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-rose-600 text-white hover:bg-rose-700 disabled:opacity-40 disabled:cursor-not-allowed shadow-2xs"
            >
              {{ deleting ? 'Deleting...' : 'Delete & Cascade Retract' }}
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

const loading = ref(false)
const statusFilter = ref('')
const documents = ref<any[]>([])
const activeDoc = ref<any>(null)

const deleteTarget = ref<any>(null)
const deleteConfirmInput = ref('')
const deleting = ref(false)

const formatDate = (isoStr: string) => {
  if (!isoStr) return ''
  const d = new Date(isoStr)
  return d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })
}

const fetchDocuments = async () => {
  loading.value = true
  try {
    const params = new URLSearchParams()
    if (statusFilter.value) params.set('status', statusFilter.value)
    const res = await $fetch<any>(`/api/admin/documents?${params.toString()}`)
    documents.value = res.documents || []
  } catch (err) {
    console.error('Failed to list documents:', err)
  } finally {
    loading.value = false
  }
}

const inspectDocument = async (id: string) => {
  try {
    const res = await $fetch<any>(`/api/admin/documents/${id}`)
    activeDoc.value = res
  } catch (err: any) {
    alert('Failed to get document details: ' + (err?.data?.error?.message || err.message))
  }
}

const reprocessDocument = async (id: string) => {
  try {
    await $fetch(`/api/admin/documents/${id}/reprocess`, { method: 'POST' })
    alert('Document re-processing queued successfully!')
    await fetchDocuments()
  } catch (err: any) {
    alert('Failed to reprocess: ' + (err?.data?.error?.message || err.message))
  }
}

const openDeleteModal = (doc: any) => {
  deleteTarget.value = doc
  deleteConfirmInput.value = ''
}

const closeDeleteModal = () => {
  deleteTarget.value = null
  deleteConfirmInput.value = ''
}

const confirmDeleteDocument = async () => {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    const res = await $fetch<any>(`/api/admin/documents/${deleteTarget.value.id}`, {
      method: 'DELETE',
      body: { confirm_title: deleteConfirmInput.value }
    })
    alert(`Document deleted. Cascade retraction: ${res.retracted_props} propositions retracted, ${res.orphaned_concepts} concepts orphaned.`)
    closeDeleteModal()
    await fetchDocuments()
  } catch (err: any) {
    alert('Failed to delete document: ' + (err?.data?.error?.message || err.message))
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  fetchDocuments()
})
</script>
