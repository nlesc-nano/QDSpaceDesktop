<script>
  import { onMount } from "svelte";
  import Viewer from "./Viewer.svelte";

  // --- Common Oxidation States ---
  const OXIDATION_STATES = {
    Cd: 2,
    Zn: 2,
    Pb: 2,
    Hg: 2,
    Mg: 2,
    Ca: 2,
    Sr: 2,
    Ba: 2,
    In: 3,
    Ga: 3,
    Al: 3,
    Bi: 3,
    Cs: 1,
    Rb: 1,
    K: 1,
    Na: 1,
    Li: 1,
    Ag: 1,
    Cu: 1,
    Au: 1,
    S: -2,
    Se: -2,
    Te: -2,
    O: -2,
    P: -3,
    As: -3,
    N: -3,
    Sb: -3,
    F: -1,
    Cl: -1,
    Br: -1,
    I: -1,
  };

  // --- State Variables ---
  let metadata = $state({});
  let fileList = $state([]);
  let activeViewer = $state("molstar");

  // Filter selections
  let filters = $state({
    system: "",
    material: "",
    size: "",
    functional: "",
    runtype: "",
  });

  // UI States
  let showMatches = $state(false);

  // Current active molecule
  let currentFile = $state("");

  let originalXyzData = $state("");
  let currentXyzData = $state("");
  let currentFileUrl = $state("");
  let propertiesStatus = $state("idle");
  let activePropertyTab = $state("fuzzy_sf");
  let plotUrls = $state({ fuzzy_sf: null, fuzzy_soc: null, exciton_sf: null, exciton_soc: null });

  // MD Trajectory detection
  let isMD = $derived(currentMeta?.run_type === "Molecular Dynamics");

  // Ligand Passivation State
  let capDist = $state("random");
  let anionicLigands = $state([
    { id: crypto.randomUUID(), smiles: "CCC(=O)O", ratio: 1.0, dummy: "Cl" },
  ]);
  let showCationic = $state(false);
  let cationicLigands = $state([]);
  let isAttaching = $state(false);
  let attachError = $state("");

  // Terminal State
  let logs = $state(
    "[status] Library Ready. Awaiting structure selection...\n",
  );
  let logContainer;

  // Reactive metadata
  let currentMeta = $derived(currentFile ? metadata[currentFile] : null);

  // --- DYNAMIC STOICHIOMETRY & RATIOS PARSER ---
  let calculatedStoich = $derived.by(() => {
    if (!currentXyzData) return {};
    
    // Find the end of the first line to get atom count
    const firstNewline = currentXyzData.indexOf("\n");
    if (firstNewline === -1) return {};
    
    const nAtoms = parseInt(currentXyzData.slice(0, firstNewline).trim());
    if (isNaN(nAtoms)) return {};

    // Extract ONLY the text corresponding to the first frame (nAtoms + 2 lines)
    // Assuming a max of 100 characters per line as a generous safe buffer
    const firstFrameText = currentXyzData.slice(0, (nAtoms + 2) * 100);
    const lines = firstFrameText.trim().split("\n");

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
  
  // Calculate Charge (Excluding organics to prevent math errors)
  let calculatedCharge = $derived.by(() => {
    let charge = 0;
    const qdCoreElements = [
      "Cd",
      "Zn",
      "Pb",
      "Hg",
      "In",
      "Ga",
      "Al",
      "S",
      "Se",
      "Te",
      "P",
      "As",
      "Sb",
      "Ag",
      "Cu",
      "Au",
      "Cs",
      "Rb",
      "K",
      "Na",
    ];

    for (const [el, count] of Object.entries(calculatedStoich)) {
      if (qdCoreElements.includes(el) || ["Cl", "Br", "I", "F"].includes(el)) {
        charge += (OXIDATION_STATES[el] || 0) * count;
      }
    }

    if (currentMeta?.anionic_count) charge -= currentMeta.anionic_count;
    if (currentMeta?.cationic_count) charge += currentMeta.cationic_count;

    return charge;
  });

  // Compute all combinations of elemental ratios dynamically
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

  // --- Load Database ---
  onMount(async () => {
    try {
      const [metaRes, filesRes] = await Promise.all([
        fetch("/metadata.json"),
        fetch("/file_list.json"),
      ]);
      metadata = await metaRes.json();
      fileList = await filesRes.json();
    } catch (err) {
      console.error("Failed to load QD database:", err);
      logs += `[error] Failed to load QD database: ${err.message}\n`;
    }
  });

  // --- Terminal Auto-Scroll ---
  $effect(() => {
    if (logs && logContainer) {
      logContainer.scrollTop = logContainer.scrollHeight;
    }
  });

  // --- Reactive Filters ---
  let filteredFiles = $derived(
    fileList.filter((file) => {
      const meta = metadata[file];
      if (!meta) return false;
      if (filters.system && meta.system_type !== filters.system) return false;
      if (filters.material && meta.material !== filters.material) return false;
      if (filters.size && String(meta.size) !== filters.size) return false;
      if (filters.functional && meta.functional !== filters.functional)
        return false;
      if (filters.runtype && meta.run_type !== filters.runtype) return false;
      return true;
    }),
  );

  let availableSystems = $derived(
    [...new Set(Object.values(metadata).map((m) => m.system_type))].filter(
      Boolean,
    ),
  );
  let availableMaterials = $derived(
    [
      ...new Set(
        Object.values(metadata)
          .filter((m) => !filters.system || m.system_type === filters.system)
          .map((m) => m.material),
      ),
    ].filter(Boolean),
  );
  let availableSizes = $derived(
    [
      ...new Set(
        Object.values(metadata)
          .filter(
            (m) =>
              (!filters.system || m.system_type === filters.system) &&
              (!filters.material || m.material === filters.material),
          )
          .map((m) => String(m.size)),
      ),
    ].filter(Boolean),
  );
  let availableFunctionals = $derived(
    [
      ...new Set(
        Object.values(metadata)
          .filter(
            (m) =>
              (!filters.system || m.system_type === filters.system) &&
              (!filters.material || m.material === filters.material),
          )
          .map((m) => m.functional),
      ),
    ].filter(Boolean),
  );
  let availableRuntypes = $derived(
    [
      ...new Set(
        Object.values(metadata)
          .filter(
            (m) =>
              (!filters.system || m.system_type === filters.system) &&
              (!filters.material || m.material === filters.material),
          )
          .map((m) => m.run_type),
      ),
    ].filter(Boolean),
  );

  // ==========================================
  // FIX: Isolated User Action (No more infinite loops!)
  // ==========================================
  let previousBlobUrl = null;

  async function selectFile(file) {
    currentFile = file;
    attachError = "";
    let filename = file.split("/").pop();
    
    // Diagnostic timer
    const startTime = performance.now();
    const getTime = () => `[${(performance.now() - startTime).toFixed(0)}ms]`;

    logs += `\n[cmd] Loading structure: ${filename}...\n`;
    
    // Clean up previous blob URL to prevent memory leaks
    if (previousBlobUrl) {
      URL.revokeObjectURL(previousBlobUrl);
      previousBlobUrl = null;
    }

    // Yield to the browser to paint the UI logs before heavy lifting
    await new Promise(resolve => setTimeout(resolve, 30));

    const meta = metadata[file];

    if (meta?.run_type === "Molecular Dynamics") {
      logs += `[status] ${getTime()} MD Trajectory detected.\n`;
      
      // CRITICAL: Disable stoichiometry calculations for MDs to save memory
      originalXyzData = "";
      currentXyzData = "";
      try {
        logs += `[status] ${getTime()} Downloading and optimizing trajectory...\n`;
        const res = await fetch(`/${file}`);
        
        // Normalize line endings to prevent frame misalignments
        const text = (await res.text()).replace(/\r\n/g, '\n');
        
        await new Promise(r => setTimeout(r, 20)); // Yield to paint log
        
        const lines = text.split('\n');
        const nAtoms = parseInt(lines[0].trim());
        
        if (!isNaN(nAtoms) && nAtoms > 0) {
          const linesPerFrame = nAtoms + 2;
          const totalFrames = Math.floor(lines.length / linesPerFrame);
          
          // Target ~150 frames for perfectly smooth 60fps WebGL playback
          const TARGET_FRAMES = 150; 
          const stride = Math.max(1, Math.floor(totalFrames / TARGET_FRAMES));
          
          logs += `[status] ${getTime()} Downsampling ${totalFrames} frames to ${Math.floor(totalFrames/stride)}...\n`;
          await new Promise(r => setTimeout(r, 20)); // Yield to paint log
          
          // Fast-slice the optimized text
          let optimizedLines =[];
          for(let i = 0; i < totalFrames; i += stride) {
            const startIdx = i * linesPerFrame;
            const endIdx = startIdx + linesPerFrame;
            
            // Ensure we only grab complete frames
            if (endIdx <= lines.length) {
              optimizedLines.push(lines.slice(startIdx, endIdx).join('\n'));
            }
          }
          
          // Ensure file ends with a clean newline
          const optimizedText = optimizedLines.join('\n') + '\n';
          const blob = new Blob([optimizedText], { type: 'text/plain' });
          
          const baseBlobUrl = URL.createObjectURL(blob);
          
          // THE FIX: Append #trajectory.xyz so Matterviz recognizes the format
          currentFileUrl = baseBlobUrl + "#trajectory.xyz"; 
          previousBlobUrl = baseBlobUrl;
          
          logs += `[status] ${getTime()} Passing lightweight Blob URL to Matterviz Viewer...\n`;
        } else {
           currentFileUrl = `/${file}`;
        }
      } catch (err) {
        logs += `[error] ${getTime()} Optimization failed: ${err.message}\n`;
        currentFileUrl = `/${file}`;
      } 
      
    } else {
      // Normal single structures
      logs += `[status] ${getTime()} Fetching single structure...\n`;
      try {
        const res = await fetch(`/${file}`);
        const text = await res.text();
        originalXyzData = text;
        currentXyzData = text;
        currentFileUrl = `/${file}`;
        logs += `[status] ${getTime()} Loaded successfully.\n`;
      } catch(e) {
        logs += `[error] Fetch failed: ${e.message}\n`;
      }
    }

    // Properties plot fetch
    const parts = file.split("/");
    if (parts.length >= 4) {
      const basePath = parts.slice(0, 4).join("/");
      const dir = `/${basePath}/properties`;
      
      propertiesStatus = "loading";
      plotUrls = { fuzzy_sf: null, fuzzy_soc: null, exciton_sf: null, exciton_soc: null };
      activePropertyTab = "fuzzy"; // Reset to default

      // The installed app has no library plots. A missing file still returns the
      // app's own home page with status 200, so the frame must reject that page.
      async function existingPlot(url) {
        try {
          const response = await fetch(url, { cache: "no-store" });
          if (!response.ok) return null;
          const bytes = new Uint8Array(await response.arrayBuffer());
          if (url.endsWith(".gz")) {
            const gzip = bytes.length >= 2 && bytes[0] === 0x1f && bytes[1] === 0x8b;
            return gzip ? url : null;
          }
          const head = new TextDecoder().decode(bytes.slice(0, 8192));
          if (
            head.includes("<title>Quantum Dot Suite</title>") ||
            head.includes("Accelerating Quantum") ||
            head.includes("Quantum Dot Space")
          ) return null;
          return url;
        } catch {
          return null;
        }
      }

      Promise.all([
        existingPlot(`${dir}/fuzzy_dashboard_sf.html`),
        existingPlot(`${dir}/plot.html`),
        existingPlot(`${dir}/plot.html.gz`),
        existingPlot(`${dir}/fuzzy_dashboard_soc.html`),
        existingPlot(`${dir}/exciton_analysis_sf.html`),
        existingPlot(`${dir}/exciton_analysis_soc.html`)
      ]).then(([fuzzy_sf, oldPlot, oldPlotGz, fuzzy_soc, exSf, exSoc]) => { 
        
        // Priority: fuzzy_sf > plot.html > plot.html.gz
        plotUrls.fuzzy_sf = fuzzy_sf || oldPlot || oldPlotGz;
        plotUrls.fuzzy_soc = fuzzy_soc; 
        plotUrls.exciton_sf = exSf;
        plotUrls.exciton_soc = exSoc;

        if (plotUrls.fuzzy_sf || plotUrls.fuzzy_soc || plotUrls.exciton_sf || plotUrls.exciton_soc) {
          propertiesStatus = "ready";
          
          // Auto-select the first genuinely available tab
          if (plotUrls.fuzzy_sf) {
            activePropertyTab = "fuzzy_sf";
          } else if (plotUrls.fuzzy_soc) {
            activePropertyTab = "fuzzy_soc";
          } else if (plotUrls.exciton_sf) {
            activePropertyTab = "exciton_sf";
          } else if (plotUrls.exciton_soc) {
            activePropertyTab = "exciton_soc";
          }
          
        } else {
          propertiesStatus = "error";
        }

      });

    } else {
      propertiesStatus = "error";
    }

  }
  // --- Ligand Passivation API Call ---
  // --- Ligand Passivation API Call ---
  async function handlePassivate() {
    if (!originalXyzData) return;

    const jobs = [];

    // 1. Process Anionic Ligands from the UI array
    for (const lig of anionicLigands) {
      if (!lig.smiles.trim()) continue;
      jobs.push({
        ligands: lig.smiles.split(",").map((s) => s.trim()),
        dummy: lig.dummy ? lig.dummy.trim() : "Cl",
        dist: `${lig.ratio || 1.0}:${capDist}`, // Uses the global capDist radio button
      });
    }

    // 2. Process Cationic Ligands from the UI array
    for (const lig of cationicLigands) {
      if (!lig.smiles.trim()) continue;
      jobs.push({
        ligands: lig.smiles.split(",").map((s) => s.trim()),
        dummy: lig.dummy ? lig.dummy.trim() : "Rb",
        dist: `${lig.ratio || 1.0}:${capDist}`,
      });
    }

    if (jobs.length === 0) {
      logs += `\n[Client]: No ligands provided.\n`;
      return;
    }

    isAttaching = true;
    logs += `\n[Client]: Sending passivation request to miniCAT engine...`;

    const payload = {
      xyztext: originalXyzData,
      out_prefix: "svelte_passivated",
      jobs: jobs,
    };

    try {
      const response = await fetch(
        `${import.meta.env.VITE_API_BASE_URL || ""}/api/attach`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(payload),
        }
      );

      if (!response.ok) {
        throw new Error(`Server error: ${response.status}`);
      }

      // --- STREAMING LOGIC ---
      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        // Decode the incoming byte chunk
        buffer += decoder.decode(value, { stream: true });
        
        // Split by newline to parse NDJSON properly
        const lines = buffer.split("\n");
        buffer = lines.pop(); // Keep the last incomplete line in the buffer

        for (const line of lines) {
          if (!line.trim()) continue;
          
          try {
            const data = JSON.parse(line);
            
            if (data.event === "status") {
              logs += `\n[Server]: ${data.line}`;
            } else if (data.event === "log") {
              logs += `\n${data.line}`;
            } else if (data.event === "result") {
              if (data.status === "failed" || data.error) {
                throw new Error(data.error || "Unknown passivation error");
              }
              // Handle Success
              logs += `\n[Server]: ${data.message || "Passivation complete."}`;
              if (data.results && data.results.length > 0) {
                // Svelte 5 will automatically trigger the calculatedCharge derived rune when this updates!
                currentXyzData = data.results[0].xyz;
              }
            }
          } catch (e) {
            console.warn("Could not parse stream line:", line, e);
          }
        }
      }

      // Flush anything left in the buffer
      if (buffer.trim()) {
        try {
          const data = JSON.parse(buffer);
          if (data.event === "log") logs += `\n${data.line}`;
        } catch (e) {}
      }

    } catch (error) {
      console.error("Passivation error:", error);
      logs += `\n[Error]: ${error.message}`;
    } finally {
      isAttaching = false;
      logs += `\n[Client]: Ready.\n`;
    }
  }


  function downloadXYZ() {
    // If it's a massive MD file, download directly via URL to avoid memory crashes
    if (isMD && currentFileUrl) {
      const a = document.createElement("a");
      a.href = currentFileUrl;
      a.download = currentFile.split("/").pop() || "trajectory.xyz";
      a.click();
      logs += `[status] Downloaded ${a.download}\n`;
      return;
    }

    if (!currentXyzData) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(
      new Blob([currentXyzData], { type: "text/plain" }),
    );
    a.download = currentFile.split("/").pop() || "structure.xyz";
    a.click();
    logs += `[status] Downloaded ${a.download}\n`;
  }
</script>

<div
  class="flex flex-col lg:flex-row h-[calc(100vh-64px)] overflow-hidden font-sans bg-slate-50"
>
  <aside
    class="w-full lg:w-[380px] p-6 bg-slate-50 overflow-y-auto flex-shrink-0 border-r border-slate-200 flex flex-col gap-6"
  >
    <div class="px-2 pt-2">
      <h1
        class="font-heading text-2xl font-bold flex items-center gap-3 mb-2 text-slate-900 tracking-tight"
      >
        <img
          src="/assets/logos/QD_Library_mini.png"
          alt="QD Library"
          class="h-9 w-auto mix-blend-multiply"
        />
        Quantum Dot Library
      </h1>
      <p class="text-sm text-slate-600 font-medium leading-relaxed">
        Explore a massive database of pre-computed quantum dots, interactive
        properties, and stoichiometry.
      </p>
    </div>

    <div
      class="bg-white rounded-[1.5rem] shadow-sm border border-slate-100 p-6"
    >
      <h2 class="font-heading text-xl font-bold text-slate-900 mb-5">
        Database Filters
      </h2>

      <div class="mb-4">
        <label
          class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-2"
          for="sys">System Type</label
        >
        <select
          id="sys"
          class="w-full border-none ring-1 ring-slate-200 rounded-xl p-3 text-sm bg-slate-50 focus:ring-2 focus:ring-accent-400 outline-none font-medium"
          bind:value={filters.system}
          onchange={() => {
            filters.material = "";
            filters.size = "";
            filters.functional = "";
            filters.runtype = "";
          }}
        >
          <option value="">All Systems</option>
          {#each availableSystems as sys}
            <option value={sys}>{sys}</option>
          {/each}
        </select>
      </div>

      <div class="mb-4">
        <label
          class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-2"
          for="mat">Material</label
        >
        <select
          id="mat"
          class="w-full border-none ring-1 ring-slate-200 rounded-xl p-3 text-sm bg-slate-50 focus:ring-2 focus:ring-accent-400 outline-none font-medium disabled:opacity-50"
          bind:value={filters.material}
          onchange={() => {
            filters.size = "";
            filters.functional = "";
            filters.runtype = "";
          }}
          disabled={!filters.system}
        >
          <option value="">All Materials</option>
          {#each availableMaterials as mat}
            <option value={mat}>{mat}</option>
          {/each}
        </select>
      </div>

      <div class="mb-4">
        <label
          class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-2"
          for="sz">Size (nm)</label
        >
        <select
          id="sz"
          class="w-full border-none ring-1 ring-slate-200 rounded-xl p-3 text-sm bg-slate-50 focus:ring-2 focus:ring-accent-400 outline-none font-medium disabled:opacity-50"
          bind:value={filters.size}
          disabled={!filters.material}
        >
          <option value="">All Sizes</option>
          {#each availableSizes as sz}
            <option value={sz}>{sz}</option>
          {/each}
        </select>
      </div>

      <div class="mb-4">
        <label
          class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-2"
          for="func">Functional</label
        >
        <select
          id="func"
          class="w-full border-none ring-1 ring-slate-200 rounded-xl p-3 text-sm bg-slate-50 focus:ring-2 focus:ring-accent-400 outline-none font-medium disabled:opacity-50"
          bind:value={filters.functional}
          disabled={!filters.material}
        >
          <option value="">All Functionals</option>
          {#each availableFunctionals as func}
            <option value={func}>{func}</option>
          {/each}
        </select>
      </div>

      <div class="mb-2">
        <label
          class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-2"
          for="rt">Run Type</label
        >
        <select
          id="rt"
          class="w-full border-none ring-1 ring-slate-200 rounded-xl p-3 text-sm bg-slate-50 focus:ring-2 focus:ring-accent-400 outline-none font-medium"
          bind:value={filters.runtype}
        >
          <option value="">All Run Types</option>
          {#each availableRuntypes as rt}
            <option value={rt}>{rt}</option>
          {/each}
        </select>
      </div>
    </div>

    <div
      class="bg-white rounded-[1.5rem] shadow-sm border border-slate-100 flex flex-col max-h-[400px]"
    >
      <button
        class="w-full flex justify-between items-center p-5 font-heading font-bold text-slate-900 hover:bg-slate-50 transition-colors rounded-[1.5rem]"
        onclick={() => (showMatches = !showMatches)}
      >
        <span>Matches ({filteredFiles.length})</span>
        <span class="text-xs text-slate-400">{showMatches ? "▼" : "▶"}</span>
      </button>

      {#if showMatches}
        <div
          class="p-3 pt-0 border-t border-slate-100 overflow-y-auto flex flex-col gap-1"
        >
          {#each filteredFiles as file}
            <button
              class="text-left px-4 py-3 text-sm rounded-xl transition-all font-medium {currentFile ===
              file
                ? 'bg-accent-50 text-accent-700 font-bold ring-1 ring-accent-400'
                : 'bg-white hover:bg-slate-50 hover:text-accent-600'}"
              onclick={() => selectFile(file)}
            >
              {metadata[file]?.filename || file.split("/").pop()}
            </button>
          {/each}
          {#if filteredFiles.length === 0}
            <span class="text-sm text-slate-400 italic p-4 text-center"
              >No structures found.</span
            >
          {/if}
        </div>
      {/if}
    </div>

    <div
      class="bg-brand-50 rounded-[1.5rem] shadow-sm border border-brand-100 p-6 relative overflow-hidden flex-shrink-0"
    >
      <div class="absolute top-0 left-0 w-1.5 h-full bg-brand-500"></div>

      <h2 class="font-heading text-xl font-bold text-brand-900 mb-5">
        Ligand Passivation
      </h2>

      <div class="border border-brand-200 p-5 rounded-[1.25rem] bg-white/50">
        <span
          class="block text-[10px] font-extrabold text-brand-700 uppercase tracking-widest mb-3"
          >Anionic Ligands</span
        >
        <div
          class="grid grid-cols-[1fr_3rem_3.5rem_28px] gap-2 text-[10px] text-brand-600 uppercase font-bold tracking-widest mb-2 px-1"
        >
          <span>SMILES</span><span>Dummy</span><span>Ratio</span><span></span>
        </div>
        {#each anionicLigands as lig, i (lig.id)}
          <div class="grid grid-cols-[1fr_3rem_3.5rem_28px] gap-2 mb-3">
            <input
              type="text"
              bind:value={lig.smiles}
              class="border-none ring-1 ring-brand-200 rounded-lg px-2 py-2 text-sm bg-white focus:ring-2 focus:ring-brand-400 outline-none font-medium min-w-0"
              disabled={!currentFile}
            />
            <input
              type="text"
              bind:value={lig.dummy}
              class="border-none ring-1 ring-brand-200 rounded-lg px-1 py-2 text-sm text-center bg-white focus:ring-2 focus:ring-brand-400 outline-none font-medium min-w-0"
              disabled={!currentFile}
            />
            <input
              type="number"
              bind:value={lig.ratio}
              step="0.1"
              class="border-none ring-1 ring-brand-200 rounded-lg px-1 py-2 text-sm text-center bg-white focus:ring-2 focus:ring-brand-400 outline-none font-medium min-w-0"
              disabled={!currentFile}
            />
            <button
              class="bg-red-100 text-red-600 hover:bg-red-200 rounded-lg flex items-center justify-center text-xs font-bold transition-colors disabled:opacity-50"
              onclick={() => anionicLigands.splice(i, 1)}
              disabled={!currentFile}>✕</button
            >
          </div>
        {/each}
        <button
          class="w-full bg-white hover:bg-brand-50 border border-brand-200 text-xs py-2 rounded-lg text-brand-700 mb-6 font-bold transition-colors disabled:opacity-50"
          onclick={() =>
            anionicLigands.push({
              id: crypto.randomUUID(),
              smiles: "",
              ratio: 1.0,
              dummy: "Cl",
            })}
          disabled={!currentFile}>+ Add Anion</button
        >

        <span
          class="block text-[10px] font-extrabold text-brand-700 uppercase tracking-widest mb-3"
          >Distribution</span
        >
        <div
          class="flex flex-wrap gap-x-3 gap-y-2 text-sm mb-6 bg-white p-2.5 rounded-xl border border-brand-100"
        >
          <label class="flex items-center gap-1.5 cursor-pointer"
            ><input
              type="radio"
              bind:group={capDist}
              value="uniform"
              class="accent-brand-600"
              disabled={!currentFile}
            /> <span class="font-medium text-slate-700">Uniform</span></label
          >
          <label class="flex items-center gap-1.5 cursor-pointer"
            ><input
              type="radio"
              bind:group={capDist}
              value="segmented"
              class="accent-brand-600"
              disabled={!currentFile}
            /> <span class="font-medium text-slate-700">Segmented</span></label
          >
          <label class="flex items-center gap-1.5 cursor-pointer"
            ><input
              type="radio"
              bind:group={capDist}
              value="random"
              class="accent-brand-600"
              disabled={!currentFile}
            /> <span class="font-medium text-slate-700">Random</span></label
          >
        </div>

        {#if !showCationic}
          <button
            class="w-full bg-white hover:bg-brand-50 border border-brand-200 text-xs py-2 rounded-lg text-brand-700 font-bold transition-colors disabled:opacity-50"
            onclick={() => (showCationic = true)}
            disabled={!currentFile}>+ Add Cationic Ligand</button
          >
        {:else}
          <span
            class="block text-[10px] font-extrabold text-brand-700 uppercase tracking-widest mb-3 pt-4 border-t border-brand-200"
            >Cationic Ligands</span
          >
          {#each cationicLigands as lig, i (lig.id)}
            <div class="grid grid-cols-[1fr_3rem_3.5rem_28px] gap-2 mb-3">
              <input
                type="text"
                bind:value={lig.smiles}
                class="border-none ring-1 ring-brand-200 rounded-lg px-2 py-2 text-sm bg-white focus:ring-2 focus:ring-brand-400 outline-none font-medium min-w-0"
                disabled={!currentFile}
              />
              <input
                type="text"
                bind:value={lig.dummy}
                class="border-none ring-1 ring-brand-200 rounded-lg px-1 py-2 text-sm text-center bg-white focus:ring-2 focus:ring-brand-400 outline-none font-medium min-w-0"
                disabled={!currentFile}
              />
              <input
                type="number"
                bind:value={lig.ratio}
                step="0.1"
                class="border-none ring-1 ring-brand-200 rounded-lg px-1 py-2 text-sm text-center bg-white focus:ring-2 focus:ring-brand-400 outline-none font-medium min-w-0"
                disabled={!currentFile}
              />
              <button
                class="bg-red-100 text-red-600 hover:bg-red-200 rounded-lg flex items-center justify-center text-xs font-bold transition-colors disabled:opacity-50"
                onclick={() => cationicLigands.splice(i, 1)}
                disabled={!currentFile}>✕</button
              >
            </div>
          {/each}
          <button
            class="w-full bg-white hover:bg-brand-50 border border-brand-200 text-xs py-2 rounded-lg text-brand-700 font-bold transition-colors disabled:opacity-50"
            onclick={() =>
              cationicLigands.push({
                id: crypto.randomUUID(),
                smiles: "",
                ratio: 1.0,
                dummy: "Rb",
              })}
            disabled={!currentFile}>+ Add Cation</button
          >
        {/if}
      </div>

      {#if attachError}
        <div
          class="text-xs text-red-700 font-medium bg-red-100 p-3 rounded-xl border border-red-200 mt-4"
        >
          {attachError}
        </div>
      {/if}

      <div class="flex flex-col gap-3 mt-5">
        <button
          class="w-full bg-brand-600 hover:bg-brand-700 disabled:bg-slate-300 text-white font-bold py-3 rounded-xl text-sm shadow-glow transition-all disabled:shadow-none"
          onclick={handlePassivate}
          disabled={!currentFile || isAttaching}
        >
          {isAttaching ? "Attaching Ligands..." : "Passivate Structure"}
        </button>
        {#if currentXyzData !== originalXyzData && originalXyzData !== ""}
          <button
            class="w-full bg-white hover:bg-slate-50 text-slate-800 font-bold py-2 rounded-xl text-xs transition-colors border border-slate-200"
            onclick={() => {
              currentXyzData = originalXyzData;
              logs += "[status] Reverted to unpassivated core structure.\n";
            }}
          >
            Reset to Core
          </button>
        {/if}
      </div>
    </div>
  </aside>

  <main
    class="flex-grow h-full flex flex-col p-6 gap-6 bg-slate-50 overflow-y-auto"
  >
    <div
      class="flex flex-col gap-6 flex-shrink-0 h-[calc(100vh-112px)] min-h-[700px]"
    >
      <div
        class="relative flex-1 min-h-[400px] bg-white rounded-[1.5rem] p-4 border border-slate-100 shadow-sm flex flex-col"
      >
        <div class="flex justify-between items-center mb-3 px-2">
          <h2 class="font-heading font-bold text-xl text-slate-900">
            3D Structure Viewer
          </h2>
          <div class="flex items-center gap-3">
            {#if !isMD}
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
            {/if}
            <button
              onclick={downloadXYZ}
              class="bg-slate-100 hover:bg-slate-200 disabled:opacity-50 text-slate-800 px-5 py-2 rounded-xl text-sm font-bold transition-colors"
              disabled={!currentXyzData}
            >
              Download XYZ
            </button>
          </div>
        </div>
        <div
          class="flex-1 bg-slate-50 rounded-[1rem] border border-slate-200 overflow-hidden relative shadow-inner"
        >
          <Viewer 
            xyz={currentXyzData} 
            {isMD} 
            dataUrl={currentFileUrl} 
            sizeMetrics={currentMeta?.size_metrics} 
            activeViewer={activeViewer}
          />
          {#if isAttaching}
            <div
              class="absolute inset-0 bg-slate-900/60 backdrop-blur-sm flex flex-col items-center justify-center text-white z-10"
            >
              <div
                class="w-12 h-12 border-4 border-brand-500 border-t-transparent rounded-full animate-spin mb-4"
              ></div>
              <p class="font-bold text-lg tracking-wide">
                Attaching Ligands...
              </p>
            </div>
          {/if}
        </div>
      </div>

      <div class="h-1/3 grid grid-cols-1 md:grid-cols-4 gap-6 min-h-[280px]">
        <div
          class="bg-white border border-slate-100 shadow-sm rounded-[1.5rem] p-6 md:col-span-1 overflow-y-auto h-full"
        >
          <h2
            class="font-heading text-lg font-bold text-slate-900 mb-4 border-b border-slate-100 pb-2"
          >
            Structure Details
          </h2>

          {#if currentMeta || Object.keys(calculatedStoich).length > 0}
            {#if currentFile.includes("MD") || currentMeta?.run_type === "MD"}
              <div class="mb-6">
                <span
                  class="inline-flex items-center gap-2 bg-accent-100 text-accent-800 px-4 py-2 rounded-xl text-xs font-bold shadow-sm border border-accent-200"
                >
                  <svg
                    class="w-4 h-4 animate-spin-slow"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                    ><path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      stroke-width="2"
                      d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                    ></path></svg
                  >
                  MD Trajectory Loaded
                </span>
                <p class="text-[10px] text-slate-500 mt-2 font-medium">
                  Matterviz will process the frames of this trajectory.
                </p>
              </div>
            {/if}

            {#if currentMeta}
              <div
                class="space-y-2 text-sm text-slate-700 mb-6 bg-slate-50 p-3 rounded-2xl"
              >
                <p class="flex justify-between">
                  <strong class="text-slate-900 font-bold">System:</strong>
                  <span class="font-medium text-right"
                    >{currentMeta.system_type}</span
                  >
                </p>
                <p class="flex justify-between">
                  <strong class="text-slate-900 font-bold">Material:</strong>
                  <span class="font-medium text-right"
                    >{currentMeta.material}</span
                  >
                </p>
                <p class="flex justify-between">
                  <strong class="text-slate-900 font-bold">Size:</strong>
                  <span class="font-medium text-right"
                    >{currentMeta.size} nm</span
                  >
                </p>
                <p class="flex justify-between">
                  <strong class="text-slate-900 font-bold">Functional:</strong>
                  <span class="font-medium text-right"
                    >{currentMeta.functional}</span
                  >
                </p>
              </div>
            {/if}


            <h3 class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3">
              Total Stoichiometry
            </h3>
            <div class="flex flex-wrap gap-2 mb-6">
              {#if isMD}
                <span class="text-slate-500 text-sm italic bg-slate-100 px-3 py-2 rounded-lg w-full">
                  Stoichiometry calculation is disabled for MD trajectories to maximize browser performance.
                </span>
              {:else}
                {#each Object.entries(calculatedStoich) as [elem, count]}
                  <span class="bg-brand-50 text-brand-800 border border-brand-100 px-3 py-1 rounded-lg font-bold text-xs">
                    {elem}: {count}
                  </span>
                {:else}
                  <span class="text-slate-400 text-sm italic">Loading structure...</span>
                {/each}
              {/if}
            </div>

            <h3
              class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3"
            >
              Elemental Ratios
            </h3>
            <div class="flex flex-wrap gap-2 mb-6">
              {#each Object.entries(calculatedRatios) as [ratio, val]}
                <span
                  class="bg-accent-50 text-accent-800 border border-accent-100 px-2.5 py-1 rounded-lg font-mono text-xs font-bold"
                >
                  <span class="text-accent-600">{ratio}</span>: {val}
                </span>
              {:else}
                <span class="text-slate-400 text-sm italic"
                  >Loading ratios...</span
                >
              {/each}
            </div>

            <h3
              class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3"
            >
              Structure State
            </h3>
            <div class="text-sm mb-6">
              {#if currentXyzData !== originalXyzData}
                <span
                  class="inline-flex items-center gap-1.5 text-brand-700 font-bold bg-brand-50 px-3 py-1.5 rounded-lg text-xs"
                >
                  <svg
                    class="w-3.5 h-3.5"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                    ><path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      stroke-width="2"
                      d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
                    ></path></svg
                  >
                  Passivated Structure
                </span>
              {:else}
                <span
                  class="inline-flex items-center gap-1.5 text-slate-600 font-bold bg-slate-100 px-3 py-1.5 rounded-lg text-xs"
                >
                  Unpassivated Core
                </span>
              {/if}
            </div>

            <h3
              class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3"
            >
              Charge Balance
            </h3>
            <div class="mb-4">
              <div
                class="flex items-center justify-between px-3 py-2.5 rounded-lg border {calculatedCharge ===
                0
                  ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
                  : 'bg-red-50 border-red-200 text-red-800'} font-bold text-xs shadow-sm w-full"
              >
                <span>Total Charge:</span>
                <span class="text-sm"
                  >{calculatedCharge > 0 ? "+" : ""}{calculatedCharge} e</span
                >
              </div>
              {#if calculatedCharge !== 0}
                <p
                  class="text-[10px] text-red-600 mt-1.5 font-bold flex items-center gap-1"
                >
                  <svg
                    class="w-3.5 h-3.5"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                    ><path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      stroke-width="2"
                      d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                    ></path></svg
                  >
                  Structure is not charge-neutral.
                </p>
              {/if}
            </div>
          {:else}
            <div class="h-32 flex items-center justify-center">
              <p class="text-sm text-slate-400 italic">
                Select structure to view details.
              </p>
            </div>
          {/if}
        </div>

        <div
          class="bg-slate-900 border border-slate-800 rounded-[1.5rem] p-0 md:col-span-3 flex flex-col overflow-hidden shadow-inner relative h-full"
        >
          <div
            class="bg-slate-800/80 backdrop-blur-sm text-slate-400 text-[10px] px-4 py-2 font-mono font-bold uppercase tracking-widest border-b border-slate-700/50 flex justify-between items-center absolute w-full top-0 left-0 z-10"
          >
            <span class="flex items-center gap-2"
              ><div class="w-2 h-2 rounded-full bg-emerald-500"></div>
               miniCAT Engine Terminal</span
            >
            {#if isAttaching}<span class="text-brand-400 animate-pulse"
                >Running process...</span
              >{/if}
          </div>
          <pre
            bind:this={logContainer}
            class="text-xs text-emerald-400 font-mono p-5 pt-12 h-full overflow-y-auto whitespace-pre-wrap leading-relaxed selection:bg-emerald-900 selection:text-emerald-100">{logs}</pre>
        </div>
      </div>
    </div>

    <div class="w-full bg-white rounded-[1.5rem] shadow-sm border border-slate-100 p-6 min-h-[800px] flex-shrink-0 flex flex-col mt-2">
      
      <!-- Dynamic Header & Tabs -->
      <div class="flex flex-col xl:flex-row justify-between xl:items-end gap-4 border-b border-slate-100 pb-4 mb-4 z-10">
        <h2 class="font-heading font-bold text-2xl text-slate-900">
          Interactive Properties
        </h2>
        
        {#if propertiesStatus === "ready"}
          <div class="flex flex-wrap gap-2">
            <button 
              class="px-4 py-2 text-xs md:text-sm font-bold rounded-xl transition-all {activePropertyTab === 'fuzzy_sf' ? 'bg-brand-50 text-brand-700 shadow-sm ring-1 ring-brand-200' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'}"
              onclick={() => activePropertyTab = 'fuzzy_sf'}>
              Fuzzy - PDOS - COOP (Spin Free) 
            </button>
            <button 
              class="px-4 py-2 text-xs md:text-sm font-bold rounded-xl transition-all {activePropertyTab === 'fuzzy_soc' ? 'bg-brand-50 text-brand-700 shadow-sm ring-1 ring-brand-200' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'}"
              onclick={() => activePropertyTab = 'fuzzy_soc'}>
              Fuzzy - PDOS - COOP (SOC) 
            </button>
            <button 
              class="px-4 py-2 text-xs md:text-sm font-bold rounded-xl transition-all {activePropertyTab === 'exciton_sf' ? 'bg-brand-50 text-brand-700 shadow-sm ring-1 ring-brand-200' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'}"
              onclick={() => activePropertyTab = 'exciton_sf'}>
              Excited States (Spin Free)
            </button>
            <button 
              class="px-4 py-2 text-xs md:text-sm font-bold rounded-xl transition-all {activePropertyTab === 'exciton_soc' ? 'bg-brand-50 text-brand-700 shadow-sm ring-1 ring-brand-200' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'}"
              onclick={() => activePropertyTab = 'exciton_soc'}>
              Excited States (SOC)
            </button>
          </div>
        {/if}
      </div>

      <!-- Content Area -->
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
        {:else if propertiesStatus === "error"}
          <div class="absolute inset-0 flex flex-col items-center justify-center bg-red-50 text-red-700 rounded-2xl text-sm border border-red-200 text-center px-6">
            <span class="font-bold mb-2">Properties Not Found</span>
            <span class="font-mono text-xs opacity-80">Plots have not been generated for this structure yet.</span>
          </div>
        {:else if propertiesStatus === "ready"}
          {#if plotUrls[activePropertyTab]}
            <iframe
              key={plotUrls[activePropertyTab]}
              title="Interactive Properties"
              src={plotUrls[activePropertyTab]}
              class="absolute inset-0 w-full h-full rounded-[1rem] border border-slate-200 bg-white"
              sandbox="allow-scripts allow-same-origin allow-popups allow-modals"
              referrerpolicy="no-referrer"
            ></iframe>
          {:else}
            <div class="absolute inset-0 flex items-center justify-center bg-slate-50 text-slate-500 rounded-2xl italic text-sm font-medium border border-slate-200 border-dashed">
              This specific plot is not available for the selected structure.
            </div>
          {/if}
        {/if}
      </div>
    </div>

  </main>
</div>
