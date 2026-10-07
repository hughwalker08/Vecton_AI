/// <reference types="vitest/config" />
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
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
    css: true,
    // Default is 5000ms; give a slower/loaded CI runner some headroom over
    // the 5000ms asyncUtilTimeout set in src/test/setup.js.
    testTimeout: 10000,
    coverage: {
      provider: 'v8',
      // Vitest skips the coverage report entirely if any test fails, which
      // hides the numbers exactly when you're debugging. Always print them.
      reportOnFailure: true,
      reporter: ['text', 'html', 'lcov'],
      exclude: ['src/main.jsx', 'src/test/**'],
    },
  },
})
