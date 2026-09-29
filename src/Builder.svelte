<script>
  import { untrack } from 'svelte';
  import Viewer from './Viewer.svelte';
  import { isDesktopApp } from './lib/desktop.js';

  const BUILDER_NOT_INCLUDED = 'The structure builder is not included in this installer yet.';

  function localBuilderMissing(err) {
    const msg = err && err.message ? String(err.message) : String(err ?? '');
    return err instanceof TypeError || /failed to fetch|networkerror|load failed|network request failed/i.test(msg);
  }

  // --- Common Oxidation States for QD Elements & Ligands ---
  const OXIDATION_STATES = {
    'Cd': 2, 'Zn': 2, 'Pb': 2, 'Hg': 2, 'Mg': 2, 'Ca': 2, 'Sr': 2, 'Ba': 2,
    'In': 3, 'Ga': 3, 'Al': 3, 'Bi': 3, 
    'Cs': 1, 'Rb': 1, 'K': 1, 'Na': 1, 'Li': 1, 'Ag': 1, 'Cu': 1, 'Au': 1,
    'S': -2, 'Se': -2, 'Te': -2, 'O': -2,
    'P': -3, 'As': -3, 'N': -3, 'Sb': -3,
    'F': -1, 'Cl': -1, 'Br': -1, 'I': -1
  };

  // --- Bulk CIF Templates ---
  const bulkTemplates = {
    "ABX3": [
      { name: "CsPbCl3", phase: "cubic", a: 5.680, path: "/ABX3/bulk_cifs/CsPbCl3_cubic.cif" },
      { name: "CsPbBr3", phase: "cubic", a: 5.949, path: "/ABX3/bulk_cifs/CsPbBr3_cubic.cif" },
      { name: "CsPbI3", phase: "cubic", a: 6.275, path: "/ABX3/bulk_cifs/CsPbI3_cubic.cif" }
    ],
    "II-VI": [
      { name: "CdS", phase: "zinc-blende", a: 5.886, path: "/II-VI/bulk_cifs/CdS_zb.cif" },
      { name: "CdSe", phase: "zinc-blende", a: 6.141, path: "/II-VI/bulk_cifs/CdSe_zb.cif" },
      { name: "CdTe", phase: "zinc-blende", a: 6.564, path: "/II-VI/bulk_cifs/CdTe_zb.cif" },
      { name: "ZnS", phase: "zinc-blende", a: 5.387, path: "/II-VI/bulk_cifs/ZnS_zb.cif" },
      { name: "ZnSe", phase: "zinc-blende", a: 5.665, path: "/II-VI/bulk_cifs/ZnSe_zb.cif" },
      { name: "ZnTe", phase: "zinc-blende", a: 6.111, path: "/II-VI/bulk_cifs/ZnTe_zb.cif" },
      { name: "HgS", phase: "zinc-blende", a: 5.939, path: "/II-VI/bulk_cifs/HgS_zb.cif" },
      { name: "HgSe", phase: "zinc-blende", a: 6.193, path: "/II-VI/bulk_cifs/HgSe_zb.cif" },
      { name: "HgTe", phase: "zinc-blende", a: 6.580, path: "/II-VI/bulk_cifs/HgTe_zb.cif" }
    ],
    "III-V": [
      { name: "GaAs", phase: "zinc-blende", a: 5.750, path: "/III-V/bulk_cifs/GaAs_zb.cif" },
      { name: "GaP", phase: "zinc-blende", a: 5.452, path: "/III-V/bulk_cifs/GaP_zb.cif" },
      { name: "GaSb", phase: "zinc-blende", a: 6.137, path: "/III-V/bulk_cifs/GaSb_zb.cif" },
      { name: "InAs", phase: "zinc-blende", a: 6.107, path: "/III-V/bulk_cifs/InAs_zb.cif" },
      { name: "InP", phase: "zinc-blende", a: 5.904, path: "/III-V/bulk_cifs/InP_zb.cif" },
      { name: "InSb", phase: "zinc-blende", a: 6.633, path: "/III-V/bulk_cifs/InSb_zb.cif" }
    ],
    "IV-VI": [
      { name: "PbS", phase: "rock-salt", a: 5.976, path: "/IV-VI/bulk_cifs/PbS_rs.cif" },
      { name: "PbSe", phase: "rock-salt", a: 6.182, path: "/IV-VI/bulk_cifs/PbSe_rs.cif" },
      { name: "PbTe", phase: "rock-salt", a: 6.542, path: "/IV-VI/bulk_cifs/PbTe_rs.cif" }
    ]
  };

  let activeFamilyTab = $state("II-VI");
  let isLoadingTemplate = $state(false);
  let activeViewer = $state("molstar");

  async function loadTemplate(template) {
    isLoadingTemplate = true;
    currentCorePhase = template.phase;
    logs += `[status] Fetching ${template.name} bulk structure...\n`;
    try {
      const response = await fetch(template.path);
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      
      const text = await response.text();
      const blob = new Blob([text], { type: 'text/plain' });
      const filename = template.path.split('/').pop();
      
      // Mimic a user file upload
      coreFile = new File([blob], filename, { type: 'text/plain' });
      logs += `[status] Loaded ${filename} successfully.\n`;
    } catch (err) {
      logs += `[error] Failed to load template: ${err.message}\n`;
    } finally {
      isLoadingTemplate = false;
    }
  }

  // ==========================================
  // STATE: Inputs & Configuration
  // ==========================================
  let coreFile = $state(null);
  let sizeUnitCells = $state([4.0, 4.0, 4.0]);
  let latticeLengths = $state([5.0, 5.0, 5.0]);
  let aspect = $derived([
    sizeUnitCells[0] / Math.min(...sizeUnitCells),
    sizeUnitCells[1] / Math.min(...sizeUnitCells),
    sizeUnitCells[2] / Math.min(...sizeUnitCells)
  ]);
  let activePreset = $state('Sphere');
  let coreFacets = $state([]);
  let shells = $state([]);
 
  let detectedFacets = $state([]);
  let isAnalyzingCif = $state(false);
  let currentCorePhase = $state(null);
  let activeHeteroMode = $state('concentric'); // 'concentric' | 'janus'

  // Janus Heterointerface state
  let janusPartnerFile = $state(null);
  let janusBuildMode = $state('wulff_janus');
  let janusInterfaceHkl = $state('001');
  let janusClippingMode = $state('mushroom');

  let passivateExpanded = $state(false);
  let capDist = $state('random');
  let anionicLigands = $state([]);
  let showCationic = $state(false);
  let cationicLigands = $state([]);
  
  let reconEnabled = $state(false);
  let reconRatio = $state(0.5);

  let neutralEnabled = $state(false);
  let neutralLigands = $state([]);
  let neutralDist = $state('random');
  let zTypeEnabled = $state(false);
  let zTypeOptions = $state([]);
  let alloyingEnabled = $state(false);
  let alloyingOptions = $state([]);
  let xTypeEnabled = $state(false);
  let xTypeOptions = $state([]);
  let neutralExchangeEnabled = $derived(neutralExchangeOptions.some(opt => opt.enabled));
  let neutralExchangeOptions = $state([]);
  let lTypeOptions = $state([]);
  let detectedAnions = $state([]);
  let detectedCations = $state([]);
  let detectedSpecies = $state([]);

  let runMode = $state('quiet');
  let posQ = $state('remove');
  let centerIon = $state('');
  let sidebarView = $state('builder'); // 'builder' | 'postTreatment'
  let asideEl = $state(null);

  // ==========================================
  // STATE: UI & Outputs
  // ==========================================
  let isBuilding = $state(false);
  let logs = $state("[status] Ready.\n");
  let xyzData = $state("");
  let finalResult = $state(null);
  let logContainer;

  let lastUnpassivatedXyz = $state("");
  let tooltipText = $state("");
  let tooltipPos = $state({ x: 0, y: 0 });

  // --- DYNAMIC STOICHIOMETRY & RATIOS PARSER ---
  let calculatedStoich = $derived.by(() => {
    if (!xyzData) return {};
    const lines = xyzData.trim().split('\n');
    const nAtoms = parseInt(lines[0].trim());
    if (isNaN(nAtoms)) return {};
    
    const sto = {};
    for (let i = 2; i < 2 + nAtoms && i < lines.length; i++) {
      const parts = lines[i].trim().split(/\s+/);
      if (parts.length >= 4) {
        const el = parts[0];
        sto[el] = (sto[el] || 0) + 1;
      }
    }
    return sto;
  });

  // Calculate Elemental Ratios
  let calculatedRatios = $derived.by(() => {
    const sto = calculatedStoich;
    const elements = Object.keys(sto);
    const ratios = {};
    
    for (let i = 0; i < elements.length; i++) {
      for (let j = 0; j < elements.length; j++) {
        if (i !== j) {
          const el1 = elements[i];
          const el2 = elements[j];
          ratios[`${el1}/${el2}`] = (sto[el1] / sto[el2]).toFixed(3);
        }
      }
    }
    return ratios;
  });

  // Advanced Charge Calculator
  let calculatedCharge = $derived.by(() => {
    if (!xyzData) return 0;
    let charge = 0;

    // 1. If we have the API response breakdown, it's the safest way to calculate
    if (finalResult?.grouped_counts) {
      const core = finalResult.grouped_counts.core?.by_element || {};
      const shell = finalResult.grouped_counts.shell?.by_element || {};

      // A) Calculate core + shell inorganic charges
      for (const [el, count] of Object.entries(core)) {
         charge += (OXIDATION_STATES[el] || 0) * count;
      }
      for (const [el, count] of Object.entries(shell)) {
         charge += (OXIDATION_STATES[el] || 0) * count;
      }

      // B) Calculate complex organic ligand charges (-1 for anionic, +1 for cationic)
      if (finalResult.ligand_detail) {
         const anions = Object.values(finalResult.ligand_detail.anionic || {}).reduce((a,b)=>a+b, 0);
         const cations = Object.values(finalResult.ligand_detail.cationic || {}).reduce((a,b)=>a+b, 0);
         charge -= anions;
         charge += cations;
      }

      // C) Add leftover/initial Dummy atoms (like Cl, Br, Rb) present in the XYZ
      // This ensures dummy-passivated cores are correctly calculated as 0
      const inorganicElements = { ...core };
      for (const [el, count] of Object.entries(shell)) {
          inorganicElements[el] = (inorganicElements[el] || 0) + count;
      }
      const countedElements = { ...inorganicElements };

      const knownDummies = ['Cl', 'Br', 'I', 'F', 'Na', 'K', 'Rb', 'Cs'];
      for (const dummy of knownDummies) {
          if (calculatedStoich[dummy]) {
              const coreCount = inorganicElements[dummy] || 0;
              const extraDummies = calculatedStoich[dummy] - coreCount; // Only count dummies NOT part of the core
              if (extraDummies > 0) {
                  charge += (OXIDATION_STATES[dummy] || 0) * extraDummies;
                  countedElements[dummy] = (countedElements[dummy] || 0) + extraDummies;
              }
          }
      }

      // Neutral exchange can introduce inorganic replacement cations that are
      // not part of the original core/shell groups, e.g. In in CdCl2 -> InBr3.
      // Count only positive inorganic leftovers here so neutral organic ligands
      // are not atom-wise charged.
      for (const [el, count] of Object.entries(calculatedStoich)) {
          const uncounted = count - (countedElements[el] || 0);
          const ox = OXIDATION_STATES[el] || 0;
          if (uncounted > 0 && ox > 0) {
              charge += ox * uncounted;
          }
      }
      return charge;
    }

    // 2. Fallback if API fails: Ignore purely organic elements
    const qdCoreElements = ['Cd', 'Zn', 'Pb', 'Hg', 'In', 'Ga', 'Al', 'S', 'Se', 'Te', 'P', 'As', 'Sb', 'Ag', 'Cu', 'Au', 'Cs', 'Rb', 'K', 'Na'];
    for (const [el, count] of Object.entries(calculatedStoich)) {
       if (qdCoreElements.includes(el) || ['Cl', 'Br', 'I', 'F'].includes(el)) {
           charge += (OXIDATION_STATES[el] || 0) * count;
       }
    }
    return charge;
  });

  function zTypeKey(opt) {
    return `${opt.cation}|${opt.anion}|${opt.anion_count}`;
  }

  function xTypeKey(opt) {
    return `${opt.replace || opt.dummy}|${opt.replace_charge ?? opt.charge}|${opt.site_type || ''}`;
  }

  function zTypeAvailable(opt) {
    return opt?.candidate_count || 0;
  }

  function lTypeKey(opt) {
    return `${opt.target_symbol || opt.element || opt.target}|${opt.site_type || opt.target || ''}`;
  }

  function optionAvailable(opt, kind = '') {
    if (!opt) return 0;
    if (kind === 'alloy') return alloyAvailable(opt);
    if (kind === 'x_type') return xTypeAvailable(opt);
    if (kind === 'l_type') return opt.available_count || 0;
    return zTypeAvailable(opt);
  }

  function alloyAvailable(opt) {
    if (!opt) return 0;
    if (opt.region === 'surface') return opt.surface_count || 0;
    if (opt.region === 'core') return opt.core_count || 0;
    return opt.total_count || 0;
  }

  function xTypeAvailable(opt) {
    return opt?.available_count || 0;
  }

  function ensureJobs(opt, kind) {
    if (!opt.jobs || opt.jobs.length === 0) {
      opt.jobs = [makeDefaultJob(kind, opt)];
    }
    clampOptionJobs(opt, kind);
  }

  function makeDefaultJob(kind, opt) {
    const base = {
      id: crypto.randomUUID(),
      ratio: 0,
      target_count: 0,
      distribution: opt?.distribution || 'random',
    };
    if (kind === 'alloy') {
      const defaultReplacement = opt?.site_type === 'cation' ? (detectedCations.find((s) => s !== opt.element) || 'Zn') : (detectedAnions.find((s) => s !== opt.element) || 'S');
      return {
        ...base,
        replacement: opt?.replacement || defaultReplacement,
        replacement_charge: opt?.replacement_charge ?? (OXIDATION_STATES[defaultReplacement] || 0),
      };
    }
    if (kind === 'neutral_exchange') {
      return {
        ...base,
        exchange_type: (opt?.exchange_type === 'salt' ? 'mxn' : opt?.exchange_type) || 'mxn',
        smiles: opt?.smiles || '',
      };
    }
    return {
      ...base,
      smiles: opt?.smiles || '',
      target: opt?.target || (opt?.site_type === 'cation' ? 'cation' : 'anion'),
      target_symbol: opt?.target_symbol || opt?.element || null,
    };
  }

  function normalizeJobs(prev, kind, opt) {
    const jobs = Array.isArray(prev.jobs) ? prev.jobs : [];
    if (jobs.length > 0) {
      return jobs.map((job) => ({ ...makeDefaultJob(kind, opt), ...job, id: job.id || crypto.randomUUID() }));
    }
    if ((prev.target_count || 0) > 0 || prev.smiles || prev.replacement) {
      return [{ ...makeDefaultJob(kind, opt), ...prev, id: crypto.randomUUID() }];
    }
    return [];
  }

  function addOptionJob(opt, kind) {
    opt.jobs = [...(opt.jobs || []), makeDefaultJob(kind, opt)];
    clampOptionJobs(opt, kind);
  }

  function removeOptionJob(opt, job, kind) {
    opt.jobs = (opt.jobs || []).filter((candidate) => candidate !== job);
    clampOptionJobs(opt, kind);
  }

  function siblingJobTotal(opt, exceptJob = null) {
    return (opt.jobs || []).reduce((sum, job) => sum + (job === exceptJob ? 0 : Number(job.target_count || 0)), 0);
  }

  function clampJobCount(opt, job, kind) {
    const available = optionAvailable(opt, kind);
    const remaining = Math.max(0, available - siblingJobTotal(opt, job));
    job.target_count = Math.max(0, Math.min(remaining, Math.round(Number(job.target_count || 0))));
    job.ratio = available > 0 ? job.target_count / available : 0;
  }

  function syncJobCountFromRatio(opt, job, kind) {
    const available = optionAvailable(opt, kind);
    const requested = Math.round(Number(job.ratio || 0) * available);
    job.target_count = requested;
    clampJobCount(opt, job, kind);
  }

  function syncJobRatioFromCount(opt, job, kind) {
    clampJobCount(opt, job, kind);
  }

  function clampOptionJobs(opt, kind) {
    for (const job of opt.jobs || []) {
      clampJobCount(opt, job, kind);
    }
  }

  function optionJobTotal(opt) {
    return (opt.jobs || []).reduce((sum, job) => sum + Number(job.target_count || 0), 0);
  }

  function selectionPercent(count, available) {
    const denom = Number(available || 0);
    if (denom <= 0) return 0;
    return Math.round((Number(count || 0) / denom) * 100);
  }

  function formulaParts(formula) {
    return String(formula || '').split(/(\d+)/).filter(Boolean).map((text) => ({
      text,
      subscript: /^\d+$/.test(text),
    }));
  }

  function decorateZTypeOptions(options) {
    const previous = new Map(zTypeOptions.map((opt) => [zTypeKey(opt), opt]));
    return (options || []).map((opt) => {
      const prev = previous.get(zTypeKey(opt)) || {};
      const next = { ...opt, enabled: prev.enabled || false, distribution: prev.distribution || 'random' };
      next.jobs = normalizeJobs(prev, 'z_type', next);
      if (next.jobs.length > 1) {
        next.jobs = [next.jobs[0]];
      }
      clampOptionJobs(next, 'z_type');
      return next;
    });
  }

  function decorateNeutralExchangeOptions(options) {
    const previous = new Map(neutralExchangeOptions.map((opt) => [zTypeKey(opt), opt]));
    return (options || []).map((opt) => {
      const prev = previous.get(zTypeKey(opt)) || {};
      const next = {
        ...opt,
        enabled: prev.enabled || false,
        distribution: prev.distribution || 'random',
      };
      next.jobs = normalizeJobs(prev, 'neutral_exchange', next);
      clampOptionJobs(next, 'neutral_exchange');
      return next;
    });
  }

  function decorateAlloyingOptions(options) {
    const previous = new Map(alloyingOptions.map((opt) => [opt.element, opt]));
    return (options || []).map((opt) => {
      const prev = previous.get(opt.element) || {};
      const defaultReplacement = opt.site_type === 'cation' ? 'Cd' : 'Se';
      const next = {
        ...opt,
        enabled: prev.enabled || false,
        region: prev.region || 'surface',
        distribution: prev.distribution || 'random',
      };
      next.jobs = normalizeJobs(prev, 'alloy', {
        ...next,
        replacement: prev.replacement || defaultReplacement,
        replacement_charge: prev.replacement_charge ?? (OXIDATION_STATES[defaultReplacement] || 0),
      });
      clampOptionJobs(next, 'alloy');
      return next;
    });
  }

  function decorateXTypeOptions(options) {
    const previous = new Map(xTypeOptions.map((opt) => [xTypeKey(opt), opt]));
    return (options || []).map((opt) => {
      const key = xTypeKey(opt);
      const prev = previous.get(key) || {};
      const siteType = opt.site_type || (Number(opt.replace_charge ?? opt.charge ?? 0) < 0 ? 'anion' : 'cation');
      const next = {
        ...opt,
        replace: opt.replace || opt.dummy,
        dummy: opt.dummy || opt.replace,
        site_type: siteType,
        replace_charge: opt.replace_charge ?? opt.charge,
        ligand_charge: opt.ligand_charge ?? (siteType === 'anion' ? -1 : 1),
        enabled: prev.enabled || false,
        distribution: prev.distribution || 'uniform',
      };
      next.jobs = normalizeJobs(prev, 'x_type', next);
      clampOptionJobs(next, 'x_type');
      return next;
    });
  }

  function decorateLTypeOptions(options) {
    const previous = new Map(lTypeOptions.map((opt) => [lTypeKey(opt), opt]));
    return (options || []).map((opt) => {
      const key = lTypeKey(opt);
      const prev = previous.get(key) || {};
      const next = {
        ...opt,
        enabled: prev.enabled || false,
        distribution: prev.distribution || 'random',
      };
      next.jobs = normalizeJobs(prev, 'l_type', next);
      clampOptionJobs(next, 'l_type');
      return next;
    });
  }

  // ==========================================
  // HELPERS & UI LOGIC
  // ==========================================
  function isNonnegativeCompact(h) {
    const s = String(h).trim();
    return s.length > 0 && !s.startsWith('-') && !s.slice(1).includes('-');
  }

  /** Parse nc-builder-style compact hkl into (h,k,l) — matches builder.config._parse_hkl. */
  function parseCompactHkl(s) {
    const str = String(s).trim();
    const s3 = str.replace(/[()[\]\s,;]/g, '');
    if (/^\d{3}$/.test(s3)) {
      return [parseInt(s3[0], 10), parseInt(s3[1], 10), parseInt(s3[2], 10)];
    }
    const s2 = str.replace(/[^0-9+-]/g, '');
    const tokens = s2.match(/[+-]?\d/g);
    if (tokens?.length === 3 && tokens.every((t) => t.replace(/[+-]/g, '').length === 1)) {
      return tokens.map((t) => parseInt(t, 10));
    }
    return null;
  }

  function tupleToCompactHkl(tup) {
    return tup.map((x) => (x < 0 ? `-${Math.abs(x)}` : String(x))).join('');
  }

  /** Opposite Miller index in compact form (111 -> -1-1-1, 100 -> -100). */
  function oppositeCompactHkl(hkl) {
    const tup = parseCompactHkl(hkl);
    if (!tup) return String(hkl);
    return tupleToCompactHkl(tup.map((x) => -x));
  }

  /** Canonical Miller index per termination (matches nc-builder recipe style). */
  function canonicalHklForTermination(fam, termination) {
    const rec = fam.recommended_hkl || {};
    if (rec[termination]) return rec[termination];
    const list = fam.hkl_list || [];
    const positive = list.filter(isNonnegativeCompact);
    const negative = list.filter((h) => String(h).startsWith('-'));
    if (termination === 'cation_rich') return positive[0] || list[0] || '100';
    if (termination === 'anion_rich') {
      const catH = rec.cation_rich || positive[0];
      if (catH) return oppositeCompactHkl(catH);
      return negative[0] || oppositeCompactHkl(list[0] || '100');
    }
    return list[0] || '100';
  }

  function scrollAsideToTop() {
    asideEl?.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function makeFacetEntry(fam, { termination = null, gamma = 1.0, scope = 'family', hkl = null } = {}) {
    return {
      id: crypto.randomUUID(),
      family: fam.family,
      hkl: hkl ?? (termination ? canonicalHklForTermination(fam, termination) : (fam.hkl_list?.[0] || '100')),
      gamma,
      scope,
      termination
    };
  }

  function upsertFamilyTermination(fam, termination, enabled) {
    const idx = coreFacets.findIndex((f) => f.family === fam.family && f.termination === termination);
    if (enabled && idx < 0) {
      const gamma = coreFacets.find((f) => f.family === fam.family)?.gamma ?? 1.0;
      let hkl = null;
      if (termination === 'anion_rich') {
        const cat = coreFacets.find((f) => f.family === fam.family && f.termination === 'cation_rich');
        if (cat) hkl = oppositeCompactHkl(cat.hkl);
      }
      coreFacets.push(makeFacetEntry(fam, { termination, gamma, scope: 'family', hkl }));
    } else if (!enabled && idx >= 0) {
      coreFacets.splice(idx, 1);
    }
  }

  function applyPreset(name) {
    activePreset = name;
    const presets = {
      Sphere:   { size: [4.0, 4.0, 4.0],   facets: [{ hkl: '100', gamma: 1.0 }] },
      Platelet: { size: [4.0, 4.0, 1.0],   facets: [{ hkl: '100', gamma: 0.8 }] },
      Rod:      { size: [10.0, 2.0, 2.0],  facets: [{ hkl: '100', gamma: 0.8 }] }
    };
    if (presets[name]) {
      sizeUnitCells = [...presets[name].size];
      coreFacets = presets[name].facets.map(f => ({ id: crypto.randomUUID(), ...f }));
    }
  }

  function handleCoreDrop(e) {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      coreFile = e.dataTransfer.files[0];
    }
  }

  function addShell() {
    shells.push({
      id: crypto.randomUUID(),
      file: null,
      templateName: null, // Track if a template was used
      isLoading: false,   // Track fetching state for this specific shell
      aspect: [1.0, 1.0, 1.0],
      size_unit_cells: [1.0, 1.0, 1.0],
      facets: coreFacets.map(f => ({ id: crypto.randomUUID(), hkl: f.hkl, gamma: f.gamma, scope: f.scope, termination: f.termination })),
      interface_type: "abrupt",
      interface_mixing_ratio: 0.5,
      interface_mixing_width: 3.0,
    });
  }

  $effect(() => {
    if (logs && logContainer) {
      logContainer.scrollTop = logContainer.scrollHeight;
    }
  });

  // CIF Facet Analysis Trigger
  $effect(() => {
    if (coreFile) {
      untrack(() => {
        analyzeCif(coreFile);
      });
    } else {
      detectedFacets = [];
      coreFacets = [];
      currentCorePhase = null;
    }
  });

  function getQDFamily(name, cations = [], anions = []) {
    const n = name.toLowerCase();
    
    // Check elements first if available
    if (cations.length > 0 && anions.length > 0) {
      // ABX3: e.g. CsPbCl3
      const hasCs = cations.includes('Cs');
      const hasPb = cations.includes('Pb');
      const hasHalide = anions.some(a => ['Cl', 'Br', 'I'].includes(a));
      if (hasCs && hasPb && hasHalide) return 'ABX3';
      
      // II-VI: CdSe, CdS, CdTe, ZnS, ZnSe, ZnTe, HgS, HgSe, HgTe
      const hasII = cations.some(c => ['Cd', 'Zn', 'Hg'].includes(c));
      const hasVI = anions.some(a => ['S', 'Se', 'Te', 'O'].includes(a));
      if (hasII && hasVI) return 'II-VI';
      
      // III-V: GaAs, InP, InAs, InSb, GaP, GaSb
      const hasIII = cations.some(c => ['In', 'Ga', 'Al'].includes(c));
      const hasV = anions.some(a => ['P', 'As', 'Sb', 'N'].includes(a));
      if (hasIII && hasV) return 'III-V';
      
      // IV-VI: PbS, PbSe, PbTe
      const hasIV = cations.some(c => ['Pb', 'Sn', 'Ge'].includes(c));
      const hasVI_2 = anions.some(a => ['S', 'Se', 'Te', 'O'].includes(a));
      if (hasIV && hasVI_2) return 'IV-VI';
    }
    
    // Fall back to filename check
    if (n.includes('abx3') || n.includes('cspb') || n.includes('perovskite')) return 'ABX3';
    if (n.includes('ii-vi') || n.includes('cdse') || n.includes('cds') || n.includes('cdte') || n.includes('zns') || n.includes('znse') || n.includes('znte') || n.includes('hgs') || n.includes('hgse') || n.includes('hgte')) return 'II-VI';
    if (n.includes('iii-v') || n.includes('gaas') || n.includes('gap') || n.includes('gasb') || n.includes('inas') || n.includes('inp') || n.includes('insb')) return 'III-V';
    if (n.includes('iv-vi') || n.includes('pbs') || n.includes('pbse') || n.includes('pbte')) return 'IV-VI';
    
    return null;
  }

  async function analyzeCif(file) {
    isAnalyzingCif = true;
    detectedFacets = [];
    coreFacets = [];
    logs += `[status] Analyzing crystallographic symmetry of ${file.name}...\n`;
    
    const family = getQDFamily(file.name);
    if (family === 'II-VI') {
      sizeUnitCells = [3.0, 3.0, 3.0];
      posQ = 'add';
      const n = file.name.toLowerCase();
      if (n.includes('cd')) centerIon = 'Cd';
      else if (n.includes('zn')) centerIon = 'Zn';
      else if (n.includes('hg')) centerIon = 'Hg';
      else centerIon = 'Cd';
    } else if (family === 'III-V') {
      sizeUnitCells = [2.0, 2.0, 2.0];
      posQ = 'add';
      const n = file.name.toLowerCase();
      if (n.includes('in')) centerIon = 'In';
      else if (n.includes('ga')) centerIon = 'Ga';
      else if (n.includes('al')) centerIon = 'Al';
      else centerIon = 'In';
    } else if (family === 'IV-VI') {
      sizeUnitCells = [2.0, 2.0, 2.0];
      posQ = 'add';
      const n = file.name.toLowerCase();
      if (n.includes('pbse')) centerIon = 'Se';
      else if (n.includes('pbte')) centerIon = 'Te';
      else centerIon = 'S';
    } else if (family === 'ABX3') {
      sizeUnitCells = [3.0, 3.0, 3.0];
      posQ = 'remove';
      centerIon = 'Cs';
    }
    
    const formData = new FormData();
    formData.append('file', file);
    
    const IS_LOCAL = isDesktopApp() || window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
    const ANALYZE_URL = IS_LOCAL 
      ? "http://127.0.0.1:8000/builder/api/analyze_cif" 
      : "/builder/api/analyze_cif";
      
    try {
      const res = await fetch(ANALYZE_URL, { method: 'POST', body: formData });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      
      if (data.status === 'success') {
        detectedFacets = data.facets || [];
        currentCorePhase = data.phase || null;
        latticeLengths = data.lattice_lengths || [5.0, 5.0, 5.0];
        detectedAnions = data.anions || [];
        detectedCations = data.cations || [];
        detectedSpecies = data.species || data.cations || [];
        
        const refinedFamily = getQDFamily(file.name, detectedCations, detectedAnions);
        
        if (refinedFamily === 'II-VI') {
          sizeUnitCells = [3.0, 3.0, 3.0];
          posQ = 'add';
          const cat = detectedCations.find(c => ['Cd', 'Zn', 'Hg'].includes(c)) || detectedCations[0] || 'Cd';
          centerIon = cat;
          
          coreFacets = [];
          const f100 = detectedFacets.find(f => f.family === '{100}' || f.family === '100');
          if (f100) {
            coreFacets.push(makeFacetEntry(f100, { termination: 'cation_rich', gamma: 1.0 }));
          } else {
            coreFacets.push({ id: crypto.randomUUID(), hkl: '100', gamma: 1.0, scope: 'family', family: '{100}', termination: 'cation_rich' });
          }
          
          const f111 = detectedFacets.find(f => f.family === '{111}' || f.family === '111');
          if (f111) {
            coreFacets.push(makeFacetEntry(f111, { termination: 'cation_rich', gamma: 1.0 }));
            coreFacets.push(makeFacetEntry(f111, { termination: 'anion_rich', gamma: 1.0 }));
          } else {
            coreFacets.push({ id: crypto.randomUUID(), hkl: '111', gamma: 1.0, scope: 'family', family: '{111}', termination: 'cation_rich' });
            coreFacets.push({ id: crypto.randomUUID(), hkl: '111', gamma: 1.0, scope: 'family', family: '{111}', termination: 'anion_rich' });
          }
        } else if (refinedFamily === 'III-V') {
          sizeUnitCells = [2.0, 2.0, 2.0];
          posQ = 'add';
          const cat = detectedCations.find(c => ['In', 'Ga', 'Al'].includes(c)) || detectedCations[0] || 'In';
          centerIon = cat;
          
          coreFacets = [];
          const f111 = detectedFacets.find(f => f.family === '{111}' || f.family === '111');
          if (f111) {
            coreFacets.push(makeFacetEntry(f111, { termination: 'cation_rich', gamma: 0.8 }));
            coreFacets.push(makeFacetEntry(f111, { termination: 'anion_rich', gamma: 1.6 }));
          } else {
            coreFacets.push({ id: crypto.randomUUID(), hkl: '111', gamma: 0.8, scope: 'family', family: '{111}', termination: 'cation_rich' });
            coreFacets.push({ id: crypto.randomUUID(), hkl: '111', gamma: 1.6, scope: 'family', family: '{111}', termination: 'anion_rich' });
          }
        } else if (refinedFamily === 'IV-VI') {
          sizeUnitCells = [2.0, 2.0, 2.0];
          posQ = 'add';
          const ani = detectedAnions.find(a => ['S', 'Se', 'Te'].includes(a)) || detectedAnions[0] || 'S';
          centerIon = ani;
          
          coreFacets = [];
          const f100 = detectedFacets.find(f => f.family === '{100}' || f.family === '100');
          if (f100) {
            const term = f100.terminations.includes('stoichiometric') ? 'stoichiometric' : (f100.terminations[0] || null);
            coreFacets.push(makeFacetEntry(f100, { termination: term, gamma: 0.8 }));
          } else {
            coreFacets.push({ id: crypto.randomUUID(), hkl: '100', gamma: 0.8, scope: 'family', family: '{100}', termination: 'stoichiometric' });
          }
          const f111 = detectedFacets.find(f => f.family === '{111}' || f.family === '111');
          if (f111) {
            coreFacets.push(makeFacetEntry(f111, { termination: 'cation_rich', gamma: 1.0 }));
          } else {
            coreFacets.push({ id: crypto.randomUUID(), hkl: '111', gamma: 1.0, scope: 'family', family: '{111}', termination: 'cation_rich' });
          }
        } else if (refinedFamily === 'ABX3') {
          sizeUnitCells = [3.0, 3.0, 3.0];
          posQ = 'remove';
          const cat = detectedCations.includes('Cs') ? 'Cs' : (detectedCations[0] || 'Cs');
          centerIon = cat;
          
          coreFacets = [];
          const f100 = detectedFacets.find(f => f.family === '{100}' || f.family === '100');
          if (f100) {
            const term = f100.terminations[0] || null;
            coreFacets.push(makeFacetEntry(f100, { termination: term, gamma: 1.0 }));
          } else {
            coreFacets.push({ id: crypto.randomUUID(), hkl: '100', gamma: 1.0, scope: 'family', family: '{100}', termination: null });
          }
        } else {
          centerIon = '';
          if (detectedFacets.length > 0) {
            const first = detectedFacets[0];
            const term = first.terminations.includes('cation_rich') ? 'cation_rich' : null;
            coreFacets = [makeFacetEntry(first, { termination: term })];
          }
        }
        logs += `[status] CIF analyzed successfully: Spacegroup ${data.spacegroup || 'N/A'} (Lattice Phase: ${data.phase || 'unknown'}).\n`;
      } else {
        throw new Error(data.error || 'Unknown error');
      }
    } catch (err) {
      logs += localBuilderMissing(err)
        ? `[warn] ${BUILDER_NOT_INCLUDED}\n`
        : `[warn] CIF facet analysis failed: ${err.message}. Facet family selections will remain custom.\n`;
      detectedFacets = [];
      currentCorePhase = null;
      detectedAnions = [];
      detectedCations = [];
      detectedSpecies = [];
      
      const failedFamily = getQDFamily(file.name, detectedCations, detectedAnions);
      if (failedFamily === 'II-VI') {
        coreFacets = [
          { id: crypto.randomUUID(), hkl: '100', gamma: 1.0, scope: 'family', family: '{100}', termination: 'cation_rich' },
          { id: crypto.randomUUID(), hkl: '111', gamma: 1.0, scope: 'family', family: '{111}', termination: 'cation_rich' },
          { id: crypto.randomUUID(), hkl: '111', gamma: 1.0, scope: 'family', family: '{111}', termination: 'anion_rich' }
        ];
      } else if (failedFamily === 'III-V') {
        coreFacets = [
          { id: crypto.randomUUID(), hkl: '111', gamma: 0.8, scope: 'family', family: '{111}', termination: 'cation_rich' },
          { id: crypto.randomUUID(), hkl: '111', gamma: 1.6, scope: 'family', family: '{111}', termination: 'anion_rich' }
        ];
      } else if (failedFamily === 'IV-VI') {
        coreFacets = [
          { id: crypto.randomUUID(), hkl: '100', gamma: 0.8, scope: 'family', family: '{100}', termination: 'stoichiometric' },
          { id: crypto.randomUUID(), hkl: '111', gamma: 1.0, scope: 'family', family: '{111}', termination: 'cation_rich' }
        ];
      } else if (failedFamily === 'ABX3') {
        coreFacets = [
          { id: crypto.randomUUID(), hkl: '100', gamma: 1.0, scope: 'family', family: '{100}', termination: null }
        ];
      } else {
        coreFacets = [{ id: crypto.randomUUID(), hkl: '100', gamma: 1.0, scope: 'family', family: '{100}', termination: null }];
      }
    } finally {
      isAnalyzingCif = false;
    }
  }

  // Interactive Facet Updates
  function toggleFacetFamily(fam) {
    const isEnabled = coreFacets.some(f => f.family === fam.family);
    if (isEnabled) {
      coreFacets = coreFacets.filter(f => f.family !== fam.family);
    } else {
      const term = fam.terminations.includes('cation_rich') ? 'cation_rich' : null;
      coreFacets.push(makeFacetEntry(fam, { termination: term }));
    }
  }

  function updateFacetScope(family, scope) {
    const fam = detectedFacets.find(f => f.family === family);
    if (!fam) return;
    
    if (scope === 'family') {
      const existing = coreFacets.filter(f => f.family === family);
      const gamma = existing[0]?.gamma ?? 1.0;
      const terminations = [...new Set(existing.map(f => f.termination).filter(Boolean))];
      if (terminations.length === 0 && fam.terminations.includes('cation_rich')) {
        terminations.push('cation_rich');
      }
      coreFacets = coreFacets.filter(f => f.family !== family);
      if (terminations.length > 0) {
        for (const term of terminations) {
          coreFacets.push(makeFacetEntry(fam, { termination: term, gamma, scope: 'family' }));
        }
      } else {
        coreFacets.push(makeFacetEntry(fam, { gamma, scope: 'family' }));
      }
    } else {
      coreFacets = coreFacets.filter(f => f.family !== family);
      for (const hkl of fam.hkl_list) {
        coreFacets.push({
          id: crypto.randomUUID(),
          family: family,
          hkl: hkl,
          gamma: 1.0,
          scope: 'facet',
          termination: fam.terminations.includes('cation_rich') ? 'cation_rich' : null
        });
      }
    }
  }

  function updateFamilyGamma(family, gamma) {
    for (let f of coreFacets) {
      if (f.family === family) {
        f.gamma = gamma;
      }
    }
  }

  function updateFamilyTerminationGamma(family, termination, gamma) {
    for (let f of coreFacets) {
      if (f.family === family && f.termination === termination) {
        f.gamma = gamma;
      }
    }
  }

  function terminationLabel(termination) {
    if (termination === 'cation_rich') return 'Cation-Rich';
    if (termination === 'anion_rich') return 'Anion-Rich';
    return 'Stoichiometric';
  }

  function updateFamilyTermination(family, termination) {
    for (let f of coreFacets) {
      if (f.family === family) {
        f.termination = termination;
      }
    }
  }

  function toggleIndividualPlane(family, hkl) {
    const existingIdx = coreFacets.findIndex(f => f.family === family && f.hkl === hkl);
    if (existingIdx >= 0) {
      coreFacets.splice(existingIdx, 1);
    } else {
      const fam = detectedFacets.find(f => f.family === family);
      coreFacets.push({
        id: crypto.randomUUID(),
        family: family,
        hkl: hkl,
        gamma: 1.0,
        scope: 'facet',
        termination: fam && fam.terminations.includes('cation_rich') ? 'cation_rich' : null
      });
    }
  }

  function downloadXYZ() {
    if (!xyzData) return;
    const name = finalResult?.download_name || 'final.xyz';
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([xyzData], { type: 'text/plain' }));
    a.download = name;
    a.click();
  }

  function onReset() {
    coreFile = null;
    xyzData = "";
    finalResult = null;
    lastUnpassivatedXyz = "";
    logs = "[status] Reset.\n";
    shells = [];
    anionicLigands = [];
    cationicLigands = [];
    detectedFacets = [];
    currentCorePhase = null;
    activeHeteroMode = 'concentric';
    janusPartnerFile = null;
    janusBuildMode = 'wulff_janus';
    janusInterfaceHkl = '001';
    janusClippingMode = 'mushroom';
    reconEnabled = false;
    neutralEnabled = false;
    neutralLigands = [];
    neutralDist = 'random';
    zTypeEnabled = false;
    zTypeOptions = [];
    neutralExchangeOptions = [];
    alloyingEnabled = false;
    alloyingOptions = [];
    xTypeEnabled = false;
    xTypeOptions = [];
    lTypeOptions = [];
    latticeLengths = [5.0, 5.0, 5.0];
    passivateExpanded = false;
    showCationic = false;
    detectedAnions = [];
    detectedCations = [];
    detectedSpecies = [];
    centerIon = '';
    sidebarView = 'builder';
    applyPreset('Sphere');
  }

  async function loadShellTemplate(sIndex, template) {
    shells[sIndex].isLoading = true;
    logs += `[status] Fetching ${template.name} shell structure...\n`;
    try {
      const response = await fetch(template.path);
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      
      const text = await response.text();
      const blob = new Blob([text], { type: 'text/plain' });
      const filename = template.path.split('/').pop();
      
      shells[sIndex].file = new File([blob], filename, { type: 'text/plain' });
      shells[sIndex].templateName = template.name;
      logs += `[status] Loaded ${filename} for Shell ${sIndex + 1}.\n`;
    } catch (err) {
      logs += `[error] Failed to load shell template: ${err.message}\n`;
    } finally {
      shells[sIndex].isLoading = false;
    }
  }

  // ==========================================
  // API BUILD STREAM
  // ==========================================
  async function onBuild(skipCoreBuild = false) {
    if (!coreFile) { alert('Please upload a core .cif file.'); return; }
    if (skipCoreBuild && !lastUnpassivatedXyz) {
      alert('No built structure found. Please run a full build first.');
      return;
    }

    isBuilding = true;
    if (!skipCoreBuild) {
      finalResult = null;
      xyzData = "";
    }
    logs = `[status] Sending ${skipCoreBuild ? 'repassivation' : 'build'} job to http://127.0.0.1:8000/builder/api/build_stream …\n`;

    const formData = new FormData();
    formData.append('files', coreFile);
    for (const shell of shells) {
      if (shell.file) formData.append('files', shell.file);
    }

    if (activeHeteroMode === 'janus') {
      alert('Janus-type heterostructure Wulff-ZSL matching is an experimental script workflow. Concentric Core@Shell building is fully functional.');
      isBuilding = false;
      return;
    }

    const options = {
      size_unit_cells: sizeUnitCells,
      radius_A: Math.min(...sizeUnitCells) * Math.min(...latticeLengths),
      core_cif_filename: coreFile.name,
      aspect: aspect,
      facets: coreFacets.map(f => ({ hkl: f.hkl, gamma: f.gamma, scope: f.scope, termination: f.termination })),
      shells: shells.filter(s => s.file).map(s => ({
        material_cif: s.file.name,
        aspect: s.aspect,
        size_unit_cells: s.size_unit_cells,
        facets: s.facets.map(f => ({ hkl: f.hkl, gamma: f.gamma, scope: f.scope, termination: f.termination })),
        interface_type: s.interface_type || "abrupt",
        interface_mixing_ratio: s.interface_mixing_ratio !== undefined ? s.interface_mixing_ratio : 0.5,
        interface_mixing_width: s.interface_mixing_width !== undefined ? s.interface_mixing_width : 3.0,
      })),
      cap_distribution: capDist,
      x_type_enabled: skipCoreBuild ? xTypeEnabled : false,
      cap_anionic_jobs: skipCoreBuild
        ? xTypeOptions
            .filter(opt => xTypeEnabled && opt.enabled && opt.site_type === 'anion')
            .flatMap(opt => (opt.jobs || []).filter(job => job.smiles?.trim() && job.target_count > 0).map(job => ({
              smiles: job.smiles,
              ratio: job.ratio,
              target_count: job.target_count || 0,
              dummy: opt.replace || opt.dummy,
              replace: opt.replace || opt.dummy,
              replace_charge: opt.replace_charge,
              ligand_charge: null,
              distribution: job.distribution || opt.distribution || 'uniform',
            })))
        : [],
      cap_cationic_jobs: skipCoreBuild
        ? xTypeOptions
            .filter(opt => xTypeEnabled && opt.enabled && opt.site_type === 'cation')
            .flatMap(opt => (opt.jobs || []).filter(job => job.smiles?.trim() && job.target_count > 0).map(job => ({
              smiles: job.smiles,
              ratio: job.ratio,
              target_count: job.target_count || 0,
              dummy: opt.replace || opt.dummy,
              replace: opt.replace || opt.dummy,
              replace_charge: opt.replace_charge,
              ligand_charge: null,
              distribution: job.distribution || opt.distribution || 'uniform',
            })))
        : [],
      skip_core_build: skipCoreBuild,
      xyz_unpassivated: skipCoreBuild ? lastUnpassivatedXyz : null,
      reconstruction_enabled: skipCoreBuild ? reconEnabled : false,
      reconstruction_target_reduction: skipCoreBuild ? reconRatio : 0.5,
      reconstruction_min_separation: 'auto',
      neutral_enabled: skipCoreBuild ? neutralEnabled : false,
      neutral_jobs: skipCoreBuild
        ? lTypeOptions
            .filter(opt => neutralEnabled && opt.enabled)
            .flatMap(opt => (opt.jobs || []).filter(job => job.smiles?.trim() && job.target_count > 0).map(job => ({
              target: opt.target || job.target || 'anion',
              target_symbol: opt.target_symbol || opt.element || job.target_symbol || null,
              smiles: job.smiles,
              ratio: job.ratio,
              target_count: job.target_count || 0,
              distribution: job.distribution || opt.distribution || neutralDist,
            })))
        : [],
      z_type_enabled: skipCoreBuild ? zTypeEnabled : false,
      z_type_jobs: skipCoreBuild && zTypeEnabled
        ? zTypeOptions.filter(opt => opt.enabled).flatMap(opt => (opt.jobs || []).filter(job => job.target_count > 0).map(job => ({
            cation: opt.cation,
            anion: opt.anion,
            anion_count: opt.anion_count,
            target_count: job.target_count,
            ratio: job.ratio,
            distribution: job.distribution || opt.distribution,
          })))
        : [],
      neutral_exchange_enabled: skipCoreBuild ? (xTypeEnabled && neutralExchangeEnabled) : false,
      neutral_exchange_jobs: skipCoreBuild && xTypeEnabled && neutralExchangeEnabled
        ? neutralExchangeOptions.filter(opt => opt.enabled).flatMap(opt => (opt.jobs || []).filter(job => job.target_count > 0 && job.smiles?.trim()).map(job => ({
            cation: opt.cation,
            anion: opt.anion,
            anion_count: opt.anion_count,
            exchange_type: job.exchange_type === 'salt' ? 'mxn' : (job.exchange_type || 'mxn'),
            smiles: job.smiles,
            target_count: job.target_count,
            ratio: job.ratio,
            distribution: job.distribution || opt.distribution,
          })))
        : [],
      alloying_enabled: skipCoreBuild ? alloyingEnabled : false,
      alloying_jobs: skipCoreBuild && alloyingEnabled
        ? alloyingOptions.filter(opt => opt.enabled).flatMap(opt => (opt.jobs || []).filter(job => job.target_count > 0 && job.replacement).map(job => ({
            replace: opt.element,
            replacement: job.replacement,
            replacement_charge: job.replacement_charge,
            region: opt.region,
            ratio: job.ratio,
            target_count: job.target_count,
            distribution: job.distribution || opt.distribution,
          })))
        : [],
      center_ion: centerIon || null
    };

    formData.append('options', JSON.stringify(options));
    formData.append('positive_q_mode', posQ);
    formData.append('mode', runMode);

    const IS_LOCAL = isDesktopApp() || window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
    const BUILD_STREAM_URL = IS_LOCAL 
      ? "http://127.0.0.1:8000/builder/api/build_stream" 
      : "/builder/api/build_stream";

    try {
      const res = await fetch(BUILD_STREAM_URL, { method: 'POST', body: formData });
      if (!res.ok) {
        const errorText = await res.text();
        throw new Error(`HTTP ${res.status}: ${errorText}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        
        let nl;
        while ((nl = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          if (!line) continue;
          
          try {
            const evt = JSON.parse(line);
            if (evt.event === 'log') logs += evt.line + "\n";
            else if (evt.event === 'cmd') logs += `[cmd] ${evt.line}\n`;
            else if (evt.event === 'yaml_preview') logs += `[yaml] Generated config:\n${evt.text}\n`;
            else if (evt.event === 'result') finalResult = evt;
          } catch (e) {
            logs += line + "\n";
          }
        }
      }

      if (finalResult && finalResult.status === 'success') {
        xyzData = finalResult.xyz_passivated || finalResult.xyz || finalResult.xyz_unpassivated || "";
        zTypeOptions = decorateZTypeOptions(finalResult.z_type_options || []);
        neutralExchangeOptions = decorateNeutralExchangeOptions(finalResult.z_type_options || []);
        alloyingOptions = decorateAlloyingOptions(finalResult.alloying_options || []);
        xTypeOptions = decorateXTypeOptions(finalResult.x_type_options || []);
        lTypeOptions = decorateLTypeOptions(finalResult.l_type_options || []);
        if (!skipCoreBuild) {
            lastUnpassivatedXyz = finalResult.xyz_dummy || finalResult.xyz_unpassivated || finalResult.xyz_passivated || xyzData;
            sidebarView = 'postTreatment';
            passivateExpanded = true;
            scrollAsideToTop();
        }
        if (finalResult.last_command) logs += `[cmd][final] ${finalResult.last_command}\n`;
        logs += "\n[status] Rendered.\n";
      } else {
        logs += "[error] Build failed.\n";
      }
    } catch (err) {
      logs += localBuilderMissing(err)
        ? `[error] ${BUILDER_NOT_INCLUDED}\n`
        : `[error] fetch failed: ${err.message}\n`;
    } finally {
      isBuilding = false;
    }
  }
  // ==========================================
  // ADD CORE-SHELL MATCH PHASE  
  // ==========================================
  let allowedShellTemplates = $derived.by(() => {
    let matches = [];
    for (const family in bulkTemplates) {
      // If a core phase is known, strictly filter by it. Otherwise, show all.
      matches.push(...bulkTemplates[family].filter(t => !currentCorePhase || t.phase === currentCorePhase));
    }
    return matches;
  });


</script>

<svelte:window onmousemove={(e) => tooltipPos = { x: e.clientX + 15, y: e.clientY + 15 }} />
{#if tooltipText}
  <div class="fixed bg-slate-900/95 backdrop-blur-sm text-white px-3 py-2 rounded-xl text-xs z-[9999] pointer-events-none shadow-2xl font-medium max-w-[280px] break-words border border-slate-700/50 leading-relaxed" style="left: {tooltipPos.x}px; top: {tooltipPos.y}px;">
    {tooltipText}
  </div>
{/if}

<div class="flex flex-col lg:flex-row h-[calc(100vh-64px)] overflow-hidden font-sans bg-slate-50">
  
  <aside bind:this={asideEl} class="w-full lg:w-[380px] p-6 bg-slate-50 overflow-y-auto flex-shrink-0 border-r border-slate-200 flex flex-col gap-6">

    {#if sidebarView === 'postTreatment'}
    <!-- Post-build: focus on Panel 5 -->
    <div class="flex items-center justify-between mb-2">
      <h2 class="font-heading text-lg font-bold text-slate-900">5) Post-Treatment &amp; Passivation</h2>
      <button type="button" class="text-xs font-bold text-brand-600 hover:text-brand-800 px-2 py-1 rounded-lg border border-brand-200 bg-brand-50"
              onclick={() => { sidebarView = 'builder'; scrollAsideToTop(); }}>
        Back
      </button>
    </div>
    <div class="bg-white border border-slate-100 shadow-sm rounded-[1.5rem] p-6">
      {#if !passivateExpanded}
        <button class="w-full bg-slate-50 hover:bg-slate-100 border border-slate-200 text-brand-600 py-2.5 rounded-xl text-sm font-bold transition-colors" onclick={() => passivateExpanded = true}>+ Add Ligands &amp; Post-Treatments</button>
      {:else}
        <div class="space-y-4">
          <div class="border border-accent-200 bg-accent-50/20 p-4 rounded-2xl space-y-3">
            <label class="flex items-center gap-2 font-extrabold text-accent-700 text-[10px] uppercase tracking-widest cursor-pointer select-none">
              <input type="checkbox" bind:checked={alloyingEnabled} disabled={alloyingOptions.length === 0} class="accent-accent-600 rounded">
              Inorganic Alloying
            </label>
            {#if alloyingOptions.length === 0}
              <p class="text-[10px] text-slate-500 leading-snug">No inorganic alloying sites detected.</p>
            {:else if alloyingEnabled}
              <div class="space-y-3 bg-white/60 p-3 rounded-xl border border-accent-100">
                {#each ['cation', 'anion'] as siteType}
                  {@const optsForType = alloyingOptions.filter((opt) => opt.site_type === siteType)}
                  {#if optsForType.length > 0}
                    <span class="block text-[9px] font-bold text-accent-600 uppercase tracking-wider">{siteType}s</span>
                    {#each optsForType as opt (opt.element)}
                      <div class="border border-accent-100 rounded-xl p-3 bg-white/70 space-y-2">
                        <label class="space-y-2 text-xs font-bold text-slate-700 min-w-0 block">
                          <span class="flex items-center gap-2 whitespace-nowrap">
                            <input type="checkbox" bind:checked={opt.enabled} onchange={() => ensureJobs(opt, 'alloy')} class="accent-accent-600 rounded shrink-0">
                            <span>Replace {opt.element}</span>
                          </span>
                          <span class="flex flex-wrap gap-1.5 text-[10px] text-slate-500">
                            <span class="rounded-full bg-slate-100 px-2 py-0.5 whitespace-nowrap">surface {opt.surface_count}</span>
                            <span class="rounded-full bg-slate-100 px-2 py-0.5 whitespace-nowrap">core {opt.core_count}</span>
                          </span>
                        </label>
                        {#if opt.enabled}
                          <div class="grid grid-cols-[1fr_4rem] gap-2">
                            <select bind:value={opt.region} onchange={() => clampOptionJobs(opt, 'alloy')} class="border-none ring-1 ring-accent-200 rounded-lg px-1 py-1.5 text-xs bg-white focus:ring-2 focus:ring-accent-400 outline-none font-medium cursor-pointer min-w-0">
                              <option value="surface">Surf</option><option value="core">Core</option><option value="both">Both</option>
                            </select>
                            <button type="button" class="bg-white hover:bg-accent-50 border border-accent-200 text-[10px] py-1.5 rounded-lg text-accent-700 font-bold transition-colors" onclick={() => addOptionJob(opt, 'alloy')}>+ Add</button>
                          </div>
                          <div class="space-y-2">
                            {#each opt.jobs || [] as job (job.id)}
                              <div class="border border-accent-100 rounded-lg p-2 bg-white/80 space-y-2">
                                <div class="grid grid-cols-[1fr_4rem_28px] gap-2">
                                  <input type="text" bind:value={job.replacement} placeholder="Ion" class="border-none ring-1 ring-accent-200 rounded-lg px-2 py-1.5 text-xs bg-white focus:ring-2 focus:ring-accent-400 outline-none font-medium min-w-0">
                                  <input type="number" bind:value={job.replacement_charge} step="1" title="Replacement ion charge" class="border-none ring-1 ring-accent-200 rounded-lg px-2 py-1.5 text-xs text-center bg-white focus:ring-2 focus:ring-accent-400 outline-none font-medium min-w-0">
                                  <button type="button" class="bg-red-100 text-red-600 hover:bg-red-200 rounded-lg flex items-center justify-center text-xs font-bold transition-colors" onclick={() => removeOptionJob(opt, job, 'alloy')}>x</button>
                                </div>
                                <div class="grid grid-cols-[1fr_5rem] gap-2 items-center">
                                  <div class="space-y-1">
                                    <div class="flex justify-between text-[9px] font-bold text-slate-500 uppercase tracking-wider"><span>Available: {alloyAvailable(opt)}</span><span>Replace: {job.target_count} / {alloyAvailable(opt)} ({selectionPercent(job.target_count, alloyAvailable(opt))}%)</span></div>
                                    <input type="range" min="0" max="1" step="0.01" bind:value={job.ratio} oninput={() => syncJobCountFromRatio(opt, job, 'alloy')} class="w-full accent-accent-600 h-1 bg-slate-100 rounded-lg appearance-none cursor-pointer" />
                                  </div>
                                  <input type="number" min="0" max={alloyAvailable(opt)} step="1" bind:value={job.target_count} oninput={() => syncJobRatioFromCount(opt, job, 'alloy')} class="border-none ring-1 ring-accent-200 rounded-lg px-2 py-1.5 text-xs text-center bg-white focus:ring-2 focus:ring-accent-400 outline-none font-medium min-w-0">
                                </div>
                                <div class="flex flex-wrap gap-1.5 text-[10px] bg-white p-2 rounded-lg border border-accent-100">
                                  <label class="inline-flex items-center gap-1.5 cursor-pointer font-medium text-slate-700 whitespace-nowrap px-1"><input type="radio" bind:group={job.distribution} value="uniform" class="accent-accent-600 shrink-0"> Uniform</label>
                                  <label class="inline-flex items-center gap-1.5 cursor-pointer font-medium text-slate-700 whitespace-nowrap px-1"><input type="radio" bind:group={job.distribution} value="segmented" class="accent-accent-600 shrink-0"> Segmented</label>
                                  <label class="inline-flex items-center gap-1.5 cursor-pointer font-medium text-slate-700 whitespace-nowrap px-1"><input type="radio" bind:group={job.distribution} value="random" class="accent-accent-600 shrink-0"> Random</label>
                                </div>
                              </div>
                            {/each}
                            <div class="text-[9px] font-bold text-slate-500 uppercase tracking-wider text-right">Total: {optionJobTotal(opt)} / {alloyAvailable(opt)}</div>
                          </div>
                        {/if}
                      </div>
                    {/each}
                  {/if}
                {/each}
              </div>
            {/if}
          </div>
          <div class="border border-accent-200 bg-accent-50/20 p-4 rounded-2xl space-y-3">
            <label class="flex items-center gap-2 font-extrabold text-accent-700 text-[10px] uppercase tracking-widest cursor-pointer select-none">
              <input type="checkbox" bind:checked={zTypeEnabled} disabled={zTypeOptions.length === 0} class="accent-accent-600 rounded">
              Z-type Displacement
              <span class="text-[10px] bg-slate-100 hover:bg-slate-200 text-slate-400 hover:text-slate-600 w-3.5 h-3.5 rounded-full flex items-center justify-center font-bold font-mono cursor-help select-none shrink-0"
                    role="tooltip"
                    onmouseenter={() => tooltipText = "Removes neutral inorganic surface groups before X-type ligand exchange, e.g. CdCl2, CdSe, CsBr, or PbBr2. Options are detected from the current surface."}
                    onmouseleave={() => tooltipText = ""}>
                i
              </span>
            </label>
            {#if zTypeOptions.length === 0}
              <p class="text-[10px] text-slate-500 leading-snug">
                No neutral Z-type surface groups detected on the current structure.
              </p>
            {:else if zTypeEnabled}
              <div class="space-y-3 bg-white/60 p-3 rounded-xl border border-accent-100">
                {#each zTypeOptions as opt (zTypeKey(opt))}
                  <div class="border border-accent-100 rounded-xl p-3 bg-white/70 space-y-2">
                    <label class="flex items-center justify-between gap-2 text-xs font-bold text-slate-700">
                      <span class="inline-flex items-baseline gap-0.5"><input type="checkbox" bind:checked={opt.enabled} onchange={() => ensureJobs(opt, 'z_type')} class="accent-accent-600 rounded mr-1.5 shrink-0"> <span>{#each formulaParts(opt.label || opt.formula) as part}{#if part.subscript}<sub>{part.text}</sub>{:else}{part.text}{/if}{/each}</span></span>
                      <span class="text-[10px] text-slate-400">available {opt.candidate_count}</span>
                    </label>
                    {#if opt.enabled}
                      <div class="space-y-2">
                        {#each opt.jobs || [] as job (job.id)}
                          <div class="border border-accent-100 rounded-lg p-2 bg-white/80 space-y-2">
                            <div class="grid grid-cols-[1fr_5rem_28px] gap-2 items-center">
                              <div class="space-y-1">
                                <div class="flex justify-between text-[9px] font-bold text-slate-500 uppercase tracking-wider"><span>Available: {zTypeAvailable(opt)}</span><span>Remove: {job.target_count} / {zTypeAvailable(opt)} ({selectionPercent(job.target_count, zTypeAvailable(opt))}%)</span></div>
                                <input type="range" min="0" max="1" step="0.01" bind:value={job.ratio} oninput={() => syncJobCountFromRatio(opt, job, 'z_type')} class="w-full accent-accent-600 h-1 bg-slate-100 rounded-lg appearance-none cursor-pointer" />
                              </div>
                              <input type="number" min="0" max={zTypeAvailable(opt)} step="1" bind:value={job.target_count} oninput={() => syncJobRatioFromCount(opt, job, 'z_type')} class="border-none ring-1 ring-accent-200 rounded-lg px-2 py-1.5 text-xs text-center bg-white focus:ring-2 focus:ring-accent-400 outline-none font-medium min-w-0">
                              <button type="button" class="bg-red-100 text-red-600 hover:bg-red-200 rounded-lg flex items-center justify-center text-xs font-bold transition-colors h-full" onclick={() => removeOptionJob(opt, job, 'z_type')}>x</button>
                            </div>
                            <div class="flex flex-wrap gap-1.5 text-[10px] bg-white p-2 rounded-lg border border-accent-100">
                              <label class="inline-flex items-center gap-1.5 cursor-pointer font-medium text-slate-700 whitespace-nowrap px-1"><input type="radio" bind:group={job.distribution} value="uniform" class="accent-accent-600 shrink-0"> Uniform</label>
                              <label class="inline-flex items-center gap-1.5 cursor-pointer font-medium text-slate-700 whitespace-nowrap px-1"><input type="radio" bind:group={job.distribution} value="segmented" class="accent-accent-600 shrink-0"> Segmented</label>
                              <label class="inline-flex items-center gap-1.5 cursor-pointer font-medium text-slate-700 whitespace-nowrap px-1"><input type="radio" bind:group={job.distribution} value="random" class="accent-accent-600 shrink-0"> Random</label>
                            </div>
                          </div>
                        {/each}
                        <div class="text-[9px] font-bold text-slate-500 uppercase tracking-wider text-right">Total: {optionJobTotal(opt)} / {zTypeAvailable(opt)}</div>
                      </div>
                    {/if}
                  </div>
                {/each}
              </div>
            {/if}
          </div>
          <div class="border border-accent-200 bg-accent-50/20 p-4 rounded-2xl space-y-3">
            <label class="flex items-center gap-2 font-extrabold text-accent-700 text-[10px] uppercase tracking-widest cursor-pointer select-none">
              <input type="checkbox" bind:checked={xTypeEnabled} disabled={xTypeOptions.length === 0 && neutralExchangeOptions.length === 0} class="accent-accent-600 rounded">
              X-type & Neutral Ligand Exchange
              <span class="text-[10px] bg-slate-100 hover:bg-slate-200 text-slate-400 hover:text-slate-600 w-3.5 h-3.5 rounded-full flex items-center justify-center font-bold font-mono cursor-help select-none shrink-0"
                    role="tooltip"
                    onmouseenter={() => tooltipText = "Replaces charged surface species with charged organic ligands (X-type) or replaces neutral surface Z-type groups with MXn species, zwitterions, or neutral L-type ligands."}
                    onmouseleave={() => tooltipText = ""}>
                i
              </span>
            </label>
            {#if xTypeOptions.length === 0 && neutralExchangeOptions.length === 0}
              <p class="text-[10px] text-slate-500 leading-snug">No exchangeable surface sites detected on the current structure.</p>
            {:else if xTypeEnabled}
              <div class="space-y-3 bg-white/60 p-3 rounded-xl border border-accent-100">
                {#each ['anion', 'cation'] as siteType}
                  {@const optsForType = xTypeOptions.filter((opt) => opt.site_type === siteType)}
                  {#if optsForType.length > 0}
                    <div class="space-y-2">
                      <span class="block text-[9px] font-bold text-accent-600 uppercase tracking-wider">{siteType === 'anion' ? 'Anion Exchange' : 'Cation Exchange'}</span>
                      {#each optsForType as opt (xTypeKey(opt))}
                        <div class="border border-accent-100 rounded-xl p-3 bg-white/70 space-y-2">
                          <label class="space-y-2 text-xs font-bold text-slate-700 min-w-0 block">
                            <span class="flex items-center gap-2 whitespace-nowrap">
                              <input type="checkbox" bind:checked={opt.enabled} onchange={() => ensureJobs(opt, 'x_type')} class="accent-accent-600 rounded shrink-0">
                              <span>Exchange {opt.replace || opt.dummy} (q = {opt.replace_charge > 0 ? '+' : ''}{opt.replace_charge})</span>
                            </span>
                            <span class="flex flex-wrap gap-1.5 text-[10px] text-slate-500">
                              <span class="rounded-full bg-slate-100 px-2 py-0.5 whitespace-nowrap">available {xTypeAvailable(opt)}</span>
                            </span>
                          </label>
                          {#if opt.enabled}
                            <div class="space-y-2">
                              {#each opt.jobs || [] as job (job.id)}
                                <div class="border border-accent-100 rounded-lg p-2 bg-white/80 space-y-2">
                                  <div class="grid grid-cols-[1fr_28px] gap-2 items-center">
                                    <input type="text" bind:value={job.smiles} placeholder={siteType === 'anion' ? 'e.g. CCCC(=O)O' : 'e.g. CCCN'} class="border-none ring-1 ring-accent-200 rounded-lg px-2 py-1.5 text-xs bg-white focus:ring-2 focus:ring-accent-400 outline-none font-medium w-full">
                                    <button type="button" class="bg-red-100 text-red-600 hover:bg-red-200 rounded-lg flex items-center justify-center text-xs font-bold transition-colors h-full" onclick={() => removeOptionJob(opt, job, 'x_type')}>x</button>
                                  </div>
                                  <div class="grid grid-cols-[1fr_5rem] gap-2 items-center">
                                    <div class="space-y-1">
                                      <div class="flex justify-between text-[9px] font-bold text-slate-500 uppercase tracking-wider"><span>Available: {xTypeAvailable(opt)}</span><span>Exchange: {job.target_count || 0} / {xTypeAvailable(opt)} ({selectionPercent(job.target_count, xTypeAvailable(opt))}%)</span></div>
                                      <input type="range" min="0" max="1" step="0.01" bind:value={job.ratio} oninput={() => syncJobCountFromRatio(opt, job, 'x_type')} class="w-full accent-accent-600 h-1 bg-slate-100 rounded-lg appearance-none cursor-pointer" />
                                    </div>
                                    <input type="number" min="0" max={xTypeAvailable(opt)} step="1" bind:value={job.target_count} oninput={() => syncJobRatioFromCount(opt, job, 'x_type')} class="border-none ring-1 ring-accent-200 rounded-lg px-2 py-1.5 text-xs text-center bg-white focus:ring-2 focus:ring-accent-400 outline-none font-medium min-w-0">
                                  </div>
                                  <div class="flex flex-wrap gap-1.5 text-[10px] bg-white p-2 rounded-lg border border-accent-100">
                                    <label class="inline-flex items-center gap-1.5 cursor-pointer font-medium text-slate-700 whitespace-nowrap px-1"><input type="radio" bind:group={job.distribution} value="uniform" class="accent-accent-600 shrink-0"> Uniform</label>
                                    <label class="inline-flex items-center gap-1.5 cursor-pointer font-medium text-slate-700 whitespace-nowrap px-1"><input type="radio" bind:group={job.distribution} value="segmented" class="accent-accent-600 shrink-0"> Segmented</label>
                                    <label class="inline-flex items-center gap-1.5 cursor-pointer font-medium text-slate-700 whitespace-nowrap px-1"><input type="radio" bind:group={job.distribution} value="random" class="accent-accent-600 shrink-0"> Random</label>
                                  </div>
                                </div>
                              {/each}
                              <button type="button" class="w-full bg-white hover:bg-accent-50 border border-accent-200 text-[10px] py-1.5 rounded-lg text-accent-700 font-bold transition-colors" onclick={() => addOptionJob(opt, 'x_type')}>+ Add ligand</button>
                              <div class="text-[9px] font-bold text-slate-500 uppercase tracking-wider text-right">Total: {optionJobTotal(opt)} / {xTypeAvailable(opt)}</div>
                            </div>
                          {/if}
                        </div>
                      {/each}
                    </div>
                  {/if}
                {/each}

                {#if neutralExchangeOptions.length > 0}
                  <div class="space-y-2 pt-2 border-t border-accent-100/50">
                    <span class="block text-[9px] font-bold text-accent-600 uppercase tracking-wider">Neutral Exchange</span>
                    {#each neutralExchangeOptions as opt (zTypeKey(opt))}
                      <div class="border border-accent-100 rounded-xl p-3 bg-white/70 space-y-2">
                        <label class="space-y-2 text-xs font-bold text-slate-700 min-w-0 block">
                          <span class="flex items-center gap-2 whitespace-nowrap">
                            <input type="checkbox" bind:checked={opt.enabled} onchange={() => ensureJobs(opt, 'neutral_exchange')} class="accent-accent-600 rounded shrink-0">
                            <span>Exchange {#each formulaParts(opt.label || opt.formula) as part}{#if part.subscript}<sub>{part.text}</sub>{:else}{part.text}{/if}{/each}</span>
                          </span>
                          <span class="flex flex-wrap gap-1.5 text-[10px] text-slate-500">
                            <span class="rounded-full bg-slate-100 px-2 py-0.5 whitespace-nowrap">available {zTypeAvailable(opt)}</span>
                          </span>
                        </label>
                        {#if opt.enabled}
                          <div class="space-y-2">
                            {#each opt.jobs || [] as job (job.id)}
                              <div class="border border-accent-100 rounded-lg p-2 bg-white/80 space-y-2">
                                <div class="flex flex-wrap gap-1.5 text-[10px] bg-slate-50 p-1.5 rounded-lg border border-slate-200">
                                  <label class="inline-flex items-center gap-1.5 cursor-pointer font-medium text-slate-700 whitespace-nowrap px-1"><input type="radio" bind:group={job.exchange_type} value="mxn" class="accent-accent-600 shrink-0"> MXn exchange</label>
                                  <label class="inline-flex items-center gap-1.5 cursor-pointer font-medium text-slate-700 whitespace-nowrap px-1"><input type="radio" bind:group={job.exchange_type} value="zwitterion" class="accent-accent-600 shrink-0"> zwitterion</label>
                                  <label class="inline-flex items-center gap-1.5 cursor-pointer font-medium text-slate-700 whitespace-nowrap px-1"><input type="radio" bind:group={job.exchange_type} value="l_type" class="accent-accent-600 shrink-0"> l-type</label>
                                </div>
                                <div class="grid grid-cols-[1fr_28px] gap-2 items-center">
                                  <input type="text" bind:value={job.smiles}
                                         placeholder={
                                           job.exchange_type === 'mxn' ? 'e.g. InBr3, CsBr, ZnBr2, or [Zn+2].CC(=O)[O-].CC(=O)[O-]' :
                                           job.exchange_type === 'zwitterion' ? 'e.g. [NH3+]CC[S-] or [NH3+]CC(=O)[O-]' :
                                           'e.g. CN (methylamine) or CCCS (neutral thiol)'
                                         }
                                         class="border-none ring-1 ring-accent-200 rounded-lg px-2 py-1.5 text-xs bg-white focus:ring-2 focus:ring-accent-400 outline-none font-medium w-full">
                                  <button type="button" class="bg-red-100 text-red-600 hover:bg-red-200 rounded-lg flex items-center justify-center text-xs font-bold transition-colors h-full" onclick={() => removeOptionJob(opt, job, 'neutral_exchange')}>x</button>
                                </div>
                                <div class="flex flex-wrap gap-1 items-center text-[9px]">
                                  <span class="text-slate-400 font-bold uppercase mr-1">Templates:</span>
                                  {#if job.exchange_type === 'mxn'}
                                    <button type="button" class="bg-slate-100 hover:bg-slate-200 text-slate-600 px-1.5 py-0.5 rounded cursor-pointer transition-colors" onclick={() => job.smiles = 'InBr3'}>InBr₃</button>
                                    <button type="button" class="bg-slate-100 hover:bg-slate-200 text-slate-600 px-1.5 py-0.5 rounded cursor-pointer transition-colors" onclick={() => job.smiles = 'CsBr'}>CsBr</button>
                                    <button type="button" class="bg-slate-100 hover:bg-slate-200 text-slate-600 px-1.5 py-0.5 rounded cursor-pointer transition-colors" onclick={() => job.smiles = 'ZnBr2'}>ZnBr₂</button>
                                    <button type="button" class="bg-slate-100 hover:bg-slate-200 text-slate-600 px-1.5 py-0.5 rounded cursor-pointer transition-colors" onclick={() => job.smiles = '[Zn+2].CC(=O)[O-].CC(=O)[O-]'}>Zn acetate</button>
                                  {:else if job.exchange_type === 'zwitterion'}
                                    <button type="button" class="bg-slate-100 hover:bg-slate-200 text-slate-600 px-1.5 py-0.5 rounded cursor-pointer transition-colors" onclick={() => job.smiles = '[NH3+]CC[S-]'}>Cysteamine</button>
                                    <button type="button" class="bg-slate-100 hover:bg-slate-200 text-slate-600 px-1.5 py-0.5 rounded cursor-pointer transition-colors" onclick={() => job.smiles = '[NH3+]CC(=O)[O-]'}>Glycine</button>
                                    <button type="button" class="bg-slate-100 hover:bg-slate-200 text-slate-600 px-1.5 py-0.5 rounded cursor-pointer transition-colors" onclick={() => job.smiles = '[NH3+]CCCCCCCCCC(=O)[O-]'}>11-aminoundecanoic</button>
                                  {:else if job.exchange_type === 'l_type'}
                                    <button type="button" class="bg-slate-100 hover:bg-slate-200 text-slate-600 px-1.5 py-0.5 rounded cursor-pointer transition-colors" onclick={() => job.smiles = 'CN'}>Methylamine</button>
                                    <button type="button" class="bg-slate-100 hover:bg-slate-200 text-slate-600 px-1.5 py-0.5 rounded cursor-pointer transition-colors" onclick={() => job.smiles = 'CCCCC(=O)O'}>Pentanoic Acid</button>
                                    <button type="button" class="bg-slate-100 hover:bg-slate-200 text-slate-600 px-1.5 py-0.5 rounded cursor-pointer transition-colors" onclick={() => job.smiles = 'CCCCS'}>Pentanethiol</button>
                                  {/if}
                                </div>
                                <div class="grid grid-cols-[1fr_5rem] gap-2 items-center">
                                  <div class="space-y-1">
                                    <div class="flex justify-between text-[9px] font-bold text-slate-500 uppercase tracking-wider"><span>Available: {zTypeAvailable(opt)}</span><span>Exchange: {job.target_count || 0} / {zTypeAvailable(opt)} ({selectionPercent(job.target_count, zTypeAvailable(opt))}%)</span></div>
                                    <input type="range" min="0" max="1" step="0.01" bind:value={job.ratio} oninput={() => syncJobCountFromRatio(opt, job, 'neutral_exchange')} class="w-full accent-accent-600 h-1 bg-slate-100 rounded-lg appearance-none cursor-pointer" />
                                  </div>
                                  <input type="number" min="0" max={zTypeAvailable(opt)} step="1" bind:value={job.target_count} oninput={() => syncJobRatioFromCount(opt, job, 'neutral_exchange')} class="border-none ring-1 ring-accent-200 rounded-lg px-2 py-1.5 text-xs text-center bg-white focus:ring-2 focus:ring-accent-400 outline-none font-medium min-w-0">
                                </div>
                                <div class="flex flex-wrap gap-1.5 text-[10px] bg-white p-2 rounded-lg border border-accent-100">
                                  <label class="inline-flex items-center gap-1.5 cursor-pointer font-medium text-slate-700 whitespace-nowrap px-1"><input type="radio" bind:group={job.distribution} value="uniform" class="accent-accent-600 shrink-0"> Uniform</label>
                                  <label class="inline-flex items-center gap-1.5 cursor-pointer font-medium text-slate-700 whitespace-nowrap px-1"><input type="radio" bind:group={job.distribution} value="segmented" class="accent-accent-600 shrink-0"> Segmented</label>
                                  <label class="inline-flex items-center gap-1.5 cursor-pointer font-medium text-slate-700 whitespace-nowrap px-1"><input type="radio" bind:group={job.distribution} value="random" class="accent-accent-600 shrink-0"> Random</label>
                                </div>
                              </div>
                            {/each}
                            <button type="button" class="w-full bg-white hover:bg-accent-50 border border-accent-200 text-[10px] py-1.5 rounded-lg text-accent-700 font-bold transition-colors" onclick={() => addOptionJob(opt, 'neutral_exchange')}>+ Add exchange</button>
                            <div class="text-[9px] font-bold text-slate-500 uppercase tracking-wider text-right">Total: {optionJobTotal(opt)} / {zTypeAvailable(opt)}</div>
                          </div>
                        {/if}
                      </div>
                    {/each}
                  </div>
                {/if}
              </div>
            {/if}
          </div>
          <div class="border border-accent-200 bg-accent-50/20 p-4 rounded-2xl space-y-3">
            <label class="flex items-center gap-2 font-extrabold text-accent-700 text-[10px] uppercase tracking-widest cursor-pointer select-none">
              <input type="checkbox" bind:checked={neutralEnabled} disabled={lTypeOptions.length === 0} class="accent-accent-600 rounded">
              L-type Ligand Passivation
            </label>
            {#if lTypeOptions.length === 0}
              <p class="text-[10px] text-slate-500 leading-snug">No L-type passivation sites detected on the current structure.</p>
            {:else if neutralEnabled}
              <div class="space-y-3 bg-white/60 p-3 rounded-xl border border-accent-100">
                {#each ['cation', 'anion'] as siteType}
                  {@const optsForType = lTypeOptions.filter((opt) => opt.site_type === siteType)}
                  {#if optsForType.length > 0}
                    <div class="space-y-2">
                      <span class="block text-[9px] font-bold text-accent-600 uppercase tracking-wider">{siteType === 'cation' ? 'Cation Sites' : 'Anion Sites'}</span>
                      {#each optsForType as opt (lTypeKey(opt))}
                        <div class="border border-accent-100 rounded-xl p-3 bg-white/70 space-y-2">
                          <label class="space-y-2 text-xs font-bold text-slate-700 min-w-0 block">
                            <span class="flex items-center gap-2 whitespace-nowrap">
                              <input type="checkbox" bind:checked={opt.enabled} onchange={() => ensureJobs(opt, 'l_type')} class="accent-accent-600 rounded shrink-0">
                              <span>Passivate {opt.element || opt.target_symbol || opt.target}</span>
                            </span>
                            <span class="flex flex-wrap gap-1.5 text-[10px] text-slate-500">
                              <span class="rounded-full bg-slate-100 px-2 py-0.5 whitespace-nowrap">available {opt.available_count}</span>
                            </span>
                          </label>
                          {#if opt.enabled}
                            <div class="space-y-2">
                              {#each opt.jobs || [] as job (job.id)}
                                <div class="border border-accent-100 rounded-lg p-2 bg-white/80 space-y-2">
                                  <div class="grid grid-cols-[1fr_28px] gap-2">
                                    <input type="text" bind:value={job.smiles} placeholder="e.g. CCCN" class="border-none ring-1 ring-accent-200 rounded-lg px-2 py-1.5 text-xs bg-white focus:ring-2 focus:ring-accent-400 outline-none font-medium min-w-0">
                                    <button type="button" class="bg-red-100 text-red-600 hover:bg-red-200 rounded-lg flex items-center justify-center text-xs font-bold transition-colors" onclick={() => removeOptionJob(opt, job, 'l_type')}>x</button>
                                  </div>
                                  <div class="flex flex-wrap gap-1 items-center text-[9px]">
                                    <span class="text-slate-400 font-bold uppercase mr-1">Templates:</span>
                                    <button type="button" class="bg-slate-100 hover:bg-slate-200 text-slate-600 px-1.5 py-0.5 rounded cursor-pointer transition-colors" onclick={() => job.smiles = 'CN'}>Methylamine</button>
                                    <button type="button" class="bg-slate-100 hover:bg-slate-200 text-slate-600 px-1.5 py-0.5 rounded cursor-pointer transition-colors" onclick={() => job.smiles = 'CCCCC(=O)O'}>Pentanoic Acid</button>
                                    <button type="button" class="bg-slate-100 hover:bg-slate-200 text-slate-600 px-1.5 py-0.5 rounded cursor-pointer transition-colors" onclick={() => job.smiles = 'CCCCS'}>Pentanethiol</button>
                                  </div>
                                  <div class="grid grid-cols-[1fr_5rem] gap-2 text-[10px] items-center">
                                    <div class="space-y-1">
                                      <div class="flex justify-between text-[9px] font-bold text-slate-500 uppercase tracking-wider"><span>Available: {opt.available_count}</span><span>Passivate: {job.target_count || 0} / {opt.available_count} ({selectionPercent(job.target_count, opt.available_count)}%)</span></div>
                                      <input type="range" min="0" max="1" step="0.01" bind:value={job.ratio} oninput={() => syncJobCountFromRatio(opt, job, 'l_type')} class="w-full accent-accent-600 h-1 bg-slate-100 rounded-lg appearance-none cursor-pointer" />
                                    </div>
                                    <input type="number" min="0" max={opt.available_count} step="1" bind:value={job.target_count} oninput={() => syncJobRatioFromCount(opt, job, 'l_type')} class="border-none ring-1 ring-accent-200 rounded-lg px-1 py-1.5 text-xs text-center bg-white focus:ring-2 focus:ring-accent-400 outline-none font-medium min-w-0">
                                  </div>
                                  <div class="flex flex-wrap gap-1.5 text-[10px] bg-white p-2 rounded-lg border border-accent-100">
                                    <label class="inline-flex items-center gap-1.5 cursor-pointer font-medium text-slate-700 whitespace-nowrap px-1"><input type="radio" bind:group={job.distribution} value="uniform" class="accent-accent-600 shrink-0"> Uniform</label>
                                    <label class="inline-flex items-center gap-1.5 cursor-pointer font-medium text-slate-700 whitespace-nowrap px-1"><input type="radio" bind:group={job.distribution} value="segmented" class="accent-accent-600 shrink-0"> Segmented</label>
                                    <label class="inline-flex items-center gap-1.5 cursor-pointer font-medium text-slate-700 whitespace-nowrap px-1"><input type="radio" bind:group={job.distribution} value="random" class="accent-accent-600 shrink-0"> Random</label>
                                  </div>
                                </div>
                              {/each}
                              <button type="button" class="w-full bg-white hover:bg-accent-50 border border-accent-200 text-[10px] py-1.5 rounded-lg text-accent-700 font-bold transition-colors" onclick={() => addOptionJob(opt, 'l_type')}>+ Add L-type passivant</button>
                              <div class="text-[9px] font-bold text-slate-500 uppercase tracking-wider text-right">Total: {optionJobTotal(opt)} / {opt.available_count}</div>
                            </div>
                          {/if}
                        </div>
                      {/each}
                    </div>
                  {/if}
                {/each}
              </div>
            {/if}
          </div>
          <div class="border border-accent-200 bg-accent-50/20 p-4 rounded-2xl">
            <label class="flex items-center gap-2 font-extrabold text-accent-700 text-[10px] uppercase tracking-widest cursor-pointer select-none">
              <input type="checkbox" bind:checked={reconEnabled} class="accent-accent-600 rounded">
              Polar Surface Reconstruction
            </label>
            <p class="text-[10px] text-slate-500 mt-2 leading-snug">
              Cl placeholders on polar facets (auto spacing). Runs before ligand exchange.
            </p>

            {#if reconEnabled}
              <!-- Reconstruction Ratio Selector -->
              <div class="space-y-1.5 mt-3 p-3 bg-white border border-accent-100 rounded-xl">
                <div class="flex justify-between items-center text-xs">
                  <span class="font-bold text-slate-700">Reconstruction Ratio</span>
                  <span class="font-mono bg-accent-50 text-accent-700 px-2 py-0.5 rounded font-bold">{Math.round(reconRatio * 100)}%</span>
                </div>
                <input 
                  type="range" 
                  min="0.1" 
                  max="0.9" 
                  step="0.05" 
                  bind:value={reconRatio}
                  class="w-full accent-accent-600 h-1 bg-slate-100 rounded-lg appearance-none cursor-pointer"
                />
              </div>
            {/if}
          </div>
        </div>
      {/if}
      {#if lastUnpassivatedXyz}
        <hr class="my-4 border-slate-100" />
        <button class="w-full bg-accent-600 hover:bg-accent-700 text-white font-bold py-3 rounded-xl text-sm transition-all shadow-glow active:scale-95 flex items-center justify-center gap-2 mb-3"
                onclick={() => onBuild(true)} disabled={isBuilding}>
          {isBuilding ? 'Processing...' : 'Repassivate Current Structure'}
        </button>
      {/if}
      {#if xyzData && finalResult}
        <button class="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-2.5 rounded-xl shadow-sm transition-all active:scale-95 text-sm flex items-center justify-center gap-1.5"
                onclick={downloadXYZ}>
          ⬇ Download {finalResult.download_name || 'final.xyz'}
        </button>
      {/if}
    </div>
    {:else}
    
    <div class="px-2 pt-2 mb-2">
      <h1 class="font-heading text-2xl font-bold flex items-center gap-3 mb-2 text-slate-900 tracking-tight">
        <img src="/assets/logos/QD_Builder_mini.png" alt="QD Builder" class="h-9 w-auto mix-blend-multiply">
        Quantum Dot Builder
      </h1>
      <p class="text-sm text-slate-600 font-medium leading-relaxed">
        Upload a .cif, set parameters, and build your nanocrystal.
      </p>
    </div>

    <div class="bg-white border border-slate-100 shadow-sm rounded-[1.5rem] p-6">
      <div class="flex justify-between items-center mb-4">
        <h2 class="font-heading text-lg font-bold text-slate-900">1) Core Structure</h2>
        {#if coreFile}
          <button class="text-xs text-red-500 font-bold hover:text-red-700" onclick={() => coreFile = null}>Clear File</button>
        {/if}
      </div>

      {#if !coreFile}
        <div class="mb-5">
          <span class="block text-[10px] font-extrabold text-brand-700 uppercase tracking-widest mb-2">Quick Select Bulk</span>
          
          <div class="flex space-x-1 rounded-xl p-1 bg-slate-100 mb-3 overflow-x-auto">
            {#each Object.keys(bulkTemplates) as family}
              <button 
                class="flex-1 min-w-[60px] rounded-lg py-1.5 text-xs font-bold transition-all {activeFamilyTab === family ? 'bg-white text-brand-600 shadow-sm' : 'text-slate-500 hover:text-slate-700'}"
                onclick={() => activeFamilyTab = family}>
                {family}
              </button>
            {/each}
          </div>

          <div class="flex flex-wrap gap-2 min-h-[40px]">
            {#if isLoadingTemplate}
              <span class="text-xs font-bold text-brand-500 animate-pulse flex items-center gap-2">
                <div class="w-3 h-3 border-2 border-brand-500 border-t-transparent rounded-full animate-spin"></div> Fetching...
              </span>
            {:else}
              {#each bulkTemplates[activeFamilyTab] as template}
                <button 
                  class="flex flex-col items-center justify-center px-3 py-2 bg-brand-50 hover:bg-brand-100 text-brand-700 border border-brand-200 rounded-lg transition-colors w-[85px]"
                  onclick={() => loadTemplate(template)}>
                  <span class="text-sm font-bold leading-tight">{template.name}</span>
                  <span class="text-[9px] font-bold opacity-60 uppercase tracking-wider mt-0.5">{template.phase}</span>
                  <span class="text-[10px] font-mono font-medium opacity-80 mt-1 bg-white/60 px-1.5 py-0.5 rounded">{template.a} Å</span>
                </button>
              {/each}
            {/if}
          </div>
        </div>

        <div class="relative flex py-2 items-center mb-4">
          <div class="flex-grow border-t border-slate-100"></div>
          <span class="flex-shrink-0 mx-4 text-slate-300 text-[10px] font-bold uppercase tracking-widest">OR</span>
          <div class="flex-grow border-t border-slate-100"></div>
        </div>
      {/if}

      <label class="border-2 border-dashed border-slate-200 hover:bg-brand-50 hover:border-brand-400 transition-all p-5 rounded-2xl text-center cursor-pointer block group {coreFile ? 'bg-brand-50 border-brand-400' : ''}"
             ondragover={(e) => e.preventDefault()}
             ondrop={(e) => { e.preventDefault(); if(e.dataTransfer.files[0]) { coreFile = e.dataTransfer.files[0]; currentCorePhase = null; } }}>
        <input type="file" class="hidden" accept=".cif" onchange={(e) => { coreFile = e.target.files[0]; currentCorePhase = null; }}>
        <div class="text-sm text-slate-500 font-medium group-hover:text-brand-600 transition-colors flex flex-col items-center gap-2">
          {#if coreFile}
            <div class="w-10 h-10 bg-white rounded-full flex items-center justify-center shadow-sm text-brand-500 mb-1">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
            </div>
            <span class="font-bold text-brand-700">{coreFile.name}</span>
          {:else}
            <span class="font-bold text-brand-600">Click to upload custom</span>
            <span class="text-xs">or drag & drop a .cif file</span>
          {/if}
        </div>
      </label>
    </div>
 
    <div class="bg-white border border-slate-100 shadow-sm rounded-[1.5rem] p-6">
      <h2 class="font-heading text-lg font-bold text-slate-900 mb-4">2) Size & Aspect</h2>
      <span class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-2">Core Shape Presets</span>
      <div class="flex space-x-1 rounded-xl p-1 bg-slate-100 my-2">
        {#each ['Sphere', 'Platelet', 'Rod', 'Custom'] as preset}
          <button class="w-full rounded-lg py-1.5 text-xs font-bold transition-all {activePreset === preset ? 'bg-white text-brand-600 shadow-sm' : 'text-slate-500 hover:text-slate-700 hover:bg-slate-200/50'}"
                  onclick={() => applyPreset(preset)}>{preset}</button>
        {/each}
      </div>
      
      <span class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-2 mt-4 flex items-center gap-1.5 select-none"
            onmouseenter={() => tooltipText = "Number of unit cells along each axis (nx, ny, nz). Fractional values like 3.25 are supported for fine-tuning the aspect ratio."}
            onmouseleave={() => tooltipText = ""}>
        Core Size [nx, ny, nz] (Unit Cells) ⓘ
      </span>
      <div class="grid grid-cols-3 gap-3">
        <input type="number" bind:value={sizeUnitCells[0]} step="0.25" min="0.25" class="w-full text-center border-none ring-1 ring-slate-200 rounded-xl py-2 bg-slate-50 text-sm font-medium focus:ring-2 focus:ring-brand-400 outline-none" oninput={() => activePreset = 'Custom'}>
        <input type="number" bind:value={sizeUnitCells[1]} step="0.25" min="0.25" class="w-full text-center border-none ring-1 ring-slate-200 rounded-xl py-2 bg-slate-50 text-sm font-medium focus:ring-2 focus:ring-brand-400 outline-none" oninput={() => activePreset = 'Custom'}>
        <input type="number" bind:value={sizeUnitCells[2]} step="0.25" min="0.25" class="w-full text-center border-none ring-1 ring-slate-200 rounded-xl py-2 bg-slate-50 text-sm font-medium focus:ring-2 focus:ring-brand-400 outline-none" oninput={() => activePreset = 'Custom'}>
      </div>

      <span class="text-[11px] text-brand-600 font-bold block mt-3 px-3 py-2 bg-brand-50/50 rounded-xl border border-brand-100/50 text-center shadow-inner">
        📏 Real-time Size: {(sizeUnitCells[0] * latticeLengths[0]).toFixed(1)} Å × {(sizeUnitCells[1] * latticeLengths[1]).toFixed(1)} Å × {(sizeUnitCells[2] * latticeLengths[2]).toFixed(1)} Å
      </span>
    </div>

    <div class="bg-white border border-slate-100 shadow-sm rounded-[1.5rem] p-6">
      <div class="flex justify-between items-center mb-4">
        <h2 class="font-heading text-lg font-bold text-slate-900">3) Core Facets</h2>
        {#if isAnalyzingCif}
          <span class="text-xs text-brand-500 animate-pulse font-bold flex items-center gap-1">
            <div class="w-3.5 h-3.5 border-2 border-brand-500 border-t-transparent rounded-full animate-spin"></div>
            Analyzing CIF...
          </span>
        {/if}
      </div>

      {#if detectedFacets.length === 0}
        <div class="p-4 bg-slate-50 border border-slate-100 rounded-2xl text-center">
          <p class="text-xs text-slate-400 italic">Please upload or select a CIF structure first to analyze facets.</p>
        </div>
      {:else}
        <div class="space-y-4">
          {#each detectedFacets as fam (fam.family)}
            {@const isEnabled = coreFacets.some(f => f.family === fam.family)}
            <div class="border rounded-2xl overflow-hidden transition-all {isEnabled ? 'border-brand-200 bg-brand-50/10' : 'border-slate-100 bg-white hover:bg-slate-50/50'}">
              <div class="flex items-center justify-between p-4 cursor-pointer select-none" onclick={() => toggleFacetFamily(fam)}>
                <div class="flex items-start gap-3 pt-0.5">
                  <input type="checkbox" checked={isEnabled} class="accent-brand-600 rounded cursor-pointer mt-1" onclick={(e) => { e.stopPropagation(); toggleFacetFamily(fam); }}>
                  <div class="flex flex-col gap-1.5">
                    <span class="font-bold text-sm text-slate-800 leading-none">{fam.family} Facets</span>
                    
                    <span class="inline-flex items-center gap-0.5 text-[9px] font-bold uppercase px-2 py-0.5 rounded-full border whitespace-nowrap cursor-help select-none w-max shrink-0
                      {fam.status === 'polar' ? 'bg-red-50 text-red-600 border-red-100' : 
                       fam.status === 'termination-sensitive' ? 'bg-amber-50 text-amber-600 border-amber-100' : 
                       'bg-slate-100 text-slate-600 border-slate-200'}"
                      onmouseenter={() => tooltipText = fam.status === 'polar' 
                        ? "Polar: Slab contains a net dipole normal to the surface. Cation-Rich vs Anion-Rich terminations are asymmetric in charge."
                        : fam.status === 'termination-sensitive' 
                        ? "Termination-Sensitive: Slab has zero dipole (non-polar) but has multiple distinct stoichiometric cut options (e.g. Cation-rich vs Anion-rich)."
                        : "Non-polar: Slab has zero dipole and unique symmetric termination cut configurations."}
                      onmouseleave={() => tooltipText = ""}>
                      {fam.status === 'termination-sensitive' ? 'Termination-Sensitive' : 
                       fam.status === 'non-polar' ? 'Non-Polar' : 
                       fam.status === 'polar' ? 'Polar' : 
                       fam.status} ⓘ
                    </span>
                  </div>
                </div>
                <div class="flex items-center gap-2">
                  <span class="text-[10px] font-semibold text-slate-400">×{fam.multiplicity} planes</span>
                  <svg class="w-4 h-4 text-slate-400 transition-transform {isEnabled ? 'rotate-180' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>
                </div>
              </div>

              <!-- Body -->
              {#if isEnabled}
                {@const facetsForFam = coreFacets.filter(f => f.family === fam.family)}
                <div class="p-4 pt-0 border-t border-brand-100 bg-brand-50/5 space-y-4">
                  <!-- Scope Selector (Full Width) -->
                  <div class="space-y-1.5 mt-3">
                    <span class="block text-[9px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1 cursor-help select-none"
                          onmouseenter={() => tooltipText = "Choose whether to apply settings to the entire facet family ('all equivalent') or customize each index plane individually ('individual')."}
                          onmouseleave={() => tooltipText = ""}>
                      Scope ⓘ
                    </span>
                    <div class="flex rounded-lg p-0.5 bg-slate-100 border border-slate-200/50 h-[32px] items-center w-full">
                      <button type="button" class="flex-1 h-full rounded-md text-[10px] font-bold transition-all {facetsForFam[0]?.scope === 'family' ? 'bg-white text-brand-600 shadow-sm' : 'text-slate-500 hover:text-slate-700'}"
                              onclick={() => updateFacetScope(fam.family, 'family')}>
                        all equivalent
                      </button>
                      <button type="button" class="flex-1 h-full rounded-md text-[10px] font-bold transition-all {facetsForFam[0]?.scope === 'facet' ? 'bg-white text-brand-600 shadow-sm' : 'text-slate-500 hover:text-slate-700'}"
                              onclick={() => updateFacetScope(fam.family, 'facet')}>
                        individual
                      </button>
                    </div>
                  </div>
                  
                  {#if facetsForFam[0]?.scope === 'family'}
                    {#if fam.status === 'polar' || fam.status === 'termination-sensitive'}
                      <!-- Termination Style (Full Width) - multi-select checkboxes -->
                      <div class="space-y-1.5">
                        <span class="block text-[9px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1 cursor-help select-none"
                              onmouseenter={() => tooltipText = fam.status === 'polar'
                                ? "Polar facets contain alternating charged layers. Cation-Rich makes the surface metal-terminated, while Anion-Rich makes it chalcogenide/halide-terminated. You can enable both."
                                : "Non-polar plane with multiple symmetric cut configurations. You can enable both termination styles simultaneously."}
                              onmouseleave={() => tooltipText = ""}>
                          Termination Style ⓘ
                        </span>
                        <div class="flex gap-3 px-1">
                          <label class="flex items-center gap-1.5 cursor-pointer select-none text-[10px] font-bold text-slate-700">
                            <input type="checkbox"
                                   class="accent-brand-600 rounded"
                                   checked={facetsForFam.some(f => f.termination === 'cation_rich')}
                                   onchange={(e) => upsertFamilyTermination(fam, 'cation_rich', e.target.checked)}>
                            Cation-Rich
                          </label>
                          <label class="flex items-center gap-1.5 cursor-pointer select-none text-[10px] font-bold text-slate-700">
                            <input type="checkbox"
                                   class="accent-brand-600 rounded"
                                   checked={facetsForFam.some(f => f.termination === 'anion_rich')}
                                   onchange={(e) => upsertFamilyTermination(fam, 'anion_rich', e.target.checked)}>
                            Anion-Rich
                          </label>
                        </div>
                      </div>

                      <div class="space-y-2">
                        <span class="block text-[9px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1 cursor-help select-none"
                              onmouseenter={() => tooltipText = "Surface energy in J/m². For polar families, cation-rich and anion-rich terminations can be tuned independently."}
                              onmouseleave={() => tooltipText = ""}>
                          Surface Energy (γ) ⓘ
                        </span>
                        {#each facetsForFam.filter(f => f.termination === 'cation_rich' || f.termination === 'anion_rich') as termFacet (termFacet.termination)}
                          <label class="grid grid-cols-[110px_1fr] items-center gap-3">
                            <span class="text-[10px] font-bold text-slate-700 select-none">{terminationLabel(termFacet.termination)}</span>
                            <input type="number" step="0.1" class="w-full border-none ring-1 ring-brand-200 rounded-lg px-3 py-1.5 text-xs bg-white focus:ring-2 focus:ring-brand-400 outline-none font-medium h-[32px]"
                                   value={termFacet.gamma}
                                   oninput={(e) => updateFamilyTerminationGamma(fam.family, termFacet.termination, parseFloat(e.target.value))}>
                          </label>
                        {/each}
                      </div>
                    {:else}
                      <!-- Surface Energy (Full Width) -->
                      <div class="space-y-1.5">
                        <span class="block text-[9px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1 cursor-help select-none"
                              onmouseenter={() => tooltipText = "Surface energy in J/m². Determines the facet's relative area in Wulff construction. Lower energy means larger facet size."}
                              onmouseleave={() => tooltipText = ""}>
                          Surface Energy (γ) ⓘ
                        </span>
                        <input type="number" step="0.1" class="w-full border-none ring-1 ring-brand-200 rounded-lg px-3 py-1.5 text-xs bg-white focus:ring-2 focus:ring-brand-400 outline-none font-medium h-[32px]"
                               value={facetsForFam[0]?.gamma}
                               oninput={(e) => updateFamilyGamma(fam.family, parseFloat(e.target.value))}>
                      </div>

                      <div class="p-3 bg-white border border-slate-100 rounded-xl flex items-center justify-between h-[36px]">
                        <span class="text-[9px] font-bold text-slate-400 uppercase tracking-wider select-none">Termination Style</span>
                        <span class="bg-slate-100 text-slate-600 text-[9px] font-bold uppercase tracking-wider px-2.5 py-0.5 rounded-full border border-slate-200 select-none">
                          Stoichiometric (Non-polar)
                        </span>
                      </div>
                    {/if}
                  {/if}

                  <!-- Individual Scope: Customize planes list -->
                  {#if facetsForFam[0]?.scope === 'facet'}
                    <div class="space-y-3 pt-2">
                      <span class="block text-[9px] font-bold text-slate-400 uppercase tracking-wider mb-1 select-none">Customize Individual Planes</span>
                      {#each fam.hkl_list as hkl}
                        {@const pFacet = facetsForFam.find(f => f.hkl === hkl)}
                        <div class="p-3 bg-white border border-slate-100 rounded-xl space-y-2">
                          <div class="flex items-center justify-between">
                            <label class="flex items-center gap-2.5 cursor-pointer select-none font-bold text-xs text-slate-700">
                              <input type="checkbox" checked={!!pFacet} class="accent-brand-600 rounded"
                                     onchange={() => toggleIndividualPlane(fam.family, hkl)}>
                              <span class="font-mono">({hkl}) Plane</span>
                            </label>
                            {#if pFacet}
                              <span class="text-[8px] font-extrabold text-brand-600 bg-brand-50 border border-brand-100 px-2 py-0.5 rounded-full uppercase tracking-wider">Active</span>
                            {/if}
                          </div>
                          
                          {#if pFacet}
                            <div class="grid grid-cols-2 gap-3 pt-1">
                              <div>
                                <span class="block text-[8px] font-bold text-slate-400 uppercase tracking-wider mb-1">Surface Energy (γ)</span>
                                <input type="number" step="0.1" class="w-full border-none ring-1 ring-slate-200 rounded-lg px-2 py-1.5 text-xs bg-white focus:ring-2 focus:ring-brand-400 outline-none font-medium h-[28px]"
                                       bind:value={pFacet.gamma}>
                              </div>
                              
                              {#if fam.status === 'polar' || fam.status === 'termination-sensitive'}
                                <div>
                                  <span class="block text-[8px] font-bold text-slate-400 uppercase tracking-wider mb-1">Termination</span>
                                  <select class="w-full border-none ring-1 ring-slate-200 bg-white rounded-lg px-2 py-1 text-xs focus:ring-2 focus:ring-brand-400 outline-none font-medium cursor-pointer h-[28px]"
                                          bind:value={pFacet.termination}>
                                    <option value="cation_rich">Cation-Rich</option>
                                    <option value="anion_rich">Anion-Rich</option>
                                  </select>
                                </div>
                              {/if}
                            </div>
                          {/if}
                        </div>
                      {/each}
                    </div>
                  {/if}
                </div>
              {/if}
            </div>
          {/each}
        </div>
      {/if}
    </div>

    <div class="bg-white border border-slate-100 shadow-sm rounded-[1.5rem] p-6">
      <h2 class="font-heading text-lg font-bold text-slate-900 mb-4">4) Shells & Heterointerfaces</h2>
      <!-- Section 4 Tabs: Concentric vs Janus -->
      <div class="flex space-x-1 rounded-xl p-1 bg-slate-100 mb-5 border border-slate-200/50">
        <button class="flex-1 rounded-lg py-2 text-xs font-bold transition-all {activeHeteroMode === 'concentric' ? 'bg-white text-brand-600 shadow-sm' : 'text-slate-500 hover:text-slate-700 hover:bg-slate-200/50'}"
                onclick={() => activeHeteroMode = 'concentric'}>Concentric Shells</button>
        <button class="flex-1 rounded-lg py-2 text-xs font-bold transition-all {activeHeteroMode === 'janus' ? 'bg-white text-brand-600 shadow-sm' : 'text-slate-500 hover:text-slate-700 hover:bg-slate-200/50'}"
                onclick={() => { activeHeteroMode = 'janus'; shells = []; }}>Janus Heterointerface</button>
      </div>

      {#if activeHeteroMode === 'concentric'}
        {#each shells as shell, sIndex (shell.id)}
          <div class="border border-brand-200 bg-brand-50/40 p-4 rounded-[1.25rem] mb-4">
            <div class="flex justify-between items-center mb-4">
              <span class="font-bold text-brand-800 text-sm bg-brand-100 px-3 py-1 rounded-lg">Shell {sIndex + 1}</span>
              <button class="text-red-500 hover:text-red-700 text-xs font-bold transition-colors" onclick={() => shells.splice(sIndex, 1)}>Remove</button>
            </div>
            
            <span class="block text-[10px] font-extrabold text-brand-700 uppercase tracking-widest mb-2">Shell Material</span>

            {#if !shell.file}
              <div class="flex flex-wrap gap-1.5 mb-3">
                {#if shell.isLoading}
                  <span class="text-xs font-bold text-brand-500 animate-pulse flex items-center gap-2">
                    <div class="w-3 h-3 border-2 border-brand-500 border-t-transparent rounded-full animate-spin"></div> Fetching...
                  </span>
                {:else}
                  {#each allowedShellTemplates as template}
                    <button 
                      class="px-2 py-1.5 bg-white hover:bg-brand-100 text-brand-700 border border-brand-200 rounded-lg transition-colors flex flex-col items-center"
                      onclick={() => loadShellTemplate(sIndex, template)}>
                      <span class="text-xs font-bold">{template.name}</span>
                      <span class="text-[9px] font-mono opacity-80 mt-0.5">{template.a}</span>
                    </button>
                  {/each}
                {/if}
              </div>
              
              <div class="relative flex py-1 items-center mb-3">
                <div class="flex-grow border-t border-brand-200/50"></div>
                <span class="flex-shrink-0 mx-2 text-brand-400 text-[9px] font-bold uppercase tracking-widest">OR UPLOAD</span>
                <div class="flex-grow border-t border-brand-200/50"></div>
              </div>

              <input type="file" accept=".cif" class="w-full text-xs mb-4 file:mr-4 file:py-1.5 file:px-4 file:rounded-full file:border-0 file:text-xs file:font-bold file:bg-brand-100 file:text-brand-700 hover:file:bg-brand-200 transition-all text-slate-600" onchange={(e) => { shell.file = e.target.files[0]; shell.templateName = null; }}>
            {:else}
              <div class="flex items-center justify-between bg-white border border-brand-200 rounded-lg px-3 py-2 mb-4">
                <div class="flex items-center gap-2">
                  <div class="w-6 h-6 bg-brand-50 rounded-full flex items-center justify-center text-brand-500">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
                  </div>
                  <span class="text-xs font-bold text-brand-800">
                    {shell.templateName ? `${shell.templateName} (Template)` : shell.file.name}
                  </span>
                </div>
                <button class="text-[10px] text-red-500 font-bold hover:text-red-700 uppercase tracking-wide" onclick={() => { shell.file = null; shell.templateName = null; }}>Clear</button>
              </div>
            {/if}
            
            <span class="block text-[10px] font-extrabold text-brand-700 uppercase tracking-widest mb-2">Shell Thickness (Unit Cells)</span>
            <div class="grid grid-cols-3 gap-2 mb-4">
              <input type="number" bind:value={shell.size_unit_cells[0]} step="0.25" min="0.25" class="border-none ring-1 ring-brand-200 rounded-lg px-2 py-1.5 text-xs text-center bg-white focus:ring-2 focus:ring-brand-400 outline-none font-medium min-w-0">
              <input type="number" bind:value={shell.size_unit_cells[1]} step="0.25" min="0.25" class="border-none ring-1 ring-brand-200 rounded-lg px-2 py-1.5 text-xs text-center bg-white focus:ring-2 focus:ring-brand-400 outline-none font-medium min-w-0">
              <input type="number" bind:value={shell.size_unit_cells[2]} step="0.25" min="0.25" class="border-none ring-1 ring-brand-200 rounded-lg px-2 py-1.5 text-xs text-center bg-white focus:ring-2 focus:ring-brand-400 outline-none font-medium min-w-0">
            </div>

            <!-- Interface Type Selection (Abrupt / Mixed) -->
            <span class="block text-[10px] font-extrabold text-brand-700 uppercase tracking-widest mb-2">Interface Type</span>
            <div class="flex gap-2 mb-4 bg-slate-100/80 p-1 rounded-xl border border-slate-200">
              <button 
                class="flex-grow rounded-lg py-1.5 text-xs font-bold transition-all {(!shell.interface_type || shell.interface_type === 'abrupt') ? 'bg-white text-brand-700 shadow-sm' : 'text-slate-600 hover:text-slate-900'}"
                onclick={(e) => { e.preventDefault(); shell.interface_type = 'abrupt'; }}>
                Abrupt
              </button>
              <button 
                class="flex-grow rounded-lg py-1.5 text-xs font-bold transition-all {shell.interface_type === 'mixed' ? 'bg-white text-brand-700 shadow-sm' : 'text-slate-600 hover:text-slate-900'}"
                onclick={(e) => { e.preventDefault(); shell.interface_type = 'mixed'; }}>
                Mixed
              </button>
            </div>

            {#if shell.interface_type === 'mixed'}
              <!-- Mixing Ratio & Width Sliders -->
              <div class="space-y-3 mb-4 p-3 bg-white border border-brand-200 rounded-xl">
                <div class="flex justify-between items-center text-xs">
                  <span class="font-bold text-slate-700">Mixing Ratio</span>
                  <span class="font-mono bg-brand-50 text-brand-700 px-2 py-0.5 rounded font-bold">{(shell.interface_mixing_ratio !== undefined ? shell.interface_mixing_ratio : 0.5)}</span>
                </div>
                <input 
                  type="range" 
                  min="0.05" 
                  max="0.95" 
                  step="0.05" 
                  bind:value={shell.interface_mixing_ratio}
                  class="w-full accent-brand-600 h-1 bg-slate-100 rounded-lg appearance-none cursor-pointer"
                />
                
                <div class="flex justify-between items-center text-xs pt-1">
                  <span class="font-bold text-slate-700">Mixing Width</span>
                  <span class="font-mono bg-brand-50 text-brand-700 px-2 py-0.5 rounded font-bold">{(shell.interface_mixing_width !== undefined ? shell.interface_mixing_width : 3.0)} Å</span>
                </div>
                <input 
                  type="range" 
                  min="1.0" 
                  max="10.0" 
                  step="0.5" 
                  bind:value={shell.interface_mixing_width}
                  class="w-full accent-brand-600 h-1 bg-slate-100 rounded-lg appearance-none cursor-pointer"
                />
              </div>
            {/if}
            
            <span class="block text-[10px] font-extrabold text-brand-700 uppercase tracking-widest mb-2">Facets</span>
            {#each shell.facets as sfacet, fi (sfacet.id)}
              <div class="grid grid-cols-[1fr_1fr_32px] gap-2 mb-2">
                <input type="text" bind:value={sfacet.hkl} class="border-none ring-1 ring-brand-200 rounded-lg px-2 py-1.5 text-xs text-center bg-white focus:ring-2 focus:ring-brand-400 outline-none font-medium min-w-0">
                <input type="number" bind:value={sfacet.gamma} step="0.1" class="border-none ring-1 ring-brand-200 rounded-lg px-2 py-1.5 text-xs text-center bg-white focus:ring-2 focus:ring-brand-400 outline-none font-medium min-w-0">
                <button class="bg-red-100 text-red-600 hover:bg-red-200 rounded-lg flex items-center justify-center text-xs font-bold transition-colors" onclick={() => shell.facets.splice(fi, 1)}>✕</button>
              </div>
            {/each}
            <button class="w-full bg-white hover:bg-brand-50 border border-brand-200 text-brand-700 text-xs py-2 mt-2 rounded-lg font-bold transition-colors" onclick={() => shell.facets.push({ id: crypto.randomUUID(), hkl: '100', gamma: 1.0 })}>+ Add Shell Facet</button>
          </div>
        {/each}
        <button class="w-full bg-slate-50 hover:bg-slate-100 border border-slate-200 text-brand-600 py-2.5 rounded-xl text-sm font-bold transition-colors" onclick={addShell}>+ Add Concentric Shell</button>
      
      {:else}
        <!-- Janus Panel -->
        <div class="border border-brand-200 bg-brand-50/20 p-5 rounded-2xl space-y-4">
          <div>
            <span class="block text-[10px] font-extrabold text-brand-700 uppercase tracking-widest mb-2 flex items-center gap-1">
              Janus Partner Material
              <div class="group relative cursor-pointer text-slate-400 hover:text-slate-600 font-normal">
                <span class="text-[10px] bg-slate-100 w-3.5 h-3.5 rounded-full flex items-center justify-center font-bold font-mono">i</span>
                <div class="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 hidden group-hover:block w-48 bg-slate-900 text-white text-[10px] p-2 rounded-lg shadow-xl font-sans normal-case tracking-normal z-20 text-center">
                  Select the bulk material for the second half of the Janus heterointerface. Flat shared-interface lattice matching operates across differing spacegroup structures!
                </div>
              </div>
            </span>
            {#if !janusPartnerFile}
              <select class="w-full border-none ring-1 ring-brand-200 rounded-lg px-2 py-2 text-xs bg-white focus:ring-2 focus:ring-brand-400 outline-none font-medium cursor-pointer"
                      onchange={async (e) => {
                        const name = e.target.value;
                        if (!name) return;
                        // load standard bulk templates as custom file upload
                        for (const family in bulkTemplates) {
                          const t = bulkTemplates[family].find(item => item.name === name);
                          if (t) {
                            logs += `[status] Fetching Janus partner bulk structure ${t.name}...\n`;
                            const res = await fetch(t.path);
                            const text = await res.text();
                            const blob = new Blob([text], { type: 'text/plain' });
                            janusPartnerFile = new File([blob], t.path.split('/').pop(), { type: 'text/plain' });
                            break;
                          }
                        }
                      }}>
                <option value="">-- Choose Preset Partner Material --</option>
                {#each Object.keys(bulkTemplates) as family}
                  <optgroup label={family}>
                    {#each bulkTemplates[family] as template}
                      <option value={template.name}>{template.name} ({template.phase})</option>
                    {/each}
                  </optgroup>
                {/each}
              </select>
            {:else}
              <div class="flex items-center justify-between bg-white border border-brand-200 rounded-lg px-3 py-2">
                <span class="text-xs font-bold text-brand-800">{janusPartnerFile.name} (Loaded)</span>
                <button class="text-[10px] text-red-500 font-bold hover:text-red-700 uppercase tracking-wide" onclick={() => janusPartnerFile = null}>Clear</button>
              </div>
            {/if}
          </div>

          <div class="grid grid-cols-2 gap-3">
            <div>
              <span class="block text-[10px] font-extrabold text-brand-700 uppercase tracking-widest mb-2">Build Mode</span>
              <select class="w-full border-none ring-1 ring-brand-200 rounded-lg px-2 py-1.5 text-xs bg-white focus:ring-2 focus:ring-brand-400 outline-none font-medium cursor-pointer" bind:value={janusBuildMode}>
                <option value="wulff_janus">Wulff-Janus (Faceted)</option>
                <option value="interface_cell">Interface Cell (Slab)</option>
              </select>
            </div>
            <div>
              <span class="block text-[10px] font-extrabold text-brand-700 uppercase tracking-widest mb-2">Interface cut (hkl)</span>
              <input type="text" class="w-full border-none ring-1 ring-brand-200 rounded-lg px-2 py-1.5 text-xs bg-white focus:ring-2 focus:ring-brand-400 outline-none font-medium text-center" bind:value={janusInterfaceHkl}>
            </div>
          </div>

          <div>
            <span class="block text-[10px] font-extrabold text-brand-700 uppercase tracking-widest mb-2">Clipping Footprint</span>
            <div class="flex gap-4 text-xs bg-white p-2.5 rounded-lg border border-brand-100">
              <label class="flex items-center gap-1.5 cursor-pointer font-medium text-slate-700">
                <input type="radio" value="mushroom" class="accent-brand-600" checked={janusClippingMode === 'mushroom'} onchange={() => janusClippingMode = 'mushroom'}>
                Mushroom cap overhang
              </label>
              <label class="flex items-center gap-1.5 cursor-pointer font-medium text-slate-700">
                <input type="radio" value="footprint" class="accent-brand-600" checked={janusClippingMode === 'footprint'} onchange={() => janusClippingMode = 'footprint'}>
                Strict aligned footprint
              </label>
            </div>
          </div>
        </div>
      {/if}
    </div>

    <!-- Build settings (before first build) -->
    <div class="bg-white border border-slate-100 shadow-sm rounded-[1.5rem] p-5 space-y-4">
      <h2 class="font-heading text-lg font-bold text-slate-900 mb-1">Build settings</h2>

      <!-- Construction Center Ion -->
      {#if detectedSpecies.length > 0}
      <div>
        <span class="block text-[10px] font-extrabold text-slate-500 uppercase tracking-widest mb-2 flex items-center gap-1.5">
          Center structure on
          <span class="text-[10px] bg-slate-100 hover:bg-slate-200 text-slate-400 hover:text-slate-600 w-3.5 h-3.5 rounded-full flex items-center justify-center font-bold font-mono cursor-help select-none shrink-0"
                onmouseenter={() => tooltipText = "The atom on which the NC is centered during the Wulff construction. Each ion gives a differently terminated surface. Auto tries the native centers and keeps the realizable output."}
                onmouseleave={() => tooltipText = ""}>
            i
          </span>
        </span>
        <div class="flex flex-wrap gap-2">
          <button type="button"
            class="px-3 py-1 rounded-lg text-xs font-bold border transition-all {centerIon === '' ? 'bg-brand-600 text-white border-brand-600 shadow-sm' : 'bg-slate-50 text-slate-600 border-slate-200 hover:border-brand-400'}"
            onclick={() => centerIon = ''}>
            Auto
          </button>
          {#each detectedSpecies as ion}
            <button type="button"
              class="px-3 py-1 rounded-lg text-xs font-bold border transition-all {centerIon === ion ? 'bg-brand-600 text-white border-brand-600 shadow-sm' : 'bg-slate-50 text-slate-600 border-slate-200 hover:border-brand-400'}"
              onclick={() => centerIon = ion}>
              {ion}
            </button>
          {/each}
        </div>
      </div>
      {/if}

      <!-- Excess Surface Charge -->
      <div>
        <span class="block text-[10px] font-extrabold text-slate-500 uppercase tracking-widest mb-2 flex items-center gap-1.5">
          Excess Surface Charge
          <span class="text-[10px] bg-slate-100 hover:bg-slate-200 text-slate-400 hover:text-slate-600 w-3.5 h-3.5 rounded-full flex items-center justify-center font-bold font-mono cursor-help select-none shrink-0"
                onmouseenter={() => tooltipText = "Lattice cuts leave excess surface cations. 'Remove' trims undercoordinated cations (slightly smaller NC). 'Add' passivates them with placeholder Cl⁻ anions."}
                onmouseleave={() => tooltipText = ""}>
            i
          </span>
        </span>
        <div class="flex rounded-lg p-0.5 bg-slate-100 border border-slate-200/50 h-[32px] items-center w-full">
          <button type="button" class="flex-1 h-full rounded-md text-[10px] font-bold transition-all {posQ === 'remove' ? 'bg-white text-brand-600 shadow-sm' : 'text-slate-500 hover:text-slate-700'}"
                  onclick={() => posQ = 'remove'}>
            Remove
          </button>
          <button type="button" class="flex-1 h-full rounded-md text-[10px] font-bold transition-all {posQ === 'add' ? 'bg-white text-brand-600 shadow-sm' : 'text-slate-500 hover:text-slate-700'}"
                  onclick={() => posQ = 'add'}>
            Add
          </button>
        </div>
      </div>

      <!-- Run Mode + Buttons -->
      <div class="flex items-center gap-3">
        <span class="block text-[10px] font-extrabold text-slate-500 uppercase tracking-widest flex items-center gap-1 cursor-help select-none"
              onmouseenter={() => tooltipText = "Turbo skips verbose surface analysis (~2–5× faster). Live logs streams each step to the log panel."}
              onmouseleave={() => tooltipText = ""}>
          Run Mode ⓘ
        </span>
        <div class="flex gap-3 ml-auto">
          <label class="flex items-center gap-1.5 cursor-pointer text-xs font-medium text-slate-700"><input type="radio" bind:group={runMode} value="quiet" class="accent-brand-600"> Turbo</label>
          <label class="flex items-center gap-1.5 cursor-pointer text-xs font-medium text-slate-700"><input type="radio" bind:group={runMode} value="live-tty" class="accent-brand-600"> Live logs</label>
        </div>
      </div>
      <div class="flex gap-3">
        <button class="flex-1 bg-brand-600 hover:bg-brand-700 text-white font-bold py-3 rounded-xl shadow-glow transition-all active:scale-95 flex items-center justify-center gap-2"
                onclick={() => onBuild(false)} disabled={isBuilding}>
          {isBuilding ? 'Building...' : '🔨 Build Nanocrystal'}
        </button>
        <button class="bg-slate-100 hover:bg-slate-200 text-slate-700 font-bold py-3 px-6 rounded-xl transition-all" onclick={onReset}>Reset</button>
      </div>
      {#if finalResult}
        <button class="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-2.5 rounded-xl shadow-sm transition-all active:scale-95 text-sm" onclick={downloadXYZ}>
          ⬇ Download {finalResult.download_name || 'final.xyz'}
        </button>
      {/if}
    </div>
    {/if}

  </aside>
     
  <main class="flex-grow h-full flex flex-col p-6 gap-6 bg-slate-50 overflow-y-auto">
    
    <div class="flex flex-col gap-6 flex-shrink-0 h-[calc(100vh-112px)] min-h-[700px]">
      
      <div class="relative flex-1 min-h-[400px] bg-white rounded-[1.5rem] p-4 border border-slate-100 shadow-sm flex flex-col">
        <div class="flex justify-between items-center mb-3 px-2">
          <h2 class="font-heading font-bold text-xl text-slate-900">Live Render</h2>
          
          <div class="flex gap-1 bg-slate-100 p-1 rounded-xl border border-slate-200">
            <button class="px-3 py-1.5 rounded-lg text-xs font-bold transition-all {activeViewer === '3dmol' ? 'bg-brand-600 text-white shadow-sm' : 'text-slate-600 hover:text-slate-950'}"
                    onclick={() => activeViewer = '3dmol'}>
              3Dmol
            </button>
            <button class="px-3 py-1.5 rounded-lg text-xs font-bold transition-all {activeViewer === 'ngl' ? 'bg-brand-600 text-white shadow-sm' : 'text-slate-600 hover:text-slate-950'}"
                    onclick={() => activeViewer = 'ngl'}>
              NGL
            </button>
            <button class="px-3 py-1.5 rounded-lg text-xs font-bold transition-all {activeViewer === 'molstar' ? 'bg-brand-600 text-white shadow-sm' : 'text-slate-600 hover:text-slate-950'}"
                    onclick={() => activeViewer = 'molstar'}>
              Mol*
            </button>
            <button class="px-3 py-1.5 rounded-lg text-xs font-bold transition-all {activeViewer === 'matterviz' ? 'bg-brand-600 text-white shadow-sm' : 'text-slate-600 hover:text-slate-950'}"
                    onclick={() => activeViewer = 'matterviz'}>
              MatterViz
            </button>
          </div>
        </div>
        <div class="flex-1 bg-slate-50 rounded-[1rem] border border-slate-200 overflow-hidden relative shadow-inner">
          <Viewer 
            xyz={xyzData} 
            sizeMetrics={finalResult?.size_metrics} 
            activeViewer={activeViewer}
          />
          {#if isBuilding}
            <div class="absolute inset-0 bg-slate-900/60 backdrop-blur-sm flex flex-col items-center justify-center text-white z-10">
              <div class="w-12 h-12 border-4 border-brand-500 border-t-transparent rounded-full animate-spin mb-4"></div>
              <p class="font-bold text-lg tracking-wide">Processing Architecture...</p>
            </div>
          {/if}
        </div>
      </div>
      
      <div class="h-1/3 grid grid-cols-1 md:grid-cols-4 gap-6 min-h-[280px]">
        
        <div class="bg-white border border-slate-100 shadow-sm rounded-[1.5rem] p-6 md:col-span-1 overflow-y-auto h-full">
          <h2 class="font-heading text-lg font-bold text-slate-900 mb-4 border-b border-slate-100 pb-2">Stoichiometry</h2>

          {#if Object.keys(calculatedStoich).length > 0}
            
            <h3 class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3">Total Stoichiometry</h3>
            <div class="flex flex-wrap gap-2 mb-6">
              {#each Object.entries(calculatedStoich) as [elem, count]}
                <span class="bg-brand-50 text-brand-800 border border-brand-100 px-3 py-1.5 rounded-xl font-bold text-sm">
                  {elem}: {count}
                </span>
              {/each}
            </div>

            <h3 class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3">Elemental Ratios</h3>
            <div class="flex flex-wrap gap-2 mb-6">
              {#each Object.entries(calculatedRatios) as [ratio, val]}
                <span class="bg-accent-50 text-accent-800 border border-accent-100 px-2.5 py-1 rounded-lg font-mono text-xs font-bold">
                  <span class="text-accent-600">{ratio}</span>: {val}
                </span>
              {/each}
            </div>

            <h3 class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3">Charge Balance</h3>
            <div class="mb-6">
              <div class="flex items-center justify-between px-3 py-2.5 rounded-lg border {calculatedCharge === 0 ? 'bg-emerald-50 border-emerald-200 text-emerald-800' : 'bg-red-50 border-red-200 text-red-800'} font-bold text-xs shadow-sm w-full">
                <span>Total Charge:</span>
                <span class="text-sm">{calculatedCharge > 0 ? '+' : ''}{calculatedCharge} e</span>
              </div>
              {#if calculatedCharge !== 0}
                <p class="text-[10px] text-red-600 mt-1.5 font-bold flex items-center gap-1">
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                  Structure is not charge-neutral.
                </p>
              {/if}
            </div>

          {/if}

          {#if finalResult?.grouped_counts}
            <h3 class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3 border-t border-slate-100 pt-4">System Breakdown</h3>
            <div class="text-sm">
              <p class="font-extrabold text-slate-900 text-base mb-3">Total Atoms: {finalResult.grouped_counts.total_atoms}</p>
              
              <p class="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">Core ({finalResult.grouped_counts.core.total})</p>
              <div class="flex flex-wrap gap-2 mb-4">
                {#each Object.entries(finalResult.grouped_counts.core.by_element || {}) as [el, count]}
                  <span class="bg-indigo-50 text-indigo-800 border border-indigo-200 px-2 py-0.5 rounded font-medium text-xs">{el}: {count}</span>
                {/each}
              </div>

              {#if finalResult.ligand_detail && finalResult.ligand_detail.total > 0}
                <p class="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">Ligands ({finalResult.ligand_detail.total})</p>
                {#each Object.entries(finalResult.ligand_detail.anionic || {}) as [smiles, count]}
                  {#if count > 0}<div class="flex justify-between text-xs font-mono bg-slate-50 border border-slate-100 p-2 rounded-lg mb-1.5"><span class="truncate pr-2 text-slate-600">{smiles}</span><span class="font-bold text-slate-900">{count}</span></div>{/if}
                {/each}
                {#each Object.entries(finalResult.ligand_detail.cationic || {}) as [smiles, count]}
                  {#if count > 0}<div class="flex justify-between text-xs font-mono bg-slate-50 border border-slate-100 p-2 rounded-lg mb-1.5"><span class="truncate pr-2 text-slate-600">{smiles}</span><span class="font-bold text-slate-900">{count}</span></div>{/if}
                {/each}
                {#each Object.entries(finalResult.ligand_detail.neutral || {}) as [smiles, count]}
                  {#if count > 0}<div class="flex justify-between text-xs font-mono bg-slate-50 border border-slate-100 p-2 rounded-lg mb-1.5"><span class="truncate pr-2 text-slate-600">{smiles} (neutral)</span><span class="font-bold text-slate-900">{count}</span></div>{/if}
                {/each}
              {:else if finalResult.grouped_counts.shell?.total > 0}
                 <p class="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">Shell ({finalResult.grouped_counts.shell.total})</p>
                 <div class="flex flex-wrap gap-2 mb-4">
                   {#each Object.entries(finalResult.grouped_counts.shell.by_element || {}) as [el, count]}
                     <span class="bg-blue-50 text-blue-800 border border-blue-200 px-2 py-0.5 rounded font-medium text-xs">{el}: {count}</span>
                   {/each}
                 </div>
              {/if}
            </div>
          {:else if !xyzData}
            <div class="h-32 flex items-center justify-center">
              <p class="text-sm text-slate-400 italic">No structure built yet.</p>
            </div>
          {/if}
        </div>

        <div class="bg-slate-900 border border-slate-800 rounded-[1.5rem] p-0 md:col-span-3 flex flex-col overflow-hidden shadow-inner relative h-full">
          <div class="bg-slate-800/80 backdrop-blur-sm text-slate-400 text-[10px] px-4 py-2 font-mono font-bold uppercase tracking-widest border-b border-slate-700/50 flex justify-between items-center absolute w-full top-0 left-0 z-10">
            <span class="flex items-center gap-2"><div class="w-2 h-2 rounded-full bg-emerald-500"></div> nc-builder Passivation Engine Terminal</span>
            {#if isBuilding}<span class="text-brand-400 animate-pulse">Running process...</span>{/if}
          </div>
          <pre bind:this={logContainer} class="text-xs text-emerald-400 font-mono p-5 pt-12 h-full overflow-y-auto whitespace-pre-wrap leading-relaxed selection:bg-emerald-900 selection:text-emerald-100">{logs}</pre>
        </div>

      </div>
    </div>
  </main>
</div>
