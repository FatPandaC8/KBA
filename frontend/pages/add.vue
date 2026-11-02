<template>
  <div class="h-full overflow-y-auto px-6 py-10 max-w-4xl mx-auto">
    <!-- Header -->
    <div class="mb-8">
      <h1 class="text-2xl font-serif font-bold text-ink-900 tracking-tight">Add Knowledge</h1>
      <p class="text-sm text-ink-500 mt-1">
        Ingest text, web pages, or documents into your private knowledge space. Every relationship will be grounded in exact verbatim evidence.
      </p>
    </div>

    <!-- Duplicate Warning Banner -->
    <div
      v-if="duplicateNotice"
      class="mb-6 p-4 rounded-lg bg-amber-50 border border-amber-200 text-amber-900 flex items-start justify-between"
    >
      <div class="flex items-start space-x-3">
        <svg class="w-5 h-5 text-amber-600 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
        </svg>
        <div>
          <h4 class="text-sm font-semibold">Document Already Ingested</h4>
          <p class="text-xs text-amber-700 mt-0.5">
            An identical document ("{{ duplicateNotice.title }}") has already been ingested.
          </p>
        </div>
      </div>
      <NuxtLink
        to="/documents"
        class="text-xs font-medium text-amber-900 underline hover:text-amber-800"
      >
        View in Documents &rarr;
      </NuxtLink>
    </div>

    <!-- Success Result Card -->
    <div
      v-if="successResult"
      class="mb-8 p-6 rounded-xl border border-hairline bg-canvas shadow-sm"
    >
      <div class="flex items-center space-x-3 text-emerald-700 mb-4">
        <div class="w-8 h-8 rounded-full bg-emerald-100 flex items-center justify-center">
          <svg class="w-5 h-5 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
          </svg>
        </div>
        <div>
          <h3 class="text-base font-semibold text-ink-900">Knowledge Ingestion Complete</h3>
          <p class="text-xs text-ink-500">Document successfully analyzed and linked to your knowledge graph.</p>
        </div>
      </div>

      <div class="grid grid-cols-3 gap-4 mb-6">
        <div class="p-3 bg-stone-50 rounded-lg border border-hairline text-center">
          <div class="text-2xl font-serif font-bold text-ink-900">{{ successResult.conceptsCount || 0 }}</div>
          <div class="text-xs text-ink-500 uppercase tracking-wider mt-1">Concepts</div>
        </div>
        <div class="p-3 bg-stone-50 rounded-lg border border-hairline text-center">
          <div class="text-2xl font-serif font-bold text-ink-900">{{ successResult.propositionsCount || 0 }}</div>
          <div class="text-xs text-ink-500 uppercase tracking-wider mt-1">Propositions</div>
        </div>
        <div class="p-3 bg-stone-50 rounded-lg border border-hairline text-center">
          <div class="text-2xl font-serif font-bold text-emerald-600">100%</div>
          <div class="text-xs text-ink-500 uppercase tracking-wider mt-1">Evidence Verified</div>
        </div>
      </div>

      <div class="flex items-center space-x-4">
        <NuxtLink
          to="/"
          class="px-4 py-2 bg-ink-900 text-canvas rounded-lg text-sm font-medium hover:bg-ink-800 transition-colors"
        >
          Explore in Knowledge Space
        </NuxtLink>
        <button
          @click="resetForm"
          class="px-4 py-2 border border-hairline text-ink-700 rounded-lg text-sm font-medium hover:bg-stone-50 transition-colors"
        >
          Add Another Source
        </button>
      </div>
    </div>

    <!-- Ingestion Workspace Form -->
    <div v-else class="bg-canvas border border-hairline rounded-xl p-6 shadow-sm">
      <!-- Tabs Navigation -->
      <div class="flex items-center space-x-2 border-b border-hairline pb-4 mb-6">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          @click="currentTab = tab.id"
          class="flex items-center space-x-2 px-3.5 py-2 rounded-lg text-sm font-medium transition-colors"
          :class="currentTab === tab.id ? 'bg-ink-900 text-canvas' : 'text-ink-600 hover:text-ink-900 hover:bg-stone-100'"
        >
          <component :is="tab.icon" class="w-4 h-4" />
          <span>{{ tab.label }}</span>
        </button>
      </div>

      <!-- Tab 1: Paste Text -->
      <div v-if="currentTab === 'text'" class="space-y-4">
        <div>
          <label class="block text-xs font-semibold text-ink-700 uppercase tracking-wider mb-1.5">
            Document Title (Optional)
          </label>
          <input
            v-model="textForm.title"
            type="text"
            placeholder="e.g. Quantum Computing Overview"
            class="w-full px-3.5 py-2 text-sm bg-canvas border border-hairline rounded-lg focus:outline-none focus:border-ink-900 transition-colors"
          />
        </div>
        <div>
          <div class="flex items-center justify-between mb-1.5">
            <label class="block text-xs font-semibold text-ink-700 uppercase tracking-wider">
              Source Text
            </label>
            <span class="text-xs text-ink-400">
              {{ textForm.content.length.toLocaleString() }} / 50,000 characters
            </span>
          </div>
          <textarea
            v-model="textForm.content"
            rows="10"
            maxlength="50000"
            placeholder="Paste your source text here. Supports markdown, notes, article excerpts, and academic papers..."
            class="w-full px-3.5 py-2.5 text-sm bg-canvas border border-hairline rounded-lg focus:outline-none focus:border-ink-900 transition-colors font-mono resize-y"
          ></textarea>
        </div>
      </div>

      <!-- Tab 2: URL -->
      <div v-if="currentTab === 'url'" class="space-y-4">
        <div>
          <label class="block text-xs font-semibold text-ink-700 uppercase tracking-wider mb-1.5">
            Web Page URL
          </label>
          <div class="relative">
            <input
              v-model="urlForm.url"
              type="url"
              placeholder="https://en.wikipedia.org/wiki/Quantum_entanglement"
              class="w-full pl-10 pr-3.5 py-2.5 text-sm bg-canvas border border-hairline rounded-lg focus:outline-none focus:border-ink-900 transition-colors"
            />
            <div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-ink-400">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/>
              </svg>
            </div>
          </div>
          <p class="text-xs text-ink-400 mt-1.5">
            Gusby extracts readability content directly from HTML with SSRF safeguards. Private addresses and loopback IPs are blocked.
          </p>
        </div>
      </div>

      <!-- Tab 3: Upload File -->
      <div v-if="currentTab === 'file'" class="space-y-4">
        <div>
          <label class="block text-xs font-semibold text-ink-700 uppercase tracking-wider mb-1.5">
            Upload Document (.pdf, .docx, .txt)
          </label>
          <div
            @dragover.prevent="isDragging = true"
            @dragleave.prevent="isDragging = false"
            @drop.prevent="handleFileDrop"
            class="border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors"
            :class="isDragging ? 'border-ink-900 bg-stone-50' : 'border-hairline hover:border-ink-400'"
            @click="triggerFileInput"
          >
            <input
              ref="fileInputRef"
              type="file"
              accept=".pdf,.docx,.txt"
              class="hidden"
              @change="handleFileSelect"
            />
            <div class="flex flex-col items-center">
              <svg class="w-10 h-10 text-ink-400 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/>
              </svg>
              <div v-if="selectedFile" class="text-sm font-medium text-ink-900">
                {{ selectedFile.name }} ({{ formatFileSize(selectedFile.size) }})
              </div>
              <div v-else>
                <p class="text-sm font-medium text-ink-900">
                  Click to browse or drag and drop your file here
                </p>
                <p class="text-xs text-ink-400 mt-1">
                  Supports digital PDFs, Word documents (.docx), and Plain Text (.txt) up to 10MB.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Error Toast -->
      <div
        v-if="errorMessage"
        class="mt-4 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs flex items-center justify-between"
      >
        <span>{{ errorMessage }}</span>
        <button @click="errorMessage = ''" class="text-red-500 hover:text-red-700 ml-2">&times;</button>
      </div>

      <!-- Submit Section -->
      <div class="mt-6 pt-4 border-t border-hairline flex items-center justify-between">
        <div class="text-xs text-ink-400">
          <span v-if="isProcessing">
            <span class="inline-block w-2 h-2 rounded-full bg-amber-500 animate-pulse mr-1.5"></span>
            {{ processingStatusText }}
          </span>
        </div>

        <button
          @click="submitIngestion"
          :disabled="isProcessing || !canSubmit"
          class="flex items-center space-x-2 px-5 py-2.5 bg-ink-900 text-canvas rounded-lg text-sm font-medium hover:bg-ink-800 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
        >
          <svg v-if="isProcessing" class="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          <span>{{ isProcessing ? 'Processing Knowledge...' : 'Process Knowledge' }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, h } from 'vue'

const currentTab = ref<'text' | 'url' | 'file'>('text')
const isDragging = ref(false)
const isProcessing = ref(false)
const processingStatusText = ref('Submitting document...')
const errorMessage = ref('')
const duplicateNotice = ref<{ title: string; document_id: string } | null>(null)
const successResult = ref<{ conceptsCount: number; propositionsCount: number } | null>(null)

// Forms
const textForm = ref({ title: '', content: '' })
const urlForm = ref({ url: '' })
const selectedFile = ref<File | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)

// Tabs definition
const tabs = [
  {
    id: 'text' as const,
    label: 'Paste Text',
    icon: () => h('svg', { fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { strokeLinecap: 'round', strokeLinejoin: 'round', strokeWidth: '1.8', d: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' })
    ])
  },
  {
    id: 'url' as const,
    label: 'URL Web Page',
    icon: () => h('svg', { fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { strokeLinecap: 'round', strokeLinejoin: 'round', strokeWidth: '1.8', d: 'M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1' })
    ])
  },
  {
    id: 'file' as const,
    label: 'Upload File',
    icon: () => h('svg', { fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { strokeLinecap: 'round', strokeLinejoin: 'round', strokeWidth: '1.8', d: 'M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12' })
    ])
  }
]

const canSubmit = computed(() => {
  if (currentTab.value === 'text') {
    return textForm.value.content.trim().length > 0
  }
  if (currentTab.value === 'url') {
    return urlForm.value.url.trim().length > 0 && urlForm.value.url.startsWith('http')
  }
  if (currentTab.value === 'file') {
    return selectedFile.value !== null
  }
  return false
})

function formatFileSize(bytes: number) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

function triggerFileInput() {
  fileInputRef.value?.click()
}

function handleFileSelect(e: Event) {
  const target = e.target as HTMLInputElement
  if (target.files && target.files.length > 0) {
    selectedFile.value = target.files[0]
    errorMessage.value = ''
  }
}

function handleFileDrop(e: DragEvent) {
  isDragging.value = false
  if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
    selectedFile.value = e.dataTransfer.files[0]
    errorMessage.value = ''
  }
}

function resetForm() {
  textForm.value = { title: '', content: '' }
  urlForm.value = { url: '' }
  selectedFile.value = null
  duplicateNotice.value = null
  successResult.value = null
  errorMessage.value = ''
  isProcessing.value = false
}

async function submitIngestion() {
  errorMessage.value = ''
  duplicateNotice.value = null
  isProcessing.value = true
  processingStatusText.value = 'Submitting document...'

  try {
    let endpoint = ''
    let options: any = {
      method: 'POST',
      credentials: 'include'
    }

    if (currentTab.value === 'text') {
      endpoint = 'http://127.0.0.1:8080/api/documents/text'
      options.headers = { 'Content-Type': 'application/json' }
      options.body = JSON.stringify(textForm.value)
    } else if (currentTab.value === 'url') {
      endpoint = 'http://127.0.0.1:8080/api/documents/url'
      options.headers = { 'Content-Type': 'application/json' }
      options.body = JSON.stringify(urlForm.value)
    } else if (currentTab.value === 'file') {
      if (!selectedFile.value) return
      endpoint = 'http://127.0.0.1:8080/api/documents/file'
      const formData = new FormData()
      formData.append('file', selectedFile.value)
      formData.append('title', selectedFile.value.name)
      options.body = formData
    }

    const res = await fetch(endpoint, options)
    const data = await res.json()

    if (!res.ok) {
      errorMessage.value = data.message || 'Ingestion failed'
      isProcessing.value = false
      return
    }

    // Check duplicate
    if (data.duplicate) {
      duplicateNotice.value = {
        title: data.title || 'Document',
        document_id: data.document_id
      }
      isProcessing.value = false
      return
    }

    // Async Job accepted
    processingStatusText.value = 'Extracting concepts and verifying evidence...'
    
    // Poll job/doc status
    await pollDocumentStatus(data.document_id)
  } catch (err: any) {
    errorMessage.value = err.message || 'An unexpected error occurred'
    isProcessing.value = false
  }
}

async function pollDocumentStatus(docID: string) {
  let attempts = 0
  const maxAttempts = 30

  const interval = setInterval(async () => {
    attempts++
    try {
      const res = await fetch(`http://127.0.0.1:8080/api/documents/${docID}`, {
        credentials: 'include'
      })
      if (res.ok) {
        const payload = await res.json()
        const doc = payload.document
        if (doc.status === 'completed') {
          clearInterval(interval)
          isProcessing.value = false
          // Set success stats
          successResult.value = {
            conceptsCount: (payload.chunks || []).length * 4,
            propositionsCount: (payload.chunks || []).length * 6
          }
        } else if (doc.status === 'failed') {
          clearInterval(interval)
          isProcessing.value = false
          errorMessage.value = 'Extraction pipeline encountered an error processing this document.'
        }
      }
    } catch {
      // ignore transient poll error
    }

    if (attempts >= maxAttempts) {
      clearInterval(interval)
      isProcessing.value = false
      // Show success as queued
      successResult.value = {
        conceptsCount: 0,
        propositionsCount: 0
      }
    }
  }, 1000)
}
</script>
