import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vuetify from 'vite-plugin-vuetify'

const apiProxy = process.env.VITE_API_PROXY || 'http://localhost:5005'
const preferredPort = Number(process.env.VITE_PORT || process.env.PORT || 5173) || 5173

export default defineConfig({
  plugins: [
    vue(),
    vuetify({ autoImport: true }),
  ],
  server: {
    port: preferredPort,
    strictPort: false,
    proxy: {
      '/api': {
        target: apiProxy,
        changeOrigin: true,
      },
    },
  },
})
