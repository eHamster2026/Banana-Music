/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const proxyTarget = process.env.BANANA_DEV_PROXY_TARGET || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.{test,spec}.{js,jsx}'],
  },
  server: {
    proxy: {
      '/rest': proxyTarget,
      '/resource': proxyTarget,
      '/covers': proxyTarget,
    }
  },
  build: {
    outDir: 'dist',
  },
})
