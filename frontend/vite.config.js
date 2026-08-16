import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // Dev-only proxy so the browser talks to one origin and CORS stays simple.
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
