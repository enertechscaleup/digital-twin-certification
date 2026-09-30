import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the API runs separately (uvicorn on :8000); in production
// FastAPI serves the built files and the API from the same origin.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': 'http://localhost:8000', '/health': 'http://localhost:8000' } },
  // Two pages: the platform at / and the original dashboard at /legacy/ (kept for the
  // side-by-side parity check until the platform replaces it).
  build: {
    outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 1200,
    rollupOptions: { input: { main: 'index.html', legacy: 'legacy/index.html' } },
  },
})
