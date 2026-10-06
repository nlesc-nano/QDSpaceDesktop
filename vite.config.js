import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import { existsSync } from 'node:fs'

const host = process.env.TAURI_DEV_HOST

export default defineConfig(({ command }) => {
  const desktop = process.env.VITE_APP_TARGET === 'desktop'
  // Installer builds use the staged catalog. Dev (and a build before staging)
  // serves public/, which is where the header logo and favicon actually live.
  const publicDir = desktop && command === 'build' && existsSync('public-release')
    ? 'public-release'
    : 'public'

  return {
    plugins: [svelte()],
    publicDir,
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
        ignored: [
          '**/src-tauri/**', '**/sidecar/**', '**/upstream/**',
          // Packed Python runtimes: tens of thousands of files Vite must not watch
          '**/mace-runtime/**', '**/builder-runtime/**', '**/builder-sidecar/**',
          '**/public-release/**',
        ],
      },
      proxy: {
        // Existing QDSpace backend (optional)
        '/api': 'http://127.0.0.1:8000',
      },
    },
    // Only scan the app's own entry for deps, never HTML files inside the packed runtimes
    optimizeDeps: { entries: ['index.html'] },
    envPrefix: ['VITE_', 'TAURI_'],
  }
})
