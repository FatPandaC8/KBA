export default defineNuxtRouteMiddleware(async (to) => {
  // Allow public auth routes
  if (to.path.startsWith('/auth/')) {
    return
  }

  const { user, isLoaded, fetchMe } = useAuth()
  if (!isLoaded.value) {
    await fetchMe()
  }

  if (!user.value) {
    return navigateTo('/auth/login')
  }
})
