import { ref } from 'vue'
import { useRouter } from 'vue-router'

export interface User {
  id: string
  email: string
}

const currentUser = ref<User | null>(null)
const isLoaded = ref(false)

export const useAuth = () => {
  const router = useRouter()
  const config = useRuntimeConfig()
  const apiBase = config.public.apiBase ?? ''

  const fetchMe = async () => {
    try {
      const res = await $fetch<{ user: User }>(`${apiBase}/api/auth/me`, {
        credentials: 'include'
      })
      currentUser.value = res.user
      return res.user
    } catch (err) {
      currentUser.value = null
      return null
    } finally {
      isLoaded.value = true
    }
  }

  const login = async (email: string, password: string) => {
    const res = await $fetch<{ user: User }>(`${apiBase}/api/auth/login`, {
      method: 'POST',
      body: { email, password },
      credentials: 'include'
    })
    currentUser.value = res.user
    return res.user
  }

  const signup = async (email: string, password: string) => {
    const res = await $fetch<{ user: User }>(`${apiBase}/api/auth/signup`, {
      method: 'POST',
      body: { email, password },
      credentials: 'include'
    })
    currentUser.value = res.user
    return res.user
  }

  const logout = async () => {
    try {
      await $fetch(`${apiBase}/api/auth/logout`, {
        method: 'POST',
        credentials: 'include'
      })
    } finally {
      currentUser.value = null
      router.push('/auth/login')
    }
  }

  return {
    user: currentUser,
    isLoaded,
    fetchMe,
    login,
    signup,
    logout
  }
}
