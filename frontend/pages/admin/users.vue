<template>
  <div class="min-h-full bg-slate-50 flex flex-col">
    <AdminNav />

    <main class="flex-1 max-w-7xl w-full mx-auto p-6 md:p-8 space-y-6">
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 class="text-xl font-bold text-slate-900 tracking-tight">User Management</h1>
          <p class="text-xs text-slate-500 mt-1">Audit accounts, manage access status, reset quota limits, or execute permanent account deletions.</p>
        </div>
        <div class="flex items-center space-x-3">
          <input
            v-model="searchQuery"
            @keyup.enter="fetchUsers"
            type="text"
            placeholder="Search email..."
            class="px-3 py-1.5 text-xs rounded-lg border border-slate-200 bg-white focus:outline-hidden focus:ring-2 focus:ring-indigo-500 w-64 shadow-2xs"
          />
          <select
            v-model="statusFilter"
            @change="fetchUsers"
            class="px-3 py-1.5 text-xs rounded-lg border border-slate-200 bg-white focus:outline-hidden focus:ring-2 focus:ring-indigo-500 shadow-2xs"
          >
            <option value="">All Statuses</option>
            <option value="active">Active</option>
            <option value="suspended">Suspended</option>
          </select>
        </div>
      </div>

      <!-- Users Table -->
      <div class="bg-white rounded-xl border border-slate-200/80 shadow-2xs overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full text-left text-xs">
            <thead class="bg-slate-50/80 border-b border-slate-200/60 text-slate-500 font-medium">
              <tr>
                <th class="px-4 py-3">Email</th>
                <th class="px-4 py-3">Status</th>
                <th class="px-4 py-3">Role</th>
                <th class="px-4 py-3">Created</th>
                <th class="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100">
              <tr v-if="users.length === 0" class="text-center text-slate-400 py-8">
                <td colspan="5" class="py-8">No users found matching query.</td>
              </tr>
              <tr v-for="u in users" :key="u.id" class="hover:bg-slate-50/50 transition-colors">
                <td class="px-4 py-3 font-medium text-slate-900">
                  <div class="flex items-center space-x-2">
                    <span>{{ u.email }}</span>
                    <span v-if="u.id === currentUser?.id" class="text-3xs px-1.5 py-0.2 rounded bg-indigo-50 text-indigo-700 font-semibold">(You)</span>
                  </div>
                  <span class="text-2xs text-slate-400 font-mono">{{ u.id }}</span>
                </td>
                <td class="px-4 py-3">
                  <span class="px-2 py-0.5 rounded-full text-2xs font-semibold capitalize" :class="u.status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'">
                    {{ u.status }}
                  </span>
                </td>
                <td class="px-4 py-3">
                  <span v-if="u.is_admin" class="px-2 py-0.5 rounded text-2xs font-bold bg-indigo-50 text-indigo-700">Admin</span>
                  <span v-else class="text-slate-500">Member</span>
                </td>
                <td class="px-4 py-3 text-slate-500 text-2xs">
                  {{ formatDate(u.created_at) }}
                </td>
                <td class="px-4 py-3 text-right space-x-2">
                  <!-- Suspend / Unsuspend -->
                  <button
                    v-if="u.status === 'active' && u.id !== currentUser?.id"
                    @click="suspendUser(u)"
                    class="px-2.5 py-1 rounded text-2xs font-medium text-amber-700 hover:bg-amber-50 transition-colors"
                  >
                    Suspend
                  </button>
                  <button
                    v-if="u.status === 'suspended'"
                    @click="unsuspendUser(u)"
                    class="px-2.5 py-1 rounded text-2xs font-medium text-emerald-700 hover:bg-emerald-50 transition-colors"
                  >
                    Unsuspend
                  </button>

                  <!-- Reset Limits -->
                  <button
                    @click="resetLimits(u)"
                    class="px-2.5 py-1 rounded text-2xs font-medium text-slate-700 hover:bg-slate-100 transition-colors"
                    title="Reset API rate and token usage limits"
                  >
                    Reset Limits
                  </button>

                  <!-- Delete User -->
                  <button
                    v-if="u.id !== currentUser?.id"
                    @click="openDeleteModal(u)"
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

      <!-- Typed Confirmation Modal for User Delete -->
      <div v-if="deleteTarget" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
        <div class="bg-white rounded-xl shadow-xl max-w-md w-full p-6 space-y-4 border border-rose-200">
          <div class="flex items-center space-x-3 text-rose-600">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
            </svg>
            <h3 class="text-base font-bold text-slate-900">Permanent User Deletion</h3>
          </div>

          <p class="text-xs text-slate-600 leading-relaxed">
            This action is <strong>irreversible</strong>. Deleting <span class="font-mono text-slate-900 font-semibold">{{ deleteTarget.email }}</span> will permanently purge all associated documents, extraction runs, concepts, propositions, and session tokens.
          </p>

          <div>
            <label class="block text-2xs font-semibold text-slate-700 mb-1">
              Type <span class="font-mono text-rose-600 select-all">{{ deleteTarget.email }}</span> to confirm:
            </label>
            <input
              v-model="deleteConfirmInput"
              type="text"
              class="w-full px-3 py-2 text-xs rounded-lg border border-slate-300 font-mono focus:ring-2 focus:ring-rose-500 focus:outline-hidden"
              placeholder="Enter exact email"
            />
          </div>

          <div>
            <label class="block text-2xs font-semibold text-slate-700 mb-1">Reason for deletion:</label>
            <input
              v-model="deleteReasonInput"
              type="text"
              class="w-full px-3 py-1.5 text-xs rounded-lg border border-slate-300 focus:outline-hidden"
              placeholder="e.g. GDPR Request / Abuse"
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
              @click="confirmDeleteUser"
              :disabled="deleteConfirmInput !== deleteTarget.email || deleting"
              class="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-rose-600 text-white hover:bg-rose-700 disabled:opacity-40 disabled:cursor-not-allowed shadow-2xs"
            >
              {{ deleting ? 'Purging Data...' : 'Permanently Delete User' }}
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

const { currentUser } = useAuth()
const loading = ref(false)
const searchQuery = ref('')
const statusFilter = ref('')
const users = ref<any[]>([])

const deleteTarget = ref<any>(null)
const deleteConfirmInput = ref('')
const deleteReasonInput = ref('')
const deleting = ref(false)

const formatDate = (isoStr: string) => {
  if (!isoStr) return ''
  const d = new Date(isoStr)
  return d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })
}

const fetchUsers = async () => {
  loading.value = true
  try {
    const params = new URLSearchParams()
    if (searchQuery.value) params.set('q', searchQuery.value)
    if (statusFilter.value) params.set('status', statusFilter.value)
    const res = await $fetch<any>(`/api/admin/users?${params.toString()}`)
    users.value = res.users || []
  } catch (err) {
    console.error('Failed to list users:', err)
  } finally {
    loading.value = false
  }
}

const suspendUser = async (u: any) => {
  const reason = prompt(`Reason for suspending ${u.email}:`, 'Policy violation')
  if (reason === null) return
  try {
    await $fetch(`/api/admin/users/${u.id}/suspend`, {
      method: 'POST',
      body: { reason }
    })
    await fetchUsers()
  } catch (err: any) {
    alert('Failed to suspend: ' + (err?.data?.error?.message || err.message))
  }
}

const unsuspendUser = async (u: any) => {
  try {
    await $fetch(`/api/admin/users/${u.id}/unsuspend`, { method: 'POST' })
    await fetchUsers()
  } catch (err: any) {
    alert('Failed to unsuspend: ' + (err?.data?.error?.message || err.message))
  }
}

const resetLimits = async (u: any) => {
  try {
    await $fetch(`/api/admin/users/${u.id}/reset-limits`, { method: 'POST' })
    alert(`Quota and rate limits reset for ${u.email}`)
  } catch (err: any) {
    alert('Failed to reset limits: ' + (err?.data?.error?.message || err.message))
  }
}

const openDeleteModal = (u: any) => {
  deleteTarget.value = u
  deleteConfirmInput.value = ''
  deleteReasonInput.value = 'Administrative deletion'
}

const closeDeleteModal = () => {
  deleteTarget.value = null
  deleteConfirmInput.value = ''
}

const confirmDeleteUser = async () => {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await $fetch(`/api/admin/users/${deleteTarget.value.id}`, {
      method: 'DELETE',
      body: {
        confirm_email: deleteConfirmInput.value,
        reason: deleteReasonInput.value
      }
    })
    closeDeleteModal()
    await fetchUsers()
  } catch (err: any) {
    alert('Failed to delete user: ' + (err?.data?.error?.message || err.message))
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  fetchUsers()
})
</script>
