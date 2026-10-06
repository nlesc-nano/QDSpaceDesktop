// Frame helpers used only by Predict: XYZ frame slicing, range/index maps,
// playback thinning and result-frame lookup. Pure functions (no Svelte, no DOM).

/** Line ranges of each frame block in a (multi-frame) XYZ text, counted like the sidecar reads them. */
export function xyzFrameBlocks(text) {
  if (!text) return { lines: [], blocks: [] };
  const lines = String(text).replace(/\r\n?/g, '\n').split('\n');
  const blocks = [];
  let cursor = 0;
  while (cursor < lines.length) {
    while (cursor < lines.length && !lines[cursor].trim()) cursor += 1;
    if (cursor >= lines.length) break;
    const count = Number.parseInt(lines[cursor].trim(), 10);
    if (!Number.isFinite(count) || count < 1) break;
    const end = cursor + count + 2;
    if (end > lines.length) break;
    blocks.push([cursor, end]);
    cursor = end;
  }
  return { lines, blocks };
}

/** Clamp a 1-based frame number into 1..total. Returns null for non-numbers. */
export function clampFrameNumber(value, total) {
  if (value === null || value === undefined || String(value).trim() === '') return null;
  const n = Math.round(Number(value));
  if (!Number.isFinite(n)) return null;
  return Math.min(Math.max(1, n), Math.max(1, total));
}

/** 0-based file frame indices for a 1-based inclusive range with a step. */
export function rangeIndices(start, end, step, total) {
  if (!(total >= 1)) return [];
  let a = clampFrameNumber(start, total);
  let b = clampFrameNumber(end, total);
  if (a == null || b == null) return [];
  if (a > b) [a, b] = [b, a];
  const s = Math.max(1, Math.round(Number(step)) || 1);
  const out = [];
  for (let n = a; n <= b; n += s) out.push(n - 1);
  return out;
}

/**
 * Keep only the given 0-based frames of an XYZ text.
 * Returns { text, indexMap } where indexMap[i] is the original file frame of output frame i.
 */
export function sliceXyzFrames(text, indices) {
  const { lines, blocks } = xyzFrameBlocks(text);
  const parts = [];
  const indexMap = [];
  for (const index of indices) {
    const block = blocks[index];
    if (!block) continue;
    parts.push(lines.slice(block[0], block[1]).join('\n'));
    indexMap.push(index);
  }
  return { text: parts.length ? parts.join('\n') + '\n' : '', indexMap };
}

/**
 * Positions 0..count-1 to keep for smooth playback (about maxFrames of them).
 * Always keeps the first and the last position.
 */
export function thinPositions(count, maxFrames = 150) {
  if (!(count > 0)) return [];
  const limit = Math.max(2, Math.floor(maxFrames));
  if (count <= limit) return Array.from({ length: count }, (_, i) => i);
  const stride = Math.ceil(count / limit);
  const out = [];
  for (let i = 0; i < count; i += stride) out.push(i);
  if (out[out.length - 1] !== count - 1) out.push(count - 1);
  return out;
}

/** Playback frame budget: fewer frames for big structures, between 150 and 1000. */
export function playbackBudget(nAtoms) {
  const atoms = Math.max(1, Number(nAtoms) || 1);
  return Math.max(150, Math.min(1000, Math.floor(300000 / atoms)));
}

/** Index of the largest sorted[i] <= value (0 if value is below the first entry, -1 if empty). */
export function nearestAtOrBelow(sorted, value) {
  if (!sorted?.length) return -1;
  let lo = 0;
  let hi = sorted.length - 1;
  if (value <= sorted[0]) return 0;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (sorted[mid] <= value) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

/** Original file frame (0-based) of a result frame. */
export function sourceIndexOf(frame, fallback = 0) {
  return Number.isInteger(frame?.source_index) ? frame.source_index : fallback;
}

/** Result position whose source frame is `source` (frames are in increasing source order), or -1. */
export function findResultIndex(frames, source) {
  if (!frames?.length || !Number.isInteger(source)) return -1;
  if (sourceIndexOf(frames[source], source) === source && frames[source]) return source;
  let lo = 0;
  let hi = frames.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const s = sourceIndexOf(frames[mid], mid);
    if (s === source) return mid;
    if (s < source) lo = mid + 1;
    else hi = mid - 1;
  }
  return -1;
}

/** Largest per-atom force magnitude (eV/Å), or null. */
export function maxForceMagnitude(forces) {
  if (!Array.isArray(forces) || !forces.length) return null;
  let max = 0;
  for (const f of forces) {
    if (!f || f.length < 3) continue;
    const m = Math.hypot(Number(f[0]), Number(f[1]), Number(f[2]));
    if (Number.isFinite(m) && m > max) max = m;
  }
  return max;
}

/** Short text for a range: "frames 3–40 every 2". */
export function rangeLabel(indexMap, step) {
  if (!indexMap?.length) return '';
  const first = indexMap[0] + 1;
  const last = indexMap[indexMap.length - 1] + 1;
  const every = step > 1 ? ` every ${step}` : '';
  return first === last ? `frame ${first}` : `frames ${first}–${last}${every}`;
}

/**
 * Points for the Results energy plot. frame is 1-based (file number).
 * actual is null when the XYZ has no original energy for that frame.
 */
export function buildEnergySeries(frames, originalEnergyAt) {
  const points = [];
  if (!frames?.length) return points;
  for (let i = 0; i < frames.length; i++) {
    const source = sourceIndexOf(frames[i], i);
    const predicted = Number(frames[i]?.energy);
    if (!Number.isFinite(predicted)) continue;
    const raw = typeof originalEnergyAt === 'function' ? originalEnergyAt(source) : null;
    const actual = Number.isFinite(raw) ? Number(raw) : null;
    points.push({ frame: source + 1, predicted, actual });
  }
  return points;
}

/** Tight Y range for a series; pads by padFrac of the span (or ±1 if flat). */
export function energyAxisRange(values, padFrac = 0.12) {
  const nums = (values || []).filter((v) => Number.isFinite(v));
  if (!nums.length) return { min: -1, max: 1 };
  let min = Math.min(...nums);
  let max = Math.max(...nums);
  if (min === max) {
    const pad = Math.max(1, Math.abs(min) * 0.01 || 1);
    return { min: min - pad, max: max + pad };
  }
  const pad = (max - min) * padFrac;
  return { min: min - pad, max: max + pad };
}

/** Gap points (Predicted − Actual) only where both energies exist. */
export function energyGapPoints(points) {
  const out = [];
  for (const p of points || []) {
    if (!Number.isFinite(p?.predicted) || !Number.isFinite(p?.actual)) continue;
    out.push({ frame: p.frame, gap: p.predicted - p.actual });
  }
  return out;
}

/** True when Actual and Predicted span different scales and need separate Y axes. */
export function needsDualEnergyAxis(actualValues, predictedValues) {
  const a = (actualValues || []).filter(Number.isFinite);
  const p = (predictedValues || []).filter(Number.isFinite);
  if (a.length < 1 || p.length < 1) return false;
  const aMin = Math.min(...a);
  const aMax = Math.max(...a);
  const pMin = Math.min(...p);
  const pMax = Math.max(...p);
  const combined = energyAxisRange([...a, ...p], 0.08);
  const span = combined.max - combined.min || 1;
  const aSpan = Math.max(aMax - aMin, span * 0.001);
  const pSpan = Math.max(pMax - pMin, span * 0.001);
  // Dual if either series would occupy < 15% of a shared axis, or means differ by > 3× the larger series span.
  const aFrac = aSpan / span;
  const pFrac = pSpan / span;
  if (aFrac < 0.15 || pFrac < 0.15) return true;
  const midA = (aMin + aMax) / 2;
  const midP = (pMin + pMax) / 2;
  return Math.abs(midA - midP) > 3 * Math.max(aSpan, pSpan);
}
