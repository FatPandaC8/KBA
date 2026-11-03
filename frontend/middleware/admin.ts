export default defineNuxtRouteMiddleware(async (to) => {
  const { currentUser, fetchMe, isLoaded } = useAuth()

  if (!isLoaded.value) {
    await fetchMe()
  }

  if (!currentUser.value || !currentUser.value.is_admin) {
    // Raise 404 so non-admins cannot discover administrative routes exist
    throw createError({
      statusCode: 404,
      statusMessage: 'Page Not Found',
      fatal: true
    })
  }
})
