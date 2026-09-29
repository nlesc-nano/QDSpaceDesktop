/**
 * Detect desktop / Tauri build so Predict UI is gated out of plain web builds.
 * Prefer VITE_APP_TARGET=desktop; also honor Tauri-injected env / globals.
 */
export function isDesktopApp() {
  try {
    if (import.meta.env?.VITE_APP_TARGET === 'desktop') return true;
    if (import.meta.env?.TAURI_ENV_PLATFORM) return true;
    if (typeof window !== 'undefined') {
      if (window.__TAURI_INTERNALS__ || window.__TAURI__) return true;
    }
  } catch (_) {
    /* ignore */
  }
  return false;
}

export const SIDECAR_BASE =
  import.meta.env?.VITE_SIDECAR_URL || 'http://127.0.0.1:8765';
