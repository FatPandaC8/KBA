<template>
  <div class="min-h-screen w-full flex items-center justify-center bg-canvas p-6 font-sans select-none">
    <div class="w-full max-w-sm flex flex-col space-y-8">
      <!-- Brand Header -->
      <div class="flex flex-col items-center space-y-3 text-center">
        <div class="w-10 h-10 rounded-full border-2 border-ink-900 flex items-center justify-center">
          <div class="w-2.5 h-2.5 rounded-full bg-ink-900"></div>
        </div>
        <h1 class="text-xl font-semibold tracking-tight text-ink-900">Sign in to Gusby</h1>
        <p class="text-xs text-ink-600">Verifiable, evidence-backed knowledge graphs.</p>
      </div>

      <!-- Error Alert -->
      <div v-if="error" class="p-3 text-xs bg-red-50 border border-red-200 text-red-700 rounded-md">
        {{ error }}
      </div>

      <!-- Form -->
      <form @submit.prevent="handleLogin" class="space-y-4">
        <div>
          <label class="block text-xs font-medium text-ink-700 mb-1">Email address</label>
          <input
            v-model="email"
            type="email"
            required
            placeholder="you@domain.com"
            class="w-full px-3 py-2 text-sm bg-canvas border border-hairline rounded-md focus:outline-none focus:border-ink-900 text-ink-900 transition-colors"
          />
        </div>

        <div>
          <label class="block text-xs font-medium text-ink-700 mb-1">Password</label>
          <input
            v-model="password"
            type="password"
            required
            placeholder="••••••••"
            class="w-full px-3 py-2 text-sm bg-canvas border border-hairline rounded-md focus:outline-none focus:border-ink-900 text-ink-900 transition-colors"
          />
        </div>

        <button
          type="submit"
          :disabled="loading"
          class="w-full py-2 px-4 text-xs font-medium bg-ink-900 hover:bg-ink-800 text-white rounded-md transition-colors disabled:opacity-50"
        >
          <span v-if="loading">Signing in...</span>
          <span v-else>Continue</span>
        </button>
      </form>

      <!-- Toggle to Sign Up -->
      <div class="text-center text-xs text-ink-600">
        Don't have an account?
        <NuxtLink to="/auth/signup" class="text-ink-900 font-medium underline underline-offset-4 hover:text-black">
          Create one
        </NuxtLink>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '~/composables/useAuth'

definePageMeta({
  layout: false
})

const email = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

const router = useRouter()
const { login } = useAuth()

const handleLogin = async () => {
  loading.value = true
  error.value = ''
  try {
    await login(email.value, password.value)
    router.push('/')
  } catch (err: any) {
    error.value = err?.data?.error?.message || 'Invalid email or password'
  } finally {
    loading.value = false
  }
}
</script>
