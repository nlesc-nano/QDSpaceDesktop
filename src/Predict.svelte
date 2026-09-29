<script>
  import { SIDECAR_BASE } from './lib/desktop.js';
  import Viewer from './Viewer.svelte';

  const DEMO = {
    symbols: ['O', 'H', 'H'],
    positions: [
      [0.0, 0.0, 0.0],
      [0.757, 0.586, 0.0],
      [-0.757, 0.586, 0.0],
    ],
    cell: null,
    pbc: false,
  };

  let payloadText = $state(JSON.stringify(DEMO, null, 2));
  let loading = $state(false);
  let error = $state(null);
  let result = $state(null);
  let health = $state(null);
  let clientMs = $state(null);
  let fileNote = $state(null);
  let structureName = $state('');
  let sourceText = $state('');
  let frameCount = $state(1);
  let allFrames = $state(false);
  let shownFrame = $state(0);
  let fileInput = $state(null);
  let activeViewer = $state('molstar');
  let deviceChoice = $state('cpu');
  let engineChoice = $state('mace');

  function pickEngine(name) {
    if (engineChoice === name) return;
    engineChoice = name;
    modelPath = '';
    modelName = '';
    applyHeads([], '');
    if (name === 'mace') refreshHeads();
  }

  let modelPath = $state('');
  let modelName = $state('');
  let modelInput = $state(null);
  let heads = $state([]);
  let headChoice = $state('');

  function applyHeads(found, selected) {
    heads = Array.isArray(found) ? found : [];
    headChoice = selected || (heads.length ? heads[0] : '');
  }

  async function refreshHeads() {
    if (engineChoice !== 'mace') {
      applyHeads([], '');
      return;
    }
    try {
      const query = modelPath ? `?model_path=${encodeURIComponent(modelPath)}` : '';
      const res = await fetch(`${SIDECAR_BASE}/heads${query}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      applyHeads(data.heads, data.selected);
    } catch (e) {
      applyHeads([], '');
      error = e.message || String(e);
    }
  }


  function payloadToXyz(raw) {
    try {
      const body = JSON.parse(raw);
      if (!Array.isArray(body.symbols) || !Array.isArray(body.positions)) return '';
      const lines = [String(body.symbols.length), 'predict'];
      for (let i = 0; i < body.symbols.length; i++) {
        const pos = body.positions[i];
        if (!pos || pos.length < 3) return '';
        lines.push(`${body.symbols[i]} ${pos[0]} ${pos[1]} ${pos[2]}`);
      }
      return lines.join('\n') + '\n';
    } catch {
      return '';
    }
  }

  let xyzData = $derived(payloadToXyz(payloadText));
  let downloadName = $derived((structureName.replace(/\.(xyz|json)$/i, '') || 'predict') + '-predicted.xyz');


  let openStat = $state(null);

  function symbolsOf() {
    try { return JSON.parse(payloadText).symbols || []; } catch { return []; }
  }

  function forceLines(forces) {
    const symbols = symbolsOf();
    return forces.map((f, i) => {
      const el = String(symbols[i] || '').padEnd(3);
      const nums = f.map((v) => Number(v).toFixed(6).padStart(12)).join('  ');
      return `${String(i + 1).padStart(4)}  ${el} ${nums}`;
    }).join('\n');
  }

  function composition() {
    const counts = {};
    for (const el of symbolsOf()) counts[el] = (counts[el] || 0) + 1;
    return Object.entries(counts).map(([el, n]) => `${el} ${n}`).join(', ');
  }

  function loadDemo() {
    payloadText = JSON.stringify(DEMO, null, 2);
    error = null;
    structureName = '';
    sourceText = '';
    frameCount = 1;
    allFrames = false;
    shownFrame = 0;
  }

  function frameToLines(frame) {
    const symbols = frame.symbols || [];
    const positions = frame.positions || [];
    const forces = frame.forces || [];
    const n = Math.min(symbols.length, positions.length, forces.length);
    let lattice = '';
    const cell = frame.cell;
    if (Array.isArray(cell) && cell.length === 3 && cell.every((row) => Array.isArray(row) && row.length >= 3)) {
      lattice = `Lattice="${cell.flat().slice(0, 9).map((v) => Number(v).toFixed(8)).join(' ')}" `;
    }
    const pbc = Array.isArray(frame.pbc) ? frame.pbc.map((v) => (v ? 'T' : 'F')).join(' ') : 'F F F';
    const lines = [
      String(n),
      `${lattice}Properties=species:S:1:pos:R:3:forces:R:3 energy=${Number(frame.energy).toFixed(8)} pbc="${pbc}"`,
    ];
    for (let i = 0; i < n; i++) {
      const pos = positions[i];
      const f = forces[i];
      lines.push([
        symbols[i],
        Number(pos[0]).toFixed(8), Number(pos[1]).toFixed(8), Number(pos[2]).toFixed(8),
        Number(f[0]).toFixed(8), Number(f[1]).toFixed(8), Number(f[2]).toFixed(8),
      ].join(' '));
    }
    return lines.join('\n');
  }

  function showFrame(index) {
    if (!result?.frames?.length) return;
    const frame = result.frames[index];
    if (!frame) return;
    shownFrame = index;
    result = { ...result, energy: frame.energy, forces: frame.forces, n_atoms: frame.n_atoms };
    payloadText = JSON.stringify({
      symbols: frame.symbols,
      positions: frame.positions,
      cell: frame.cell,
      pbc: frame.pbc,
    }, null, 2);
  }

  async function downloadResultXyz() {
    if (!result) return;
    let text;
    if (result.frames?.length) {
      text = result.frames.map(frameToLines).join('\n') + '\n';
    } else {
      let body;
      try { body = JSON.parse(payloadText); } catch { return; }
      text = frameToLines({ ...body, energy: result.energy, forces: result.forces }) + '\n';
    }
    const filename = downloadName;
    try {
      if (window.showSaveFilePicker) {
        const handle = await window.showSaveFilePicker({
          suggestedName: filename,
          types: [{ description: 'XYZ structure', accept: { 'text/plain': ['.xyz'] } }],
        });
        const writable = await handle.createWritable();
        await writable.write(text);
        await writable.close();
        return;
      }
    } catch (e) {
      if (e && e.name === 'AbortError') return;
    }
    const blob = new Blob([text], { type: 'chemical/x-xyz' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  async function checkHealth(warmup = false) {
    error = null;
    try {
      const url = `${SIDECAR_BASE}/health${warmup ? '?warmup=true' : ''}`;
      const res = await fetch(url, { method: 'POST' });
      if (!res.ok) throw new Error(`Health HTTP ${res.status}`);
      health = await res.json();
    } catch {
      health = null;
      error = 'Property prediction is not included in this installer yet.';
    }
  }


  async function onStructureFile(event) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = '';
    if (!file) return;
    error = null;
    fileNote = null;
    result = null;
    structureName = file.name;
    sourceText = '';
    frameCount = 1;
    allFrames = false;
    shownFrame = 0;
    const name = file.name.toLowerCase();
    if (!name.endsWith('.xyz') && !name.endsWith('.json')) {
      error = 'Choose a .xyz or .json file.';
      return;
    }
    try {
      const text = await file.text();
      const res = await fetch(`${SIDECAR_BASE}/structure`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: file.name, text }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      payloadText = JSON.stringify({
        symbols: data.symbols,
        positions: data.positions,
        cell: data.cell,
        pbc: data.pbc,
      }, null, 2);
      sourceText = name.endsWith('.xyz') ? text : '';
      frameCount = data.n_frames || 1;
      const frames = frameCount > 1 ? `, ${frameCount} frames (showing frame 1)` : '';
      fileNote = `ASE accepted ${file.name}: ${data.formula}, ${data.n_atoms} atoms (${data.format})${frames}.`;
    } catch (e) {
      error = e.message || String(e);
    }
  }


  async function onModelFile(event) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = '';
    if (!file) return;
    error = null;
    try {
      const res = await fetch(`${SIDECAR_BASE}/model?filename=${encodeURIComponent(file.name)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: await file.arrayBuffer(),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      modelPath = data.model_path;
      modelName = data.filename;
      if (engineChoice === 'mace') applyHeads(data.heads, data.selected);
      else applyHeads([], '');
    } catch (e) {
      error = e.message || String(e);
    }
  }

  async function runPredict() {
    loading = true;
    error = null;
    result = null;
    clientMs = null;
    const t0 = performance.now();
    try {
      let body;
      try {
        body = JSON.parse(payloadText);
      } catch (e) {
        throw new Error(`Invalid JSON: ${e.message}`);
      }
      if (!Array.isArray(body.symbols) || !Array.isArray(body.positions)) {
        throw new Error('Payload needs symbols[] and positions[][]');
      }
      const predictAll = allFrames && frameCount > 1 && sourceText;
      const res = await fetch(predictAll ? `${SIDECAR_BASE}/predict-frames` : `${SIDECAR_BASE}/predict`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(predictAll
          ? { filename: structureName || 'trajectory.xyz', text: sourceText, device: deviceChoice, engine: engineChoice, model_path: modelPath.trim() || null, head: heads.length > 1 ? headChoice : null }
          : { ...body, device: deviceChoice, engine: engineChoice, model_path: modelPath.trim() || null, head: heads.length > 1 ? headChoice : null }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || data.message || `HTTP ${res.status}`);
      }
      if (predictAll) {
        const first = data.frames?.[0];
        if (!first) throw new Error('No frames came back.');
        result = { ...data, energy: first.energy, forces: first.forces, n_atoms: first.n_atoms };
        shownFrame = 0;
      } else {
        result = data;
        shownFrame = 0;
      }
      clientMs = performance.now() - t0;
    } catch (e) {
      error = e.message || String(e);
    } finally {
      loading = false;
    }
  }
  refreshHeads();
</script>

<div class="flex h-[calc(100vh-64px)] min-h-[640px] overflow-hidden">
  <aside class="w-[380px] shrink-0 h-full overflow-y-auto border-r border-slate-200 bg-white p-5 space-y-4">
    <div>
      <h1 class="font-heading text-2xl font-bold text-slate-900">Property prediction</h1>
    </div>

    <div class="flex flex-col gap-3">
      <button class="w-full px-4 py-2.5 rounded-lg text-sm font-semibold bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50" onclick={runPredict} disabled={loading}>
        {loading ? 'Predicting…' : 'Run predict'}
      </button>
      {#if frameCount > 1}
        <label class="flex items-start gap-2 text-xs text-slate-600">
          <input type="checkbox" class="mt-0.5" bind:checked={allFrames} />
          <span>This file has {frameCount} frames. Predict all of them. Leave this off to use frame 1 only.</span>
        </label>
      {/if}
      <div class="grid grid-cols-2 gap-2">
        <button class="px-3 py-2 rounded-lg text-xs font-medium border border-slate-200 text-slate-700 hover:bg-slate-50" onclick={() => fileInput?.click()}>Load structure</button>
        <button class="px-3 py-2 rounded-lg text-xs font-medium border border-slate-200 text-slate-700 hover:bg-slate-50" onclick={loadDemo}>H₂O demo</button>
      </div>
      <input bind:this={fileInput} type="file" accept=".xyz,.json,chemical/x-xyz,application/json" class="hidden" onchange={onStructureFile} />

      <div class="space-y-1.5">
        <p class="text-xs font-bold uppercase tracking-wide text-slate-700">Engine</p>
        <div class="grid grid-cols-2 rounded-lg border border-slate-200 p-0.5 bg-white">
          <button class="px-3 py-1.5 rounded-md text-xs font-medium {engineChoice === 'mace' ? 'bg-brand-50 text-brand-600' : 'text-slate-500 hover:text-slate-800'}" onclick={() => pickEngine('mace')}>MACE</button>
          <button class="px-3 py-1.5 rounded-md text-xs font-medium {engineChoice === 'nequip' ? 'bg-brand-50 text-brand-600' : 'text-slate-500 hover:text-slate-800'}" onclick={() => pickEngine('nequip')}>NequIP</button>
        </div>
      </div>

      <div class="space-y-1.5">
        <p class="text-xs font-bold uppercase tracking-wide text-slate-700">Model</p>
        <button class="w-full px-3 py-2 rounded-lg text-xs font-medium border border-slate-200 text-slate-700 hover:bg-slate-50 text-left truncate" onclick={() => modelInput?.click()}>
          {modelName || (engineChoice === 'nequip' ? 'Choose a NequIP file' : 'Built-in MACE model')}
        </button>
        <input bind:this={modelInput} type="file" accept=".model,.pth,.pt,.pt2,.zip" class="hidden" onchange={onModelFile} />
        {#if modelName && engineChoice === 'mace'}
          <button class="text-xs text-slate-500 hover:text-slate-800" onclick={() => { modelPath = ''; modelName = ''; refreshHeads(); }}>Use built-in model</button>
        {/if}
        {#if engineChoice === 'mace' && heads.length > 1}
          <select class="w-full px-3 py-2 rounded-lg text-xs border border-slate-200 bg-white" bind:value={headChoice}>
            {#each heads as head}
              <option value={head}>{head}</option>
            {/each}
          </select>
        {/if}
      </div>

      <div class="space-y-1.5">
        <p class="text-xs font-bold uppercase tracking-wide text-slate-700">Device</p>
        <div class="grid grid-cols-2 rounded-lg border border-slate-200 p-0.5 bg-white">
          <button class="px-3 py-1.5 rounded-md text-xs font-medium {deviceChoice === 'cpu' ? 'bg-brand-50 text-brand-600' : 'text-slate-500 hover:text-slate-800'}" onclick={() => deviceChoice = 'cpu'}>CPU</button>
          <button class="px-3 py-1.5 rounded-md text-xs font-medium {deviceChoice === 'cuda' ? 'bg-brand-50 text-brand-600' : 'text-slate-500 hover:text-slate-800'}" onclick={() => deviceChoice = 'cuda'}>GPU</button>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-2">
        <button class="px-3 py-2 rounded-lg text-xs font-medium border border-slate-200 text-slate-600 hover:bg-slate-50" onclick={() => checkHealth(false)}>Check health</button>
        <button class="px-3 py-2 rounded-lg text-xs font-medium border border-slate-200 text-slate-600 hover:bg-slate-50" onclick={() => checkHealth(true)}>Warmup model</button>
      </div>
    </div>

    {#if health}
      <p class="text-xs text-slate-600 rounded-xl bg-slate-50 border border-slate-200 p-3">
        {health.status} · {health.model} · loaded={String(health.model_loaded)} · {health.device}
      </p>
    {/if}
    {#if fileNote}
      <p class="text-xs text-emerald-800 rounded-xl bg-emerald-50 border border-emerald-200 p-3">{fileNote}</p>
    {/if}
    {#if error}
      <p class="text-xs text-rose-800 rounded-xl bg-rose-50 border border-rose-200 p-3">{error}</p>
    {/if}

    <div class="rounded-2xl border border-slate-200 overflow-hidden">
      <div class="px-3 py-2 text-xs font-semibold text-slate-700 border-b border-slate-100">Structure</div>
      <textarea class="w-full h-56 p-3 font-mono text-[11px] text-slate-800 bg-slate-50 focus:outline-none resize-y" bind:value={payloadText} spellcheck="false"></textarea>
    </div>

  </aside>

  <main class="flex-1 min-w-0 h-full p-4 bg-slate-50 flex flex-col gap-4 overflow-hidden">
    <div class="flex-1 min-h-0 bg-white rounded-[1.5rem] p-4 border border-slate-100 shadow-sm flex flex-col">
      <div class="flex justify-between items-center mb-3 px-2">
        <h2 class="font-heading font-bold text-xl text-slate-900">Structure</h2>
        <div class="flex gap-1 bg-slate-100 p-1 rounded-xl border border-slate-200">
          <button class="px-3 py-1.5 rounded-lg text-xs font-bold transition-all {activeViewer === '3dmol' ? 'bg-brand-600 text-white shadow-sm' : 'text-slate-600'}" onclick={() => activeViewer = '3dmol'}>3Dmol</button>
          <button class="px-3 py-1.5 rounded-lg text-xs font-bold transition-all {activeViewer === 'ngl' ? 'bg-brand-600 text-white shadow-sm' : 'text-slate-600'}" onclick={() => activeViewer = 'ngl'}>NGL</button>
          <button class="px-3 py-1.5 rounded-lg text-xs font-bold transition-all {activeViewer === 'molstar' ? 'bg-brand-600 text-white shadow-sm' : 'text-slate-600'}" onclick={() => activeViewer = 'molstar'}>Mol*</button>
          <button class="px-3 py-1.5 rounded-lg text-xs font-bold transition-all {activeViewer === 'matterviz' ? 'bg-brand-600 text-white shadow-sm' : 'text-slate-600'}" onclick={() => activeViewer = 'matterviz'}>MatterViz</button>
        </div>
      </div>
      <div class="flex-1 bg-slate-50 rounded-[1rem] border border-slate-200 overflow-hidden relative">
        {#if xyzData}
          <Viewer xyz={xyzData} activeViewer={activeViewer} />
        {:else}
          <div class="absolute inset-0 flex items-center justify-center text-sm text-slate-500">Load a structure to see it here.</div>
        {/if}
      </div>
    </div>
    <div class="h-1/2 shrink-0 bg-white rounded-[1.5rem] p-4 border border-slate-100 shadow-sm overflow-hidden flex flex-col">
      <div class="flex items-center justify-between mb-2">
        <h2 class="font-heading font-bold text-lg text-slate-900">Results</h2>
        <div class="flex items-center gap-2">
          {#if result}
            <button class="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-emerald-600 text-white hover:bg-emerald-700" onclick={downloadResultXyz}><span aria-hidden="true">↓</span>Download XYZ file</button>
          {/if}
          {#if loading}<span class="text-xs font-medium text-brand-600">Running…</span>{/if}
        </div>
      </div>
      {#if !result && !loading}
        <p class="text-sm text-slate-500">Energy and forces show up here after you run predict.</p>
      {:else if result}
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm mb-3">
          <button class="text-left rounded-xl border p-3 {openStat === 'energy' ? 'border-slate-300 bg-slate-100' : 'border-slate-200 bg-slate-50 hover:bg-slate-100'}" onclick={() => openStat = openStat === 'energy' ? null : 'energy'}>
            <div class="text-slate-500 text-xs">Energy</div>
            <div class="font-mono font-semibold">{result.energy.toFixed(6)} eV</div>
          </button>
          <button class="text-left rounded-xl border p-3 {openStat === 'atoms' ? 'border-slate-300 bg-slate-100' : 'border-slate-200 bg-slate-50 hover:bg-slate-100'}" onclick={() => openStat = openStat === 'atoms' ? null : 'atoms'}>
            <div class="text-slate-500 text-xs">Atoms</div>
            <div class="font-mono">{result.n_atoms}</div>
          </button>
          <button class="text-left rounded-xl border p-3 {openStat === 'device' ? 'border-slate-300 bg-slate-100' : 'border-slate-200 bg-slate-50 hover:bg-slate-100'}" onclick={() => openStat = openStat === 'device' ? null : 'device'}>
            <div class="text-slate-500 text-xs">Device</div>
            <div class="font-mono">{result.device}</div>
          </button>
          <button class="text-left rounded-xl border p-3 {openStat === 'latency' ? 'border-slate-300 bg-slate-100' : 'border-slate-200 bg-slate-50 hover:bg-slate-100'}" onclick={() => openStat = openStat === 'latency' ? null : 'latency'}>
            <div class="text-slate-500 text-xs">Latency</div>
            <div class="font-mono">{result.latency_ms?.toFixed?.(1) ?? result.latency_ms} ms</div>
          </button>
        </div>
        {#if openStat === 'energy'}
          <p class="text-xs text-slate-600 mb-2">{(result.energy / result.n_atoms).toFixed(4)} eV/atom · {(result.energy * 23.0609).toFixed(2)} kcal/mol</p>
        {:else if openStat === 'atoms'}
          <p class="text-xs text-slate-600 mb-2">{composition()}</p>
        {:else if openStat === 'device'}
          <p class="text-xs text-slate-600 mb-2">{result.model} on {result.device}</p>
        {:else if openStat === 'latency'}
          <p class="text-xs text-slate-600 mb-2">Server {result.latency_ms?.toFixed?.(1) ?? result.latency_ms} ms{#if clientMs != null} · round trip {clientMs.toFixed(1)} ms{/if}</p>
        {/if}
        {#if result.frames?.length > 1}
          <div class="flex items-center gap-2 mb-2 text-xs text-slate-600">
            <button class="px-3 py-1 rounded-lg text-xs font-semibold bg-brand-50 text-brand-600 disabled:opacity-40" onclick={() => showFrame(shownFrame - 1)} disabled={shownFrame === 0}>Previous</button>
            <span>Frame {shownFrame + 1} of {result.frames.length}</span>
            <button class="px-3 py-1 rounded-lg text-xs font-semibold bg-brand-50 text-brand-600 disabled:opacity-40" onclick={() => showFrame(shownFrame + 1)} disabled={shownFrame >= result.frames.length - 1}>Next</button>
          </div>
        {:else if frameCount > 1}
          <p class="text-xs text-slate-500 mb-2">Frame 1 of {frameCount}. The other frames were not predicted.</p>
        {/if}
        <div class="text-[10px] uppercase tracking-wide text-slate-400 mb-1">index  element  fx  fy  fz (eV/Å)</div>
        <pre class="font-mono text-xs bg-slate-50 rounded-lg p-3 overflow-auto flex-1 border border-slate-100">{forceLines(result.forces)}</pre>
      {/if}
    </div>
  </main>
</div>
