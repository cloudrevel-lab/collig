import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vuetify from 'vite-plugin-vuetify'

const apiProxy = process.env.VITE_API_PROXY || 'http://localhost:5006'
const preferredPort = Number(process.env.VITE_TERMINAL_PORT || 5174) || 5174

// Terminal-only build.  It shares TerminalView.vue and the Vuetify theme with
// the full console, but emits just terminal.html + its assets so the
// standalone FastAPI app (core.terminal_app) can serve a tiny surface.
export default defineConfig({
  plugins: [
    vue(),
    vuetify({ autoImport: true }),
  ],
  build: {
    outDir: 'dist-terminal',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        terminal: fileURLToPath(new URL('./terminal.html', import.meta.url)),
      },
    },
  },
  server: {
    port: preferredPort,
    strictPort: false,
    proxy: {
      '/api': {
        target: apiProxy,
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
