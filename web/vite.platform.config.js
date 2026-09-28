import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Design-preview build of the platform screens (mock data only). Kept separate
// from the dashboard build until F3 replaces the dashboard with these screens.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: { outDir: 'dist-platform', emptyOutDir: true, rollupOptions: { input: 'platform.html' } },
})
