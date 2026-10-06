<script>
  // Trajectory player owned by Predict (adapted from the Library MD player; not shared with it).
  // Structure-only matterviz player, thinned for playback, synced both ways with the page.
  // Optional Actual vs Predicted energy chart (Results Range/All only).
  import { untrack } from 'svelte';
  import { Trajectory } from 'matterviz/trajectory';
  import { calc_lattice_params, create_cart_to_frac } from 'matterviz/math';
  import { thinPositions, playbackBudget, nearestAtOrBelow, clampFrameNumber, energyAxisRange, energyGapPoints, needsDualEnergyAxis } from './lib/predictTrajectory.js';

  let {
    frames = [], // [{ symbols, positions, cell?, pbc? }]
    frameNumbers = null, // 0-based file frame of each entry (defaults to its position)
    current = 0, // index into frames shown on the page
    totalFrames = 0, // frames in the file, for the label and go-to clamping
    onselect = () => {}, // (index into frames) => void
    // Results Range/All only: [{ frame: 1-based, predicted, actual: number|null }]
    energyPlot = null,
  } = $props();

  let playing = $state(false);
  let fps = $state(10);
  let stepIdx = $state(0);
  let synced = -1;

  function elementOf(symbol) {
    const match = /^([A-Za-z]{1,2})/.exec(String(symbol || '').trim());
    if (!match) return 'X';
    const s = match[1];
    return s[0].toUpperCase() + s.slice(1).toLowerCase();
  }

  function latticeOf(cell, pbc) {
    if (!Array.isArray(cell) || cell.length !== 3) return null;
    const matrix = cell.map((row) => (Array.isArray(row) ? row.slice(0, 3).map(Number) : []));
    if (!matrix.every((row) => row.length === 3 && row.every(Number.isFinite))) return null;
    try {
      const toFrac = create_cart_to_frac(matrix);
      const flags = Array.isArray(pbc) ? pbc.slice(0, 3).map(Boolean) : [Boolean(pbc), Boolean(pbc), Boolean(pbc)];
      return { lattice: { matrix, ...calc_lattice_params(matrix), pbc: flags }, toFrac };
    } catch {
      return null;
    }
  }

  function buildStructure(frame) {
    const symbols = frame.symbols || [];
    const positions = frame.positions || [];
    const lat = latticeOf(frame.cell, frame.pbc);
    const n = Math.min(symbols.length, positions.length);
    const sites = [];
    for (let i = 0; i < n; i++) {
      const xyz = positions[i].slice(0, 3).map(Number);
      const element = elementOf(symbols[i]);
      sites.push({
        species: [{ element, occu: 1, oxidation_state: 0 }],
        abc: lat ? lat.toFrac(xyz) : [0, 0, 0],
        xyz,
        label: `${element}${i + 1}`,
        properties: {},
      });
    }
    return lat ? { sites, lattice: lat.lattice } : { sites };
  }

  // Build once per frames list; stepping through frames must not rebuild it.
  let cache = null;
  let built = $derived.by(() => {
    const list = frames || [];
    if (cache && cache.list === list && cache.length === list.length) return cache.value;
    const positions = thinPositions(list.length, playbackBudget(list[0]?.symbols?.length));
    let trajectory = null;
    if (positions.length >= 2) {
      const out = positions.map((p, step) => ({ structure: buildStructure(list[p]), step, metadata: {} }));
      trajectory = { frames: out, metadata: { source_format: 'predict', frame_count: out.length } };
    }
    const value = { positions, trajectory };
    cache = { list, length: list.length, value };
    return value;
  });
  let positions = $derived(built.positions);
  let trajectory = $derived(built.trajectory);

  function fileNumber(index) {
    const n = frameNumbers ? frameNumbers[index] : index;
    return Number.isInteger(n) ? n + 1 : index + 1;
  }

  // Page -> player.
  $effect(() => {
    const s = Math.max(0, nearestAtOrBelow(positions, current));
    untrack(() => {
      synced = s;
      if (stepIdx !== s) stepIdx = s;
    });
  });

  // Player -> page (slider, buttons, playback, keyboard inside matterviz).
  $effect(() => {
    const s = stepIdx;
    untrack(() => {
      if (s === synced) return;
      synced = s;
      const index = positions[s];
      if (index != null && index !== current) onselect(index);
    });
  });

  $effect(() => {
    if (!playing || positions.length < 2) return;
    const timer = setInterval(() => {
      stepIdx = stepIdx >= positions.length - 1 ? 0 : stepIdx + 1;
    }, 1000 / Math.max(1, fps));
    return () => clearInterval(timer);
  });

  function go(delta) {
    playing = false;
    stepIdx = Math.min(Math.max(0, stepIdx + delta), positions.length - 1);
  }

  // Go to a file frame number (exact, even if playback samples frames). For results, the
  // nearest predicted frame at or below the number is shown.
  function applyGoto(event) {
    const input = event.currentTarget;
    const n = clampFrameNumber(input.value, totalFrames || frames.length);
    if (n != null) {
      const source = n - 1;
      const index = frameNumbers
        ? Math.max(0, nearestAtOrBelow(frameNumbers, source))
        : Math.min(source, frames.length - 1);
      if (index !== current) {
        playing = false;
        onselect(index);
      }
    }
    input.value = String(fileNumber(current));
  }

  let sampled = $derived(positions.length < frames.length);
  let exact = $derived(positions[stepIdx] === current);

  // --- Energy plot (Results Range/All): dual-axis top + gap bottom ---
  const W = 440;
  const TOP_H = 168;
  const GAP_H = 112;
  const GAP_BETWEEN = 10;
  const H = TOP_H + GAP_BETWEEN + GAP_H;
  const PAD = { t: 22, r: 48, b: 28, l: 52 };
  const plotW = W - PAD.l - PAD.r;
  const topPlotH = TOP_H - PAD.t - 8;
  const gapTop = TOP_H + GAP_BETWEEN;
  const gapPlotH = GAP_H - 22 - PAD.b;

  function pathOf(points, xOf, yOf) {
    return points.map((p, i) => `${i ? 'L' : 'M'}${xOf(p).toFixed(1)},${yOf(p).toFixed(1)}`).join(' ');
  }

  function ticksFor(range, yScale, count = 4) {
    const ticks = [];
    for (let i = 0; i <= count; i++) {
      const v = range.min + ((range.max - range.min) * i) / count;
      ticks.push({ y: yScale(v), label: formatEnergy(v), value: v });
    }
    return ticks;
  }

  function formatEnergy(v) {
    const a = Math.abs(v);
    if (a >= 1000) return v.toFixed(0);
    if (a >= 100) return v.toFixed(1);
    if (a >= 10) return v.toFixed(2);
    if (a >= 1) return v.toFixed(3);
    return v.toFixed(4);
  }

  let chart = $derived.by(() => {
    const pts = Array.isArray(energyPlot) ? energyPlot : [];
    if (pts.length < 2) return null;
    const predicted = pts.filter((p) => Number.isFinite(p.predicted));
    if (predicted.length < 2) return null;
    const actual = pts.filter((p) => Number.isFinite(p.actual));
    const gaps = energyGapPoints(pts);
    const xs = predicted.map((p) => p.frame);
    let x0 = Math.min(...xs);
    let x1 = Math.max(...xs);
    if (x0 === x1) { x0 -= 0.5; x1 += 0.5; }
    const xScale = (x) => PAD.l + ((x - x0) / (x1 - x0)) * plotW;

    const dual = needsDualEnergyAxis(
      actual.map((p) => p.actual),
      predicted.map((p) => p.predicted),
    ) && actual.length >= 1;

    let actRange;
    let predRange;
    let yAct;
    let yPred;
    let leftTicks;
    let rightTicks;
    let shared = false;

    if (dual) {
      actRange = energyAxisRange(actual.map((p) => p.actual));
      predRange = energyAxisRange(predicted.map((p) => p.predicted));
      yAct = (y) => PAD.t + ((actRange.max - y) / (actRange.max - actRange.min)) * topPlotH;
      yPred = (y) => PAD.t + ((predRange.max - y) / (predRange.max - predRange.min)) * topPlotH;
      leftTicks = ticksFor(actRange, yAct);
      rightTicks = ticksFor(predRange, yPred);
    } else {
      shared = true;
      const vals = predicted.map((p) => p.predicted).concat(actual.map((p) => p.actual));
      const range = energyAxisRange(vals);
      actRange = range;
      predRange = range;
      yAct = (y) => PAD.t + ((range.max - y) / (range.max - range.min)) * topPlotH;
      yPred = yAct;
      leftTicks = ticksFor(range, yAct);
      rightTicks = [];
    }

    const predPath = pathOf(predicted, (p) => xScale(p.frame), (p) => yPred(p.predicted));
    const actPath = actual.length >= 2
      ? pathOf(actual, (p) => xScale(p.frame), (p) => yAct(p.actual))
      : '';

    let gapRange = { min: -1, max: 1 };
    let yGap = (y) => gapTop + 14 + ((gapRange.max - y) / (gapRange.max - gapRange.min)) * gapPlotH;
    let gapPath = '';
    let gapTicks = [];
    let zeroY = null;
    if (gaps.length) {
      gapRange = energyAxisRange(gaps.map((g) => g.gap), 0.15);
      // Keep zero in view when the gap straddles or is near zero.
      if (gapRange.min > 0) gapRange.min = Math.min(0, gapRange.min);
      if (gapRange.max < 0) gapRange.max = Math.max(0, gapRange.max);
      if (gapRange.min === gapRange.max) {
        gapRange.min -= 1;
        gapRange.max += 1;
      }
      yGap = (y) => gapTop + 14 + ((gapRange.max - y) / (gapRange.max - gapRange.min)) * gapPlotH;
      gapPath = gaps.length >= 2
        ? pathOf(gaps, (g) => xScale(g.frame), (g) => yGap(g.gap))
        : '';
      gapTicks = ticksFor(gapRange, yGap, 3);
      if (gapRange.min <= 0 && gapRange.max >= 0) zeroY = yGap(0);
    }

    const missing = predicted.length - actual.length;
    return {
      dual, shared,
      predicted, actual, gaps,
      x0, x1, xScale,
      yAct, yPred, yGap,
      predPath, actPath, gapPath,
      leftTicks, rightTicks, gapTicks, zeroY,
      gapRange,
      missing, total: predicted.length,
      hasGap: gaps.length > 0,
      marker: fileNumber(current),
      topBottom: PAD.t + topPlotH,
      gapBottom: gapTop + 14 + gapPlotH,
      gapTop: gapTop + 14,
    };
  });

</script>

<div class="flex flex-col w-full h-full">
  <div class="flex-1 min-h-0 flex {chart ? 'flex-col min-[900px]:flex-row' : ''} overflow-hidden">
    <div class="flex-1 min-h-0 relative overflow-hidden">
      {#if trajectory}
        {#key trajectory}
          <Trajectory
            {trajectory}
            bind:current_step_idx={stepIdx}
            auto_play={false}
            show_controls="never"
            allow_file_drop={false}
            display_mode="structure"
            structure_props={{
              performance_mode: 'speed',
              scene_props: {
                atom_radius: 1.8,
                same_size_atoms: false,
                show_bonds: 'always',
              },
              color_scheme: 'Jmol',
            }}
            style="height:100%"
          />
        {/key}
      {:else}
        <div class="absolute inset-0 flex items-center justify-center text-sm text-slate-500">Need at least two frames to play.</div>
      {/if}
    </div>
    {#if chart}
      <div class="shrink-0 border-t min-[900px]:border-t-0 min-[900px]:border-l border-slate-200 bg-white px-2 py-2 min-[900px]:w-[46%] min-[900px]:max-w-[480px] flex flex-col min-h-0">
        <div class="flex items-center justify-between gap-2 px-1 mb-0.5">
          <span class="text-[11px] font-bold uppercase tracking-wide text-slate-600">Energy</span>
          <div class="flex items-center gap-3 text-[11px] text-slate-600">
            <span class="inline-flex items-center gap-1.5"><span class="inline-block w-3.5 h-0.5 rounded bg-slate-500" aria-hidden="true"></span><span class="font-semibold text-slate-600">Actual</span></span>
            <span class="inline-flex items-center gap-1.5"><span class="inline-block w-3.5 h-0.5 rounded bg-brand-600" aria-hidden="true"></span><span class="font-semibold text-brand-700">Predicted</span></span>
            {#if chart.hasGap}
              <span class="inline-flex items-center gap-1.5"><span class="inline-block w-3.5 h-0.5 rounded bg-emerald-600" aria-hidden="true"></span><span class="font-semibold text-emerald-700">Gap</span></span>
            {/if}
          </div>
        </div>
        <svg viewBox="0 0 {W} {H}" class="w-full flex-1 min-h-[240px] select-none" role="img" aria-label="Actual versus predicted energy and energy gap by frame">
          <!-- Top panel -->
          <rect x={PAD.l} y={PAD.t} width={plotW} height={topPlotH} fill="#f8fafc" stroke="#e2e8f0" />
          {#each chart.leftTicks as tick}
            <line x1={PAD.l} x2={PAD.l + plotW} y1={tick.y} y2={tick.y} stroke="#e2e8f0" stroke-dasharray="3 3" />
            <text x={PAD.l - 6} y={tick.y + 3} text-anchor="end" font-size="9" fill={chart.dual ? '#64748b' : '#64748b'} font-family="ui-monospace, monospace">{tick.label}</text>
          {/each}
          {#if chart.dual}
            {#each chart.rightTicks as tick}
              <text x={PAD.l + plotW + 6} y={tick.y + 3} text-anchor="start" font-size="9" fill="#4f46e5" font-family="ui-monospace, monospace">{tick.label}</text>
            {/each}
            <text x={14} y={PAD.t + topPlotH / 2} text-anchor="middle" font-size="10" fill="#64748b" font-weight="600" transform="rotate(-90 14 {PAD.t + topPlotH / 2})">Actual (eV)</text>
            <text x={W - 12} y={PAD.t + topPlotH / 2} text-anchor="middle" font-size="10" fill="#4f46e5" font-weight="600" transform="rotate(90 {W - 12} {PAD.t + topPlotH / 2})">Predicted (eV)</text>
          {:else}
            <text x={14} y={PAD.t + topPlotH / 2} text-anchor="middle" font-size="10" fill="#64748b" transform="rotate(-90 14 {PAD.t + topPlotH / 2})">eV</text>
          {/if}
          {#if chart.actPath}
            <path d={chart.actPath} fill="none" stroke="#64748b" stroke-width="2" />
          {/if}
          <path d={chart.predPath} fill="none" stroke="#4f46e5" stroke-width="2" />
          {#each chart.actual as p}
            <circle cx={chart.xScale(p.frame)} cy={chart.yAct(p.actual)} r="3" fill="#64748b" stroke="#fff" stroke-width="1" />
          {/each}
          {#each chart.predicted as p}
            <circle cx={chart.xScale(p.frame)} cy={chart.yPred(p.predicted)} r="3" fill="#4f46e5" stroke="#fff" stroke-width="1" />
          {/each}

          <!-- Gap panel -->
          {#if chart.hasGap}
            <rect x={PAD.l} y={chart.gapTop} width={plotW} height={gapPlotH} fill="#f8fafc" stroke="#e2e8f0" />
            {#each chart.gapTicks as tick}
              <line x1={PAD.l} x2={PAD.l + plotW} y1={tick.y} y2={tick.y} stroke="#e2e8f0" stroke-dasharray="3 3" />
              <text x={PAD.l - 6} y={tick.y + 3} text-anchor="end" font-size="9" fill="#059669" font-family="ui-monospace, monospace">{tick.label}</text>
            {/each}
            {#if chart.zeroY != null}
              <line x1={PAD.l} x2={PAD.l + plotW} y1={chart.zeroY} y2={chart.zeroY} stroke="#94a3b8" stroke-width="1" />
            {/if}
            {#if chart.gapPath}
              <path d={chart.gapPath} fill="none" stroke="#059669" stroke-width="2" />
            {/if}
            {#each chart.gaps as g}
              <circle cx={chart.xScale(g.frame)} cy={chart.yGap(g.gap)} r="3" fill="#059669" stroke="#fff" stroke-width="1" />
            {/each}
            <text x={14} y={chart.gapTop + gapPlotH / 2} text-anchor="middle" font-size="10" fill="#059669" font-weight="600" transform="rotate(-90 14 {chart.gapTop + gapPlotH / 2})">Gap (eV)</text>
            <text x={PAD.l + 4} y={chart.gapTop - 2} font-size="9" fill="#64748b">Predicted - Actual</text>
          {:else}
            <text x={PAD.l + plotW / 2} y={gapTop + GAP_H / 2} text-anchor="middle" font-size="10" fill="#94a3b8">No gap: original energies missing</text>
          {/if}

          <!-- Shared current-frame marker -->
          {#if chart.marker >= chart.x0 && chart.marker <= chart.x1}
            {@const mx = chart.xScale(chart.marker)}
            <line x1={mx} x2={mx} y1={PAD.t} y2={chart.hasGap ? chart.gapBottom : chart.topBottom} stroke="#f43f5e" stroke-width="1.5" stroke-dasharray="4 3" />
            {#each chart.predicted.filter((p) => p.frame === chart.marker) as p}
              <circle cx={mx} cy={chart.yPred(p.predicted)} r="5" fill="#4f46e5" stroke="#fff" stroke-width="1.5" />
            {/each}
            {#each chart.actual.filter((p) => p.frame === chart.marker) as p}
              <circle cx={mx} cy={chart.yAct(p.actual)} r="5" fill="#64748b" stroke="#fff" stroke-width="1.5" />
            {/each}
            {#each chart.gaps.filter((g) => g.frame === chart.marker) as g}
              <circle cx={mx} cy={chart.yGap(g.gap)} r="5" fill="#059669" stroke="#fff" stroke-width="1.5" />
            {/each}
            <text x={mx} y={PAD.t - 6} text-anchor="middle" font-size="10" fill="#e11d48" font-weight="700">{chart.marker}</text>
          {/if}

          <text x={PAD.l} y={H - 8} font-size="10" fill="#94a3b8">{chart.x0}</text>
          <text x={PAD.l + plotW / 2} y={H - 8} text-anchor="middle" font-size="10" fill="#64748b">Frame</text>
          <text x={PAD.l + plotW} y={H - 8} text-anchor="end" font-size="10" fill="#94a3b8">{chart.x1}</text>
        </svg>
        {#if chart.dual}
          <p class="px-1 text-[10px] text-slate-500">Dual Y-axes: Actual (left) and Predicted (right) are scaled separately so both trends stay visible.</p>
        {/if}
        {#if chart.missing > 0}
          <p class="px-1 text-[10px] text-amber-700">{chart.missing} of {chart.total} frames have no original energy in the XYZ — Actual and Gap use the rest.</p>
        {:else if !chart.hasGap && chart.predicted.length >= 2}
          <p class="px-1 text-[10px] text-amber-700">No original energies in the XYZ — showing Predicted only.</p>
        {/if}
      </div>
    {/if}
  </div>
  {#if trajectory}
    <div class="flex flex-wrap items-center gap-2 px-3 py-2 border-t border-slate-200 bg-white text-xs text-slate-700">
      <button type="button" class="px-2 py-1 rounded-md bg-slate-100 hover:bg-slate-200 disabled:opacity-40" title="Previous" onclick={() => go(-1)} disabled={stepIdx === 0}>⏮</button>
      <button type="button" class="px-3 py-1 rounded-md font-semibold {playing ? 'bg-brand-600 text-white' : 'bg-brand-50 text-brand-700 hover:bg-brand-100'}" title={playing ? 'Pause' : 'Play'} onclick={() => (playing = !playing)}>{playing ? '⏸ Pause' : '▶ Play'}</button>
      <button type="button" class="px-2 py-1 rounded-md bg-slate-100 hover:bg-slate-200 disabled:opacity-40" title="Next" onclick={() => go(1)} disabled={stepIdx >= positions.length - 1}>⏭</button>
      <input type="range" class="flex-1 min-w-[120px] accent-brand-600" min="0" max={positions.length - 1} bind:value={stepIdx} aria-label="Trajectory position" />
      <span class="flex items-center gap-1 whitespace-nowrap font-mono">
        Frame
        <input type="number" class="w-16 px-1.5 py-0.5 rounded-md border border-slate-200 bg-white text-center text-xs font-mono" min="1" max={totalFrames || frames.length} value={fileNumber(current)} aria-label="Player go to frame" title="Type a frame number and press Enter" onkeydown={(event) => { if (event.key === 'Enter') applyGoto(event); }} onchange={applyGoto} />
        of {totalFrames || frames.length}
      </span>
      {#if !exact}
        <span class="text-amber-700 whitespace-nowrap" title="Playback uses a sample of the frames">(showing nearest sampled frame {fileNumber(positions[stepIdx])})</span>
      {/if}
      <label class="flex items-center gap-1 whitespace-nowrap">FPS
        <select class="border border-slate-200 rounded px-1 py-0.5 bg-white" bind:value={fps}>
          {#each [2, 5, 10, 20, 30] as option}<option value={option}>{option}</option>{/each}
        </select>
      </label>
      {#if sampled}
        <span class="text-slate-500 whitespace-nowrap">{positions.length} of {frames.length} frames sampled for playback</span>
      {/if}
    </div>
  {/if}
</div>
