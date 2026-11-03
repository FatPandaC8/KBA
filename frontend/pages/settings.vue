<template>
  <div class="h-full overflow-y-auto px-6 py-10 max-w-4xl mx-auto">
    <!-- Header -->
    <div class="mb-8">
      <h1 class="text-2xl font-serif font-bold text-ink-900 tracking-tight">Settings & Preferences</h1>
      <p class="text-sm text-ink-500 mt-1">
        Configure visual appearance, account credentials, and data management.
      </p>
    </div>

    <div class="space-y-8">
      <!-- Section 1: Appearance & Earthy Palette -->
      <section class="bg-canvas border border-hairline rounded-xl p-6 shadow-sm">
        <h2 class="text-base font-semibold text-ink-900 mb-1">Appearance & Earthy Preset Palette</h2>
        <p class="text-xs text-ink-500 mb-5">
          Gusby adheres strictly to pure white canvas and intellectual, earthy palettes. Select your workspace accent style.
        </p>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div
            v-for="palette in PALETTES"
            :key="palette.id"
            @click="setPalette(palette.id)"
            class="p-4 rounded-xl border-2 cursor-pointer transition-all flex items-start space-x-3.5 relative"
            :class="currentPalette === palette.id ? 'border-ink-900 bg-stone-50/60 shadow-sm' : 'border-hairline hover:border-ink-300 bg-canvas'"
          >
            <!-- Palette Color Swatch Preview -->
            <div
              class="w-10 h-10 rounded-lg flex-shrink-0 flex items-center justify-center border border-hairline"
              :style="{ backgroundColor: palette.nodeFill }"
            >
              <div
                class="w-4 h-4 rounded-full"
                :style="{ backgroundColor: palette.accentColor }"
              ></div>
            </div>

            <!-- Palette Details -->
            <div class="flex-1 min-w-0">
              <div class="flex items-center justify-between">
                <h3 class="text-sm font-medium text-ink-900">{{ palette.name }}</h3>
                <span
                  v-if="currentPalette === palette.id"
                  class="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-ink-900 text-canvas font-medium"
                >
                  Active
                </span>
              </div>
              <p class="text-xs text-ink-500 mt-1 leading-relaxed">
                {{ palette.description }}
              </p>
            </div>
          </div>
        </div>
      </section>

      <!-- Section 2: Account & Security -->
      <section class="bg-canvas border border-hairline rounded-xl p-6 shadow-sm">
        <h2 class="text-base font-semibold text-ink-900 mb-1">Account & Security</h2>
        <p class="text-xs text-ink-500 mb-5">
          Your knowledge graph is private and isolated to your account.
        </p>

        <!-- Current User Info -->
        <div class="mb-6 p-4 rounded-lg bg-stone-50 border border-hairline flex items-center justify-between">
          <div>
            <div class="text-[11px] font-semibold text-ink-400 uppercase tracking-wider">Signed In As</div>
            <div class="text-sm font-medium text-ink-900 mt-0.5">{{ user?.email || 'Loading...' }}</div>
          </div>
          <button
            @click="logout"
            class="px-3.5 py-1.5 border border-hairline bg-canvas hover:bg-red-50 hover:text-red-600 hover:border-red-200 text-xs font-medium text-ink-700 rounded-md transition-colors"
          >
            Sign Out
          </button>
        </div>

        <!-- Change Password Form -->
        <div class="border-t border-hairline pt-6">
          <h3 class="text-sm font-semibold text-ink-900 mb-3">Change Password</h3>

          <div
            v-if="passwordSuccess"
            class="mb-4 p-3 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs flex items-center justify-between"
          >
            <span>Password updated successfully.</span>
            <button @click="passwordSuccess = false" class="text-emerald-600 hover:text-emerald-800">&times;</button>
          </div>

          <div
            v-if="passwordError"
            class="mb-4 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs flex items-center justify-between"
          >
            <span>{{ passwordError }}</span>
            <button @click="passwordError = ''" class="text-red-500 hover:text-red-700">&times;</button>
          </div>

          <form @submit.prevent="handleChangePassword" class="space-y-4 max-w-md">
            <div>
              <label class="block text-xs font-semibold text-ink-700 uppercase tracking-wider mb-1">
                Current Password
              </label>
              <input
                v-model="passwordForm.currentPassword"
                type="password"
                required
                class="w-full px-3.5 py-2 text-sm bg-canvas border border-hairline rounded-lg focus:outline-none focus:border-ink-900 transition-colors"
              />
            </div>
            <div>
              <label class="block text-xs font-semibold text-ink-700 uppercase tracking-wider mb-1">
                New Password (minimum 8 characters)
              </label>
              <input
                v-model="passwordForm.newPassword"
                type="password"
                required
                minlength="8"
                class="w-full px-3.5 py-2 text-sm bg-canvas border border-hairline rounded-lg focus:outline-none focus:border-ink-900 transition-colors"
              />
            </div>
            <div>
              <label class="block text-xs font-semibold text-ink-700 uppercase tracking-wider mb-1">
                Confirm New Password
              </label>
              <input
                v-model="passwordForm.confirmPassword"
                type="password"
                required
                class="w-full px-3.5 py-2 text-sm bg-canvas border border-hairline rounded-lg focus:outline-none focus:border-ink-900 transition-colors"
              />
            </div>

            <button
              type="submit"
              :disabled="isUpdatingPassword"
              class="px-4 py-2 bg-ink-900 text-canvas rounded-lg text-xs font-medium hover:bg-ink-800 disabled:opacity-50 transition-colors"
            >
              {{ isUpdatingPassword ? 'Updating Password...' : 'Update Password' }}
            </button>
          </form>
        </div>
      </section>

      <!-- Section 3: Data Management (Planned / Needs Research) -->
      <section class="bg-canvas border border-hairline rounded-xl p-6 shadow-sm">
        <div class="flex items-center space-x-2 mb-1">
          <h2 class="text-base font-semibold text-ink-900">Data Management</h2>
          <span class="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-stone-100 text-ink-500 font-medium">
            Planned &bull; Needs Research
          </span>
        </div>
        <p class="text-xs text-ink-500 mb-6">
          Advanced account governance features per the Gusby Architecture roadmap.
        </p>

        <div class="space-y-4">
          <!-- Export Data Card -->
          <div class="p-4 rounded-lg border border-hairline bg-stone-50/50 flex items-center justify-between opacity-80">
            <div>
              <h4 class="text-xs font-semibold text-ink-800">Export Knowledge Graph (JSON / RDF)</h4>
              <p class="text-[11px] text-ink-400 mt-0.5">
                Download your canonical concepts, propositions, and verbatim evidence citations.
              </p>
            </div>
            <button
              disabled
              class="px-3 py-1.5 border border-hairline text-ink-400 rounded-md text-xs font-medium cursor-not-allowed bg-stone-100"
            >
              Export Planned
            </button>
          </div>

          <!-- Account Deletion Card -->
          <div class="p-4 rounded-lg border border-red-100 bg-red-50/30 flex items-center justify-between opacity-80">
            <div>
              <h4 class="text-xs font-semibold text-red-900">Delete Account & Purge Knowledge Space</h4>
              <p class="text-[11px] text-red-600 mt-0.5">
                Permanently cascades and deletes all documents, concepts, propositions, and sessions from PostgreSQL.
              </p>
            </div>
            <button
              disabled
              class="px-3 py-1.5 border border-red-200 text-red-400 rounded-md text-xs font-medium cursor-not-allowed bg-white"
            >
              Purge Planned
            </button>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { usePalette, PALETTES } from '~/composables/usePalette'
import { useAuth } from '~/composables/useAuth'

const { currentPalette, setPalette } = usePalette()
const { user, logout } = useAuth()

const passwordForm = ref({
  currentPassword: '',
  newPassword: '',
  confirmPassword: ''
})

const isUpdatingPassword = ref(false)
const passwordSuccess = ref(false)
const passwordError = ref('')

async function handleChangePassword() {
  passwordError.value = ''
  passwordSuccess.value = false

  if (passwordForm.value.newPassword !== passwordForm.value.confirmPassword) {
    passwordError.value = 'New passwords do not match'
    return
  }

  if (passwordForm.value.newPassword.length < 8) {
    passwordError.value = 'New password must be at least 8 characters long'
    return
  }

  isUpdatingPassword.value = true
  try {
    const res = await fetch('/api/auth/password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        current_password: passwordForm.value.currentPassword,
        new_password: passwordForm.value.newPassword
      })
    })

    const data = await res.json()
    if (!res.ok) {
      passwordError.value = data.error?.message || data.message || 'Failed to update password'
      return
    }

    passwordSuccess.value = true
    passwordForm.value = {
      currentPassword: '',
      newPassword: '',
      confirmPassword: ''
    }
  } catch (err: any) {
    passwordError.value = err.message || 'Network error updating password'
  } finally {
    isUpdatingPassword.value = false
  }
}
</script>
