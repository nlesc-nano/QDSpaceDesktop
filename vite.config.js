import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

const host = process.env.TAURI_DEV_HOST

export default defineConfig({
  plugins: [svelte()],
  publicDir: process.env.VITE_APP_TARGET === 'desktop' ? 'public-release' : 'public',
  // Prevent Vite from clearing screen when Tauri prints logs
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    host: host || false,
    hmr: host
      ? { protocol: 'ws', host, port: 1421 }
      : undefined,
    watch: {
      ignored: ['**/src-tauri/**', '**/sidecar/**', '**/upstream/**'],
    },
    proxy: {
      // Existing QDSpace backend (optional)
      '/api': 'http://127.0.0.1:8000',
    },
  },
  envPrefix: ['VITE_', 'TAURI_'],
})
