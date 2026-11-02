/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./components/**/*.{js,vue,ts}",
    "./layouts/**/*.vue",
    "./pages/**/*.vue",
    "./plugins/**/*.{js,ts}",
    "./app.vue",
    "./error.vue"
  ],
  theme: {
    extend: {
      colors: {
        canvas: '#FFFFFF',
        hairline: '#E5E7EB',
        ink: {
          900: '#111827',
          800: '#1F2937',
          700: '#374151',
          600: '#4B5563',
          400: '#9CA3AF',
          200: '#E5E7EB',
          100: '#F3F4F6',
          50: '#F9FAFB'
        },
        slate: {
          accent: '#2C3E50',
          node: '#64748B',
          fill: '#F1F5F9'
        },
        terracotta: {
          accent: '#9C4221',
          node: '#C05621',
          fill: '#FDF2E9'
        },
        moss: {
          accent: '#2D3B2D',
          node: '#5A6B5C',
          fill: '#F4F7F4'
        },
        ochre: {
          accent: '#6B4F1D',
          node: '#9A7B38',
          fill: '#FAF6ED'
        }
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace']
      }
    }
  },
  plugins: []
}
