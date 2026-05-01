/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.{test,spec}.{js,jsx}'],
  },
  server: {
    proxy: {
      '/rest': 'http://localhost:8000',
      '/resource': 'http://localhost:8000',
      '/covers': 'http://localhost:8000',
    }
  },
  build: {
    outDir: 'dist',
  },
})
