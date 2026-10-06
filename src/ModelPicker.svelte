<script>
  import catalog from './lib/maceModels.json';
  import { SIDECAR_BASE } from './lib/desktop.js';

  let {
    open = $bindable(false),
    maceTorchVersion = null,
    sidecarFetch,
    tauriInvoke,
    onLoaded = undefined,
  } = $props();

  const STORAGE_KEY = 'qdspace.maceDownloadFolder';
  const FAMILY_ORDER = ['MP-0a', 'MP-0b', 'MP-0b2', 'MP-0b3', 'MPA-0', 'OMAT-0', 'MATPES', 'MH', 'OMOL-0', 'POLAR-1', 'OFF23', 'OFF24', 'Unverified'];

  let query = $state('');
  let licenseFilter = $state('all'); // all|MIT|ASL
  let destFolder = $state('');
  let expandedId = $state('');
  let aslAccepted = $state({});
  let downloadingId = $state('');
  let downloadJobId = $state('');
  let downloadProgress = $state(null); // { done, total, status, error }
  /** Keeps progress/error UI on a row after downloadingId is cleared on failure. */
  let progressForId = $state('');
  let pollTimer = null;
  let refreshNote = $state('');
  let refreshing = $state(false);
  let extraModels = $state([]); // unverified from GitHub refresh
  let localError = $state('');

  $effect(() => {
    if (open) {
      try {
        destFolder = localStorage.getItem(STORAGE_KEY) || '';
      } catch {
        destFolder = '';
      }
      localError = '';
      refreshNote = '';
    } else {
      stopPoll();
    }
  });

  function stopPoll() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }


  /** FastAPI may return detail as string or validation list. */
  function formatApiDetail(detail, status) {
    if (detail == null || detail === '') return `HTTP ${status}`;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d) => (typeof d === 'string' ? d : d?.msg || JSON.stringify(d)))
        .filter(Boolean)
        .join('; ') || `HTTP ${status}`;
    }
    if (typeof detail === 'object' && detail.msg) return String(detail.msg);
    try {
      return JSON.stringify(detail);
    } catch {
      return `HTTP ${status}`;
    }
  }

  function failDownload(message, model) {
    const msg = message || 'Download failed';
    localError = msg;
    downloadProgress = {
      done: downloadProgress?.done || 0,
      total: (model && model.sizeBytes) || downloadProgress?.total || null,
      status: 'error',
      error: msg,
    };
    if (model?.id) progressForId = model.id;
    downloadingId = '';
    downloadJobId = '';
    stopPoll();
  }

  function formatBytes(n) {
    if (n == null || !Number.isFinite(n) || n <= 0) return 'size unknown';
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  }

  function parseVersion(v) {
    if (!v) return null;
    const parts = String(v).replace(/^v/i, '').split(/[.+-]/).map((x) => parseInt(x, 10));
    if (!parts.length || parts.some((n) => !Number.isFinite(n))) return null;
    return parts;
  }

  function versionBelow(current, minimum) {
    const a = parseVersion(current);
    const b = parseVersion(minimum);
    if (!a || !b) return false;
    const len = Math.max(a.length, b.length);
    for (let i = 0; i < len; i++) {
      const x = a[i] || 0;
      const y = b[i] || 0;
      if (x < y) return true;
      if (x > y) return false;
    }
    return false;
  }

  let allModels = $derived([...(catalog.models || []), ...extraModels]);

  let filtered = $derived(
    allModels.filter((m) => {
      if (licenseFilter !== 'all' && m.license !== licenseFilter) return false;
      const q = query.trim().toLowerCase();
      if (!q) return true;
      const hay = [m.name, m.family, m.domain, m.id, m.license].join(' ').toLowerCase();
      return hay.includes(q);
    }),
  );

  let groups = $derived(() => {
    const map = new Map();
    for (const m of filtered) {
      const fam = m.family || 'Other';
      if (!map.has(fam)) map.set(fam, []);
      map.get(fam).push(m);
    }
    const keys = [...map.keys()].sort((a, b) => {
      const ia = FAMILY_ORDER.indexOf(a);
      const ib = FAMILY_ORDER.indexOf(b);
      if (ia < 0 && ib < 0) return a.localeCompare(b);
      if (ia < 0) return 1;
      if (ib < 0) return -1;
      return ia - ib;
    });
    return keys.map((k) => ({ family: k, models: map.get(k) }));
  });

  let folderInputEl = $state(null);

  /** @returns {Promise<boolean>} true if a folder path is set afterwards */
  async function pickDestFolder() {
    localError = '';
    try {
      const picked = await tauriInvoke('pick_folder');
      if (typeof picked === 'string' && picked.trim()) {
        destFolder = picked.trim();
        try {
          localStorage.setItem(STORAGE_KEY, destFolder);
        } catch { /* ignore */ }
        return true;
      }
      return !!destFolder.trim();
    } catch (e) {
      localError = e?.message || String(e);
      return false;
    }
  }

  function canDownload(model) {
    if (downloadingId) return false;
    if (model.license === 'ASL' && !aslAccepted[model.id]) return false;
    return true;
  }

  function downloadDisabledReason(model) {
    if (downloadingId && downloadingId !== model.id) return 'Another download is in progress';
    if (model.license === 'ASL' && !aslAccepted[model.id]) return 'Accept ASL terms to enable Download';
    if (!destFolder.trim()) return "On Download you'll choose a folder if one isn't set yet.";
    return '';
  }

  function close() {
    if (downloadingId) return;
    open = false;
  }

  function onBackdrop(e) {
    if (e.target === e.currentTarget) close();
  }

  function onKey(e) {
    if (e.key === 'Escape' && !downloadingId) close();
  }

  async function startDownload(model) {
    localError = '';
    if (model.license === 'ASL' && !aslAccepted[model.id]) {
      localError = 'Accept the ASL academic-use terms before downloading this model.';
      return;
    }
    if (!destFolder.trim()) {
      const ok = await pickDestFolder();
      if (!ok || !destFolder.trim()) {
        // User cancelled folder picker — abort without starting download
        return;
      }
    }
    const exactUrl = String(model.url || '').trim();
    if (!exactUrl) {
      localError = 'Model catalog entry has no download URL.';
      return;
    }
    downloadingId = model.id;
    progressForId = model.id;
    downloadProgress = { done: 0, total: model.sizeBytes || null, status: 'starting', error: null };
    try {
      try {
        localStorage.setItem(STORAGE_KEY, destFolder.trim());
      } catch { /* ignore */ }
      const filename = exactUrl.split('/').pop()?.split('?')[0] || `${model.id}.model`;
      const res = await sidecarFetch(`${SIDECAR_BASE}/download-model`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: exactUrl,
          dest_dir: destFolder.trim(),
          filename,
          expected_size: model.sizeBytes || null,
          sha256: model.sha256 || null,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        let msg = formatApiDetail(data.detail, res.status);
        if (res.status === 404) {
          msg = `${msg} — sidecar has no /download-model (restart the Python sidecar so it loads the latest sidecar_app.py).`;
        }
        throw new Error(msg);
      }
      if (!data.job_id) throw new Error('Sidecar did not return a download job_id');
      downloadJobId = data.job_id;
      downloadProgress = { done: 0, total: model.sizeBytes || null, status: data.status || 'starting', error: null };
      pollDownload(model);
    } catch (e) {
      failDownload(e.message || String(e), model);
    }
  }

  function pollDownload(model) {
    stopPoll();
    const tick = async () => {
      if (!downloadJobId) return;
      try {
        const res = await sidecarFetch(`${SIDECAR_BASE}/download-model/${encodeURIComponent(downloadJobId)}`);
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(formatApiDetail(data.detail, res.status));
        downloadProgress = {
          done: data.bytes_done || 0,
          total: data.bytes_total || model.sizeBytes || null,
          status: data.status,
          error: data.error || null,
        };
        if (data.status === 'done' && data.path) {
          downloadingId = '';
          downloadJobId = '';
          progressForId = '';
          downloadProgress = null;
          stopPoll();
          open = false;
          onLoaded?.({
            model_path: data.path,
            filename: data.path.split(/[/\\]/).pop(),
            model_type: model.modelType === 'PolarMACE' ? 'PolarMACE' : null,
            needsChargeSpin: !!model.needsChargeSpin,
            modelId: model.id,
            name: model.name,
          });
          return;
        }
        if (data.status === 'error' || data.status === 'cancelled') {
          const msg =
            data.status === 'error'
              ? data.error || 'Download failed'
              : data.error || 'Download cancelled';
          failDownload(msg, model);
          return;
        }
        pollTimer = setTimeout(tick, 400);
      } catch (e) {
        failDownload(e.message || String(e), model);
      }
    };
    pollTimer = setTimeout(tick, 200);
  }

  async function cancelDownload() {
    if (!downloadJobId) return;
    try {
      await sidecarFetch(`${SIDECAR_BASE}/cancel-download/${encodeURIComponent(downloadJobId)}`, { method: 'POST' });
    } catch { /* ignore */ }
  }

  async function refreshFromGitHub() {
    refreshing = true;
    refreshNote = '';
    localError = '';
    try {
      const known = new Set((catalog.models || []).map((m) => (m.url || '').split('/').pop()));
      const repos = [
        'https://api.github.com/repos/ACEsuit/mace-foundations/releases?per_page=15',
        'https://api.github.com/repos/ACEsuit/mace-off/releases?per_page=5',
      ];
      const found = [];
      for (const url of repos) {
        const res = await fetch(url, { headers: { Accept: 'application/vnd.github+json' } });
        if (res.status === 403 || res.status === 429) {
          refreshNote = 'GitHub rate-limited the refresh. Curated list is unchanged.';
          return;
        }
        if (!res.ok) continue;
        const releases = await res.json();
        if (!Array.isArray(releases)) continue;
        for (const rel of releases) {
          for (const asset of rel.assets || []) {
            const name = asset.name || '';
            if (!name.endsWith('.model')) continue;
            if (known.has(name)) continue;
            if (/mdp/i.test(name)) continue;
            found.push({
              id: `unverified-${name}`,
              name: `${name} (unverified)`,
              family: 'Unverified',
              url: asset.browser_download_url,
              sizeBytes: asset.size || null,
              license: 'ASL',
              domain: `From GitHub release ${rel.tag_name || rel.name || ''}. Not in the curated list — verify before use.`,
              minMaceTorch: '0.3.0',
              modelType: 'default',
              unverified: true,
            });
            known.add(name);
          }
        }
      }
      extraModels = found;
      refreshNote = found.length
        ? `Found ${found.length} new .model asset(s) not in the curated list (marked Unverified).`
        : 'No new .model assets beyond the curated list.';
    } catch (e) {
      refreshNote = `Refresh soft-failed: ${e.message || e}`;
    } finally {
      refreshing = false;
    }
  }

  function pct(progress) {
    if (!progress?.total || !progress.total) return null;
    return Math.max(0, Math.min(100, Math.round((100 * (progress.done || 0)) / progress.total)));
  }
</script>

<svelte:window onkeydown={onKey} />

{#if open}
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/45 p-4" role="presentation" onclick={onBackdrop}>
    <div class="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl" role="dialog" aria-modal="true" aria-labelledby="mace-picker-title">
      <div class="flex items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div>
          <h2 id="mace-picker-title" class="text-base font-bold text-slate-900">Download foundation model</h2>
          <p class="mt-0.5 text-xs text-slate-500">Curated from ACEsuit/mace-foundations (+ MACE-OFF). Downloads go to a folder you choose.</p>
        </div>
        <button type="button" class="rounded-lg px-2 py-1 text-sm text-slate-500 hover:bg-slate-100 disabled:opacity-40" onclick={close} disabled={!!downloadingId}>Close</button>
      </div>

      <div class="space-y-3 border-b border-slate-100 px-5 py-3">
        <div class="flex flex-wrap gap-2">
          <input class="min-w-0 flex-1 rounded-lg border border-slate-200 px-3 py-2 text-xs" placeholder="Search name, family, domain…" bind:value={query} />
          <select class="rounded-lg border border-slate-200 px-2 py-2 text-xs" bind:value={licenseFilter}>
            <option value="all">All licenses</option>
            <option value="MIT">MIT</option>
            <option value="ASL">ASL</option>
          </select>
          <button type="button" class="rounded-lg border border-slate-200 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50" onclick={refreshFromGitHub} disabled={refreshing || !!downloadingId}>{refreshing ? 'Refreshing…' : 'Refresh'}</button>
        </div>
        <div class="flex gap-2">
          <input
            bind:this={folderInputEl}
            class="min-w-0 flex-1 rounded-lg border border-slate-200 px-3 py-2 text-xs"
            spellcheck="false"
            placeholder="Download folder (optional shortcut — Browse…)"
            bind:value={destFolder}
            disabled={!!downloadingId}
          />
          <button
            type="button"
            class="shrink-0 rounded-lg border border-slate-200 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            onclick={pickDestFolder}
            disabled={!!downloadingId}
          >Browse folder…</button>
        </div>
        <p class="text-[11px] text-slate-500" role="status">
          On Download you'll choose a folder if one isn't set yet.
        </p>
        {#if maceTorchVersion}
          <p class="text-[11px] text-slate-500">Sidecar mace-torch: <span class="font-semibold text-slate-700">{maceTorchVersion}</span></p>
        {/if}
        {#if refreshNote}
          <p class="text-[11px] text-slate-600">{refreshNote}</p>
        {/if}
        {#if localError}
          <p class="text-xs text-rose-700">{localError}</p>
        {/if}
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto px-5 py-3">
        {#each groups() as group}
          <div class="mb-4">
            <h3 class="mb-2 text-[11px] font-bold uppercase tracking-widest text-slate-500">{group.family}</h3>
            <ul class="space-y-2">
              {#each group.models as model}
                {@const busy = downloadingId === model.id}
                  {@const showProgress = (busy || progressForId === model.id) && downloadProgress}
                {@const warnVersion = maceTorchVersion && model.minMaceTorch && versionBelow(maceTorchVersion, model.minMaceTorch)}
                <li class="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
                  <div class="flex items-start gap-2">
                    <div class="min-w-0 flex-1">
                      <div class="flex flex-wrap items-center gap-2">
                        <span class="text-sm font-bold text-slate-900" title="{formatBytes(model.sizeBytes)} · {model.license}">{model.name}</span>
                        <span class="rounded-full bg-white px-2 py-0.5 text-[10px] font-semibold text-slate-600 ring-1 ring-slate-200" title="License">{model.license}</span>
                        <span class="rounded-full bg-white px-2 py-0.5 text-[10px] font-medium text-slate-500 ring-1 ring-slate-200" title="Approximate size">{formatBytes(model.sizeBytes)}</span>
                        {#if model.unverified}
                          <span class="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700 ring-1 ring-amber-200">unverified</span>
                        {/if}
                        <button type="button" class="ml-auto rounded-full px-1.5 py-0.5 text-xs text-slate-500 hover:bg-white" title="Details" onclick={() => (expandedId = expandedId === model.id ? '' : model.id)} aria-expanded={expandedId === model.id}>ⓘ</button>
                      </div>
                      {#if expandedId === model.id}
                        <div class="mt-2 space-y-1 text-[11px] leading-relaxed text-slate-600">
                          <p>{model.domain}</p>
                          <p>Min mace-torch: <code class="rounded bg-white px-1">{model.minMaceTorch || '—'}</code>
                            {#if model.modelType && model.modelType !== 'default'}
                              · model_type <code class="rounded bg-white px-1">{model.modelType}</code>
                            {/if}
                          </p>
                          {#if model.heads?.length}
                            <p>Heads: {model.heads.join(', ')}</p>
                          {/if}
                          {#if model.needsChargeSpin}
                            <p class="font-medium text-amber-800">This model expects charge/spin on the structure (defaults of charge 0 / spin 1 if unsupported).</p>
                          {/if}
                          <p class="break-all font-mono text-[10px] text-slate-500" title="Exact release download URL">{model.url}</p>
                        </div>
                      {/if}
                      <p class="mt-1 break-all font-mono text-[10px] text-slate-400" title="Exact download URL used on Download">{model.url}</p>
                      {#if warnVersion}
                        <p class="mt-1 text-[11px] text-amber-700">Your mace-torch ({maceTorchVersion}) is below this model’s minimum ({model.minMaceTorch}). Use a newer custom Python env if load fails.</p>
                      {/if}
                      {#if model.license === 'ASL'}
                        <label class="mt-2 flex items-start gap-2 text-[11px] text-slate-700">
                          <input type="checkbox" class="mt-0.5" checked={!!aslAccepted[model.id]} onchange={(e) => { aslAccepted = { ...aslAccepted, [model.id]: e.currentTarget.checked }; }} disabled={!!downloadingId && !busy} />
                          <span>I accept — academic use only (ASL)</span>
                        </label>
                      {/if}
                      {#if showProgress}
                        <div class="mt-2 space-y-1">
                          <div class="flex items-center justify-between text-[11px] text-slate-600">
                            <span>{downloadProgress.status} · {formatBytes(downloadProgress.done)}{#if downloadProgress.total} / {formatBytes(downloadProgress.total)}{/if}</span>
                            {#if busy && downloadJobId && downloadProgress.status !== 'error'}
                              <button type="button" class="font-semibold text-red-600 hover:underline" onclick={cancelDownload}>Cancel</button>
                            {/if}
                          </div>
                          <div class="h-1.5 w-full overflow-hidden rounded-full bg-slate-200" role="progressbar" aria-valuenow={pct(downloadProgress) ?? undefined} aria-valuemin="0" aria-valuemax="100">
                            {#if downloadProgress.status === 'error'}
                              <div class="h-full w-full rounded-full bg-rose-400"></div>
                            {:else if pct(downloadProgress) != null}
                              <div class="h-full rounded-full bg-brand-600" style="width: {pct(downloadProgress)}%"></div>
                            {:else}
                              <div class="h-full w-1/3 animate-pulse rounded-full bg-brand-600"></div>
                            {/if}
                          </div>
                          {#if downloadProgress.error}
                            <p class="text-[11px] text-rose-700">{downloadProgress.error}</p>
                          {/if}
                        </div>
                      {/if}
                    <button
                      type="button"
                      class="shrink-0 rounded-lg bg-brand-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-brand-700 disabled:opacity-40"
                      disabled={!canDownload(model)}
                      title={downloadDisabledReason(model)}
                      onclick={() => startDownload(model)}
                    >Download</button>
                  </div>
                </li>
              {/each}
            </ul>
          </div>
        {:else}
          <p class="py-8 text-center text-sm text-slate-500">No models match this filter.</p>
        {/each}
      </div>
    </div>
  </div>
{/if}
