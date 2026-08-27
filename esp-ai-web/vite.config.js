import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': { target: 'http://192.168.31.176:8088', changeOrigin: true, timeout: 60000 },
      '/health': { target: 'http://192.168.31.176:8088', changeOrigin: true },
      '/ws': { target: 'ws://192.168.31.176:8088', ws: true, changeOrigin: true }
    }
  }
})
