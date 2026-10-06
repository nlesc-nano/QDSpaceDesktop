/**
 * On-demand access to Library files (structures, MD trajectories, property plots).
 *
 * The installer ships only the catalog JSONs. Structure files live on the public
 * QDSpace site under the same relative paths as in library_index.json. Lookup order:
 *   1. in-memory session cache
 *   2. desktop disk cache (Tauri: <app data>/library-cache/<relative path>)
 *   3. the file served next to the app (dev/web), only if its content is valid
 *   4. download from REMOTE_BASE (CloudFront host as fallback), validate, cache
 * Invalid content (the app's own index.html, 404 pages, non-XYZ text) is never returned.
 */
import { isDesktopApp } from './desktop.js';

export const REMOTE_BASE = 'https://quantumdotspace.org';
export const REMOTE_FALLBACK = 'https://dmq59n0f96mxz.cloudfront.net';
const REMOTE_HOSTS = [REMOTE_BASE, REMOTE_FALLBACK];

const ALWAYS_KEY = 'qdspace.library.alwaysDownload';

// ---------------------------------------------------------------- paths / URLs

/** "II-VI/CdSe/.../relaxed.xyz" with no leading slash, no "." / ".." segments. */
export function normalizeLibraryPath(path) {
  const raw = String(path ?? '').trim().replace(/\\/g, '/').replace(/^\/+/, '');
  const parts = raw.split('/').filter((s) => s && s !== '.');
  if (!parts.length || parts.some((s) => s === '..' || s.includes(':') || s.includes('\0'))) {
    throw new Error(`Invalid library path: ${path}`);
  }
  return parts.join('/');
}

export function remoteLibraryUrl(path, base = REMOTE_BASE) {
  return `${base}/${normalizeLibraryPath(path).split('/').map(encodeURIComponent).join('/')}`;
}

function localLibraryUrl(path) {
  return `/${normalizeLibraryPath(path).split('/').map(encodeURIComponent).join('/')}`;
}

// ------------------------------------------------------------------ validation

export function looksLikeHtml(text) {
  const head = String(text ?? '').slice(0, 4096).trimStart().toLowerCase();
  return head.startsWith('<') || head.includes('<!doctype') || head.includes('<html');
}

/** True for this app's own index.html (what a SPA host returns for a missing file). */
export function isAppIndexHtml(text) {
  const t = String(text ?? '').slice(0, 16384);
  return (
    /<div\s+id=["']app["']/i.test(t) ||
    /src=["']\/src\/main\.js["']/i.test(t) ||
    /src=["']\/assets\/index-[^"']*\.js["']/i.test(t) ||
    /<title>\s*Quantum Dot Suite\s*<\/title>/i.test(t)
  );
}

/** '' when valid, otherwise a short reason. Checks the first frame only. */
export function xyzProblem(text) {
  const t = String(text ?? '');
  if (!t.trim()) return 'empty file';
  if (looksLikeHtml(t)) return 'got an HTML page instead of an XYZ file';
  const lines = t.replace(/\r\n?/g, '\n').split('\n');
  const first = lines[0].trim();
  if (!/^\d+$/.test(first)) return 'first line is not an atom count';
  const n = parseInt(first, 10);
  if (n <= 0) return 'atom count is zero';
  while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
  if (lines.length < n + 2) return `expected ${n} atoms, file is truncated`;
  const atom = lines[2].trim().split(/\s+/);
  if (atom.length < 4 || !/^[A-Za-z]/.test(atom[0]) || atom.slice(1, 4).some((v) => !Number.isFinite(Number(v)))) {
    return 'atom lines are not "Element x y z"';
  }
  return '';
}

export const isValidXyz = (text) => xyzProblem(text) === '';

export function plotProblem(text) {
  const t = String(text ?? '');
  if (!t.trim()) return 'empty file';
  if (isAppIndexHtml(t)) return "got the app's own page instead of a plot";
  if (!/<(html|body|script|div)[\s>]/i.test(t.slice(0, 65536))) return 'not an HTML plot';
  return '';
}

/** kind: 'xyz' | 'md' | 'plot' */
export function libraryFileProblem(kind, text) {
  return kind === 'plot' ? plotProblem(text) : xyzProblem(text);
}

// ------------------------------------------------------------- Tauri disk cache

function tauriInvoke(command, args) {
  const internals = typeof window !== 'undefined' ? window.__TAURI_INTERNALS__ : null;
  if (!internals?.invoke) return Promise.reject(new Error('not running in the desktop app'));
  return internals.invoke(command, args || {});
}

const hasDiskCache = () => typeof window !== 'undefined' && Boolean(window.__TAURI_INTERNALS__?.invoke);
let diskCacheBroken = false;

async function diskRead(path) {
  if (!hasDiskCache() || diskCacheBroken) return null;
  try {
    const data = await tauriInvoke('library_cache_read', { path });
    if (data === null || data === undefined) return null;
    if (typeof data === 'string') return data;
    const bytes = data instanceof ArrayBuffer ? new Uint8Array(data) : Array.isArray(data) ? new Uint8Array(data) : data;
    return new TextDecoder().decode(bytes);
  } catch (e) {
    if (!/not cached/i.test(String(e?.message ?? e))) {
      if (/not (found|allowed)|unknown command/i.test(String(e?.message ?? e))) diskCacheBroken = true;
      console.warn('[library-cache] read failed:', e);
    }
    return null;
  }
}

async function diskWrite(path, text) {
  if (!hasDiskCache() || diskCacheBroken) return false;
  try {
    await tauriInvoke('library_cache_write', { path, contents: text });
    return true;
  } catch (e) {
    console.warn('[library-cache] write failed:', e);
    return false;
  }
}

/** Sizes (bytes) of cached files, null where not cached. All null outside the desktop app. */
export async function cachedSizes(paths) {
  const norm = paths.map((p) => normalizeLibraryPath(p));
  const out = norm.map((p) => (memory.has(p) ? memory.get(p).length : null));
  if (!hasDiskCache() || diskCacheBroken) return out;
  try {
    const sizes = await tauriInvoke('library_cache_stat', { paths: norm });
    return out.map((v, i) => v ?? sizes?.[i] ?? null);
  } catch {
    return out;
  }
}

export async function libraryCacheDir() {
  try { return await tauriInvoke('library_cache_dir'); } catch { return null; }
}

// --------------------------------------------------------- in-memory session cache

const MEMORY_LIMIT = 200_000_000; // characters
const memory = new Map();
let memoryChars = 0;

function memGet(path) {
  const v = memory.get(path);
  if (v === undefined) return null;
  memory.delete(path);
  memory.set(path, v); // LRU bump
  return v;
}

function memPut(path, text) {
  if (memory.has(path)) memoryChars -= memory.get(path).length;
  memory.set(path, text);
  memoryChars += text.length;
  for (const [k, v] of memory) {
    if (memoryChars <= MEMORY_LIMIT || k === path) break;
    memory.delete(k);
    memoryChars -= v.length;
  }
}

// --------------------------------------------------------------- lookups

async function fetchServedCopy(path, kind) {
  // In the installed app this returns index.html (rejected below); in dev/web it may be the real file.
  try {
    const res = await fetch(localLibraryUrl(path));
    if (!res.ok) return null;
    const type = res.headers.get('content-type') || '';
    if (kind !== 'plot' && /text\/html/i.test(type)) return null;
    const text = await res.text();
    return libraryFileProblem(kind, text) ? null : text;
  } catch {
    return null;
  }
}

/**
 * Find a file without touching the network beyond the app's own origin.
 * Returns { text, source: 'memory' | 'cache' | 'bundled' } or null.
 */
export async function findLocalLibraryFile(path, kind) {
  const p = normalizeLibraryPath(path);
  const mem = memGet(p);
  if (mem !== null) return { text: mem, source: 'memory' };
  const disk = await diskRead(p);
  if (disk !== null && !libraryFileProblem(kind, disk)) {
    memPut(p, disk);
    return { text: disk, source: 'cache' };
  }
  const served = await fetchServedCopy(p, kind);
  if (served !== null) {
    memPut(p, served);
    return { text: served, source: 'bundled' };
  }
  return null;
}

async function withTimeout(ms, signal, run) {
  const ctl = new AbortController();
  const onAbort = () => ctl.abort();
  signal?.addEventListener('abort', onAbort);
  const timer = ms ? setTimeout(() => ctl.abort(), ms) : null;
  try {
    return await run(ctl.signal);
  } finally {
    if (timer) clearTimeout(timer);
    signal?.removeEventListener('abort', onAbort);
  }
}

/** Download size in bytes (HEAD content-length), or null if unknown/unreachable. */
export async function remoteLibrarySize(path, { timeoutMs = 5000 } = {}) {
  for (const host of REMOTE_HOSTS) {
    try {
      const res = await withTimeout(timeoutMs, null, (signal) =>
        fetch(remoteLibraryUrl(path, host), { method: 'HEAD', signal, cache: 'no-store' }),
      );
      if (res.status === 404) return null;
      if (!res.ok) continue;
      const n = Number(res.headers.get('content-length'));
      return Number.isFinite(n) && n > 0 ? n : null;
    } catch {
      /* try the fallback host */
    }
  }
  return null;
}

/** Does the remote site have this file? (HEAD; used to probe legacy property folders.) */
export async function remoteLibraryExists(path, { timeoutMs = 5000 } = {}) {
  for (const host of REMOTE_HOSTS) {
    try {
      const res = await withTimeout(timeoutMs, null, (signal) =>
        fetch(remoteLibraryUrl(path, host), { method: 'HEAD', signal, cache: 'no-store' }),
      );
      if (res.ok) return true;
      if (res.status === 404) return false;
    } catch {
      /* try the fallback host */
    }
  }
  return false;
}

async function readWithProgress(res, onProgress) {
  if (!onProgress || !res.body?.getReader) return res.text();
  const total = Number(res.headers.get('content-length')) || null;
  const encoded = Boolean(res.headers.get('content-encoding'));
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let received = 0;
  let text = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    received += value.byteLength;
    text += decoder.decode(value, { stream: true });
    // With content-encoding the header is the compressed size, so no percentage.
    onProgress({ received, total: encoded ? null : total });
  }
  return text + decoder.decode();
}

/**
 * Download from the public site (fallback host on network/HTTP errors), validate,
 * store in the session cache and (unless persist === false) the desktop disk cache.
 */
export async function downloadLibraryFile(path, kind, { signal, onProgress, persist = true, timeoutMs = 120000 } = {}) {
  const p = normalizeLibraryPath(path);
  let lastError = null;
  for (const host of REMOTE_HOSTS) {
    if (signal?.aborted) throw new DOMException('Download cancelled', 'AbortError');
    try {
      const text = await withTimeout(timeoutMs, signal, async (sig) => {
        const res = await fetch(remoteLibraryUrl(p, host), { signal: sig });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return readWithProgress(res, onProgress);
      });
      const problem = libraryFileProblem(kind, text);
      if (problem) throw new Error(problem);
      memPut(p, text);
      if (persist) await diskWrite(p, text);
      return text;
    } catch (e) {
      if (signal?.aborted) throw new DOMException('Download cancelled', 'AbortError');
      lastError = e;
    }
  }
  throw lastError || new Error('download failed');
}

/** Local copy if any, otherwise download. No prompting. */
export async function loadLibraryFile(path, kind, opts = {}) {
  const local = await findLocalLibraryFile(path, kind);
  if (local) return local.text;
  return downloadLibraryFile(path, kind, opts);
}

// ------------------------------------------------------------- prompting policy

export function getAlwaysDownload() {
  try { return localStorage.getItem(ALWAYS_KEY) === '1'; } catch { return false; }
}

export function setAlwaysDownload(on) {
  try { on ? localStorage.setItem(ALWAYS_KEY, '1') : localStorage.removeItem(ALWAYS_KEY); } catch { /* ignore */ }
}

/** Ask before downloading? Only in the desktop app (the web site just streams files). */
export const shouldAskBeforeDownload = () => isDesktopApp() && !getAlwaysDownload();

export function formatBytes(n) {
  if (!Number.isFinite(n) || n <= 0) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

// --------------------------------------------------------------------- catalog

const catalogTime = (idx) => {
  const t = Date.parse(idx?.generated ?? '');
  return Number.isFinite(t) ? t : 0;
};

export const isValidLibraryIndex = (idx) => Array.isArray(idx?.structures) && idx.structures.length > 0;

/** Newest of two library_index.json objects (by "generated"); first wins ties. */
export function newerIndex(a, b) {
  if (!isValidLibraryIndex(b)) return a;
  if (!isValidLibraryIndex(a)) return b;
  return catalogTime(b) > catalogTime(a) ? b : a;
}

const CATALOG_CHECKS = {
  'library_index.json': isValidLibraryIndex,
  'file_list.json': (v) => Array.isArray(v) && v.length > 0,
  'metadata.json': (v) => v && typeof v === 'object',
};

function parseCatalog(name, text) {
  if (!text || looksLikeHtml(text)) return null;
  try {
    const value = JSON.parse(text);
    return (CATALOG_CHECKS[name] || (() => true))(value) ? value : null;
  } catch {
    return null;
  }
}

/** Catalog shipped with the app (or served next to it in dev/web). */
export async function loadBundledCatalog(name) {
  try {
    const res = await fetch(`/${name}`);
    if (!res.ok) return null;
    return parseCatalog(name, await res.text());
  } catch {
    return null;
  }
}

/** Last remote catalog saved by the desktop app. */
export async function loadCachedCatalog(name) {
  return parseCatalog(name, await diskRead(name));
}

/** Fetch the catalog from the public site with a short timeout; caches it to disk on success. */
export async function fetchRemoteCatalog(name, { timeoutMs = 10000, persist = true } = {}) {
  for (const host of REMOTE_HOSTS) {
    try {
      const text = await withTimeout(timeoutMs, null, async (signal) => {
        const res = await fetch(`${host}/${name}`, { signal, cache: 'no-store' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.text();
      });
      const value = parseCatalog(name, text);
      if (!value) continue;
      if (persist) diskWrite(name, text);
      return value;
    } catch {
      /* try the fallback host */
    }
  }
  return null;
}

let catalogRefresh = null;
/**
 * Desktop startup: refresh library_index.json from the public site once per session
 * (non-blocking). Resolves to the remote index or null. file_list.json / metadata.json are
 * not read by the desktop UI, so they are not downloaded.
 */
export function startCatalogRefresh() {
  if (!catalogRefresh) {
    catalogRefresh = isDesktopApp() && (typeof navigator === 'undefined' || navigator.onLine !== false)
      ? fetchRemoteCatalog('library_index.json').catch(() => null)
      : Promise.resolve(null);
  }
  return catalogRefresh;
}
