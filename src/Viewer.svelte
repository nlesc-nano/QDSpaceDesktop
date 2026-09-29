<script>
  import { Structure } from "matterviz";
  import { Trajectory } from "matterviz/trajectory";
  import { parse_xyz } from "matterviz/structure/parse";
  import { onMount } from "svelte";

  let props = $props();

  // Parse the structure synchronously (used for non-MD single-frame mode)
  let structure = $derived(props.xyz && !props.isMD ? parse_xyz(props.xyz) : null);

  // Only disable bonds if the structure is truly massive (>5000 atoms) to protect the browser
  let isMassive = $derived(structure ? structure.num_atoms > 5000 : false);

  // Helper to parse elements, count stoichiometry, and assign CPK/Jmol colors
  function parseXyzElements(xyzText) {
    if (!xyzText) return [];
    const lines = xyzText.trim().split("\n");
    if (lines.length < 3) return [];
    const counts = {};
    for (let i = 2; i < lines.length; i++) {
      const parts = lines[i].trim().split(/\s+/);
      if (parts.length >= 4) {
        const elem = parts[0];
        counts[elem] = (counts[elem] || 0) + 1;
      }
    }
    const colors = {
      H: "#ffffff", C: "#909090", N: "#3050f8", O: "#ff0d0d",
      F: "#b0e0e6", Cl: "#1ff01f", Br: "#a62929", I: "#940094",
      He: "#ffffc0", Ne: "#b3e3f5", Ar: "#80d1e3", Kr: "#5cb8d1", Xe: "#429eb8",
      Na: "#ab5cf2", Mg: "#8aff00", Al: "#bfa6a6", Si: "#f0c8a0", P: "#ffa500", S: "#ffff30",
      K: "#8f40d4", Ca: "#3dff00", Sc: "#e6e6e6", Ti: "#bfc2c7", V: "#a6a6ab", Cr: "#8a99c7", Mn: "#9c7ac7", Fe: "#e06633", Co: "#f090a0", Ni: "#50d050", Cu: "#c88033", Zn: "#7d80b0", Ga: "#c28f8f", Ge: "#668f8f", As: "#bd80e3", Se: "#ffa100",
      Rb: "#702eb0", Sr: "#00ff00", Y: "#94ffff", Zr: "#94e3e3", Nb: "#73c2c9", Mo: "#54b5b5", Tc: "#3b9e9e", Ru: "#248f8f", Rh: "#0a7d7d", Pd: "#006969", Ag: "#c0c0c0", Cd: "#ffd98f", In: "#a67d7d", Sn: "#669999", Sb: "#9e63b5", Te: "#d47a00",
      Cs: "#57178f", Ba: "#00c900", La: "#70d4ff", Ce: "#ffffc7", Pr: "#d9ffc7", Nd: "#c7ffc7", Pm: "#a3ffc7", Sm: "#8fffc7", Eu: "#61ffc7", Gd: "#45ffc7", Tb: "#30ffc7", Dy: "#1fffc7", Ho: "#09ffc7", Er: "#00e69c", Tm: "#00d470", Yb: "#00bf38", Lu: "#00ab24", Hf: "#4dc2ff", Ta: "#4da6ff", W: "#2194d6", Re: "#267dab", Os: "#266694", Ir: "#175487", Pt: "#d0d0e0", Au: "#ffd12b", Hg: "#b8b8d0", Tl: "#a6544d", Pb: "#575961", Bi: "#9e4fb5"
    };
    return Object.entries(counts).map(([element, count]) => ({
      element,
      count,
      color: colors[element] || "#a0a0a0"
    })).sort((a, b) => b.count - a.count);
  }

  let activeViewer = $derived(props.activeViewer || (props.isMD ? "matterviz" : "molstar"));
  
  let container3dmol = $state(null);
  let containerNgl = $state(null);
  let containerMolstar = $state(null);
  
  let viewer3dmol = null;
  let stageNgl = null;
  let viewerMolstar = null;
  let myLabelProvider = null;
  
  let scriptLoaded3dmol = $state(false);
  let scriptLoadedNgl = $state(false);
  let scriptLoadedMolstar = $state(false);

  // Helper to load external scripts asynchronously and handle duplicates/race conditions
  function loadScript(src, checkGlobal) {
    return new Promise((resolve) => {
      if (window[checkGlobal]) {
        resolve(true);
        return;
      }
      
      const existing = document.querySelector(`script[src="${src}"]`);
      if (existing) {
        const checkInterval = setInterval(() => {
          if (window[checkGlobal]) {
            clearInterval(checkInterval);
            resolve(true);
          }
        }, 50);
        return;
      }

      const script = document.createElement("script");
      script.src = src;
      script.async = true;
      script.onload = () => resolve(true);
      script.onerror = () => resolve(false);
      document.head.appendChild(script);
    });
  }

  // Render 3Dmol structure (White background, Orthographic projection, VDW Spheres only)
  function render3dmol() {
    if (!scriptLoaded3dmol || !container3dmol || !props.xyz || props.isMD) return;
    container3dmol.innerHTML = "";

    try {
      if (window.$3Dmol) {
        viewer3dmol = window.$3Dmol.createViewer(container3dmol, {
          backgroundColor: "white",
          orthographic: true
        });

        // Add Model
        viewer3dmol.addModel(props.xyz, "xyz");

        // Style: Spacefill with large VDW spheres (no sticks)
        viewer3dmol.setStyle({}, {
          sphere: { colorscheme: "Jmol" }
        });

        viewer3dmol.zoomTo();
        viewer3dmol.render();
      }
    } catch (err) {
      console.error("[3Dmol] Render error:", err);
    }
  }

  // Render NGL Viewer structure (White background, VDW spacefill style)
  function renderNgl() {
    if (!scriptLoadedNgl || !containerNgl || !props.xyz || props.isMD) return;
    containerNgl.innerHTML = "";

    try {
      if (window.NGL) {
        if (stageNgl) {
          stageNgl.dispose();
          stageNgl = null;
        }

        stageNgl = new window.NGL.Stage(containerNgl, { 
          backgroundColor: "white"
        });
        stageNgl.setParameters({ cameraType: "orthographic" });

        const file = new File([props.xyz], "structure.xyz", { type: "text/plain" });

        stageNgl.loadFile(file).then(function (o) {
          // Large VDW spacefill representation
          o.addRepresentation("spacefill", { colorscheme: "element" });
          stageNgl.autoView();
        }).catch(err => {
          console.error("[NGL] Load file error:", err);
        });
      }
    } catch (err) {
      console.error("[NGL] Render error:", err);
    }
  }

  // Render Molstar structure (White background, loadStructureFromUrl)
  function renderMolstar() {
    if (!scriptLoadedMolstar || !containerMolstar || !props.xyz || props.isMD) return;
    containerMolstar.innerHTML = "";

    try {
      if (window.molstar) {
        window.molstar.Viewer.create(containerMolstar, {
          layoutIsExpanded: false,
          layoutShowControls: false,
          layoutShowRemoteState: false,
          layoutShowSequence: false,
          layoutShowLog: false,
          viewportShowExpand: false,
          viewportShowSelectionMode: true,
          viewportShowAnimation: false,
          collapseLeftControls: true,
        }).then(async v => {
          viewerMolstar = v;
          const plugin = viewerMolstar.plugin;

          // Set orthographic camera mode and white background color
          plugin.canvas3d.setProps({
            camera: { mode: 'orthographic' },
            renderer: { backgroundColor: 16777215 } // 0xffffff in decimal
          });

          // Register a custom loci label provider to fix the "unknown entity" hover tooltip
          if (myLabelProvider) {
            plugin.managers.lociLabels.removeProvider(myLabelProvider);
          }
          myLabelProvider = {
            label: (loci) => {
              if (window.molstar.StructureElement.Loci.is(loci)) {
                const location = window.molstar.StructureElement.Loci.getFirstLocation(loci);
                if (location) {
                  const element = window.molstar.StructureProperties.atom.element_symbol(location);
                  const id = window.molstar.StructureProperties.atom.id(location);
                  return `Atom: ${element} (Index: ${id})`;
                }
              }
              return undefined;
            },
            priority: 100
          };
          plugin.managers.lociLabels.addProvider(myLabelProvider);

          // Custom low-level Molstar loaders to parse coordinates and apply spacefill
          const blob = new Blob([props.xyz], { type: "text/plain" });
          const url = URL.createObjectURL(blob);

          try {
            const data = await plugin.builders.data.download({ url, isBinary: false }, { state: { isGhost: true } });
            const trajectory = await plugin.builders.structure.parseTrajectory(data, 'xyz');
            const model = await plugin.builders.structure.createModel(trajectory);
            const structure = await plugin.builders.structure.createStructure(model);
            
            const component = await plugin.builders.structure.tryCreateComponentStatic(structure, 'all');
            if (component) {
              await plugin.builders.structure.representation.addRepresentation(component, { type: 'spacefill' });
            }
            
            // Center the camera on the newly loaded structure
            plugin.managers.camera.reset();
          } catch (err) {
            console.error("[Molstar] Builder pipeline error:", err);
          } finally {
            URL.revokeObjectURL(url);
          }
        }).catch(err => {
          console.error("[Molstar] Create viewer error:", err);
        });
      }
    } catch (err) {
      console.error("[Molstar] Render error:", err);
    }
  }

  // React to changes in loading status, xyz data, and activeViewer choice (with deferred rendering)
  $effect(() => {
    if (activeViewer === "3dmol" && scriptLoaded3dmol && props.xyz && container3dmol) {
      setTimeout(render3dmol, 50);
    }
  });

  $effect(() => {
    if (activeViewer === "ngl" && scriptLoadedNgl && props.xyz && containerNgl) {
      setTimeout(renderNgl, 50);
    }
  });

  $effect(() => {
    if (activeViewer === "molstar" && scriptLoadedMolstar && props.xyz && containerMolstar) {
      setTimeout(renderMolstar, 50);
    }
  });

  onMount(() => {
    // Parallel scripts load
    loadScript("https://3Dmol.org/build/3Dmol-min.js", "$3Dmol").then(ok => {
      if (ok) scriptLoaded3dmol = true;
    });

    loadScript("https://cdn.jsdelivr.net/npm/ngl@2.4.0/dist/ngl.js", "NGL").then(ok => {
      if (ok) scriptLoadedNgl = true;
    });

    loadScript("https://cdn.jsdelivr.net/npm/molstar@4.3.0/build/viewer/molstar.js", "molstar").then(ok => {
      if (ok) scriptLoadedMolstar = true;
    });

    return () => {
      if (viewer3dmol) viewer3dmol.clear();
      if (stageNgl) stageNgl.dispose();
      if (viewerMolstar && myLabelProvider) {
        viewerMolstar.plugin.managers.lociLabels.removeProvider(myLabelProvider);
      }
    };
  });
</script>

<svelte:head>
  <link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/molstar@4.3.0/build/viewer/molstar.css" />
</svelte:head>

<div class="relative w-full h-full">

  <!-- Embedded Selector Toolbar Removed (Moved to header by parent) -->

  {#if !props.xyz}
    <div class="p-4 flex items-center justify-center h-full text-slate-500 font-medium bg-slate-900 rounded-[1.5rem]" style="min-height: 400px; height: 100%;">
      No structure loaded
    </div>
  {:else if props.isMD && props.dataUrl}
    {#key props.dataUrl}
      <Trajectory
        data_url={props.dataUrl}
        auto_play={true}
        fps={10}
        structure_props={{
          performance_mode: "speed",
          scene_props: {
            atom_radius: 1.8,
            same_size_atoms: false,
            show_bonds: "always",
          },
          color_scheme: "Jmol",
        }}
        display_mode="structure"
        style="height:100%"
      />
    {/key}
  {:else if activeViewer === "3dmol"}
    <div bind:this={container3dmol} class="w-full h-full rounded-[1.5rem] overflow-hidden bg-white border border-slate-200" style="min-height: 400px; height: 100%;">
      {#if !scriptLoaded3dmol}
        <div class="flex items-center justify-center h-full text-slate-500 font-medium bg-slate-900">
          Loading 3Dmol library...
        </div>
      {/if}
    </div>
  {:else if activeViewer === "ngl"}
    <div bind:this={containerNgl} class="w-full h-full rounded-[1.5rem] overflow-hidden bg-white border border-slate-200" style="min-height: 400px; height: 100%;">
      {#if !scriptLoadedNgl}
        <div class="flex items-center justify-center h-full text-slate-500 font-medium bg-slate-900">
          Loading NGL Viewer...
        </div>
      {/if}
    </div>
  {:else if activeViewer === "molstar"}
    <div bind:this={containerMolstar} class="w-full h-full rounded-[1.5rem] overflow-hidden relative bg-white border border-slate-200" style="min-height: 400px; height: 100%;">
      {#if !scriptLoadedMolstar}
        <div class="flex items-center justify-center h-full text-slate-500 font-medium bg-slate-900">
          Loading Mol* library...
        </div>
      {/if}
    </div>
  {:else if structure}
    {#key structure}
      <Structure
        {structure}
        color_scheme="Jmol"
        performance_mode={isMassive}
        scene_props={{
          atom_radius: 1.8,
          same_size_atoms: false,
          show_bonds: "always",
        }}
        style="height:100%"
      />
    {/key}
  {/if}

  {#if props.sizeMetrics}
    <div class="absolute top-4 left-4 bg-white/80 backdrop-blur-md border border-slate-200 p-3 rounded-lg shadow-soft pointer-events-none z-10">
      <h4 class="text-[10px] font-mono font-bold text-slate-500 uppercase tracking-widest mb-1.5">
        Effective Size (Core)
      </h4>
      <div class="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        
        <span class="text-slate-600">Radius</span>
        <span class="font-mono text-brand-600 font-medium text-right">
          {Number((props.sizeMetrics.R_eff_hull / 10).toFixed(2))} nm
        </span>
        
        <span class="text-slate-600">Diameter</span>
        <span class="font-mono text-brand-600 font-medium text-right">
          {Number((props.sizeMetrics.diameter_hull / 10).toFixed(2))} nm
        </span>

      </div>
    </div>
  {/if}

  <!-- Element Legend & Stoichiometry Overlay -->
  {#if props.xyz && !props.isMD}
    {@const elements = parseXyzElements(props.xyz)}
    {#if elements.length > 0}
      <div class="absolute bottom-4 left-4 bg-white/90 backdrop-blur-md border border-slate-200/60 p-3 rounded-2xl shadow-lg z-10 max-w-[200px] flex flex-col gap-1.5 pointer-events-auto">
        <h4 class="text-[10px] font-extrabold text-slate-500 uppercase tracking-widest border-b border-slate-100 pb-1 flex items-center gap-1.5">
          🎨 Element Legend
        </h4>
        <div class="flex flex-col gap-1 max-h-[140px] overflow-y-auto pr-1">
          {#each elements as el}
            <div class="flex items-center justify-between gap-3 text-xs font-semibold">
              <div class="flex items-center gap-2">
                <span class="w-3 h-3 rounded-full border border-slate-300 shadow-inner shrink-0" style="background-color: {el.color}"></span>
                <span class="text-slate-800 font-bold">{el.element}</span>
              </div>
              <span class="font-mono text-slate-500 text-[10px]">{el.count}</span>
            </div>
          {/each}
        </div>
      </div>
    {/if}
  {/if}

</div>
