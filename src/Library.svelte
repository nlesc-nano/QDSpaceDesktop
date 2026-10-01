<script>
  import { onMount } from "svelte";
  import Viewer from "./Viewer.svelte";
  import { templateFor } from "./bulkTemplates.js";
  import { makeZip } from "./zip.js";

  // Opens a structure in the Builder's post-treatment view (set by App).
  let { onOpenInBuilder = null } = $props();

  // Structures are not bundled. Prefer /library_index.json, then the published site.
  const LIBRARY_REMOTE = "https://dmq59n0f96mxz.cloudfront.net";
  let assetBase = $state("");

  function assetUrl(path) {
    const pth = String(path || "").startsWith("/") ? String(path) : `/${path}`;
    return `${assetBase}${pth}`;
  }

  // --- Index (library_index.json: one record per structure) ---
  let structures = $state([]);
  let loadError = $state("");
  let activeViewer = $state("molstar");

  // --- Filters ---
  let filters = $state({
    family: "",
    material: "",
    phase: "",
    centre: "",
    surface: "",
    facet: "",
    functional: "",
    source: "",
    dMin: null,
    dMax: null,
    unrelaxed: false,
    optimized: false,
    md: false,
    properties: false,
  });
  let selectedFormulas = $state([]);
  let showAllFormulas = $state(false);

  // --- Current selection ---
  let current = $state(null); // record
  let stageIndex = $state(0);
  let xyzText = $state("");
  let fileUrl = $state("");
  let loadingStage = $state(false);
  let previousBlobUrl = null;

  let propertiesStatus = $state("idle");
  let activePropertyTab = $state("fuzzy_sf");
  let plotUrls = $state({ fuzzy_sf: null, fuzzy_soc: null, exciton_sf: null, exciton_soc: null });

  const SOURCE_LABEL = { builder: "Builder", dft: "DFT", "builder+dft": "Builder + DFT" };
  const PHASE_SHORT = { "zinc-blende": "zb", wurtzite: "wz", "rock-salt": "rs" };

  onMount(async () => {
    try {
      let res = await fetch("/library_index.json");
      let fromRemote = false;
      if (!res.ok) {
        res = await fetch(`${LIBRARY_REMOTE}/library_index.json`);
        fromRemote = true;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const index = await res.json();
      structures = index.structures || [];
      if (fromRemote) {
        assetBase = LIBRARY_REMOTE;
      } else {
        const probe = structures[0]?.stages?.[0]?.file;
        if (probe) {
          const head = await fetch(`/${probe}`, { method: "HEAD" }).catch(() => null);
          if (!head?.ok) assetBase = LIBRARY_REMOTE;
        }
      }
    } catch (err) {
      loadError = `Failed to load the library index: ${err.message}`;
    }
  });

  // --- Helpers ---
  const uniq = (xs) => [...new Set(xs.filter((x) => x !== undefined && x !== null && x !== ""))];
  const dOf = (r) => r.size?.d_nm ?? 0;
  const functionalsOf = (r) => uniq(r.stages.map((s) => s.functional));

  const hasUnrelaxed = (r) => r.stages.some((s) => s.stage === "start");

  function stageLabel(st) {
    if (st.stage === "start") {
      if (st.dft_start) return "Unrelaxed · DFT input";
      return current?.source?.startsWith("builder") ? "Unrelaxed · builder" : "Unrelaxed";
    }
    if (st.stage === "geo_opt") return `Relaxed · ${st.functional || "functional unknown"}`;
    if (st.stage === "md") return st.functional ? `MD · ${st.functional}` : "MD";
    return st.stage;
  }

  // "Cd68Se55Cl26" -> [{t:"Cd"},{t:"68",sub:true},...] for subscript rendering.
  const formulaParts = (f) =>
    String(f).split(/(\d+)/).filter(Boolean).map((t) => ({ t, sub: /^\d+$/.test(t) }));

  // Relaxed geometry with no unrelaxed input (e.g. legacy "old/" files).
  const relaxedOnlyNote = (r) => {
    if (hasUnrelaxed(r)) return "";
    const opt = r.stages.find((s) => s.stage === "geo_opt");
    if (!opt) return "";
    return opt.functional ? "relaxed only" : "relaxed only · functional unknown";
  };

  // --- Centre role (cation / anion / interstitial) ---
  const ANIONS = new Set(["O", "S", "Se", "Te", "N", "P", "As", "Sb", "F", "Cl", "Br", "I"]);
  const centreRole = (c) => (c === "interstitial" ? "interstitial" : ANIONS.has(c) ? "anion" : "cation");
  const centreLabel = (c) => (c === "interstitial" ? "interstitial" : `${c}-centred`);

  // --- Facet recipe (builder records: origin.recipe.facets) ---
  const facetsOf = (r) => r.origin?.recipe?.facets || null;
  const hklText = (hkl) => String(hkl);
  // Facet family for filtering: sign and order dropped, so "-1-1-1" -> "111", "010" -> "100".
  const hklFamily = (hkl) => (String(hkl).match(/\d/g) || []).sort().reverse().join("");
  const facetFamiliesOf = (r) => uniq((facetsOf(r) || []).map((f) => hklFamily(f.hkl)));
  const gammaText = (g) => (g === undefined || g === null ? "?" : Number(g).toFixed(1));
  const terminationText = (t) => (t ? String(t).replace("_", "-") : "stoichiometric");
  const recipeKey = (r) => {
    const fs = facetsOf(r);
    return fs ? fs.map((f) => `${f.hkl}:${gammaText(f.gamma)}:${f.termination || ""}`).join("|") : "";
  };
  const recipeLabel = (r) => (facetsOf(r) || []).map((f) => `{${hklText(f.hkl)}}${gammaText(f.gamma)}`).join(" · ");
  const recipeTooltip = (r) =>
    (facetsOf(r) || [])
      .map((f) => `{${hklText(f.hkl)}}  γ = ${gammaText(f.gamma)}  ${terminationText(f.termination)}`)
      .join("\n");
  // One dot colour per distinct recipe, assigned over the whole index so it is
  // stable under filtering.
  const RECIPE_DOTS = ["bg-cyan-500", "bg-fuchsia-500", "bg-lime-500", "bg-orange-500", "bg-violet-500",
                       "bg-rose-500", "bg-yellow-500", "bg-teal-500", "bg-stone-500", "bg-blue-500"];

  // Filters except composition (the composition chips list what these leave).
  function passesBase(r, f) {
    if (f.family && r.family !== f.family) return false;
    if (f.material && r.material !== f.material) return false;
    if (f.phase && r.phase !== f.phase) return false;
    if (f.centre && r.centre !== f.centre) return false;
    if (f.surface && r.surface !== f.surface) return false;
    if (f.facet && !facetFamiliesOf(r).includes(f.facet)) return false;
    if (f.source === "builder" && !r.source.includes("builder")) return false;
    if (f.source === "dft" && !r.source.includes("dft")) return false;
    if (f.source === "dft" && f.functional && !functionalsOf(r).includes(f.functional)) return false;
    if (f.dMin !== null && f.dMin !== "" && dOf(r) < Number(f.dMin)) return false;
    if (f.dMax !== null && f.dMax !== "" && dOf(r) > Number(f.dMax)) return false;
    if (f.unrelaxed && !hasUnrelaxed(r)) return false;
    if (f.optimized && !r.flags?.optimized) return false;
    if (f.md && !r.flags?.md) return false;
    if (f.properties && !r.flags?.properties) return false;
    return true;
  }

  let baseMatches = $derived(
    structures.filter((r) => passesBase(r, filters)).sort((a, b) => dOf(a) - dOf(b) || a.id.localeCompare(b.id)),
  );
  let matches = $derived(
    selectedFormulas.length ? baseMatches.filter((r) => selectedFormulas.includes(r.formula)) : baseMatches,
  );

  // Options narrow with the higher-level choices.
  let families = $derived(uniq(structures.map((r) => r.family)).sort());
  let materials = $derived(
    uniq(structures.filter((r) => !filters.family || r.family === filters.family).map((r) => r.material)).sort(),
  );
  let scopedMaterial = $derived(
    structures.filter(
      (r) => (!filters.family || r.family === filters.family) && (!filters.material || r.material === filters.material),
    ),
  );
  let phases = $derived(uniq(scopedMaterial.map((r) => r.phase)).sort());
  let scoped = $derived(scopedMaterial.filter((r) => !filters.phase || r.phase === filters.phase));
  let centres = $derived(uniq(scoped.map((r) => r.centre)).sort());
  let functionals = $derived(uniq(scoped.flatMap(functionalsOf)).sort());
  let recipeDot = $derived.by(() => {
    const counts = new Map();
    for (const r of structures) {
      const k = recipeKey(r);
      if (k) counts.set(k, (counts.get(k) || 0) + 1);
    }
    const keys = [...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a) || a.localeCompare(b));
    return new Map(keys.map((k, i) => [k, RECIPE_DOTS[i % RECIPE_DOTS.length]]));
  });
  let facetFamilies = $derived(uniq(scoped.flatMap(facetFamiliesOf)).sort());
  let dBounds = $derived.by(() => {
    const ds = scoped.map(dOf).filter((d) => d > 0);
    return ds.length ? [Math.floor(Math.min(...ds) * 10) / 10, Math.ceil(Math.max(...ds) * 10) / 10] : [0, 0];
  });
  let formulaChips = $derived(
    uniq(baseMatches.map((r) => r.formula)).map((f) => ({
      formula: f,
      d: dOf(baseMatches.find((r) => r.formula === f)),
    })),
  );

  function resetBelow(level) {
    if (level <= 0) filters.material = "";
    if (level <= 1) filters.phase = "";
    if (level <= 2) {
      filters.centre = "";
      filters.facet = "";
      filters.functional = "";
      filters.dMin = null;
      filters.dMax = null;
    }
    selectedFormulas = [];
  }

  function toggleFormula(f) {
    selectedFormulas = selectedFormulas.includes(f)
      ? selectedFormulas.filter((x) => x !== f)
      : [...selectedFormulas, f];
  }

  function clearFilters() {
    Object.assign(filters, {
      family: "", material: "", phase: "", centre: "", surface: "", facet: "", functional: "", source: "",
      dMin: null, dMax: null, unrelaxed: false, optimized: false, md: false, properties: false,
    });
    selectedFormulas = [];
  }

  // --- Selection & loading ---
  function defaultStageIndex(r) {
    const opt = r.stages.findIndex((s) => s.stage === "geo_opt");
    if (opt >= 0) return opt;
    const start = r.stages.findIndex((s) => s.stage === "start");
    return start >= 0 ? start : 0;
  }

  async function selectStructure(r) {
    current = r;
    await selectStage(defaultStageIndex(r));
    loadProperties(r);
  }

  let currentStage = $derived(current ? current.stages[stageIndex] : null);
  let isMD = $derived(currentStage?.stage === "md");

  async function selectStage(i) {
    if (!current) return;
    stageIndex = i;
    const st = current.stages[i];
    loadingStage = true;
    if (previousBlobUrl) {
      URL.revokeObjectURL(previousBlobUrl);
      previousBlobUrl = null;
    }
    try {
      const res = await fetch(assetUrl(st.file));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const text = (await res.text()).replace(/\r\n/g, "\n");
      if (st.stage === "md") {
        xyzText = "";
        fileUrl = trajectoryBlobUrl(text) || assetUrl(st.file);
      } else {
        xyzText = text;
        fileUrl = assetUrl(st.file);
      }
    } catch (err) {
      xyzText = "";
      fileUrl = "";
      loadError = `Could not load ${st.file}: ${err.message}`;
    } finally {
      loadingStage = false;
    }
  }

  // Downsample a trajectory to ~150 frames for smooth playback.
  function trajectoryBlobUrl(text) {
    const lines = text.split("\n");
    const nAtoms = parseInt(lines[0].trim());
    if (isNaN(nAtoms) || nAtoms <= 0) return null;
    const perFrame = nAtoms + 2;
    const total = Math.floor(lines.length / perFrame);
    const stride = Math.max(1, Math.floor(total / 150));
    const frames = [];
    for (let i = 0; i < total; i += stride) {
      const a = i * perFrame;
      if (a + perFrame <= lines.length) frames.push(lines.slice(a, a + perFrame).join("\n"));
    }
    const url = URL.createObjectURL(new Blob([frames.join("\n") + "\n"], { type: "text/plain" }));
    previousBlobUrl = url;
    return url + "#trajectory.xyz";
  }

  // --- Properties: from the record; probe the legacy folder as a fallback ---
  const PROPERTY_FILES = {
    fuzzy_sf: ["fuzzy_dashboard_sf.html", "plot.html", "plot.html.gz"],
    fuzzy_soc: ["fuzzy_dashboard_soc.html"],
    exciton_sf: ["exciton_analysis_sf.html"],
    exciton_soc: ["exciton_analysis_soc.html"],
  };

  async function loadProperties(r) {
    plotUrls = { fuzzy_sf: null, fuzzy_soc: null, exciton_sf: null, exciton_soc: null };
    const props = r.properties || {};
    for (const [tab, names] of Object.entries(PROPERTY_FILES)) {
      const hit = names.find((n) => props[n]);
      if (hit) plotUrls[tab] = assetUrl(props[hit]);
    }
    const legacy = (r.origin?.legacy_paths || []).find((p) => !p.endsWith(".xyz"));
    if (!Object.values(plotUrls).some(Boolean) && legacy) {
      propertiesStatus = "loading";
      const dir = assetUrl(`${legacy}/properties`);
      const probe = (n) =>
        fetch(`${dir}/${n}`, { method: "HEAD", cache: "no-store" })
          .then((res) => (res.ok ? `${dir}/${n}` : null))
          .catch(() => null);
      for (const [tab, names] of Object.entries(PROPERTY_FILES)) {
        for (const n of names) {
          const url = await probe(n);
          if (url) { plotUrls[tab] = url; break; }
        }
      }
    }
    const first = Object.keys(PROPERTY_FILES).find((t) => plotUrls[t]);
    if (first) {
      activePropertyTab = first;
      propertiesStatus = "ready";
    } else {
      propertiesStatus = "none";
    }
  }

  // --- Actions ---
  function download() {
    if (!current || !currentStage) return;
    const a = document.createElement("a");
    if (isMD) {
      a.href = assetUrl(currentStage.file);
    } else {
      a.href = URL.createObjectURL(new Blob([xyzText], { type: "text/plain" }));
    }
    const suffix = currentStage.stage === "start" ? (currentStage.dft_start ? "dft_start" : "start") : currentStage.stage;
    a.download = `${current.id}_${suffix}${currentStage.functional ? "_" + currentStage.functional : ""}.xyz`;
    a.click();
  }

  // --- Download every structure left by the filters as one zip ---
  let zipIncludeMD = $state(false);
  let zipStatus = $state("");

  function stageFileName(st, used) {
    let base;
    if (st.stage === "start") base = st.dft_start ? "unrelaxed_dft_input" : "unrelaxed";
    else if (st.stage === "geo_opt") base = `relaxed_${st.functional || "functional_unknown"}`;
    else if (st.stage === "md") base = `md_${st.functional || "trajectory"}`;
    else base = st.stage;
    let name = `${base}.xyz`;
    for (let k = 2; used.has(name); k++) name = `${base}_${k}.xyz`;
    used.add(name);
    return name;
  }

  function csvCell(v) {
    const t = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
  }

  async function downloadMatchesZip() {
    const list = matches;
    if (!list.length) return;
    if (list.length > 150 && !confirm(`Download ${list.length} structures as one zip?`)) return;
    const enc = new TextEncoder();
    const files = [];
    const header = ["id", "formula", "material", "family", "centre", "surface", "facets", "source",
                    "d_nm", "n_atoms", "total_charge", "unit_cells", "files"];
    const rows = [header];
    try {
      for (let k = 0; k < list.length; k++) {
        const r = list[k];
        zipStatus = `Fetching ${k + 1}/${list.length}…`;
        const used = new Set();
        const names = [];
        for (const st of r.stages) {
          if (st.stage === "md" && !zipIncludeMD) continue;
          const res = await fetch(assetUrl(st.file));
          if (!res.ok) continue;
          const name = stageFileName(st, used);
          files.push({ name: `${r.id}/${name}`, data: new Uint8Array(await res.arrayBuffer()) });
          names.push(name);
        }
        files.push({ name: `${r.id}/record.json`, data: enc.encode(JSON.stringify(r, null, 1)) });
        rows.push([r.id, r.formula, r.material, r.family, r.centre, r.surface, recipeTooltip(r).replace(/\n/g, "; "), r.source,
                   dOf(r).toFixed(3), r.n_atoms, r.total_charge, r.size?.unit_cells ?? "", names.join(" ")]);
      }
      files.push({ name: "index.csv", data: enc.encode(rows.map((row) => row.map(csvCell).join(",")).join("\n") + "\n") });
      zipStatus = "Packing…";
      const blob = makeZip(files);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      const tag = [filters.material || filters.family || "library", filters.surface, filters.centre && `${filters.centre}-centred`]
        .filter(Boolean).join("_");
      a.download = `qdspace_${tag}_${list.length}_structures.zip`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 10000);
      zipStatus = `${list.length} structures, ${(blob.size / 1e6).toFixed(1)} MB`;
    } catch (err) {
      zipStatus = `Download failed: ${err.message}`;
    }
  }

  let builderTemplate = $derived(current ? templateFor(current.family, current.material, current.phase) : null);
  let canOpenInBuilder = $derived(Boolean(onOpenInBuilder && builderTemplate && xyzText && !isMD));

  function openInBuilder() {
    if (!canOpenInBuilder) return;
    const recipe = current.origin?.recipe || {};
    onOpenInBuilder({
      template: builderTemplate,
      xyz: xyzText,
      facets: recipe.facets || null,
      centre: current.centre,
      unitCells: current.size?.unit_cells || null,
      label: `${current.id} (${stageLabel(currentStage)})`,
    });
  }

  function badgeClass(kind) {
    return {
      clean: "bg-slate-100 text-slate-700 border-slate-200",
      cation: "bg-rose-50 text-rose-800 border-rose-200",
      anion: "bg-teal-50 text-teal-800 border-teal-200",
      interstitial: "bg-violet-50 text-violet-800 border-violet-200",
      unrelaxed: "bg-sky-50 text-sky-800 border-sky-200",
      reconstructed: "bg-amber-50 text-amber-800 border-amber-200",
      opt: "bg-emerald-50 text-emerald-800 border-emerald-200",
      md: "bg-indigo-50 text-indigo-800 border-indigo-200",
      props: "bg-brand-50 text-brand-800 border-brand-200",
      source: "bg-accent-50 text-accent-800 border-accent-200",
    }[kind];
  }
</script>

<div class="flex flex-col lg:flex-row h-[calc(100vh-64px)] overflow-hidden font-sans bg-slate-50">
  <aside class="w-full lg:w-[400px] p-6 bg-slate-50 overflow-y-auto flex-shrink-0 border-r border-slate-200 flex flex-col gap-6">
    <div class="px-2 pt-2">
      <h1 class="font-heading text-2xl font-bold flex items-center gap-3 mb-2 text-slate-900 tracking-tight">
        <img src="/assets/logos/QD_Library_mini.png" alt="QD Library" class="h-9 w-auto mix-blend-multiply" />
        Quantum Dot Library
      </h1>
      <p class="text-sm text-slate-600 font-medium leading-relaxed">
        Builder-generated and DFT-computed quantum dots: starting structures, optimized geometries, MD and interactive properties.
      </p>
    </div>

    <!-- Filters -->
    <div class="bg-white rounded-[1.5rem] shadow-sm border border-slate-100 p-6 flex flex-col gap-4">
      <div class="flex justify-between items-center">
        <h2 class="font-heading text-xl font-bold text-slate-900">Database Filters</h2>
        <button class="text-xs font-bold text-slate-400 hover:text-accent-600" onclick={clearFilters}>Clear</button>
      </div>

      <div class="grid grid-cols-2 gap-3">
        <label class="block">
          <span class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-1.5">Family</span>
          <select class="w-full ring-1 ring-slate-200 rounded-xl p-2.5 text-sm bg-slate-50 outline-none font-medium"
                  bind:value={filters.family} onchange={() => resetBelow(0)}>
            <option value="">All</option>
            {#each families as f}<option value={f}>{f}</option>{/each}
          </select>
        </label>
        <label class="block">
          <span class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-1.5">Material</span>
          <select class="w-full ring-1 ring-slate-200 rounded-xl p-2.5 text-sm bg-slate-50 outline-none font-medium"
                  bind:value={filters.material} onchange={() => resetBelow(1)}>
            <option value="">All</option>
            {#each materials as m}<option value={m}>{m}</option>{/each}
          </select>
        </label>
      </div>

      {#if phases.length}
        <label class="block">
          <span class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-1.5">Phase</span>
          <select class="w-full ring-1 ring-slate-200 rounded-xl p-2.5 text-sm bg-slate-50 outline-none font-medium"
                  value={phases.length === 1 ? phases[0] : filters.phase}
                  onchange={(e) => { filters.phase = e.currentTarget.value; resetBelow(2); }}>
            {#if phases.length > 1}<option value="">All</option>{/if}
            {#each phases as p}<option value={p}>{p}</option>{/each}
          </select>
        </label>
      {/if}

      <label class="block">
        <span class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-1.5">Centre</span>
        <select class="w-full ring-1 ring-slate-200 rounded-xl p-2.5 text-sm bg-slate-50 outline-none font-medium"
                bind:value={filters.centre} onchange={() => (selectedFormulas = [])}>
          <option value="">All</option>
          {#each centres as c}<option value={c}>{centreLabel(c)}</option>{/each}
        </select>
      </label>

      {#if facetFamilies.length}
        <label class="block">
          <span class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-1.5">Facet</span>
          <select class="w-full ring-1 ring-slate-200 rounded-xl p-2.5 text-sm bg-slate-50 outline-none font-medium"
                  bind:value={filters.facet} onchange={() => (selectedFormulas = [])}>
            <option value="">All</option>
            {#each facetFamilies as h}<option value={h}>{`{${h}}`}</option>{/each}
          </select>
        </label>
      {/if}

      <div>
        <span class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-1.5">Surface</span>
        <div class="flex gap-1 bg-slate-100 p-1 rounded-xl">
          {#each [["", "All"], ["clean", "Clean"], ["reconstructed", "Reconstructed"]] as [v, label]}
            <button class="flex-1 px-2 py-1.5 rounded-lg text-xs font-bold transition-all {filters.surface === v ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-800'}"
                    onclick={() => { filters.surface = v; selectedFormulas = []; }}>{label}</button>
          {/each}
        </div>
      </div>

      <div>
        <span class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-1.5">Source</span>
        <div class="flex gap-1 bg-slate-100 p-1 rounded-xl">
          {#each [["", "All"], ["builder", "Builder"], ["dft", "DFT"]] as [v, label]}
            <button class="flex-1 px-2 py-1.5 rounded-lg text-xs font-bold transition-all {filters.source === v ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-800'}"
                    onclick={() => { filters.source = v; if (v !== "dft") filters.functional = ""; selectedFormulas = []; }}>{label}</button>
          {/each}
        </div>
        {#if filters.source === "dft"}
          <label class="block mt-3">
            <span class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-1.5">Functional</span>
            <select class="w-full ring-1 ring-slate-200 rounded-xl p-2.5 text-sm bg-slate-50 outline-none font-medium"
                    bind:value={filters.functional} onchange={() => (selectedFormulas = [])}>
              <option value="">Any</option>
              {#each functionals as f}<option value={f}>{f}</option>{/each}
            </select>
          </label>
        {/if}
      </div>

      <div>
        <span class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-1.5">
          Diameter (nm){#if dBounds[1] > 0}<span class="normal-case font-medium text-slate-400"> · {dBounds[0]}–{dBounds[1]}</span>{/if}
        </span>
        <div class="grid grid-cols-2 gap-3">
          <input type="number" step="0.1" min="0" placeholder="min" bind:value={filters.dMin}
                 oninput={() => (selectedFormulas = [])}
                 class="w-full ring-1 ring-slate-200 rounded-xl p-2.5 text-sm bg-slate-50 outline-none font-medium" />
          <input type="number" step="0.1" min="0" placeholder="max" bind:value={filters.dMax}
                 oninput={() => (selectedFormulas = [])}
                 class="w-full ring-1 ring-slate-200 rounded-xl p-2.5 text-sm bg-slate-50 outline-none font-medium" />
        </div>
      </div>

      <div>
        <span class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-1.5">Available data</span>
        <div class="flex flex-wrap gap-x-4 gap-y-2 text-sm">
          <label class="flex items-center gap-1.5 cursor-pointer"><input type="checkbox" bind:checked={filters.unrelaxed} class="accent-accent-600" /> <span class="font-medium text-slate-700">Unrelaxed</span></label>
          <label class="flex items-center gap-1.5 cursor-pointer"><input type="checkbox" bind:checked={filters.optimized} class="accent-accent-600" /> <span class="font-medium text-slate-700">Relaxed</span></label>
          <label class="flex items-center gap-1.5 cursor-pointer"><input type="checkbox" bind:checked={filters.md} class="accent-accent-600" /> <span class="font-medium text-slate-700">MD</span></label>
          <label class="flex items-center gap-1.5 cursor-pointer"><input type="checkbox" bind:checked={filters.properties} class="accent-accent-600" /> <span class="font-medium text-slate-700">Properties</span></label>
        </div>
      </div>

      <div>
        <span class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-1.5">
          Composition <span class="normal-case font-medium text-slate-400">· {formulaChips.length} in range</span>
        </span>
        <div class="flex flex-wrap gap-1.5 {showAllFormulas ? '' : 'max-h-28 overflow-hidden'}">
          {#each formulaChips as chip}
            <button class="px-2 py-1 rounded-lg text-[11px] font-mono font-bold border transition-all {selectedFormulas.includes(chip.formula) ? 'bg-accent-600 text-white border-accent-600' : 'bg-white text-slate-700 border-slate-200 hover:border-accent-400'}"
                    title="{chip.d.toFixed(2)} nm" onclick={() => toggleFormula(chip.formula)}>{#each formulaParts(chip.formula) as p}{#if p.sub}<sub>{p.t}</sub>{:else}{p.t}{/if}{/each}</button>
          {:else}
            <span class="text-xs text-slate-400 italic">No structures in range.</span>
          {/each}
        </div>
        {#if formulaChips.length > 12}
          <button class="text-[11px] font-bold text-accent-600 mt-1.5" onclick={() => (showAllFormulas = !showAllFormulas)}>
            {showAllFormulas ? "Show fewer" : `Show all ${formulaChips.length}`}
          </button>
        {/if}
      </div>
    </div>

    <!-- Matches -->
    <div class="bg-white rounded-[1.5rem] shadow-sm border border-slate-100 flex flex-col min-h-[300px] max-h-[520px]">
      <div class="p-5 pb-3 font-heading font-bold text-slate-900 flex justify-between">
        <span>Matches ({matches.length})</span>
        <span class="text-xs text-slate-400 font-sans font-medium">sorted by diameter</span>
      </div>
      <div class="px-5 pb-3 flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <button class="bg-accent-600 hover:bg-accent-700 disabled:bg-slate-300 text-white text-xs font-bold px-3 py-1.5 rounded-lg transition-colors"
                onclick={downloadMatchesZip} disabled={!matches.length || zipStatus.startsWith("Fetching") || zipStatus === "Packing…"}>
          Download matches (.zip)
        </button>
        <label class="flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer">
          <input type="checkbox" bind:checked={zipIncludeMD} class="accent-accent-600" /> include MD
        </label>
        {#if zipStatus}<span class="text-[11px] text-slate-500">{zipStatus}</span>{/if}
      </div>
      <div class="px-3 pb-3 overflow-y-auto flex flex-col gap-1">
        {#each matches as r (r.id)}
          <button class="text-left px-3 py-2.5 rounded-xl transition-all {current?.id === r.id ? 'bg-accent-50 ring-1 ring-accent-400' : 'hover:bg-slate-50'}"
                  onclick={() => selectStructure(r)}>
            <div class="flex justify-between items-baseline gap-2">
              <span class="text-[13px] font-bold text-slate-900 truncate">{#each formulaParts(r.formula) as p}{#if p.sub}<sub>{p.t}</sub>{:else}{p.t}{/if}{/each}</span>
              <span class="text-xs font-bold text-slate-500 whitespace-nowrap">{dOf(r).toFixed(2)} nm</span>
            </div>
            <div class="flex flex-wrap gap-1 mt-1">
              <span class="text-[10px] font-bold text-slate-500">{r.material}{#if PHASE_SHORT[r.phase]} <span class="font-medium text-slate-400">{PHASE_SHORT[r.phase]}</span>{/if}</span>
              <span class="px-1.5 rounded border text-[10px] font-bold {badgeClass(centreRole(r.centre))}">{centreLabel(r.centre)}</span>
              {#if facetsOf(r)}
                <span class="inline-flex items-center gap-1 px-1.5 rounded border text-[10px] font-mono font-bold bg-white text-slate-600 border-slate-200"
                      title={recipeTooltip(r)}><span class="w-1.5 h-1.5 rounded-full {recipeDot.get(recipeKey(r)) || 'bg-slate-400'}"></span>{recipeLabel(r)}</span>
              {/if}
              <span class="px-1.5 rounded border text-[10px] font-bold {badgeClass(r.surface)}">{r.surface}</span>
              <span class="px-1.5 rounded border text-[10px] font-bold {badgeClass('source')}">{SOURCE_LABEL[r.source] || r.source}</span>
              {#if hasUnrelaxed(r)}<span class="px-1.5 rounded border text-[10px] font-bold {badgeClass('unrelaxed')}">Unrelaxed</span>{/if}
              {#if r.flags?.optimized}<span class="px-1.5 rounded border text-[10px] font-bold {badgeClass('opt')}">Relaxed{functionalsOf(r).length ? " · " + functionalsOf(r).join("/") : ""}</span>{/if}
              {#if r.flags?.md}<span class="px-1.5 rounded border text-[10px] font-bold {badgeClass('md')}">MD</span>{/if}
              {#if r.flags?.properties}<span class="px-1.5 rounded border text-[10px] font-bold {badgeClass('props')}">Props</span>{/if}
            </div>
            {#if relaxedOnlyNote(r)}
              <div class="text-[10px] text-slate-400 mt-0.5 truncate" title={(r.origin?.legacy_paths || []).join(", ")}>
                {relaxedOnlyNote(r)} · {(r.origin?.legacy_paths || [])[0]}
              </div>
            {/if}
          </button>
        {:else}
          <span class="text-sm text-slate-400 italic p-4 text-center">{loadError || "No structures found."}</span>
        {/each}
      </div>
    </div>
  </aside>

  <main class="flex-grow h-full flex flex-col p-6 gap-6 bg-slate-50 overflow-y-auto">
    <div class="flex flex-col gap-6 flex-shrink-0 h-[calc(100vh-112px)] min-h-[700px]">
      <!-- Viewer -->
      <div class="relative flex-1 min-h-[400px] bg-white rounded-[1.5rem] p-4 border border-slate-100 shadow-sm flex flex-col">
        <div class="flex flex-wrap justify-between items-center gap-3 mb-3 px-2">
          <div class="flex items-center gap-3 min-w-0">
            <h2 class="font-heading font-bold text-xl text-slate-900 truncate">{#if current}{#each formulaParts(current.formula) as p}{#if p.sub}<sub>{p.t}</sub>{:else}{p.t}{/if}{/each}{:else}3D Structure Viewer{/if}</h2>
            {#if current}
              <div class="flex gap-1 bg-slate-100 p-1 rounded-xl border border-slate-200 overflow-x-auto">
                {#each current.stages as st, i}
                  <button class="px-3 py-1.5 rounded-lg text-xs font-bold whitespace-nowrap transition-all {stageIndex === i ? 'bg-accent-600 text-white shadow-sm' : 'text-slate-600 hover:text-slate-950'}"
                          onclick={() => selectStage(i)}>{stageLabel(st)}</button>
                {/each}
              </div>
            {/if}
          </div>
          <div class="flex items-center gap-3">
            {#if !isMD}
              <div class="flex gap-1 bg-slate-100 p-1 rounded-xl border border-slate-200">
                {#each [["3dmol", "3Dmol"], ["ngl", "NGL"], ["molstar", "Mol*"], ["matterviz", "MatterViz"]] as [v, label]}
                  <button class="px-3 py-1.5 rounded-lg text-xs font-bold transition-all {activeViewer === v ? 'bg-brand-600 text-white shadow-sm' : 'text-slate-600 hover:text-slate-950'}"
                          onclick={() => (activeViewer = v)}>{label}</button>
                {/each}
              </div>
            {/if}
            <button onclick={download} disabled={!current || (!xyzText && !isMD)}
                    class="bg-slate-100 hover:bg-slate-200 disabled:opacity-50 text-slate-800 px-4 py-2 rounded-xl text-sm font-bold transition-colors">Download XYZ</button>
          </div>
        </div>
        <div class="flex-1 bg-slate-50 rounded-[1rem] border border-slate-200 overflow-hidden relative shadow-inner">
          <Viewer xyz={xyzText} {isMD} dataUrl={fileUrl}
                  sizeMetrics={current ? { R_eff_hull: dOf(current) * 5, diameter_hull: dOf(current) * 10 } : null}
                  {activeViewer} />
          {#if loadingStage}
            <div class="absolute inset-0 bg-slate-900/40 backdrop-blur-sm flex items-center justify-center text-white z-10">
              <div class="w-10 h-10 border-4 border-brand-500 border-t-transparent rounded-full animate-spin"></div>
            </div>
          {/if}
        </div>
      </div>

      <!-- Details / provenance -->
      <div class="h-1/3 grid grid-cols-1 md:grid-cols-3 gap-6 min-h-[280px]">
        <div class="bg-white border border-slate-100 shadow-sm rounded-[1.5rem] p-6 overflow-y-auto h-full">
          <h2 class="font-heading text-lg font-bold text-slate-900 mb-4 border-b border-slate-100 pb-2">Structure</h2>
          {#if current}
            <div class="space-y-1.5 text-sm text-slate-700 bg-slate-50 p-3 rounded-2xl mb-4">
              <p class="flex justify-between"><strong class="text-slate-900">Material</strong><span>{current.material} · {current.family} · {current.phase}</span></p>
              <p class="flex justify-between"><strong class="text-slate-900">Centre</strong><span class="px-1.5 rounded border text-xs font-bold {badgeClass(centreRole(current.centre))}">{centreLabel(current.centre)}</span></p>
              <p class="flex justify-between"><strong class="text-slate-900">Surface</strong><span>{current.surface}</span></p>
              <p class="flex justify-between"><strong class="text-slate-900">Diameter</strong><span>{dOf(current).toFixed(2)} nm <span class="text-slate-400">(max {current.size?.d_max_nm?.toFixed(2)})</span></span></p>
              {#if current.size?.unit_cells}
                <p class="flex justify-between"><strong class="text-slate-900">Unit cells</strong><span>{current.size.unit_cells_all?.join(", ") ?? current.size.unit_cells}</span></p>
              {/if}
              <p class="flex justify-between"><strong class="text-slate-900">Atoms</strong><span>{current.n_atoms}</span></p>
              <p class="flex justify-between"><strong class="text-slate-900">Total charge</strong>
                <span class="{current.total_charge === 0 ? 'text-emerald-700' : 'text-red-700'} font-bold">{current.total_charge ?? "?"}</span></p>
            </div>
            <h3 class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-2">Core</h3>
            <div class="flex flex-wrap gap-2 mb-4">
              {#each Object.entries(current.core || {}) as [el, n]}
                <span class="bg-brand-50 text-brand-800 border border-brand-100 px-3 py-1 rounded-lg font-bold text-xs">{el}: {n}</span>
              {/each}
            </div>
            {#if facetsOf(current)}
              <h3 class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-2 flex items-center gap-1.5">
                <span class="w-2 h-2 rounded-full {recipeDot.get(recipeKey(current)) || 'bg-slate-400'}"></span>Facets
              </h3>
              <table class="w-full text-xs text-slate-700 mb-4">
                <thead><tr class="text-slate-400 text-left"><th class="font-bold pb-1">hkl</th><th class="font-bold pb-1">γ</th><th class="font-bold pb-1">termination</th></tr></thead>
                <tbody>
                  {#each facetsOf(current) as f}
                    <tr class="border-t border-slate-100">
                      <td class="py-1 font-mono font-bold">{"{"}{hklText(f.hkl)}{"}"}</td>
                      <td class="py-1 font-mono">{gammaText(f.gamma)}</td>
                      <td class="py-1">{terminationText(f.termination)}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            {/if}
            <h3 class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-2">Ligands</h3>
            <div class="flex flex-wrap gap-2">
              {#each Object.entries(current.ligands || {}) as [el, n]}
                <span class="bg-accent-50 text-accent-800 border border-accent-100 px-3 py-1 rounded-lg font-bold text-xs">{el}: {n}</span>
              {:else}
                <span class="text-slate-400 text-sm italic">none</span>
              {/each}
            </div>
          {:else}
            <p class="text-sm text-slate-400 italic">Select a structure to view details.</p>
          {/if}
        </div>

        <div class="bg-white border border-slate-100 shadow-sm rounded-[1.5rem] p-6 overflow-y-auto h-full">
          <h2 class="font-heading text-lg font-bold text-slate-900 mb-4 border-b border-slate-100 pb-2">Provenance</h2>
          {#if current}
            <div class="space-y-1.5 text-sm text-slate-700 mb-4">
              <p class="flex justify-between"><strong class="text-slate-900">Source</strong><span>{SOURCE_LABEL[current.source] || current.source}</span></p>
              {#if current.origin?.qd_builder_commit}
                <p class="flex justify-between"><strong class="text-slate-900">QD_Builder</strong><span class="font-mono text-xs">{current.origin.qd_builder_commit.slice(0, 7)}</span></p>
              {/if}
              {#if current.origin?.dft_twin_deviation_A !== undefined}
                <p class="flex justify-between"><strong class="text-slate-900">DFT start vs builder</strong><span>{current.origin.dft_twin_deviation_A} Å</span></p>
              {/if}
              {#if current.parent}
                <p class="flex justify-between gap-2"><strong class="text-slate-900">Reconstructed from</strong><span class="font-mono text-xs truncate">{current.parent}</span></p>
              {/if}
              {#if current.origin?.notes}
                <p class="text-xs text-slate-500 italic">{current.origin.notes}</p>
              {/if}
            </div>
            <h3 class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-2">Stages</h3>
            <ul class="text-xs text-slate-600 space-y-1 mb-4">
              {#each current.stages as st}
                <li class="flex justify-between gap-2">
                  <span class="font-bold">{stageLabel(st)}</span>
                  <span class="text-slate-400">{[st.code, st.basis].filter(Boolean).join(" · ")}</span>
                </li>
              {/each}
            </ul>
            {#if current.origin?.legacy_paths?.length}
              <h3 class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-2">Library folders</h3>
              <ul class="text-[11px] font-mono text-slate-500 space-y-0.5 break-all">
                {#each current.origin.legacy_paths as p}<li>{p}</li>{/each}
              </ul>
            {/if}
          {:else}
            <p class="text-sm text-slate-400 italic">—</p>
          {/if}
        </div>

        <div class="bg-brand-50 rounded-[1.5rem] shadow-sm border border-brand-100 p-6 relative overflow-hidden h-full flex flex-col">
          <div class="absolute top-0 left-0 w-1.5 h-full bg-brand-500"></div>
          <h2 class="font-heading text-lg font-bold text-brand-900 mb-3">Post-treatment</h2>
          <p class="text-sm text-slate-600 leading-relaxed mb-4">
            Open the displayed geometry in the Builder's post-treatment tools: surface reconstruction,
            X-type and L-type ligands, Z-type displacement, neutral exchange and alloying.
          </p>
          <button class="mt-auto w-full bg-brand-600 hover:bg-brand-700 disabled:bg-slate-300 text-white font-bold py-3 rounded-xl text-sm shadow-glow transition-all disabled:shadow-none"
                  onclick={openInBuilder} disabled={!canOpenInBuilder}>
            Open in Builder post-treatment
          </button>
          {#if current && !builderTemplate}
            <p class="text-[11px] text-slate-500 mt-2">No bulk template for {current.material} yet.</p>
          {:else if isMD}
            <p class="text-[11px] text-slate-500 mt-2">Select a single-geometry stage (not MD).</p>
          {/if}
        </div>
      </div>
    </div>

    <!-- Properties -->
    <div class="w-full bg-white rounded-[1.5rem] shadow-sm border border-slate-100 p-6 min-h-[800px] flex-shrink-0 flex flex-col mt-2">
      <div class="flex flex-col xl:flex-row justify-between xl:items-end gap-4 border-b border-slate-100 pb-4 mb-4 z-10">
        <h2 class="font-heading font-bold text-2xl text-slate-900">Interactive Properties</h2>
        {#if propertiesStatus === "ready"}
          <div class="flex flex-wrap gap-2">
            {#each [["fuzzy_sf", "Fuzzy - PDOS - COOP (Spin Free)"], ["fuzzy_soc", "Fuzzy - PDOS - COOP (SOC)"], ["exciton_sf", "Excited States (Spin Free)"], ["exciton_soc", "Excited States (SOC)"]] as [tab, label]}
              {#if plotUrls[tab]}
                <button class="px-4 py-2 text-xs md:text-sm font-bold rounded-xl transition-all {activePropertyTab === tab ? 'bg-brand-50 text-brand-700 shadow-sm ring-1 ring-brand-200' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'}"
                        onclick={() => (activePropertyTab = tab)}>{label}</button>
              {/if}
            {/each}
          </div>
        {/if}
      </div>
      <div class="flex-1 w-full relative min-h-[750px]">
        {#if propertiesStatus === "idle"}
          <div class="absolute inset-0 flex items-center justify-center bg-slate-50 text-slate-500 rounded-2xl italic text-sm font-medium border border-slate-200 border-dashed">
            Select a structure to view its calculated properties.
          </div>
        {:else if propertiesStatus === "loading"}
          <div class="absolute inset-0 flex flex-col items-center justify-center bg-slate-50 text-brand-600 rounded-2xl text-sm font-bold border border-brand-100">
            <div class="w-8 h-8 border-4 border-brand-500 border-t-transparent rounded-full animate-spin mb-4"></div>
            Checking properties files...
          </div>
        {:else if propertiesStatus === "none"}
          <div class="absolute inset-0 flex flex-col items-center justify-center bg-slate-50 text-slate-500 rounded-2xl text-sm border border-slate-200 border-dashed text-center px-6">
            <span class="font-bold mb-1">No properties yet</span>
            <span class="text-xs">Properties are available for DFT-optimized structures once they have been computed.</span>
          </div>
        {:else if plotUrls[activePropertyTab]}
          <iframe title="Interactive Properties" src={plotUrls[activePropertyTab]}
                  class="absolute inset-0 w-full h-full rounded-[1rem] border border-slate-200 bg-white"
                  sandbox="allow-scripts allow-same-origin allow-popups allow-modals" referrerpolicy="no-referrer"></iframe>
        {/if}
      </div>
    </div>
  </main>
</div>
