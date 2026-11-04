// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  ssr: false,
  devtools: { enabled: false },
  devServer: {
    host: '0.0.0.0',
    port: 3000
  },
  modules: ['@nuxtjs/tailwindcss'],
  css: ['~/assets/css/main.css'],
  runtimeConfig: {
    public: {
      apiBase: process.env.GUSBY_API_BASE || ''
    }
  },
  routeRules: {
    '/api/**': {
      proxy: `${process.env.GUSBY_BACKEND_URL || 'http://127.0.0.1:8081'}/api/**`
    }
  },
  nitro: {
    devProxy: {
      '/api': {
        target: `${process.env.GUSBY_BACKEND_URL || 'http://127.0.0.1:8081'}/api`,
        changeOrigin: true
      }
    }
  },
  app: {
    head: {
      title: 'Gusby — Text-to-Knowledge-Graph',
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'description', content: 'Transform text, URLs, and files into connected, structured, trustworthy knowledge.' }
      ],
      link: [
        { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
        { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: '' },
        { rel: 'stylesheet', href: 'https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap' }
      ]
    }
  }
})
