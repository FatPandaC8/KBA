<template>
  <div class="h-full flex overflow-hidden">
    <!-- Main Documents Table Surface -->
    <div class="flex-1 h-full overflow-y-auto px-6 py-8">
      <div class="max-w-6xl mx-auto">
        <!-- Header -->
        <div class="flex items-center justify-between mb-6">
          <div>
            <h1 class="text-2xl font-serif font-bold text-ink-900 tracking-tight">Documents</h1>
            <p class="text-sm text-ink-500 mt-1">
              Source repository for all ingested knowledge texts, web pages, and files.
            </p>
          </div>
          <NuxtLink
            to="/add"
            class="flex items-center space-x-2 px-4 py-2 bg-ink-900 text-canvas rounded-lg text-sm font-medium hover:bg-ink-800 transition-colors"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
            </svg>
            <span>Add Knowledge</span>
          </NuxtLink>
        </div>

        <!-- Filter / Search Toolbar -->
        <div class="flex items-center justify-between mb-4 pb-3 border-b border-hairline">
          <div class="flex items-center space-x-2">
            <button
              v-for="filter in statusFilters"
              :key="filter.value"
              @click="currentFilter = filter.value"
              class="px-3 py-1 rounded-md text-xs font-medium transition-colors"
              :class="currentFilter === filter.value ? 'bg-ink-900 text-canvas' : 'text-ink-600 hover:bg-stone-100'"
            >
              {{ filter.label }}
            </button>
          </div>
          <button
            @click="fetchDocuments"
            class="flex items-center space-x-1.5 text-xs text-ink-500 hover:text-ink-900 transition-colors"
            title="Refresh list"
          >
            <svg class="w-3.5 h-3.5" :class="isLoading ? 'animate-spin' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
            </svg>
            <span>Refresh</span>
          </button>
        </div>

        <!-- Empty State -->
        <div
          v-if="!isLoading && filteredDocuments.length === 0"
          class="py-16 text-center border border-dashed border-hairline rounded-xl"
        >
          <svg class="w-12 h-12 mx-auto text-ink-300 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
          </svg>
          <h3 class="text-base font-serif font-medium text-ink-800">No documents ingested yet</h3>
          <p class="text-xs text-ink-400 mt-1 max-w-sm mx-auto">
            Add your first document, URL, or plain text excerpt to begin constructing your grounded knowledge graph.
          </p>
          <NuxtLink
            to="/add"
            class="inline-flex items-center space-x-1.5 mt-4 px-3.5 py-1.5 bg-ink-900 text-canvas rounded-lg text-xs font-medium hover:bg-ink-800 transition-colors"
          >
            <span>Ingest Knowledge</span>
          </NuxtLink>
        </div>

        <!-- Documents Table -->
        <div v-else class="bg-canvas border border-hairline rounded-xl overflow-hidden shadow-sm">
          <table class="w-full text-left border-collapse">
            <thead>
              <tr class="border-b border-hairline bg-stone-50/70 text-[11px] font-semibold text-ink-500 uppercase tracking-wider">
                <th class="py-3 px-4">Title / Source</th>
                <th class="py-3 px-3">Type</th>
                <th class="py-3 px-3">Length</th>
                <th class="py-3 px-3">Status</th>
                <th class="py-3 px-3">Added</th>
                <th class="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-hairline text-xs text-ink-800">
              <tr
                v-for="doc in filteredDocuments"
                :key="doc.id"
                @click="openDocumentDrawer(doc)"
                class="hover:bg-stone-50/80 cursor-pointer transition-colors"
                :class="selectedDoc?.id === doc.id ? 'bg-stone-100/70' : ''"
              >
                <!-- Title & Source -->
                <td class="py-3.5 px-4 font-medium max-w-xs truncate text-ink-900">
                  <div class="truncate" :title="doc.title">{{ doc.title }}</div>
                  <div v-if="doc.source_url" class="text-[11px] text-ink-400 truncate mt-0.5" :title="doc.source_url">
                    {{ doc.source_url }}
                  </div>
                </td>

                <!-- Type -->
                <td class="py-3.5 px-3">
                  <span class="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-mono uppercase tracking-wider bg-stone-100 text-ink-600">
                    {{ doc.source_type }}
                  </span>
                </td>

                <!-- Length / Chars -->
                <td class="py-3.5 px-3 font-mono text-ink-500">
                  {{ doc.char_count?.toLocaleString() || 0 }} chars
                </td>

                <!-- Status Badge -->
                <td class="py-3.5 px-3">
                  <span
                    class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium"
                    :class="getStatusBadgeClass(doc.status)"
                  >
                    <span
                      class="w-1.5 h-1.5 rounded-full mr-1.5"
                      :class="getStatusDotClass(doc.status)"
                    ></span>
                    {{ doc.status }}
                  </span>
                </td>

                <!-- Date -->
                <td class="py-3.5 px-3 text-ink-400 whitespace-nowrap">
                  {{ formatDate(doc.created_at) }}
                </td>

                <!-- Actions -->
                <td class="py-3.5 px-4 text-right whitespace-nowrap" @click.stop>
                  <button
                    @click="openDocumentDrawer(doc)"
                    class="px-2.5 py-1 text-xs text-ink-700 hover:text-ink-950 font-medium hover:underline"
                  >
                    View Source
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Slide-out Document Detail Drawer -->
    <div
      v-if="selectedDoc"
      class="w-[450px] h-full border-l border-hairline bg-canvas flex flex-col shadow-lg z-20 flex-shrink-0 animate-fadeIn"
    >
      <!-- Drawer Header -->
      <div class="p-5 border-b border-hairline flex items-center justify-between bg-stone-50/50">
        <div class="truncate pr-2">
          <h2 class="text-sm font-semibold text-ink-900 truncate" :title="selectedDoc.title">
            {{ selectedDoc.title }}
          </h2>
          <div class="flex items-center space-x-2 text-[11px] text-ink-500 mt-0.5">
            <span class="uppercase font-mono">{{ selectedDoc.source_type }}</span>
            <span>&bull;</span>
            <span>{{ selectedDoc.char_count?.toLocaleString() }} characters</span>
          </div>
        </div>
        <button
          @click="selectedDoc = null"
          class="p-1.5 text-ink-400 hover:text-ink-800 rounded-md hover:bg-stone-100 transition-colors"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>

      <!-- Drawer Tabs -->
      <div class="flex border-b border-hairline px-4 text-xs font-medium">
        <button
          @click="drawerTab = 'source'"
          class="py-2.5 px-3 border-b-2 transition-colors"
          :class="drawerTab === 'source' ? 'border-ink-900 text-ink-900 font-semibold' : 'border-transparent text-ink-500 hover:text-ink-800'"
        >
          Source Text
        </button>
        <button
          @click="drawerTab = 'chunks'"
          class="py-2.5 px-3 border-b-2 transition-colors"
          :class="drawerTab === 'chunks' ? 'border-ink-900 text-ink-900 font-semibold' : 'border-transparent text-ink-500 hover:text-ink-800'"
        >
          Chunks ({{ docChunks.length }})
        </button>
      </div>

      <!-- Drawer Body -->
      <div class="flex-1 overflow-y-auto p-5 space-y-4">
        <!-- Tab: Source Text -->
        <div v-if="drawerTab === 'source'" class="space-y-3">
          <div class="flex items-center justify-between text-[11px] text-ink-400">
            <span>Raw Normalized Text</span>
            <span>Content Hash: {{ selectedDoc.content_hash.slice(0, 12) }}...</span>
          </div>
          <div class="p-3.5 bg-stone-50 rounded-lg border border-hairline text-xs font-mono leading-relaxed text-ink-800 whitespace-pre-wrap select-text max-h-[600px] overflow-y-auto">
            {{ selectedDoc.source_text || selectedDoc.raw_content }}
          </div>
        </div>

        <!-- Tab: Chunks -->
        <div v-if="drawerTab === 'chunks'" class="space-y-3">
          <div v-if="docChunks.length === 0" class="text-xs text-ink-400 py-6 text-center">
            No chunks extracted yet.
          </div>
          <div
            v-for="(chunk, idx) in docChunks"
            :key="chunk.id"
            class="p-3.5 bg-canvas border border-hairline rounded-lg text-xs space-y-2"
          >
            <div class="flex items-center justify-between text-[11px] text-ink-400">
              <span class="font-semibold text-ink-700">Chunk #{{ idx + 1 }}</span>
              <span>Byte {{ chunk.byte_start }} - {{ chunk.byte_end }}</span>
            </div>
            <p class="text-ink-800 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">
              {{ chunk.text }}
            </p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

interface DocumentItem {
  id: string
  user_id: string
  title: string
  source_type: string
  source_url?: string
  content_hash: string
  raw_content: string
  source_text: string
  char_count: number
  status: string
  created_at: string
  updated_at: string
}

interface ChunkItem {
  id: string
  document_id: string
  chunk_index: number
  byte_start: number
  byte_end: number
  char_start: number
  char_end: number
  text: string
}

const documents = ref<DocumentItem[]>([])
const isLoading = ref(false)
const currentFilter = ref('all')
const selectedDoc = ref<DocumentItem | null>(null)
const docChunks = ref<ChunkItem[]>([])
const drawerTab = ref<'source' | 'chunks'>('source')

const statusFilters = [
  { label: 'All', value: 'all' },
  { label: 'Completed', value: 'completed' },
  { label: 'Processing', value: 'processing' },
  { label: 'Failed', value: 'failed' }
]

const filteredDocuments = computed(() => {
  if (currentFilter.value === 'all') return documents.value
  return documents.value.filter(d => d.status === currentFilter.value)
})

function getStatusBadgeClass(status: string) {
  switch (status) {
    case 'completed':
      return 'bg-emerald-50 text-emerald-700 border border-emerald-200'
    case 'processing':
    case 'queued':
    case 'uploading':
      return 'bg-amber-50 text-amber-700 border border-amber-200'
    case 'failed':
      return 'bg-red-50 text-red-700 border border-red-200'
    default:
      return 'bg-stone-100 text-stone-700 border border-stone-200'
  }
}

function getStatusDotClass(status: string) {
  switch (status) {
    case 'completed':
      return 'bg-emerald-500'
    case 'processing':
    case 'queued':
    case 'uploading':
      return 'bg-amber-500 animate-pulse'
    case 'failed':
      return 'bg-red-500'
    default:
      return 'bg-stone-400'
  }
}

function formatDate(iso: string) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric'
  })
}

async function fetchDocuments() {
  isLoading.value = true
  try {
    const res = await fetch('/api/documents', {
      credentials: 'include'
    })
    if (res.ok) {
      const data = await res.json()
      documents.value = data.documents || []
    }
  } catch (err) {
    console.error('Failed to fetch documents', err)
  } finally {
    isLoading.value = false
  }
}

async function openDocumentDrawer(doc: DocumentItem) {
  selectedDoc.value = doc
  docChunks.value = []
  drawerTab.value = 'source'

  try {
    const res = await fetch(`/api/documents/${doc.id}`, {
      credentials: 'include'
    })
    if (res.ok) {
      const data = await res.json()
      docChunks.value = data.chunks || []
    }
  } catch (err) {
    console.error('Failed to fetch document chunks', err)
  }
}

onMounted(() => {
  fetchDocuments()
})
</script>
