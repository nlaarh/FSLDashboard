import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      '/api': 'http://localhost:8000',
      '/login': 'http://localhost:8000',
      '/forgot-password': 'http://localhost:8000',
      '/reset-password': 'http://localhost:8000',
      '/track/': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
