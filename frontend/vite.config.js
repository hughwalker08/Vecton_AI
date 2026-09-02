import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Proxies API calls to the FastAPI backend during local dev.
      '/api': 'http://localhost:8000',
    },
  },
})
