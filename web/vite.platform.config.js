import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Design-preview build of the platform screens (mock data only). Kept separate
// from the dashboard build until F3 replaces the dashboard with these screens.
export default defineConfig({
  plugins: [react()],
  base: './',
  // In development the evidence API runs separately (uvicorn on :8000).
  server: { proxy: { '/api': 'http://localhost:8000', '/health': 'http://localhost:8000' } },
  build: { outDir: 'dist-platform', emptyOutDir: true, chunkSizeWarningLimit: 1200, rollupOptions: { input: 'platform.html' } },
})
