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
      '/api': 'http://localhost:8000',
      '/auth': 'http://localhost:8000',
      '/home': 'http://localhost:8000',
      '/search': 'http://localhost:8000',
      '/tracks': 'http://localhost:8000',
      '/albums': 'http://localhost:8000',
      '/artists': 'http://localhost:8000',
      '/playlists': 'http://localhost:8000',
      '/library': 'http://localhost:8000',
      '/history': 'http://localhost:8000',
      '/resource': 'http://localhost:8000',
      '/covers': 'http://localhost:8000',
      '/queue': 'http://localhost:8000',
      '/admin': 'http://localhost:8000',
      '/plugins': 'http://localhost:8000',
    }
  },
  build: {
    outDir: 'dist',
  },
})
