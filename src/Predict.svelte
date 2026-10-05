<script module>
  // Survives leaving Predict. Only successful head discovery is kept, never an error.
  let keptHeads = null;
</script>

<script>
  import { SIDECAR_BASE } from './lib/desktop.js';
  import Viewer from './Viewer.svelte';

  const SAMPLES = [
    { name: 'CsPbBr3', subtitle: '12 Å', file: 'Cs20Pb8Br36_HLE17_12ang_OPT.xyz' },
    { name: 'CdSe', subtitle: '12 Å', file: 'Cd16Se13Cl6_HLE17_12ang_opt.xyz' },
    { name: 'PbS', subtitle: '9 Å', file: 'Pb19S6Cl26_PBE_9ang_OPT.xyz' },
  ];

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
  let predictCancelling = $state(false);
  let predictAbort = null;
  let cancelledNote = $state('');
  let error = $state(null);
  // Raw (not deeply reactive): an all-frames run can hold thousands of frames.
  let result = $state.raw(null);
  // Streaming Predict all frames: progress, and which result frame is shown.
  let streamDone = $state(0);
  let streamTotal = $state(0);
  let followLatest = $state(true);
  let resultIndex = $state(0);
  let activeStream = null;
  let clientMs = $state(null);
  let fileNote = $state(null);
  let structureName = $state('');
  let structureLoaded = $state(false);
  let sourceText = $state('');
  let originalEnergy = $state(null);
  let frameCount = $state(1);
  let allFrames = $state(false);
  let shownFrame = $state(0);
  let structureFrames = $state([]);
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
  let pythonPath = $state('');
  let pythonBusy = $state(false);
  let pythonBusyLabel = $state('Checking…');
  let pythonNote = $state('');
  let userPythonOn = $state(false);
  let installPrompt = $state(null);
  let installing = $state(false);
  let installCancelling = $state(false);
  let installPercent = $state(null);
  let installPackage = $state('');
  let installLog = $state([]);
  let installLogEl = $state(null);
  let installGen = 0;
  let predictBlockNote = $state('');

  async function tauriInvoke(command, args) {
    const internals = typeof window !== 'undefined' ? window.__TAURI_INTERNALS__ : null;
    if (!internals?.invoke) {
      throw new Error('Use my Python only works in the QDSpace Desktop app, not in a browser tab.');
    }
    return internals.invoke(command, args || {});
  }

  function invokeError(e) {
    if (typeof e === 'string' && e) return e;
    if (e && typeof e === 'object') {
      if (typeof e.message === 'string' && e.message) return e.message;
      try { return JSON.stringify(e); } catch { /* ignore */ }
    }
    return String(e || 'Unknown error');
  }

  function sampleBodyIsHtml(text) {
    const start = String(text || '').trimStart().slice(0, 64).toLowerCase();
    return start.startsWith('<!doctype') || start.startsWith('<html');
  }

  async function takeSidecarFailure() {
    try {
      const internals = typeof window !== 'undefined' ? window.__TAURI_INTERNALS__ : null;
      if (!internals?.invoke) return null;
      const message = await internals.invoke('take_sidecar_failure');
      if (typeof message === 'string' && message.trim()) {
        userPythonOn = false;
        pythonNote = '';
        return message.trim();
      }
    } catch {
      /* not in the desktop app */
    }
    return null;
  }

  async function waitForSidecarFailure() {
    if (!userPythonOn) return null;
    for (let attempt = 0; attempt < 10; attempt += 1) {
      const message = await takeSidecarFailure();
      if (message) return message;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    return null;
  }

  async function sidecarFetch(url, options) {
    const pending = await takeSidecarFailure();
    if (pending) throw new Error(pending);
    try {
      return await fetch(url, options);
    } catch (e) {
      if (e?.name === 'AbortError' || options?.signal?.aborted) throw e;
      const message = await waitForSidecarFailure();
      if (message) throw new Error(message);
      throw e;
    }
  }

  async function browsePython() {
    const picked = await tauriInvoke('pick_python_path');
    if (typeof picked === 'string' && picked.trim()) pythonPath = picked.trim();
    return pythonPath.trim();
  }

  async function onBrowsePython() {
    error = null;
    try {
      await browsePython();
    } catch (e) {
      error = invokeError(e);
    }
  }

  function missingLabel(name) {
    return name === 'mace' ? 'mace-torch' : name;
  }

  function pinChangeMessage(change) {
    if (change?.message && typeof change.message === 'string') return change.message;
    const name = change?.name || 'package';
    const required = change?.required || '';
    if (change?.current) {
      return `MACE in this app needs ${name} ${required}; yours is ${change.current}. Install will change it to ${required}.`;
    }
    return `MACE in this app needs ${name} ${required}; it is not installed. Install will set it to ${required}.`;
  }

  function installPackagesFromPrompt(pending) {
    const missing = Array.isArray(pending?.missing) ? pending.missing.slice() : [];
    const pins = Array.isArray(pending?.pinChanges)
      ? pending.pinChanges.map((change) => change?.name).filter((name) => typeof name === 'string' && name.trim())
      : [];
    const seen = new Set();
    const packages = [];
    for (const name of [...missing, ...pins]) {
      if (seen.has(name)) continue;
      seen.add(name);
      packages.push(name);
    }
    return packages;
  }

  async function finishUserPython(python, packages) {
    const info = await tauriInvoke('apply_user_python', {
      pythonPath: python,
      packages,
    });
    userPythonOn = true;
    const device = info?.device || 'CPU';
    const torch = info?.torch ? ` · torch ${info.torch}` : '';
    const installed = info?.installedMace ? ' Installed the missing libraries into this environment.' : '';
    pythonNote = `Using this Python · ${device}${torch}.${installed} ${info?.python || python}`;
    if (info?.python) pythonPath = info.python;
  }

  function cancelInstall() {
    installPrompt = null;
  }

  function isCancelError(e) {
    return invokeError(e).startsWith('Install cancelled');
  }

  function pythonStatusText() {
    if (installing) {
      const name = installPackage ? `Installing ${installPackage}…` : 'Installing into this Python…';
      return installPercent != null ? `${name} ${installPercent}%` : name;
    }
    if (pythonBusyLabel === 'Checking…') return 'Checking this Python…';
    if (pythonBusyLabel === 'Installing…') return 'Installing into this Python…';
    return 'Starting your Python…';
  }

  function notePredictBlocked() {
    predictBlockNote = 'Install is in progress. Cancel it or wait.';
  }

  async function watchInstall(gen) {
    while (installing && installGen === gen) {
      try {
        const status = await tauriInvoke('python_install_status');
        if (!installing || installGen !== gen) return;
        if (status?.running) {
          installPackage = typeof status.package === 'string' ? status.package : '';
          installPercent = typeof status.percent === 'number' ? status.percent : null;
          installLog = Array.isArray(status.lines) ? status.lines : [];
          if (installLogEl) installLogEl.scrollTop = installLogEl.scrollHeight;
        }
      } catch {
        /* keep the last progress line */
      }
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
  }

  async function cancelRunningInstall() {
    if (!installing || installCancelling) return;
    const gen = installGen;
    installCancelling = true;
    try {
      for (let attempt = 0; attempt < 20 && installing && installGen === gen; attempt += 1) {
        await tauriInvoke('cancel_python_install');
        await new Promise((resolve) => setTimeout(resolve, 200));
      }
    } catch (e) {
      if (installGen === gen) error = invokeError(e);
    }
  }

  async function confirmInstall() {
    if (!installPrompt || pythonBusy) return;
    const pending = installPrompt;
    installPrompt = null;
    error = null;
    predictBlockNote = '';
    const gen = ++installGen;
    installing = true;
    installCancelling = false;
    installPercent = null;
    installPackage = '';
    installLog = [];
    pythonBusy = true;
    pythonBusyLabel = 'Installing…';
    const watch = watchInstall(gen);
    try {
      await finishUserPython(pending.python, installPackagesFromPrompt(pending));
    } catch (e) {
      if (!isCancelError(e)) {
        userPythonOn = false;
        pythonNote = '';
        error = invokeError(e);
      }
    } finally {
      if (installGen === gen) {
        installing = false;
        installCancelling = false;
        pythonBusy = false;
        predictBlockNote = '';
      }
      await watch;
    }
  }

  async function useMyPython() {
    if (pythonBusy || installPrompt) return;
    error = null;
    pythonBusy = true;
    pythonBusyLabel = 'Checking…';
    try {
      if (!pythonPath.trim()) {
        await browsePython();
        if (!pythonPath.trim()) return;
      }
      const info = await tauriInvoke('check_user_python', { pythonPath: pythonPath.trim() });
      const missing = Array.isArray(info?.missing)
        ? info.missing.filter((name) => typeof name === 'string' && name.trim())
        : [];
      const pinChanges = Array.isArray(info?.pinChanges)
        ? info.pinChanges.filter((change) => change && typeof change === 'object')
        : [];
      const python = info?.python || pythonPath.trim();
      if (info?.python) pythonPath = info.python;
      if (missing.length || pinChanges.length) {
        installPrompt = { python, missing, pinChanges };
        return;
      }
      pythonBusyLabel = 'Starting…';
      try {
        await finishUserPython(python, []);
      } catch (e) {
        userPythonOn = false;
        pythonNote = '';
        throw e;
      }
    } catch (e) {
      error = invokeError(e);
    } finally {
      pythonBusy = false;
    }
  }

  let heads = $state([]);
  let headChoice = $state('');

  function applyHeads(found, selected) {
    heads = Array.isArray(found) ? found : [];
    headChoice = selected || (heads.length ? heads[0] : '');
  }

  async function refreshHeads({ reportError = true } = {}) {
    if (engineChoice !== 'mace') {
      applyHeads([], '');
      return;
    }
    try {
      const query = modelPath ? `?model_path=${encodeURIComponent(modelPath)}` : '';
      const res = await sidecarFetch(`${SIDECAR_BASE}/heads${query}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      applyHeads(data.heads, data.selected);
      keptHeads = {
        found: Array.isArray(data.heads) ? data.heads : [],
        selected: data.selected || '',
      };
    } catch (e) {
      const message = e.message || String(e);
      if (!reportError && !message.startsWith('Your Python stopped')) {
        if (keptHeads) applyHeads(keptHeads.found, keptHeads.selected);
        return;
      }
      keptHeads = null;
      applyHeads([], '');
      error = message;
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

  function energyFromXyzComment(comment) {
    const match = String(comment || '').match(/(?:\benergy\s*(?:=|:)|\bE\s*=)\s*[\"]?([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)/i);
    if (!match) return null;
    const value = Number(match[1]);
    return Number.isFinite(value) ? value : null;
  }

  function energyFromXyzFrame(text, targetFrame = 0) {
    if (!text) return null;
    const lines = String(text).replace(/\r\n?/g, '\n').split('\n');
    let cursor = 0;
    let frame = 0;
    while (cursor < lines.length) {
      while (cursor < lines.length && !lines[cursor].trim()) cursor += 1;
      if (cursor >= lines.length) break;
      const count = Number.parseInt(lines[cursor].trim(), 10);
      if (!Number.isFinite(count) || count < 1) break;
      const comment = lines[cursor + 1] || '';
      if (frame === targetFrame) return energyFromXyzComment(comment);
      cursor += count + 2;
      frame += 1;
    }
    return null;
  }

  function latticeFromComment(comment) {
    const match = String(comment || '').match(/Lattice\s*=\s*"([^"]+)"/i);
    if (!match) return null;
    const nums = match[1].trim().split(/\s+/).map(Number);
    if (nums.length < 9 || nums.slice(0, 9).some((n) => !Number.isFinite(n))) return null;
    return [nums.slice(0, 3), nums.slice(3, 6), nums.slice(6, 9)];
  }

  function pbcFromComment(comment) {
    const match = String(comment || '').match(/pbc\s*=\s*"([^"]+)"/i);
    if (!match) return false;
    const flags = match[1].trim().split(/\s+/).slice(0, 3).map((v) => /^t(?:rue)?$/i.test(v));
    if (flags.length < 3) return false;
    return flags.some(Boolean) ? flags : false;
  }

  function parseXyzFrames(text) {
    if (!text) return [];
    const lines = String(text).replace(/\r\n?/g, '\n').split('\n');
    const frames = [];
    let cursor = 0;
    while (cursor < lines.length) {
      while (cursor < lines.length && !lines[cursor].trim()) cursor += 1;
      if (cursor >= lines.length) break;
      const count = Number.parseInt(lines[cursor].trim(), 10);
      if (!Number.isFinite(count) || count < 1) break;
      if (cursor + count + 1 >= lines.length) break;
      const comment = lines[cursor + 1] || '';
      const symbols = [];
      const positions = [];
      let ok = true;
      for (let i = 0; i < count; i++) {
        const parts = (lines[cursor + 2 + i] || '').trim().split(/\s+/);
        if (parts.length < 4) { ok = false; break; }
        const xyz = [Number(parts[1]), Number(parts[2]), Number(parts[3])];
        if (xyz.some((n) => !Number.isFinite(n))) { ok = false; break; }
        symbols.push(parts[0]);
        positions.push(xyz);
      }
      if (!ok) break;
      frames.push({
        symbols,
        positions,
        cell: latticeFromComment(comment),
        pbc: pbcFromComment(comment),
        energy: energyFromXyzComment(comment),
      });
      cursor += count + 2;
    }
    return frames;
  }

  function applyFramePayload(frame) {
    payloadText = JSON.stringify({
      symbols: frame.symbols,
      positions: frame.positions,
      cell: frame.cell,
      pbc: frame.pbc,
    }, null, 2);
  }

  function selectInputFrame(index) {
    if (index < 0 || index >= structureFrames.length) return;
    const frame = structureFrames[index];
    if (!frame) return;
    shownFrame = index;
    originalEnergy = frame.energy != null ? frame.energy : energyFromXyzFrame(sourceText, index);
    applyFramePayload(frame);
    if (fileNote && frameCount > 1) {
      fileNote = fileNote.replace(/showing frame \d+/, `showing frame ${index + 1}`);
    }
    if (result?.frames?.length) {
      const predicted = result.frames[index];
      if (predicted) {
        result = { ...result, energy: predicted.energy, forces: predicted.forces, n_atoms: predicted.n_atoms, symbols: predicted.symbols };
        resultIndex = index;
        if (loading) followLatest = false;
      }
    }
  }

  let xyzData = $derived(payloadToXyz(payloadText));
  let downloadName = $derived((structureName.replace(/\.(xyz|json)$/i, '') || 'predict') + '-predicted.xyz');


  let openStat = $state(null);

  function symbolsOf() {
    try { return JSON.parse(payloadText).symbols || []; } catch { return []; }
  }

  function resultSymbols() {
    return Array.isArray(result?.symbols) ? result.symbols : symbolsOf();
  }

  function forceLines(forces) {
    const symbols = resultSymbols();
    return forces.map((f, i) => {
      const el = String(symbols[i] || '').padEnd(3);
      const nums = f.map((v) => Number(v).toFixed(6).padStart(12)).join('  ');
      return `${String(i + 1).padStart(4)}  ${el} ${nums}`;
    }).join('\n');
  }

  function composition() {
    const counts = {};
    for (const el of resultSymbols()) counts[el] = (counts[el] || 0) + 1;
    return Object.entries(counts).map(([el, n]) => `${el} ${n}`).join(', ');
  }

  function loadDemo() {
    payloadText = JSON.stringify(DEMO, null, 2);
    error = null;
    structureName = '';
    structureLoaded = true;
    sourceText = '';
    frameCount = 1;
    allFrames = false;
    shownFrame = 0;
    structureFrames = [];
    fileNote = null;
    originalEnergy = null;
    result = null;
  }

  function clearStructureFile() {
    payloadText = '';
    structureName = '';
    structureLoaded = false;
    sourceText = '';
    fileNote = null;
    originalEnergy = null;
    frameCount = 1;
    allFrames = false;
    shownFrame = 0;
    structureFrames = [];
    result = null;
    clientMs = null;
    openStat = null;
    error = null;
    cancelledNote = '';
  }

  async function loadSample(sample) {
    error = null;
    try {
      const res = await fetch(`/predict/${encodeURIComponent(sample.file)}`);
      const text = await res.text();
      if (sampleBodyIsHtml(text, res.headers.get('content-type'))) {
        throw new Error(`sample file missing (${sample.name})`);
      }
      if (!res.ok) throw new Error(`Could not load ${sample.name} (${res.status})`);
      const file = new File([text], sample.file, { type: 'chemical/x-xyz' });
      await loadStructureFile(file);
    } catch (e) {
      error = e.message || String(e);
    }
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
    if (structureFrames.length > 1) {
      selectInputFrame(index);
      return;
    }
    if (!result?.frames?.length) return;
    const frame = result.frames[index];
    if (!frame) return;
    shownFrame = index;
    resultIndex = index;
    if (loading) followLatest = false;
    originalEnergy = energyFromXyzFrame(sourceText, index);
    result = { ...result, energy: frame.energy, forces: frame.forces, n_atoms: frame.n_atoms, symbols: frame.symbols };
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

  async function loadStructureFile(file) {
    if (!file) return;
    error = null;
    fileNote = null;
    originalEnergy = null;
    result = null;
    structureName = file.name;
    structureLoaded = true;
    sourceText = '';
    frameCount = 1;
    allFrames = false;
    shownFrame = 0;
    structureFrames = [];
    const name = file.name.toLowerCase();
    if (!name.endsWith('.xyz') && !name.endsWith('.json')) {
      structureName = '';
      structureLoaded = false;
      error = 'Choose a .xyz or .json file.';
      return;
    }
    try {
      const text = await file.text();
      const res = await sidecarFetch(`${SIDECAR_BASE}/structure`, {
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
      const parsed = sourceText ? parseXyzFrames(text) : [];
      if (parsed.length) {
        parsed[0] = {
          ...parsed[0],
          symbols: data.symbols,
          positions: data.positions,
          cell: data.cell,
          pbc: data.pbc,
        };
      }
      structureFrames = parsed;
      originalEnergy = name.endsWith('.xyz')
        ? (parsed[0]?.energy ?? energyFromXyzFrame(text, 0))
        : null;
      frameCount = parsed.length || data.n_frames || 1;
      const frames = frameCount > 1 ? `, ${frameCount} frames (showing frame 1)` : '';
      fileNote = `ASE accepted ${file.name}: ${data.formula}, ${data.n_atoms} atoms (${data.format})${frames}.`;
    } catch (e) {
      error = e.message || String(e);
    }
  }


  function onStructureFile(event) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = '';
    loadStructureFile(file);
  }

  function onStructureDrop(event) {
    event.preventDefault();
    loadStructureFile(event.dataTransfer?.files?.[0]);
  }

  async function loadModelFile(file) {
    if (!file) return;
    error = null;
    try {
      const res = await sidecarFetch(`${SIDECAR_BASE}/model?filename=${encodeURIComponent(file.name)}`, {
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

  function onModelFile(event) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = '';
    loadModelFile(file);
  }

  function onModelDrop(event) {
    event.preventDefault();
    loadModelFile(event.dataTransfer?.files?.[0]);
  }

  function useBuiltInModel() {
    modelPath = '';
    modelName = '';
    refreshHeads();
  }

  function clearModelFile() {
    useBuiltInModel();
  }

  function isPredictCancelError(e, aborted) {
    if (aborted) return true;
    if (!e) return false;
    if (e.name === 'AbortError') return true;
    const message = String(e.message || e || '');
    return /prediction cancelled/i.test(message) || /The user aborted a request/i.test(message);
  }

  async function cancelPredict() {
    if (!loading || predictCancelling) return;
    predictCancelling = true;
    try {
      await fetch(`${SIDECAR_BASE}/cancel-predict`, { method: 'POST' }).catch(() => null);
    } finally {
      if (predictAbort) predictAbort.abort();
    }
  }

  function originalEnergyFor(index) {
    const parsed = structureFrames[index];
    if (parsed) return parsed.energy ?? null;
    // Scanning the whole XYZ text is too slow to repeat while frames stream in.
    return loading ? null : energyFromXyzFrame(sourceText, index);
  }

  // Push streamed frames into Results. Throttled so a fast run does not re-render per frame.
  function flushStream(stream) {
    if (stream.timer) {
      clearTimeout(stream.timer);
      stream.timer = null;
    }
    if (activeStream !== stream) return;
    const frames = stream.frames;
    streamDone = frames.length;
    if (!frames.length) return;
    const last = frames.length - 1;
    const base = {
      device: stream.meta.device || stream.device,
      model: stream.meta.model || '',
      latency_ms: stream.meta.latency_ms ?? frames[last].elapsed_ms,
      cold_load_s: stream.meta.cold_load_s ?? null,
      n_frames: frames.length,
      frames: frames.slice(),
    };
    if (followLatest || !result?.frames) {
      const frame = frames[last];
      resultIndex = last;
      originalEnergy = originalEnergyFor(last);
      result = { ...base, energy: frame.energy, forces: frame.forces, n_atoms: frame.n_atoms, symbols: frame.symbols };
    } else {
      result = { ...result, ...base };
    }
  }

  function scheduleFlush(stream) {
    if (stream.timer) return;
    stream.timer = setTimeout(() => {
      stream.timer = null;
      flushStream(stream);
    }, 120);
  }

  function jumpToLatest() {
    followLatest = true;
    if (activeStream) flushStream(activeStream);
  }

  // Read newline-delimited JSON from a fetch body, one event per line, as it arrives.
  async function readNdjson(res, onEvent) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let newline;
        while ((newline = buffer.indexOf('\n')) >= 0) {
          const line = buffer.slice(0, newline).trim();
          buffer = buffer.slice(newline + 1);
          if (line) onEvent(JSON.parse(line));
        }
      }
      buffer += decoder.decode();
      if (buffer.trim()) onEvent(JSON.parse(buffer));
    } catch (e) {
      reader.cancel().catch(() => {});
      throw e;
    }
  }

  async function predictErrorFrom(res) {
    const data = await res.json().catch(() => ({}));
    const detail = data.detail || data.message || `HTTP ${res.status}`;
    if (res.status === 409 || /prediction cancelled/i.test(String(detail))) {
      return new Error('Prediction cancelled');
    }
    return new Error(detail);
  }

  // Older sidecar without /predict-frames-stream: one request, results at the end.
  async function runFramesAtOnce(stream, controller, options) {
    const res = await sidecarFetch(`${SIDECAR_BASE}/predict-frames`, { ...options, signal: controller.signal });
    if (!res.ok) throw await predictErrorFrom(res);
    const data = await res.json().catch(() => ({}));
    if (controller.signal.aborted) throw new Error('Prediction cancelled');
    if (!data.frames?.length) throw new Error('No frames came back.');
    stream.meta = { device: data.device, model: data.model, latency_ms: data.latency_ms };
    stream.frames = data.frames;
    followLatest = false;
    flushStream(stream);
    const first = data.frames[0];
    resultIndex = 0;
    originalEnergy = originalEnergyFor(0);
    result = { ...result, energy: first.energy, forces: first.forces, n_atoms: first.n_atoms, symbols: first.symbols };
  }

  async function runFrameStream(stream, controller, request) {
    const options = {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    };
    const res = await sidecarFetch(`${SIDECAR_BASE}/predict-frames-stream`, { ...options, signal: controller.signal });
    if (res.status === 404 || res.status === 405) {
      await runFramesAtOnce(stream, controller, options);
      return;
    }
    if (!res.ok) throw await predictErrorFrom(res);
    if (!res.body?.getReader) throw new Error('This window cannot read streamed results.');
    let finished = false;
    try {
      await readNdjson(res, (event) => {
        if (activeStream !== stream) return;
        switch (event?.type) {
          case 'start':
            if (Number.isFinite(event.n_frames)) {
              stream.total = event.n_frames;
              streamTotal = event.n_frames;
            }
            break;
          case 'ready':
            stream.meta = { ...stream.meta, device: event.device, model: event.model, cold_load_s: event.cold_load_s };
            break;
          case 'frame':
            stream.frames.push(event);
            scheduleFlush(stream);
            break;
          case 'done':
            stream.meta = { ...stream.meta, latency_ms: event.latency_ms };
            finished = true;
            break;
          case 'cancelled':
            throw new Error('Prediction cancelled');
          case 'error':
            throw new Error(event.message || 'Prediction failed');
          default:
            break;
        }
      });
    } catch (e) {
      if (isPredictCancelError(e, controller.signal.aborted)) throw e;
      if (e instanceof TypeError) {
        // The connection dropped mid-run, usually because the Python process stopped.
        const message = await waitForSidecarFailure();
        if (message) throw new Error(message);
      }
      throw e;
    }
    if (controller.signal.aborted) throw new Error('Prediction cancelled');
    if (!finished) {
      throw new Error(`The prediction stopped early after ${stream.frames.length} of ${stream.total} frames.`);
    }
    flushStream(stream);
  }

  // Predict all frames as a sidecar job polled with short requests. WebView2 (the Tauri
  // window on Windows) can hold a streamed fetch body until the response ends, so
  // /predict-frames-stream progress may arrive all at once; plain polls always complete.
  const JOB_POLL_MS = 200;
  const JOB_POLL_RETRIES = 3;

  function pollDelay(ms, signal) {
    return new Promise((resolve) => {
      if (signal.aborted) return resolve();
      const timer = setTimeout(done, ms);
      function done() {
        clearTimeout(timer);
        signal.removeEventListener('abort', done);
        resolve();
      }
      signal.addEventListener('abort', done, { once: true });
    });
  }

  // Add frames from one poll, in order, and update meta.
  function applyJobSnapshot(stream, data) {
    if (Number.isFinite(data.total) && data.total > 0 && data.total !== stream.total) {
      stream.total = data.total;
      streamTotal = data.total;
    }
    stream.meta = {
      ...stream.meta,
      device: data.device || stream.meta.device,
      model: data.model || stream.meta.model,
      cold_load_s: data.cold_load_s ?? stream.meta.cold_load_s ?? null,
    };
    let added = 0;
    for (const frame of data.frames || []) {
      if (frame?.index !== stream.frames.length) continue;
      stream.frames.push(frame);
      added += 1;
    }
    return added;
  }

  async function fetchJobSnapshot(stream, signal) {
    const url = `${SIDECAR_BASE}/predict-frames-job/${encodeURIComponent(stream.jobId)}?after=${stream.frames.length}`;
    const res = await fetch(url, { cache: 'no-store', signal });
    if (res.status === 404) throw new Error('The prediction job was lost. The Python process may have restarted.');
    if (!res.ok) throw await predictErrorFrom(res);
    return res.json();
  }

  // After Cancel, grab frames that finished since the last poll so Results keep them.
  async function collectLastJobFrames(stream) {
    if (!stream.jobId) return;
    const timeout = new AbortController();
    const timer = setTimeout(() => timeout.abort(), 1500);
    try {
      const data = await fetchJobSnapshot(stream, timeout.signal);
      applyJobSnapshot(stream, data);
    } catch {
      // Keep what we already have.
    } finally {
      clearTimeout(timer);
    }
  }

  async function runFrameJob(stream, controller, request) {
    const res = await sidecarFetch(`${SIDECAR_BASE}/predict-frames-job`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
      signal: controller.signal,
    });
    if (res.status === 404 || res.status === 405) {
      // Older sidecar without jobs.
      await runFrameStream(stream, controller, request);
      return;
    }
    if (!res.ok) throw await predictErrorFrom(res);
    const started = await res.json().catch(() => ({}));
    if (!started.job_id) throw new Error('The sidecar did not start a prediction job.');
    stream.jobId = started.job_id;
    if (Number.isFinite(started.n_frames) && started.n_frames > 0) {
      stream.total = started.n_frames;
      streamTotal = started.n_frames;
    }
    let failures = 0;
    try {
      for (;;) {
        if (controller.signal.aborted) throw new Error('Prediction cancelled');
        let data;
        try {
          data = await fetchJobSnapshot(stream, controller.signal);
          failures = 0;
        } catch (e) {
          if (isPredictCancelError(e, controller.signal.aborted)) throw e;
          if (!(e instanceof TypeError)) throw e;
          // Connection error: retry a few times, then report why Python stopped if we know.
          failures += 1;
          if (failures >= JOB_POLL_RETRIES) {
            const message = await waitForSidecarFailure();
            throw new Error(message || `Lost contact with the sidecar after ${stream.frames.length} of ${stream.total} frames.`);
          }
          await pollDelay(JOB_POLL_MS * 2, controller.signal);
          continue;
        }
        if (activeStream !== stream) return;
        if (applyJobSnapshot(stream, data)) flushStream(stream);
        switch (data.status) {
          case 'done':
            stream.meta = { ...stream.meta, latency_ms: data.latency_ms };
            if (stream.frames.length < (data.done ?? 0)) continue; // more frames than one poll returned
            flushStream(stream);
            return;
          case 'cancelled':
            throw new Error('Prediction cancelled');
          case 'error':
            throw new Error(data.error || 'Prediction failed');
          default:
            break;
        }
        await pollDelay(JOB_POLL_MS, controller.signal);
      }
    } catch (e) {
      if (isPredictCancelError(e, controller.signal.aborted)) await collectLastJobFrames(stream);
      throw e;
    }
  }

  async function runPredict() {
    if (loading) return;
    if (installing) {
      notePredictBlocked();
      return;
    }
    predictBlockNote = '';
    cancelledNote = '';
    loading = true;
    predictCancelling = false;
    error = null;
    result = null;
    clientMs = null;
    streamDone = 0;
    streamTotal = 0;
    followLatest = true;
    resultIndex = 0;
    const controller = new AbortController();
    predictAbort = controller;
    const t0 = performance.now();
    let stream = null;
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
      const settings = { device: deviceChoice, engine: engineChoice, model_path: modelPath.trim() || null, head: heads.length > 1 ? headChoice : null };
      if (predictAll) {
        stream = { frames: [], total: frameCount, device: deviceChoice, meta: {}, timer: null, jobId: null };
        activeStream = stream;
        streamTotal = frameCount;
        await runFrameJob(stream, controller, { filename: structureName || 'trajectory.xyz', text: sourceText, ...settings });
      } else {
        const res = await sidecarFetch(`${SIDECAR_BASE}/predict`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: controller.signal,
          body: JSON.stringify({ ...body, ...settings }),
        });
        if (!res.ok) throw await predictErrorFrom(res);
        const data = await res.json().catch(() => ({}));
        if (controller.signal.aborted) {
          throw new Error('Prediction cancelled');
        }
        result = data;
      }
      clientMs = performance.now() - t0;
    } catch (e) {
      if (stream) flushStream(stream);
      const kept = stream ? stream.frames.length : 0;
      if (isPredictCancelError(e, controller.signal.aborted)) {
        cancelledNote = kept
          ? `Prediction cancelled after ${kept} of ${stream.total} frames. Results keep the finished frames.`
          : 'Prediction cancelled.';
        error = null;
        if (!kept) result = null;
      } else {
        const message = e.message || String(e);
        error = kept ? `${message} Results keep the ${kept} frames that finished.` : message;
        if (!kept) result = null;
      }
    } finally {
      if (stream?.timer) clearTimeout(stream.timer);
      if (activeStream === stream) activeStream = null;
      if (predictAbort === controller) predictAbort = null;
      loading = false;
      predictCancelling = false;
      // Point the structure viewer at the result frame now shown (it is not reloaded per frame).
      if (stream && result?.frames?.length) showFrame(Math.min(resultIndex, result.frames.length - 1));
    }
  }
  if (keptHeads) applyHeads(keptHeads.found, keptHeads.selected);
  refreshHeads({ reportError: false });
</script>

<div class="flex h-[calc(100vh-64px)] min-h-[640px] overflow-hidden">
  <aside class="w-[380px] shrink-0 h-full overflow-y-auto border-r border-slate-200 bg-white p-5 space-y-4">
    <div>
      <h1 class="font-heading text-2xl font-bold text-slate-900">Property prediction</h1>
    </div>

    <div class="flex flex-col gap-3">
      <div class="relative space-y-2">
        {#if loading}
          <button type="button" class="w-full px-4 py-2.5 rounded-lg text-sm font-semibold bg-brand-600 text-white disabled:opacity-50" disabled>
            Predicting…{streamTotal > 1 ? ` ${streamDone} / ${streamTotal}` : ''}
          </button>
          <button type="button" class="w-full px-4 py-2.5 rounded-lg text-sm font-semibold border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-50" onclick={cancelPredict} disabled={predictCancelling}>
            {predictCancelling ? 'Cancelling…' : 'Cancel'}
          </button>
        {:else}
          <button type="button" class="w-full px-4 py-2.5 rounded-lg text-sm font-semibold bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50" onclick={runPredict} disabled={installing}>
            Run predict
          </button>
          {#if installing}
            <button type="button" class="absolute inset-0 cursor-not-allowed rounded-lg" aria-label="Install in progress" onclick={notePredictBlocked}></button>
          {/if}
        {/if}
      </div>
      {#if predictBlockNote}
        <p class="text-xs text-slate-600">{predictBlockNote}</p>
      {/if}
      {#if cancelledNote}
        <p class="text-xs text-amber-900 rounded-xl bg-amber-50 border border-amber-200 p-3">{cancelledNote}</p>
      {/if}

      <div>
        <span class="block text-sm font-bold text-slate-700 uppercase tracking-widest mb-2">Engine</span>
        <div class="flex space-x-1 rounded-xl p-1 bg-slate-100 my-2">
          <button type="button" class="w-full rounded-lg py-1.5 text-xs font-bold transition-all {engineChoice === 'mace' ? 'bg-white text-brand-600 shadow-sm' : 'text-slate-500 hover:text-slate-700 hover:bg-slate-200/50'}" onclick={() => pickEngine('mace')}>MACE</button>
          <button type="button" class="w-full rounded-lg py-1.5 text-xs font-bold transition-all {engineChoice === 'nequip' ? 'bg-white text-brand-600 shadow-sm' : 'text-slate-500 hover:text-slate-700 hover:bg-slate-200/50'}" onclick={() => pickEngine('nequip')}>NequIP</button>
        </div>
      </div>

      <div>
        <span class="block text-sm font-bold text-slate-700 uppercase tracking-widest mb-2">Device</span>
        <div class="flex space-x-1 rounded-xl p-1 bg-slate-100 my-2">
          <button type="button" class="w-full rounded-lg py-1.5 text-xs font-bold transition-all {deviceChoice === 'cpu' ? 'bg-white text-brand-600 shadow-sm' : 'text-slate-500 hover:text-slate-700 hover:bg-slate-200/50'}" onclick={() => deviceChoice = 'cpu'}>CPU</button>
          <button type="button" class="w-full rounded-lg py-1.5 text-xs font-bold transition-all {deviceChoice === 'cuda' ? 'bg-white text-brand-600 shadow-sm' : 'text-slate-500 hover:text-slate-700 hover:bg-slate-200/50'}" onclick={() => deviceChoice = 'cuda'}>GPU</button>
        </div>
      </div>

      <div>
        <div class="flex justify-between items-center mb-2">
          <span class="block text-sm font-bold text-slate-700 uppercase tracking-widest">Structure</span>
          {#if structureLoaded}
            <button type="button" class="text-xs text-red-500 font-bold hover:text-red-700" onclick={clearStructureFile}>Clear File</button>
          {/if}
        </div>
        <div class="border-2 border-dashed border-slate-200 hover:bg-brand-50 hover:border-brand-400 transition-all p-5 rounded-2xl text-center group {structureName ? 'bg-brand-50 border-brand-400' : ''}"
             ondragover={(e) => e.preventDefault()}
             ondrop={onStructureDrop}>
          <label class="cursor-pointer block">
            <input bind:this={fileInput} type="file" class="hidden" accept=".xyz,.json,chemical/x-xyz,application/json" onchange={onStructureFile} />
            <div class="text-sm text-slate-500 font-medium group-hover:text-brand-600 transition-colors flex flex-col items-center gap-2">
              {#if structureName}
                <div class="w-10 h-10 bg-white rounded-full flex items-center justify-center shadow-sm text-brand-500 mb-1">
                  <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
                </div>
                <span class="font-bold text-brand-700 break-all">{structureName}</span>
              {:else}
                <span class="font-bold text-brand-600">Click to upload custom</span>
                <span class="text-xs">or drag & drop a .xyz or .json file</span>
              {/if}
            </div>
          </label>
          {#if structureFrames.length > 1}
            <div class="flex items-center justify-center gap-2 mt-2">
              <button type="button" class="px-3 py-1 rounded-lg text-xs font-semibold bg-white text-brand-600 disabled:opacity-40" onclick={() => selectInputFrame(shownFrame - 1)} disabled={shownFrame === 0}>Previous</button>
              <span class="text-xs font-semibold text-brand-800">Frame {shownFrame + 1} of {structureFrames.length}</span>
              <button type="button" class="px-3 py-1 rounded-lg text-xs font-semibold bg-white text-brand-600 disabled:opacity-40" onclick={() => selectInputFrame(shownFrame + 1)} disabled={shownFrame >= structureFrames.length - 1}>Next</button>
            </div>
          {/if}
        </div>
        <div class="flex flex-wrap gap-2 mt-2">
          <button type="button" class="flex flex-col items-center justify-center px-3 py-2 bg-brand-50 hover:bg-brand-100 text-brand-700 border border-brand-200 rounded-lg transition-colors w-[85px]" onclick={loadDemo}>
            <span class="text-sm font-bold leading-tight">H2O</span>
            <span class="text-[9px] font-bold text-slate-500 uppercase tracking-wider mt-0.5">demo</span>
          </button>
          {#each SAMPLES as sample}
            <button type="button" class="flex flex-col items-center justify-center px-3 py-2 bg-brand-50 hover:bg-brand-100 text-brand-700 border border-brand-200 rounded-lg transition-colors w-[85px]" onclick={() => loadSample(sample)}>
              <span class="text-sm font-bold leading-tight">{sample.name}</span>
              <span class="text-[9px] font-bold text-slate-500 uppercase tracking-wider mt-0.5">{sample.subtitle}</span>
            </button>
          {/each}
        </div>
        {#if frameCount > 1}
          <label class="flex items-start gap-2 mt-2 text-xs text-slate-600">
            <input type="checkbox" class="mt-0.5" bind:checked={allFrames} />
            <span>This file has {frameCount} frames. Predict all of them. Leave this off to predict the frame shown above.</span>
          </label>
        {/if}
      </div>

      <div>
        <div class="flex justify-between items-center mb-2">
          <span class="block text-sm font-bold text-slate-700 uppercase tracking-widest">Model</span>
          {#if modelName}
            <button type="button" class="text-xs text-red-500 font-bold hover:text-red-700" onclick={clearModelFile}>Clear File</button>
          {/if}
        </div>
        <label class="border-2 border-dashed border-slate-200 hover:bg-brand-50 hover:border-brand-400 transition-all p-5 rounded-2xl text-center cursor-pointer block group {modelName ? 'bg-brand-50 border-brand-400' : ''}"
               ondragover={(e) => e.preventDefault()}
               ondrop={onModelDrop}>
          <input bind:this={modelInput} type="file" class="hidden" accept=".model,.pth,.pt,.pt2,.zip" onchange={onModelFile} />
          <div class="text-sm text-slate-500 font-medium group-hover:text-brand-600 transition-colors flex flex-col items-center gap-2">
            {#if modelName}
              <div class="w-10 h-10 bg-white rounded-full flex items-center justify-center shadow-sm text-brand-500 mb-1">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
              </div>
              <span class="font-bold text-brand-700 break-all">{modelName}</span>
            {:else}
              <span class="font-bold text-brand-600">Click to upload custom</span>
              <span class="text-xs">or drag & drop a model file</span>
            {/if}
          </div>
        </label>
        <button type="button" class="w-full mt-2 rounded-lg py-1.5 text-xs font-bold transition-all {!modelName ? 'bg-white text-brand-600 shadow-sm' : 'text-slate-500 hover:text-slate-700 hover:bg-slate-200/50'}" onclick={useBuiltInModel}>Use built-in model</button>
        {#if engineChoice === 'mace' && heads.length > 1}
          <select class="w-full mt-2 px-3 py-2 rounded-lg text-xs border border-slate-200 bg-white" bind:value={headChoice}>
            {#each heads as head}
              <option value={head}>{head}</option>
            {/each}
          </select>
        {/if}
      </div>

      <div class="space-y-2">
        <span class="block text-sm font-bold text-slate-700 uppercase tracking-widest">Python</span>
        <div class="flex gap-2">
          <input class="min-w-0 flex-1 px-3 py-2 rounded-lg text-xs border border-slate-200 bg-white" spellcheck="false" placeholder="C:\Users\...\anaconda3\envs\qdspace-user\python.exe" bind:value={pythonPath} disabled={pythonBusy} onkeydown={(event) => { if (event.key === 'Enter') useMyPython(); }} />
          <button type="button" class="px-3 py-2 rounded-lg text-xs font-medium border border-slate-200 text-slate-700 hover:bg-slate-50 disabled:opacity-50" onclick={onBrowsePython} disabled={pythonBusy}>Browse</button>
        </div>
        <button type="button" class="w-full px-3 py-2 rounded-lg text-sm font-bold transition-all border border-slate-200 {userPythonOn ? 'bg-white text-brand-600 shadow-sm' : 'text-slate-700 hover:text-slate-900 hover:bg-slate-50'} disabled:opacity-50" onclick={useMyPython} disabled={pythonBusy || !!installPrompt}>{pythonBusy ? pythonBusyLabel : 'Use this Python'}</button>
        {#if installing}
          <div class="space-y-1.5 px-1" role="status" aria-live="polite">
            <div class="flex items-center gap-2">
              <p class="min-w-0 flex-1 truncate text-xs font-medium text-brand-700">{pythonStatusText()}</p>
              <button type="button" class="shrink-0 rounded-lg border border-red-200 px-2.5 py-1 text-xs font-semibold text-red-600 hover:bg-red-50 disabled:opacity-50" onclick={cancelRunningInstall} disabled={installCancelling}>{installCancelling ? 'Cancelling…' : 'Cancel'}</button>
            </div>
            <div class="h-1.5 w-full overflow-hidden rounded-full bg-slate-200" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={installPercent ?? undefined}>
              {#if installPercent != null}
                <div class="h-full rounded-full bg-brand-600" style="width: {Math.max(0, Math.min(100, installPercent))}%"></div>
              {:else}
                <div class="install-indet h-full w-1/3 rounded-full bg-brand-600"></div>
              {/if}
            </div>
            <pre bind:this={installLogEl} class="max-h-24 min-h-10 overflow-y-auto whitespace-pre-wrap break-all rounded-lg border border-slate-100 bg-slate-50 p-2 font-mono text-[10px] leading-snug text-slate-600">{installLog.length ? installLog.join('\n') : 'Waiting for pip…'}</pre>
          </div>
        {:else if pythonBusy}
          <p class="flex items-center gap-2 px-1 text-xs font-medium text-brand-700" role="status">
            <span class="inline-block h-3.5 w-3.5 shrink-0 rounded-full border-2 border-brand-200 border-t-brand-600 animate-spin" aria-hidden="true"></span>
            <span>{pythonStatusText()}</span>
          </p>
        {/if}
        {#if pythonNote}
          <p class="px-1 text-xs text-slate-500 break-all">{pythonNote}</p>
        {/if}
      </div>
    </div>
    {#if fileNote}
      <p class="text-xs text-emerald-800 rounded-xl bg-emerald-50 border border-emerald-200 p-3">{fileNote}</p>
    {/if}
    {#if error}
      <p class="text-xs text-rose-800 rounded-xl bg-rose-50 border border-rose-200 p-3">{error}</p>
    {/if}

    <div class="rounded-2xl border border-slate-200 overflow-hidden">
      <div class="px-3 py-2 text-sm font-bold text-slate-900 border-b border-slate-100">Structure</div>
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
          {#if loading}<span class="text-xs font-medium text-brand-600">{predictCancelling ? 'Cancelling…' : 'Running…'}</span>{/if}
        </div>
      </div>
      {#if loading && streamTotal > 1}
        <div class="mb-3" role="status" aria-live="polite">
          <div class="flex items-center justify-between text-xs mb-1">
            <span class="font-semibold text-brand-700">{streamDone ? `Frame ${streamDone} of ${streamTotal}` : `Starting… 0 of ${streamTotal} frames`}</span>
            <span class="font-mono text-slate-500">{Math.floor((streamDone / streamTotal) * 100)}%</span>
          </div>
          <div class="h-1.5 w-full overflow-hidden rounded-full bg-slate-200" role="progressbar" aria-valuemin="0" aria-valuemax={streamTotal} aria-valuenow={streamDone}>
            <div class="h-full rounded-full bg-brand-600 transition-[width] duration-150" style="width: {Math.min(100, (streamDone / streamTotal) * 100)}%"></div>
          </div>
        </div>
      {/if}
      {#if !result && !loading}
        <p class="text-sm text-slate-500">{cancelledNote || 'Energy and forces show up here after you run predict.'}</p>
      {:else if !result}
        <p class="text-sm text-slate-500">{streamTotal > 1 ? 'Loading the model. Results appear as each frame finishes.' : 'Running predict…'}</p>
      {:else if result}
        <div class="flex flex-wrap items-start gap-3 mb-3">
          <div class="min-w-[260px] max-w-3xl flex-1 rounded-xl border border-slate-200 border-l-4 border-blue-500 bg-white p-2 shadow-sm">
            <div class="divide-y divide-slate-100 text-sm">
              <div class="flex items-center justify-between gap-4 py-1 first:pt-0">
                <div class="text-slate-500 text-xs">Original energy</div>
                <div class="font-mono text-base font-bold text-slate-900">{originalEnergy != null ? originalEnergy : '—'}</div>
              </div>
              <button type="button" class="flex items-center justify-between gap-4 w-full text-left py-1" onclick={() => openStat = openStat === 'energy' ? null : 'energy'}>
                <div class="text-slate-500 text-xs">Predicted energy</div>
                <div class="font-mono text-base font-bold text-slate-900">{result.energy.toFixed(6)} eV</div>
              </button>
              <div class="flex items-center justify-between gap-4 py-1 last:pb-0">
                <div class="text-slate-500 text-xs">Energy gap</div>
                <div class="font-mono text-base font-bold text-slate-900">{originalEnergy != null && result.energy != null ? (result.energy - originalEnergy).toFixed(6) : '—'}</div>
              </div>
            </div>
          </div>
          <div class="flex flex-wrap items-center gap-2 text-sm">
          <button class="text-left rounded-lg border border-slate-200 border-l-4 border-green-500 bg-white px-3 py-2 shadow-sm hover:bg-slate-50" onclick={() => openStat = openStat === 'atoms' ? null : 'atoms'}>
            <span class="text-slate-500 text-xs">Atoms</span>
            <span class="font-mono font-bold text-slate-900"> {result.n_atoms}</span>
          </button>
          <button class="text-left rounded-lg border border-slate-200 border-l-4 border-purple-500 bg-white px-3 py-2 shadow-sm hover:bg-slate-50" onclick={() => openStat = openStat === 'device' ? null : 'device'}>
            <span class="text-slate-500 text-xs">Device</span>
            <span class="font-mono font-bold text-slate-900"> {result.device}</span>
          </button>
          <button class="text-left rounded-lg border border-slate-200 border-l-4 border-blue-500 bg-white px-3 py-2 shadow-sm hover:bg-slate-50" onclick={() => openStat = openStat === 'latency' ? null : 'latency'}>
            <span class="text-slate-500 text-xs">Latency</span>
            <span class="font-mono font-bold text-slate-900"> {result.latency_ms?.toFixed?.(1) ?? result.latency_ms} ms</span>
          </button>
          </div>
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
        {#if result.frames?.length > 1 || (loading && result.frames?.length)}
          <div class="flex flex-wrap items-center gap-2 mb-2 text-xs text-slate-600">
            <button class="px-3 py-1 rounded-lg text-xs font-semibold bg-brand-50 text-brand-600 disabled:opacity-40" onclick={() => showFrame(resultIndex - 1)} disabled={resultIndex === 0}>Previous</button>
            <span>Frame {resultIndex + 1} of {loading ? streamTotal : result.frames.length}</span>
            <button class="px-3 py-1 rounded-lg text-xs font-semibold bg-brand-50 text-brand-600 disabled:opacity-40" onclick={() => showFrame(resultIndex + 1)} disabled={resultIndex >= result.frames.length - 1}>Next</button>
            {#if loading}
              {#if followLatest}
                <span class="text-brand-600">Showing the latest finished frame</span>
              {:else}
                <button class="px-3 py-1 rounded-lg text-xs font-semibold bg-brand-600 text-white hover:bg-brand-700" onclick={jumpToLatest}>Follow latest</button>
              {/if}
            {:else if result.frames.length < frameCount}
              <span class="text-amber-700">{frameCount - result.frames.length} frames were not predicted.</span>
            {/if}
          </div>
        {:else if frameCount > 1}
          <p class="text-xs text-slate-500 mb-2">Frame {shownFrame + 1} of {frameCount}. The other frames were not predicted.</p>
        {/if}
        <div class="text-xs font-bold uppercase tracking-wide text-slate-700 mb-1">index  element  fx  fy  fz (eV/Å)</div>
        <pre class="font-mono text-xs bg-slate-50 rounded-lg p-3 overflow-auto flex-1 border border-slate-100">{forceLines(result.forces)}</pre>
      {/if}
    </div>
  </main>
</div>

{#if pythonBusy}
  <div class="fixed bottom-4 right-4 z-40 flex items-center gap-2 rounded-full border border-brand-200 bg-white px-4 py-2 text-sm font-semibold text-brand-700 shadow-lg" role="status">
    <span class="inline-block h-4 w-4 shrink-0 rounded-full border-2 border-brand-200 border-t-brand-600 animate-spin" aria-hidden="true"></span>
    <span class="max-w-[16rem] truncate">{pythonStatusText()}</span>
    {#if installing}
      <button type="button" class="shrink-0 rounded-full border border-red-200 px-2.5 py-1 text-xs font-semibold text-red-600 hover:bg-red-50 disabled:opacity-50" onclick={cancelRunningInstall} disabled={installCancelling}>{installCancelling ? 'Cancelling…' : 'Cancel'}</button>
    {/if}
  </div>
{/if}

{#if installPrompt}
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-6">
    <div class="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-5 shadow-xl" role="dialog" aria-modal="true" aria-labelledby="install-python-title">
      <h2 id="install-python-title" class="font-heading text-lg font-bold text-slate-900">Install these into this Python?</h2>
      {#if installPrompt.missing?.length}
        <ul class="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-800">
          {#each installPrompt.missing as name}
            <li class="font-mono">{missingLabel(name)}</li>
          {/each}
        </ul>
      {/if}
      {#if installPrompt.pinChanges?.length}
        <div class="mt-3 space-y-2" role="status">
          {#each installPrompt.pinChanges as change}
            <p class="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-950">{pinChangeMessage(change)}</p>
          {/each}
        </div>
      {/if}
      <p class="mt-3 break-all text-xs text-slate-500">{installPrompt.python}</p>
      <div class="mt-5 flex justify-end gap-2">
        <button type="button" class="rounded-lg border border-red-200 px-4 py-2 text-sm font-semibold text-red-600 hover:bg-red-50" onclick={cancelInstall}>Cancel</button>
        <button type="button" class="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700" onclick={confirmInstall}>Install</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .install-indet {
    animation: install-indet 1.1s ease-in-out infinite;
  }
  @keyframes install-indet {
    0% { transform: translateX(-120%); }
    100% { transform: translateX(400%); }
  }
</style>
