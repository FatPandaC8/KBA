<template>
  <div class="flex h-screen w-screen bg-canvas overflow-hidden font-sans text-ink-900 select-none">
    <!-- Compact Icon Sidebar (56px) -->
    <aside class="w-14 h-full border-r border-hairline flex flex-col justify-between items-center py-4 bg-canvas z-30 flex-shrink-0">
      <!-- Top Group: Logo & Primary Nav -->
      <div class="flex flex-col items-center space-y-6 w-full">
        <!-- Gusby Logo Mark -->
        <NuxtLink to="/" class="group relative flex items-center justify-center w-9 h-9 rounded-lg hover:bg-ink-100 transition-colors">
          <div class="w-5 h-5 rounded-full border-2 border-ink-900 flex items-center justify-center group-hover:scale-105 transition-transform">
            <div class="w-1.5 h-1.5 rounded-full bg-ink-900"></div>
          </div>
          <span class="sr-only">Gusby</span>
        </NuxtLink>

        <!-- Navigation Links -->
        <nav class="flex flex-col items-center space-y-2 w-full px-2">
          <!-- Knowledge Space -->
          <NuxtLink
            to="/"
            class="relative flex items-center justify-center w-10 h-10 rounded-md transition-colors"
            :class="route.path === '/' ? 'text-ink-900 bg-ink-100 font-medium' : 'text-ink-400 hover:text-ink-800 hover:bg-ink-50'"
            title="Knowledge Space"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="3" stroke-width="1.8"/>
              <circle cx="6" cy="6" r="2" stroke-width="1.8"/>
              <circle cx="18" cy="7" r="2" stroke-width="1.8"/>
              <circle cx="16" cy="18" r="2" stroke-width="1.8"/>
              <circle cx="6" cy="16" r="2" stroke-width="1.8"/>
              <path stroke-width="1.4" d="M8 7.5l2.5 3M16 8.5l-2.5 2.5M7.5 15l3-2M14.5 16.5l-2-3"/>
            </svg>
            <div v-if="route.path === '/'" class="absolute left-0 w-0.5 h-5 bg-ink-900 rounded-r"></div>
          </NuxtLink>

          <!-- Add Knowledge -->
          <NuxtLink
            to="/add"
            class="relative flex items-center justify-center w-10 h-10 rounded-md transition-colors"
            :class="route.path === '/add' ? 'text-ink-900 bg-ink-100 font-medium' : 'text-ink-400 hover:text-ink-800 hover:bg-ink-50'"
            title="Add Knowledge"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M12 4v16m8-8H4"/>
            </svg>
            <div v-if="route.path === '/add'" class="absolute left-0 w-0.5 h-5 bg-ink-900 rounded-r"></div>
          </NuxtLink>

          <!-- Documents -->
          <NuxtLink
            to="/documents"
            class="relative flex items-center justify-center w-10 h-10 rounded-md transition-colors"
            :class="route.path === '/documents' ? 'text-ink-900 bg-ink-100 font-medium' : 'text-ink-400 hover:text-ink-800 hover:bg-ink-50'"
            title="Documents"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M4 6h16M4 12h16M4 18h11"/>
            </svg>
            <div v-if="route.path === '/documents'" class="absolute left-0 w-0.5 h-5 bg-ink-900 rounded-r"></div>
          </NuxtLink>

          <!-- Admin Dashboard (Only shown if user is admin) -->
          <NuxtLink
            v-if="currentUser?.is_admin"
            to="/admin"
            class="relative flex items-center justify-center w-10 h-10 rounded-md transition-colors"
            :class="route.path.startsWith('/admin') ? 'text-indigo-600 bg-indigo-50 font-medium' : 'text-ink-400 hover:text-indigo-600 hover:bg-indigo-50/50'"
            title="Admin Dashboard"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/>
            </svg>
            <div v-if="route.path.startsWith('/admin')" class="absolute left-0 w-0.5 h-5 bg-indigo-600 rounded-r"></div>
          </NuxtLink>
        </nav>
      </div>

      <!-- Bottom Group: Settings & Logout -->
      <div class="flex flex-col items-center space-y-3 w-full px-2">
        <!-- Settings -->
        <NuxtLink
          to="/settings"
          class="relative flex items-center justify-center w-10 h-10 rounded-md transition-colors"
          :class="route.path === '/settings' ? 'text-ink-900 bg-ink-100 font-medium' : 'text-ink-400 hover:text-ink-800 hover:bg-ink-50'"
          title="Settings"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
            <circle cx="12" cy="12" r="3" stroke-width="1.8"/>
          </svg>
          <div v-if="route.path === '/settings'" class="absolute left-0 w-0.5 h-5 bg-ink-900 rounded-r"></div>
        </NuxtLink>

        <!-- User Logout Button -->
        <button
          @click="logout"
          class="flex items-center justify-center w-9 h-9 rounded-md text-ink-400 hover:text-red-600 hover:bg-red-50 transition-colors"
          title="Sign Out"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/>
          </svg>
        </button>
      </div>
    </aside>

    <!-- Main Workspace -->
    <main class="flex-1 h-full overflow-hidden relative bg-canvas">
      <slot />
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useAuth } from '~/composables/useAuth'
import { usePalette } from '~/composables/usePalette'

const route = useRoute()
const { currentUser, logout } = useAuth()
const { initPalette } = usePalette()

onMounted(() => {
  initPalette()
})
</script>
