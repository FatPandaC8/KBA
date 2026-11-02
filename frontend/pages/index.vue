<template>
  <div class="relative w-full h-full bg-canvas overflow-hidden">
    <!-- Top Floating Toolbar -->
    <header class="absolute top-4 left-6 right-6 z-20 flex justify-between items-center pointer-events-none">
      <!-- Left: Workspace Status / Active Topic Title -->
      <div class="pointer-events-auto flex items-center space-x-3 bg-canvas/90 backdrop-blur-md px-3.5 py-1.5 rounded-lg border border-hairline shadow-sm">
        <span class="text-xs font-semibold text-ink-900 tracking-tight">Knowledge Space</span>
        <span class="text-ink-200">|</span>
        <span class="text-xs text-ink-600 font-mono">{{ nodeCount }} nodes &middot; {{ edgeCount }} edges</span>
      </div>

      <!-- Center: Floating Search Bar -->
      <div class="pointer-events-auto relative w-96">
        <div class="relative flex items-center">
          <svg class="absolute left-3 w-4 h-4 text-ink-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
          </svg>
          <input
            v-model="searchQuery"
            @input="handleSearch"
            type="text"
            placeholder="Search concepts or topics..."
            class="w-full pl-9 pr-8 py-2 text-xs bg-canvas/95 backdrop-blur-md border border-hairline rounded-lg shadow-sm focus:outline-none focus:border-ink-900 transition-all text-ink-900 placeholder:text-ink-400"
          />
          <button v-if="searchQuery" @click="clearSearch" class="absolute right-2.5 text-ink-400 hover:text-ink-700">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>

        <!-- Search Autocomplete Dropdown -->
        <div v-if="searchResults.length > 0" class="absolute top-11 left-0 right-0 bg-canvas border border-hairline rounded-lg shadow-lg max-h-60 overflow-y-auto py-1 z-30">
          <button
            v-for="res in searchResults"
            :key="res.id"
            @click="selectSearchResult(res)"
            class="w-full px-3 py-2 text-left hover:bg-ink-50 flex items-center justify-between text-xs transition-colors"
          >
            <span class="font-medium text-ink-900">{{ res.name }}</span>
            <span class="text-[10px] text-ink-400 font-mono">deg: {{ res.degree }}</span>
          </button>
        </div>
      </div>

      <!-- Right: Review State Filter Toggle & Zoom Indicator -->
      <div class="pointer-events-auto flex items-center space-x-2">
        <button
          @click="toggleNeedsReview"
          class="flex items-center space-x-2 px-3 py-1.5 rounded-lg border text-xs font-medium transition-all shadow-sm"
          :class="filterNeedsReview
            ? 'bg-amber-50 border-amber-300 text-amber-900 shadow-amber-100/50'
            : 'bg-canvas/90 backdrop-blur-md border-hairline text-ink-600 hover:text-ink-900 hover:bg-ink-50'"
        >
          <div class="w-2 h-2 rounded-full" :class="filterNeedsReview ? 'bg-amber-500 animate-pulse' : 'bg-ink-300'"></div>
          <span>Needs Review</span>
          <span v-if="reviewItemCount > 0" class="px-1.5 py-0.2 rounded-full text-[10px] bg-amber-200 text-amber-900 font-mono">
            {{ reviewItemCount }}
          </span>
        </button>
      </div>
    </header>

    <!-- Graph Canvas Container -->
    <div ref="cyContainer" class="w-full h-full cursor-grab active:cursor-grabbing"></div>

    <!-- Empty Space State -->
    <div v-if="!loading && nodeCount === 0" class="absolute inset-0 flex flex-col items-center justify-center pointer-events-none z-10">
      <div class="pointer-events-auto max-w-sm text-center p-8 bg-canvas border border-hairline rounded-xl shadow-sm space-y-4">
        <div class="w-12 h-12 rounded-full bg-ink-50 border border-hairline flex items-center justify-center mx-auto text-ink-400">
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="3" stroke-width="1.8"/>
            <circle cx="6" cy="6" r="2" stroke-width="1.8"/>
            <circle cx="18" cy="7" r="2" stroke-width="1.8"/>
            <path stroke-width="1.4" d="M8 7.5l2.5 3M16 8.5l-2.5 2.5"/>
          </svg>
        </div>
        <h2 class="text-sm font-semibold text-ink-900">Your Knowledge Space is Empty</h2>
        <p class="text-xs text-ink-600 leading-relaxed">
          Gusby turns unstructured text, URLs, and documents into connected, evidence-backed knowledge.
        </p>
        <NuxtLink to="/add" class="inline-block px-4 py-2 bg-ink-900 hover:bg-ink-800 text-white text-xs font-medium rounded-md transition-colors">
          Add First Document
        </NuxtLink>
      </div>
    </div>

    <!-- Floating Bottom-Right Camera Controls -->
    <div class="absolute bottom-6 right-6 z-20 flex flex-col space-y-1.5 bg-canvas/90 backdrop-blur-md p-1 border border-hairline rounded-lg shadow-sm">
      <button @click="zoomIn" class="w-8 h-8 flex items-center justify-center text-ink-600 hover:text-ink-900 hover:bg-ink-100 rounded text-sm font-medium" title="Zoom In">+</button>
      <button @click="zoomOut" class="w-8 h-8 flex items-center justify-center text-ink-600 hover:text-ink-900 hover:bg-ink-100 rounded text-sm font-medium" title="Zoom Out">&minus;</button>
      <button @click="fitView" class="w-8 h-8 flex items-center justify-center text-ink-600 hover:text-ink-900 hover:bg-ink-100 rounded text-xs" title="Fit to View">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4"/>
        </svg>
      </button>
    </div>

    <!-- Right Detail Drawer (Inspector) -->
    <transition
      enter-active-class="transform transition ease-out duration-200"
      enter-from-class="translate-x-full"
      enter-to-class="translate-x-0"
      leave-active-class="transform transition ease-in duration-150"
      leave-from-class="translate-x-0"
      leave-to-class="translate-x-full"
    >
      <aside
        v-if="selectedNode"
        class="absolute top-0 right-0 bottom-0 w-[420px] bg-canvas border-l border-hairline shadow-xl z-30 flex flex-col overflow-hidden"
      >
        <!-- Header -->
        <div class="p-5 border-b border-hairline flex items-center justify-between">
          <div class="space-y-1 pr-4">
            <div class="flex items-center space-x-2">
              <span class="text-[10px] font-mono tracking-wider uppercase px-2 py-0.5 rounded bg-ink-100 text-ink-700">
                {{ selectedNode.type }}
              </span>
              <span v-if="selectedNode.needs_review" class="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-100 text-amber-800 font-medium">
                Review Required
              </span>
            </div>
            <h3 class="text-base font-semibold text-ink-900 leading-snug">{{ selectedNode.label }}</h3>
          </div>
          <button @click="selectedNode = null" class="text-ink-400 hover:text-ink-700 p-1 rounded-md hover:bg-ink-50">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>

        <!-- Scrollable Content -->
        <div class="flex-1 overflow-y-auto p-5 space-y-6 text-xs">
          <!-- Concept Metadata -->
          <div v-if="selectedConceptDetails" class="space-y-3">
            <p v-if="selectedConceptDetails.description" class="text-ink-700 leading-relaxed italic bg-ink-50 p-3 rounded-md border border-hairline">
              "{{ selectedConceptDetails.description }}"
            </p>
            <div class="flex items-center space-x-4 text-ink-500 font-mono text-[11px]">
              <span>Degree: {{ selectedConceptDetails.degree }}</span>
              <span>Connections: {{ selectedPropositions.length }}</span>
            </div>
          </div>

          <!-- Connected Propositions -->
          <div class="space-y-3">
            <h4 class="text-xs font-semibold text-ink-900 uppercase tracking-wider">Verifiable Propositions</h4>
            <div v-if="selectedPropositions.length === 0" class="text-ink-400 italic py-2">
              No direct propositions connected to this entity.
            </div>
            <div
              v-for="prop in selectedPropositions"
              :key="prop.id"
              class="p-3 border border-hairline rounded-lg space-y-2 hover:border-ink-400 transition-colors"
            >
              <div class="flex items-center justify-between">
                <span class="font-medium text-ink-900">
                  <span class="text-ink-400">&rarr;</span> {{ prop.predicate }}
                </span>
                <span v-if="prop.has_conflict" class="text-[10px] px-1.5 py-0.5 bg-red-100 text-red-700 font-mono rounded">
                  Conflict
                </span>
              </div>
              <button
                @click="openEvidenceModal(prop.id)"
                class="text-xs text-ink-600 hover:text-ink-900 underline underline-offset-2 flex items-center space-x-1"
              >
                <span>View Exact Verbatim Proof</span>
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/>
                </svg>
              </button>
            </div>
          </div>

          <!-- Review State Action Cards -->
          <div v-if="selectedNode.needs_review" class="p-4 bg-amber-50 border border-amber-200 rounded-lg space-y-3">
            <div class="font-semibold text-amber-900 text-xs">Pending Review Decision</div>
            <p class="text-amber-800 text-[11px] leading-relaxed">
              This concept or associated relationship was flagged by the 4-dimension confidence pipeline for explicit confirmation.
            </p>
            <div class="flex space-x-2 pt-1">
              <button
                @click="resolveReviewItem(true)"
                class="px-3 py-1.5 bg-ink-900 hover:bg-ink-800 text-white rounded font-medium text-xs transition-colors"
              >
                Approve &amp; Canonicalize
              </button>
              <button
                @click="resolveReviewItem(false)"
                class="px-3 py-1.5 bg-canvas border border-amber-300 text-amber-900 hover:bg-amber-100 rounded text-xs transition-colors"
              >
                Dismiss
              </button>
            </div>
          </div>
        </div>
      </aside>
    </transition>

    <!-- Exact Verbatim Evidence Modal -->
    <div v-if="activeEvidence" class="fixed inset-0 z-50 flex items-center justify-center p-6 bg-black/30 backdrop-blur-sm">
      <div class="w-full max-w-xl bg-canvas border border-hairline rounded-xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh]">
        <!-- Modal Header -->
        <div class="p-4 border-b border-hairline flex items-center justify-between bg-ink-50">
          <div>
            <span class="text-[10px] font-mono uppercase text-ink-500">Source Evidence Provenance</span>
            <h4 class="text-sm font-semibold text-ink-900">{{ activeEvidence.document_title || 'Document Source' }}</h4>
          </div>
          <button @click="activeEvidence = null" class="text-ink-400 hover:text-ink-700 p-1 rounded-md">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>

        <!-- Evidence Body -->
        <div class="p-6 overflow-y-auto space-y-4">
          <div class="text-xs text-ink-500">Exact character span citation [{{ activeEvidence.char_start }}..{{ activeEvidence.char_end }}]:</div>
          <div class="p-4 bg-ink-50 border border-hairline rounded-lg font-mono text-xs leading-relaxed text-ink-800">
            <mark class="evidence-highlight">
              "{{ activeEvidence.quote }}"
            </mark>
          </div>
          <div class="text-[11px] text-ink-400">
            Every edge in Gusby is backed by mathematically verified substrings from the original source text.
          </div>
        </div>

        <!-- Modal Footer -->
        <div class="p-4 border-t border-hairline flex justify-end bg-canvas">
          <button @click="activeEvidence = null" class="px-4 py-1.5 bg-ink-900 hover:bg-ink-800 text-white rounded text-xs font-medium">
            Done
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import cytoscape from 'cytoscape'

interface NodeData {
  id: string
  label: string
  type: string
  needs_review?: boolean
  degree?: number
  x?: number
  y?: number
}

const cyContainer = ref<HTMLElement | null>(null)
let cy: cytoscape.Core | null = null

const loading = ref(true)
const nodeCount = ref(0)
const edgeCount = ref(0)
const reviewItemCount = ref(0)
const filterNeedsReview = ref(false)

const searchQuery = ref('')
const searchResults = ref<any[]>([])

const selectedNode = ref<NodeData | null>(null)
const selectedConceptDetails = ref<any>(null)
const selectedPropositions = ref<any[]>([])
const activeEvidence = ref<any>(null)

// Initialize & Load Graph
const loadGraphData = async () => {
  loading.value = true
  try {
    const res = await $fetch<any>('/api/graph', {
      params: {
        zoom: 'deep',
        needs_review: filterNeedsReview.value ? 'true' : 'false'
      },
      credentials: 'include'
    })

    const elements: any[] = []
    let reviewCount = 0

    if (res.nodes) {
      res.nodes.forEach((n: any) => {
        if (n.needs_review) reviewCount++
        elements.push({
          group: 'nodes',
          data: {
            id: n.id,
            label: n.label,
            type: n.type,
            needs_review: n.needs_review,
            degree: n.degree || 1
          }
        })
      })
    }

    if (res.edges) {
      res.edges.forEach((e: any) => {
        elements.push({
          group: 'edges',
          data: {
            id: e.id,
            source: e.source,
            target: e.target,
            label: e.label,
            has_conflict: e.has_conflict
          }
        })
      })
    }

    nodeCount.value = res.nodes?.length || 0
    edgeCount.value = res.edges?.length || 0
    reviewItemCount.value = reviewCount

    if (cy) {
      cy.elements().remove()
      cy.add(elements)
      applyLayout()
    }
  } catch (err) {
    console.error('Failed to load graph:', err)
  } finally {
    loading.value = false
  }
}

const initCytoscape = () => {
  if (!cyContainer.value) return

  cy = cytoscape({
    container: cyContainer.value,
    style: [
      {
        selector: 'node',
        style: {
          'background-color': '#F1F5F9',
          'border-width': 1.5,
          'border-color': '#64748B',
          'label': 'data(label)',
          'color': '#111827',
          'font-family': 'Inter, sans-serif',
          'font-size': '11px',
          'text-valign': 'bottom',
          'text-margin-y': 5,
          'width': 28,
          'height': 28
        }
      },
      {
        selector: 'node[type="topic"]',
        style: {
          'background-color': '#F8FAFC',
          'border-width': 2,
          'border-color': '#2C3E50',
          'font-size': '14px',
          'font-weight': 'bold',
          'width': 44,
          'height': 44
        }
      },
      {
        selector: 'node[?needs_review]',
        style: {
          'border-color': '#D97706',
          'border-width': 2.5,
          'background-color': '#FEF3C7'
        }
      },
      {
        selector: 'node:selected',
        style: {
          'border-color': '#111827',
          'border-width': 3
        }
      },
      {
        selector: 'edge',
        style: {
          'width': 1.2,
          'line-color': '#CBD5E1',
          'target-arrow-color': '#CBD5E1',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          'arrow-scale': 0.8
        }
      },
      {
        selector: 'edge[?has_conflict]',
        style: {
          'line-color': '#DC2626',
          'target-arrow-color': '#DC2626',
          'line-style': 'dashed'
        }
      }
    ],
    wheelSensitivity: 0.3
  })

  cy.on('tap', 'node', (evt) => {
    const node = evt.target
    selectedNode.value = node.data()
    loadNodeDetails(node.id())
  })

  cy.on('tap', (evt) => {
    if (evt.target === cy) {
      selectedNode.value = null
    }
  })
}

const applyLayout = () => {
  if (!cy || cy.elements().length === 0) return
  cy.layout({
    name: 'cose',
    animate: false,
    idealEdgeLength: 100,
    nodeOverlap: 20
  } as any).run()
}

const loadNodeDetails = async (nodeID: string) => {
  try {
    const res = await $fetch<any>(`/api/graph/concept/${nodeID}`, { credentials: 'include' })
    selectedConceptDetails.value = res.concept
    selectedPropositions.value = res.propositions || []
  } catch (err) {
    console.error('Failed to load concept details:', err)
  }
}

const openEvidenceModal = async (propID: string) => {
  try {
    const res = await $fetch<any>(`/api/graph/proposition/${propID}`, { credentials: 'include' })
    if (res.evidence && res.evidence.length > 0) {
      activeEvidence.value = res.evidence[0]
    }
  } catch (err) {
    console.error('Failed to load evidence:', err)
  }
}

const handleSearch = async () => {
  if (!searchQuery.value.trim()) {
    searchResults.value = []
    return
  }
  try {
    const res = await $fetch<any>('/api/graph/search', {
      params: { q: searchQuery.value },
      credentials: 'include'
    })
    searchResults.value = res.results || []
  } catch (err) {
    console.error('Search failed:', err)
  }
}

const selectSearchResult = (item: any) => {
  searchQuery.value = item.name
  searchResults.value = []
  if (cy) {
    const node = cy.getElementById(item.id)
    if (node.length > 0) {
      cy.animate({
        center: { eles: node },
        zoom: 1.5,
        duration: 300
      })
      node.select()
      selectedNode.value = node.data()
      loadNodeDetails(node.id())
    }
  }
}

const clearSearch = () => {
  searchQuery.value = ''
  searchResults.value = []
}

const toggleNeedsReview = () => {
  filterNeedsReview.value = !filterNeedsReview.value
  loadGraphData()
}

const resolveReviewItem = async (approve: boolean) => {
  // In-place review resolution
  selectedNode.value = null
  await loadGraphData()
}

const zoomIn = () => cy?.zoom(cy.zoom() * 1.3)
const zoomOut = () => cy?.zoom(cy.zoom() * 0.7)
const fitView = () => cy?.fit(undefined, 40)

onMounted(() => {
  initCytoscape()
  loadGraphData()
})
</script>
